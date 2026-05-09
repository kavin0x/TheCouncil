from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from rich.console import Console

from council.core import council
from council.features.guardrails import Guardrails
from council.features.personalities import PersonalityMode
from council.realtime import emit_run_event


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "agents.yaml"


class CouncilRunBlockedError(RuntimeError):
    pass


def _silent_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None, highlight=False)


def _parse_mode(raw: Any) -> PersonalityMode | None:
    if raw is None:
        return None
    if isinstance(raw, PersonalityMode):
        return raw
    if isinstance(raw, str):
        value = raw.strip().lower()
        for m in PersonalityMode:
            if m.value == value:
                return m
    return None


def _effective_num_rounds(config: dict[str, Any]) -> int:
    raw = config.get("num_rounds") or config.get("rounds")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4
    return max(1, min(4, n))


def _effective_num_agents(config: dict[str, Any], default: int) -> int:
    raw = config.get("num_agents") or config.get("agents")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, n)


async def run_council_for_api(
    *,
    question: str,
    config: dict[str, Any] | None = None,
    owner_id: str | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Run a council debate headlessly and return a JSON-safe dict result.

    This reuses the debate logic from `council.py` but suppresses Rich output.
    """
    cfg = config or {}
    start = time.monotonic()

    # Guardrails (same semantics as CLI, but raise so worker can mark FAILED)
    if cfg.get("guardrails", True) and os.getenv("COUNCIL_GUARDRAILS", "1") not in ("0", "false", "False"):
        g = Guardrails()
        res = g.screen(question)
        if res.blocked:
            raise CouncilRunBlockedError(res.summary())

    # Suppress output from council module globals.
    prior_console = council.console
    council.console = _silent_console()
    try:
        base_agents, settings = council.load_config(config_path or DEFAULT_CONFIG_PATH)
        default_model = settings.get("model", council.MODEL)

        selected_personas = cfg.get("selected_personas")
        personality_mode = _parse_mode(cfg.get("mode"))
        generated_data = cfg.get("generated_data")
        topic = question

        # Resolve agents
        if isinstance(selected_personas, list) and selected_personas:
            agents = council._dicts_to_agents(selected_personas)
        elif personality_mode is None:
            agents = council._resolve_default_agents(base_agents, generated_data, topic=topic)
        elif personality_mode == PersonalityMode.DYNAMIC:
            n = _effective_num_agents(cfg, default=5)
            agents = await council._generate_dynamic_agents(topic, n=n, model=default_model)
        elif personality_mode == PersonalityMode.GENERATED:
            agent_dicts = council.build_agent_panel(
                PersonalityMode.GENERATED,
                base_agents=[],
                topic=topic,
                generated_data=generated_data,
            )
            agents = council._dicts_to_agents(agent_dicts)
        else:
            agent_dicts = council.build_agent_panel(
                personality_mode,
                base_agents=[a.__dict__ for a in base_agents],
                topic=topic,
            )
            agents = council._dicts_to_agents(agent_dicts)

        if not agents:
            raise RuntimeError("No agents configured.")

        # Apply agent cap for demo speed.
        max_agents = _effective_num_agents(cfg, default=len(agents))
        agents = agents[:max_agents]

        stream_for_api = run_id is not None
        session = council.DebateSession(
            question=question,
            agents=agents,
            model=settings.get("model", council.MODEL),
            stream_cross_debate=stream_for_api,
            show_dm_indicators=False,
        )
        if run_id:

            async def _on_stream_delta(agent_name: str, rn: int, delta: str) -> None:
                await emit_run_event(
                    run_id,
                    "agent_delta",
                    {"agent": agent_name, "round_num": rn, "delta": delta},
                )

            session.on_stream_delta = _on_stream_delta
            await emit_run_event(
                run_id,
                "agents_announced",
                {"agents": [{"name": a.name, "role": a.role} for a in agents]},
            )

        async def emit_response(resp: council.AgentResponse, phase: str) -> None:
            if not run_id:
                return
            await emit_run_event(
                run_id,
                "agent_response",
                {
                    "agent": resp.agent.name,
                    "role": resp.agent.role,
                    "round_num": resp.round_num,
                    "content": resp.content,
                    "phase": phase,
                },
            )

        async def emit_dm(dm: council.DM) -> None:
            council.deliver_dm(dm, session)
            if run_id:
                await emit_run_event(
                    run_id,
                    "agent_dm",
                    {
                        "sender": dm.sender,
                        "recipient": dm.recipient,
                        "content": dm.content,
                        "round_num": dm.round_num,
                    },
                )

        num_rounds = _effective_num_rounds(cfg)

        # Round 1 (parallel — emit each agent as it finishes; preserve agent order in session)
        async def _round1_indexed(i: int, agent: council.Agent) -> tuple[int, tuple[council.AgentResponse, council.DM | None]]:
            r = await council._agent_round1(agent, session)
            return i, r

        r1_tasks = [_round1_indexed(i, a) for i, a in enumerate(agents)]
        r1_by_index: dict[int, tuple[council.AgentResponse, council.DM | None]] = {}
        for coro in council.asyncio.as_completed(r1_tasks):
            i, (resp, dm) = await coro
            r1_by_index[i] = (resp, dm)
            await emit_response(resp, "round1")
        round1_responses = [r1_by_index[j][0] for j in range(len(agents))]
        session.rounds.append(round1_responses)
        for j in range(len(agents)):
            _r, dm = r1_by_index[j]
            if dm:
                await emit_dm(dm)

        # Round 2 (sequential)
        if num_rounds >= 2:
            round2_responses: list[council.AgentResponse] = []
            for a in agents:
                resp, dm = await council._agent_cross_debate(a, session, 2, round2_responses)
                round2_responses.append(resp)
                await emit_response(resp, "cross_debate_1")
                if dm:
                    await emit_dm(dm)
            session.rounds.append(round2_responses)

        # Round 3 (private deliberation)
        if num_rounds >= 3:
            dm_batches = await council.asyncio.gather(*[council._dm_only_round(a, session) for a in agents])
            for batch in dm_batches:
                for dm in batch:
                    await emit_dm(dm)

        # Round 4 (sequential)
        if num_rounds >= 4:
            round4_responses: list[council.AgentResponse] = []
            for a in agents:
                resp, dm = await council._agent_cross_debate(a, session, 4, round4_responses)
                round4_responses.append(resp)
                await emit_response(resp, "cross_debate_2")
                if dm:
                    await emit_dm(dm)
            session.rounds.append(round4_responses)

        # Propose resolutions
        for a in agents:
            session.resolutions[a.name] = await council._agent_propose_resolution(a, session)

        # Vote + tie-breaker
        max_tiebreaker_rounds = 5
        active_resolutions = list(session.resolutions.keys())
        tiebreaker_round_num = 5
        final_winner: str | None = None

        while True:
            resolutions_in_play = [(p, session.resolutions[p]) for p in active_resolutions]
            votes: dict[str, str] = {}
            for voter in agents:
                voted_for = await council._agent_vote_for_one_resolution(voter, session, resolutions_in_play)
                if voted_for:
                    votes[voter.name] = voted_for
            session.vote_rounds.append(votes)

            counts = council._compute_vote_counts(votes)
            winners = council._get_tied_winners(counts)

            if len(winners) == 1:
                final_winner = winners[0]
                break

            if not winners:
                winners = active_resolutions

            if tiebreaker_round_num - 5 >= max_tiebreaker_rounds:
                final_winner = winners[0] if winners else None
                break

            active_resolutions = winners

            # Tie-breaker debate round
            tiebreaker_responses: list[council.AgentResponse] = []
            for a in agents:
                resp = await council._agent_tiebreaker_debate(
                    a, session, tiebreaker_round_num, active_resolutions, tiebreaker_responses
                )
                tiebreaker_responses.append(resp)
                await emit_response(resp, "tiebreaker")
            session.rounds.append(tiebreaker_responses)
            tiebreaker_round_num += 1

        final_resolution = session.resolutions.get(final_winner or "", "") if final_winner else ""

        # Top-3 resolutions + moderator analysis
        top3 = council._get_top3_resolutions(session)
        report = await council._moderator_pros_cons(
            question=question,
            top3=top3,
            agents=agents,
            model=session.model,
        )

        # Build compact JSON result
        per_round = []
        for round_responses in session.rounds:
            if not round_responses:
                continue
            rn = round_responses[0].round_num
            per_round.append(
                {
                    "round_num": rn,
                    "responses": [
                        {"agent": r.agent.name, "role": r.agent.role, "content": r.content}
                        for r in round_responses
                    ],
                }
            )

        dms = [{"sender": dm.sender, "recipient": dm.recipient, "content": dm.content, "round_num": dm.round_num} for dm in session.dms]

        top3_output = [
            {
                "rank": a.rank,
                "agent": a.agent_name,
                "role": a.agent_role,
                "resolution": a.resolution,
                "summary": a.summary,
                "pros": a.pros,
                "cons": a.cons,
            }
            for a in report.analyses
        ]

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "question": question,
            "model": session.model,
            "agents": [{"name": a.name, "role": a.role, "model": a.model} for a in agents],
            "rounds": per_round,
            "dms": dms,
            "resolutions": session.resolutions,
            "vote_rounds": session.vote_rounds,
            "winner": final_winner,
            "final_resolution": final_resolution,
            "top3": top3_output,
            "meta": {
                "num_rounds": num_rounds,
                "elapsed_ms": elapsed_ms,
                "generated_at": time.time(),
            },
        }
    finally:
        council.console = prior_console

