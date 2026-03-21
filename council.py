#!/usr/bin/env python3
"""
Council — A Mixture-of-Experts debate system powered by OpenRouter (Grok).

Round structure:
  1       Independent Takes — async parallel, no cross-knowledge
  2       Cross-Debate I    — sequential
  3       Private Deliberation — DMs only
  4       Cross-Debate II   — sequential
  ★       Resolutions + Vote — each agent proposes a resolution; each agent votes for ONE resolution.
          If tied for first, non-winners are dropped and a tie-breaker debate runs on the tied set.
          Vote again; repeat until one resolution wins. Final resolution presented to user.

Usage:
    python council.py
    python council.py "Is this auth design secure?"
    python council.py --config my_panel.yaml "Should I pivot?"
    python council.py --list-agents
"""

import argparse
import asyncio
import os
import sys
import textwrap
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme

load_dotenv()

MODEL = "x-ai/grok-4.20-multi-agent-beta"
API_BASE = "https://openrouter.ai/api/v1"
XAI_API_BASE = "https://api.x.ai/v1"
DEFAULT_CONFIG = Path(__file__).parent / "agents.yaml"

# Map OpenRouter x-ai model IDs to native XAI model IDs (for direct XAI API)
XAI_MODEL_MAP = {
    "x-ai/grok-4.20-multi-agent-beta": "grok-4.20-multi-agent-beta-0309",
    "x-ai/grok-4.20-multi-agent-beta-0309": "grok-4.20-multi-agent-beta-0309",
    "x-ai/grok-4": "grok-4-0709",
    "x-ai/grok-4-0709": "grok-4-0709",
    "x-ai/grok-4-1-fast-reasoning": "grok-4-1-fast-reasoning",
    "x-ai/grok-4-1-fast-non-reasoning": "grok-4-1-fast-non-reasoning",
    "x-ai/grok-4-fast-reasoning": "grok-4-fast-reasoning",
    "x-ai/grok-4-fast-non-reasoning": "grok-4-fast-non-reasoning",
    "x-ai/grok-3": "grok-3",
    "x-ai/grok-3-mini": "grok-3-mini",
}

AGENT_COLORS = {
    "blue": "bold blue",
    "red": "bold red",
    "green": "bold green",
    "yellow": "bold yellow",
    "magenta": "bold magenta",
    "cyan": "bold cyan",
    "gold": "bold gold",
    "white": "bold white",
}

console = Console(highlight=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    name: str
    role: str
    system_prompt: str
    color: str = "cyan"
    model: str | None = None  # OpenRouter model; if unset, uses session.model

    @property
    def rich_color(self) -> str:
        return AGENT_COLORS.get(self.color, "bold cyan")


@dataclass
class AgentResponse:
    agent: Agent
    round_num: int
    content: str


@dataclass
class DM:
    sender: str
    recipient: str
    content: str
    round_num: int


# Private persuasion only: agents sway each other in DMs using logic and earnest appeal (e.g. begging, pleading), not bribes.
PERSUASION_NARRATIVE = (
    "In private messages you may only sway others with logic and earnest appeal "
    "(e.g. begging, pleading for their vote). No bribes of any kind — no money, "
    "crypto, favors, or promises of resources. Nothing of monetary value."
)


@dataclass
class DebateSession:
    question: str
    agents: list[Agent]
    model: str = MODEL
    stream_cross_debate: bool = True
    show_dm_indicators: bool = True
    rounds: list[list[AgentResponse]] = field(default_factory=list)
    dms: list[DM] = field(default_factory=list)
    inbox: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    resolutions: dict[str, str] = field(default_factory=dict)  # proposer_name -> resolution text
    vote_rounds: list[dict[str, str]] = field(default_factory=list)  # each round: voter_name -> proposer_name voted for


# ---------------------------------------------------------------------------
# Config + client
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> tuple[list[Agent], dict]:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    agents = [
        Agent(
            name=a["name"],
            role=a["role"],
            system_prompt=textwrap.dedent(a["system_prompt"]).strip(),
            color=a.get("color", "cyan"),
            model=a.get("model"),
        )
        for a in raw.get("agents", [])
    ]
    return agents, raw.get("settings", {})


_openrouter_client: AsyncOpenAI | None = None
_xai_client: AsyncOpenAI | None = None


def _get_openrouter_client() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            console.print(
                Panel(
                    "[bold red]OPENROUTER_API_KEY not set.[/]\n"
                    "Add it to [bold].env[/] or export it:\n"
                    "  [dim]export OPENROUTER_API_KEY=your_key_here[/]",
                    title="Missing API Key",
                    border_style="red",
                )
            )
            sys.exit(1)
        _openrouter_client = AsyncOpenAI(
            api_key=api_key,
            base_url=API_BASE,
            default_headers={
                "HTTP-Referer": "https://github.com/TheCouncil",
                "X-Title": "TheCouncil",
            },
        )
    return _openrouter_client


def _get_xai_client() -> AsyncOpenAI:
    global _xai_client
    if _xai_client is None:
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            console.print(
                Panel(
                    "[bold red]XAI_API_KEY not set.[/]\n"
                    "Add it to [bold].env[/] for Grok models:\n"
                    "  [dim]export XAI_API_KEY=your_key_here[/]",
                    title="Missing XAI API Key",
                    border_style="red",
                )
            )
            sys.exit(1)
        _xai_client = AsyncOpenAI(api_key=api_key, base_url=XAI_API_BASE)
    return _xai_client


def get_client_for_model(model: str) -> tuple[AsyncOpenAI, str]:
    """Return (client, resolved_model) for the given model. Uses XAI API when available for Grok models."""
    model = (model or MODEL).split(":")[0]
    if model in XAI_MODEL_MAP and os.getenv("XAI_API_KEY"):
        return _get_xai_client(), XAI_MODEL_MAP[model]
    return _get_openrouter_client(), model


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

# Cost efficiency: truncate older round responses when context grows. Same char budget as
# a single tail slice, but keep opening + closing so votes and later rounds still see thesis + conclusion.
_TRUNCATE_RESPONSE_CHARS = 420


def _truncate_response(content: str, max_chars: int = _TRUNCATE_RESPONSE_CHARS) -> str:
    """Truncate long responses for cost efficiency, preserving start + end (same budget as one slice)."""
    content = content.strip()
    if len(content) <= max_chars:
        return content
    sep = "\n… [earlier detail omitted] …\n"
    inner = max_chars - len(sep)
    if inner < 120:
        return content[: max_chars - 20].rsplit(maxsplit=1)[0] + "… [truncated]"
    head_budget = int(inner * 0.62)
    tail_budget = inner - head_budget
    head = content[:head_budget].rsplit(maxsplit=1)[0]
    tail = content[-tail_budget:].strip()
    # Avoid starting tail mid-word when possible
    if " " in tail[:24]:
        tail = tail[tail.find(" ") + 1 :].strip()
    if len(head) + len(sep) + len(tail) > max_chars + 40:
        return content[: max_chars - 20].rsplit(maxsplit=1)[0] + "… [truncated]"
    return head + sep + tail


def build_transcript(
    session: DebateSession,
    up_to_round: int,
    truncate_rounds_before: int | None = None,
) -> str:
    """Build public transcript from all rounds strictly before up_to_round.
    When truncate_rounds_before is set (e.g. 3), rounds before that get truncated responses."""
    ROUND_LABELS = {
        1: "Round 1 — Independent Takes",
        2: "Round 2 — Cross-Debate I",
        3: "Round 3 — Private Deliberation",
        4: "Round 4 — Cross-Debate II",
    }
    parts = []
    for responses in session.rounds:
        if not responses:
            continue
        rn = responses[0].round_num
        if rn >= up_to_round:
            break
        truncate = truncate_rounds_before is not None and rn < truncate_rounds_before
        label = ROUND_LABELS.get(rn, f"Round {rn} — Tie-Breaker Debate" if rn >= 5 else f"Round {rn}")
        parts.append(f"## {label}\n")
        for r in responses:
            content = _truncate_response(r.content) if truncate else r.content
            parts.append(f"### {r.agent.name} ({r.agent.role}):\n{content}\n")
    return "\n".join(parts)


def pop_inbox(session: DebateSession, agent_name: str) -> str:
    """Pop and format all pending DMs for this agent. Returns empty string if none."""
    messages: list[tuple[str, str]] = session.inbox.pop(agent_name, [])  # type: ignore[arg-type]
    if not messages:
        return ""
    lines = ["\n\n---\nPRIVATE MESSAGES (visible only to you):"]
    for sender, content in messages:
        lines.append(f"\nFrom {sender} (private): {content}")
    lines.append("---")
    return "\n".join(lines)


def deliver_dm(dm: DM, session: DebateSession) -> None:
    session.inbox[dm.recipient].append((dm.sender, dm.content))
    session.dms.append(dm)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def api_call(
    input_msgs: list[dict],
    max_tokens: int = 1024,
    model: str | None = None,
) -> str:
    """Non-streaming async call. Returns full output text. Routes to XAI or OpenRouter based on model."""
    client, resolved_model = get_client_for_model(model or MODEL)
    response = await client.responses.create(
        model=resolved_model,
        input=input_msgs,
        max_output_tokens=max_tokens,
    )
    return response.output_text or ""


async def api_stream(
    input_msgs: list[dict],
    max_tokens: int = 1024,
    model: str | None = None,
) -> str:
    """Streaming async call — prints tokens live. Use only in sequential context."""
    client, resolved_model = get_client_for_model(model or MODEL)
    collected: list[str] = []
    async with client.responses.stream(
        model=resolved_model,
        input=input_msgs,
        max_output_tokens=max_tokens,
    ) as stream:
        async for event in stream:
            if event.type == "response.output_text.delta":
                delta = event.delta or ""
                if delta:
                    collected.append(delta)
                    console.print(delta, end="", markup=False)
    console.print()
    return "".join(collected)


# ---------------------------------------------------------------------------
# DM system
# ---------------------------------------------------------------------------

_DM_SINGLE_PROMPT = """\
You have completed your public response. You may now send ONE private message \
to a single council member. This is completely secret — no one else will ever \
see it. It will be delivered as private context before their next response.

You may only sway them with logic and earnest appeal (e.g. begging, pleading for their vote). \
No bribes — no money, cryptocurrency, favors, or promises of resources. Nothing of monetary value. Use reason and persuasion only.

Available recipients: {recipients}

WORD LIMIT: Your message must be 50 words or fewer. Every word counts — be sharp and direct.

To send a DM, reply in EXACTLY this format:
TO: [exact agent name from the list above]
MESSAGE: [your private message — max 50 words]

To send nothing, reply exactly:
NO DM"""

_DM_MULTI_PROMPT = """\
This is a PRIVATE DELIBERATION ROUND. You will not give a public response. \
Instead, send private messages to any council member(s) you choose. \
Use this to share private concerns, make logical arguments, or appeal earnestly (e.g. beg, plead) for their vote. No bribes — no money, cryptocurrency, favors, or promises of resources. Nothing of monetary value. Logic and persuasion only.

Available recipients: {recipients}

WORD LIMIT: Each individual message must be 50 words or fewer. Every word counts — be sharp and direct.

Format (repeat for each DM):
---DM---
TO: [agent name]
MESSAGE: [your message — max 50 words]
---END---

If you have nothing to communicate privately, reply exactly:
NOTHING TO SAY"""


def _parse_single_dm(raw: str, sender: Agent, session: DebateSession, round_num: int) -> DM | None:
    raw = raw.strip()
    if not raw or raw.upper().startswith("NO DM") or "NO DM" in raw[:25].upper():
        return None

    to_line = ""
    message_lines: list[str] = []
    in_message = False

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TO:") and not to_line:
            to_line = stripped[3:].strip().strip('"').strip("'")
        elif stripped.upper().startswith("MESSAGE:"):
            in_message = True
            message_lines.append(stripped[8:].strip())
        elif in_message:
            message_lines.append(stripped)

    valid_names = {a.name for a in session.agents if a.name != sender.name}
    matched = next(
        (n for n in valid_names if n.lower() in to_line.lower() or to_line.lower() in n.lower()),
        None,
    )
    if not matched or not any(message_lines):
        return None

    return DM(
        sender=sender.name,
        recipient=matched,
        content="\n".join(message_lines).strip(),
        round_num=round_num,
    )


def _parse_multi_dm(raw: str, sender: Agent, session: DebateSession, round_num: int) -> list[DM]:
    raw = raw.strip()
    if not raw or "NOTHING TO SAY" in raw[:30].upper():
        return []

    dms: list[DM] = []
    valid_names = {a.name for a in session.agents if a.name != sender.name}

    for block in raw.split("---DM---"):
        if "---END---" not in block:
            continue
        block = block.split("---END---")[0].strip()

        to_line = ""
        message_lines: list[str] = []
        in_message = False

        for line in block.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("TO:") and not to_line:
                to_line = stripped[3:].strip().strip('"').strip("'")
            elif stripped.upper().startswith("MESSAGE:"):
                in_message = True
                message_lines.append(stripped[8:].strip())
            elif in_message:
                message_lines.append(stripped)

        matched = next(
            (n for n in valid_names if n.lower() in to_line.lower() or to_line.lower() in n.lower()),
            None,
        )
        if matched and any(message_lines):
            dms.append(DM(
                sender=sender.name,
                recipient=matched,
                content="\n".join(message_lines).strip(),
                round_num=round_num,
            ))

    return dms


async def _attempt_dm(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    public_response: str,
    prior_ctx: str,
) -> DM | None:
    """After a public response, ask agent if they want to DM someone."""
    other_names = ", ".join(f'"{a.name}"' for a in session.agents if a.name != agent.name)
    dm_prompt = _DM_SINGLE_PROMPT.format(recipients=other_names)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Question under debate: {session.question}\n\n"
            f"{prior_ctx}\n\n"
            f"Your public response:\n{public_response}\n\n"
            f"{dm_prompt}"
        )},
    ]
    model = agent.model or session.model
    raw = await api_call(input_msgs, max_tokens=120, model=model)
    return _parse_single_dm(raw, agent, session, round_num)


async def _dm_only_round(
    agent: Agent,
    session: DebateSession,
) -> list[DM]:
    """Round 3: agent generates private DMs, no public output."""
    prior_ctx = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    inbox_ctx = pop_inbox(session, agent.name)
    other_names = ", ".join(f'"{a.name}"' for a in session.agents if a.name != agent.name)
    dm_prompt = _DM_MULTI_PROMPT.format(recipients=other_names)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Question under debate: {session.question}\n\n"
            f"Full public debate transcript:\n{prior_ctx}"
            f"{inbox_ctx}\n\n"
            f"{dm_prompt}"
        )},
    ]
    # 4 agents × (header + 50-word message) = ~120 tokens each, 480 max for all DMs
    model = agent.model or session.model
    raw = await api_call(input_msgs, max_tokens=480, model=model)
    return _parse_multi_dm(raw, agent, session, 4)


# ---------------------------------------------------------------------------
# Round runners
# ---------------------------------------------------------------------------

async def _agent_round1(
    agent: Agent,
    session: DebateSession,
) -> tuple[AgentResponse, DM | None]:
    """Round 1: independent take (parallel, non-streaming)."""
    inbox_ctx = pop_inbox(session, agent.name)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"The council has been asked to evaluate:\n\n---\n{session.question}\n---\n\n"
            f"Provide your independent analysis. Do not hedge — be direct and specific."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]
    model = agent.model or session.model
    content = (await api_call(input_msgs, model=model)).strip()
    response = AgentResponse(agent=agent, round_num=1, content=content)

    dm = await _attempt_dm(agent, session, 1, content, "")
    return response, dm


async def _agent_cross_debate(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    already_responded: list[AgentResponse],
) -> tuple[AgentResponse, DM | None]:
    """Cross-debate round (sequential, streaming). Agent sees prior rounds + already-responded peers."""
    truncate_before = 3 if round_num >= 4 else None
    prior_ctx = build_transcript(session, up_to_round=round_num, truncate_rounds_before=truncate_before)
    inbox_ctx = pop_inbox(session, agent.name)

    # Agents who already spoke in THIS round are appended as "in-progress" context
    in_round_ctx = ""
    if already_responded:
        blocks = "\n\n".join(
            f"### {r.agent.name} (this round, just now):\n{r.content}"
            for r in already_responded
        )
        in_round_ctx = f"\n\n## Responses already given in this round:\n{blocks}"

    round_labels = {2: "Cross-Debate I", 4: "Cross-Debate II"}
    round_label = round_labels.get(round_num, f"Round {round_num}")

    console.print()
    console.rule(
        Text(f"  {agent.name}  ·  {agent.role}  ·  {round_label}  ", style=agent.rich_color)
    )
    console.print()

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Original question:\n\n---\n{session.question}\n---\n\n"
            f"{prior_ctx}{in_round_ctx}\n\n"
            f"Now engage in debate. Respond to the other experts — agree where they are right, "
            f"challenge where they are wrong. Name who you are responding to."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]

    model = agent.model or session.model
    start = time.monotonic()
    if session.stream_cross_debate:
        content = (await api_stream(input_msgs, model=model)).strip()
    else:
        content = (await api_call(input_msgs, model=model)).strip()
        console.print(content, markup=False)
    elapsed = time.monotonic() - start
    console.print(f"[dim]└─ {agent.name} finished in {elapsed:.1f}s[/]")

    response = AgentResponse(agent=agent, round_num=round_num, content=content)
    truncate_before = 3 if round_num >= 4 else None
    prior_for_dm = build_transcript(session, up_to_round=round_num, truncate_rounds_before=truncate_before)
    dm = await _attempt_dm(agent, session, round_num, content, prior_for_dm)
    return response, dm


async def _agent_tiebreaker_debate(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    tied_proposers: list[str],
    already_responded: list[AgentResponse],
) -> AgentResponse:
    """Tie-breaker debate: agents discuss only the tied resolutions. No DM."""
    prior_ctx = build_transcript(session, up_to_round=round_num, truncate_rounds_before=5)
    inbox_ctx = pop_inbox(session, agent.name)
    tied_resolutions = "\n\n".join(
        f"**{p}**: {session.resolutions[p]}" for p in tied_proposers
    )
    in_round_ctx = ""
    if already_responded:
        blocks = "\n\n".join(
            f"### {r.agent.name} (this round, just now):\n{r.content}"
            for r in already_responded
        )
        in_round_ctx = f"\n\n## Responses already given in this round:\n{blocks}"

    console.print()
    console.rule(
        Text(
            f"  {agent.name}  ·  {agent.role}  ·  Tie-Breaker Debate  ",
            style=agent.rich_color,
        )
    )
    console.print()

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Original question:\n\n---\n{session.question}\n---\n\n"
            f"{prior_ctx}{in_round_ctx}\n\n"
            f"These resolutions are TIED for first place. Debate which should win. "
            f"Focus only on these options:\n\n{tied_resolutions}\n\n"
            f"Engage with the other experts. Try to converge on one resolution."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]

    model = agent.model or session.model
    start = time.monotonic()
    if session.stream_cross_debate:
        content = (await api_stream(input_msgs, model=model)).strip()
    else:
        content = (await api_call(input_msgs, model=model)).strip()
        console.print(content, markup=False)
    elapsed = time.monotonic() - start
    console.print(f"[dim]└─ {agent.name} finished in {elapsed:.1f}s[/]")

    return AgentResponse(agent=agent, round_num=round_num, content=content)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_header(question: str, agents: list[Agent]) -> None:
    console.print()
    console.print(
        Panel(
            Text("⚖  C O U N C I L", style="bold white", justify="center"),
            subtitle="Mixture-of-Experts Decision Engine",
            border_style="blue",
            padding=(1, 4),
        )
    )
    console.print()
    panel_lines = "\n".join(
        f"  [{a.rich_color}]▸ {a.name}[/]  [dim]{a.role}[/]" for a in agents
    )
    console.print(
        Panel(
            f"[bold]Question:[/]\n  {question}\n\n[bold]Panel:[/]\n{panel_lines}",
            border_style="blue",
            title="[bold blue]Session[/]",
            padding=(1, 2),
        )
    )
    console.print()


def _print_async_responses(responses: list[AgentResponse]) -> None:
    """Display collected async responses one by one."""
    for r in responses:
        console.print()
        console.rule(
            Text(f"  {r.agent.name}  ·  {r.agent.role}  ", style=r.agent.rich_color)
        )
        console.print()
        console.print(r.content, markup=False)
        console.print()


def _print_dm_indicator(dm: DM) -> None:
    console.print()
    console.print(f"  [dim]📨  {dm.sender}  →  {dm.recipient}[/]")
    for line in dm.content.splitlines():
        console.print(f"  [dim]│  {line}[/]", markup=False)
    console.print()


# ---------------------------------------------------------------------------
# Resolution + vote
# ---------------------------------------------------------------------------

_PROPOSE_RESOLUTION_PROMPT = """\
Based on the debate, propose your own resolution for the council to vote on.
It must be one clear, actionable sentence (e.g. "The council recommends..." or "The council finds that...").
Reply with ONLY the resolution text. No preamble, no explanation."""


_VOTE_FOR_ONE_RESOLUTION_PROMPT = """\
Below are the resolutions still in contention. You must vote for exactly ONE.

{resolutions_block}

Review the debate. Pick the resolution you believe is best. You may vote for your own resolution.

Reply with EXACTLY one line in this format:
VOTE: [exact proposer name from the list above]

You may add one short sentence of rationale after the VOTE line if you wish, but the VOTE line must appear first."""


def _compute_vote_counts(votes: dict[str, str]) -> dict[str, int]:
    """Count votes per proposer. votes: voter_name -> proposer_name."""
    counts: dict[str, int] = defaultdict(int)
    for proposer in votes.values():
        if proposer:
            counts[proposer] += 1
    return dict(counts)


def _get_tied_winners(counts: dict[str, int]) -> list[str]:
    """Return proposers with max vote count. Single element if clear winner, 2+ if tie."""
    if not counts:
        return []
    max_count = max(counts.values())
    return [p for p, c in counts.items() if c == max_count]


def _parse_single_preference_vote(raw: str, valid_proposers: set[str]) -> str | None:
    """Extract proposer name from agent response. Returns None if unparseable or invalid."""
    raw_stripped = raw.strip()
    if not raw_stripped or not valid_proposers:
        return None
    # Normalize markdown / bullets that models sometimes add before VOTE:
    cleaned = raw_stripped.replace("**", "").replace("*", "")
    low = cleaned.lower()
    idx = low.find("vote:")
    if idx < 0:
        return None
    rest = cleaned[idx + 5 :].lstrip()
    first_line = rest.split("\n")[0].strip().strip('"\'')
    # Strip trailing parenthetical or em-dash rationale
    for cut in (" — ", " - ", " (", "\t"):
        if cut in first_line:
            first_line = first_line.split(cut)[0].strip()
            break
    if not first_line:
        return None
    fl = first_line.lower().rstrip(".!?:;")
    # Exact match first (case-insensitive), then prefix (e.g. "Red Teamer's resolution")
    for p in valid_proposers:
        if fl == p.lower():
            return p
    for p in sorted(valid_proposers, key=len, reverse=True):
        if fl.startswith(p.lower()):
            return p
    return None


async def _agent_propose_resolution(
    agent: Agent,
    session: DebateSession,
) -> str:
    """Agent proposes their own resolution. Returns resolution text."""
    transcript = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    user_content = (
        f"Original question:\n\n---\n{session.question}\n---\n\n"
        f"Debate transcript:\n\n{transcript}\n\n"
        f"{_PROPOSE_RESOLUTION_PROMPT}"
    )
    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": user_content},
    ]
    model = agent.model or session.model
    return (await api_call(input_msgs, max_tokens=200, model=model)).strip()


def _build_resolutions_block(resolutions_in_play: list[tuple[str, str]]) -> str:
    """Format resolutions for the vote prompt."""
    lines = []
    for proposer, resolution in resolutions_in_play:
        lines.append(f"Proposed by {proposer}:\n---\n{resolution}\n---")
    return "\n\n".join(lines)


async def _agent_vote_for_one_resolution(
    voter: Agent,
    session: DebateSession,
    resolutions_in_play: list[tuple[str, str]],
) -> str | None:
    """Agent votes for exactly one resolution. Returns proposer name or None if invalid."""
    transcript = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    resolutions_block = _build_resolutions_block(resolutions_in_play)
    valid_proposers = {p for p, _ in resolutions_in_play}
    user_content = (
        f"Original question:\n\n---\n{session.question}\n---\n\n"
        f"Debate transcript:\n\n{transcript}\n\n"
        f"{_VOTE_FOR_ONE_RESOLUTION_PROMPT.format(resolutions_block=resolutions_block)}"
    )
    input_msgs = [
        {"role": "system", "content": voter.system_prompt},
        {"role": "user", "content": user_content},
    ]
    model = voter.model or session.model
    raw = await api_call(input_msgs, max_tokens=120, model=model)
    return _parse_single_preference_vote(raw, valid_proposers)


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------

async def run_council(question: str, config_path: Path) -> None:
    agents, settings = load_config(config_path)

    if not agents:
        console.print("[bold red]No agents defined in config.[/]")
        sys.exit(1)

    session = DebateSession(
        question=question,
        agents=agents,
        model=settings.get("model", MODEL),
        stream_cross_debate=settings.get("stream_cross_debate", True),
        show_dm_indicators=settings.get("show_dm_indicators", True),
    )
    _print_header(question, agents)
    console.print()

    # ── ROUND 1: INDEPENDENT (async parallel) ──────────────────────────────
    console.rule(Text("  ROUND 1 ·  INDEPENDENT TAKES  ", style="bold yellow"), style="yellow")
    console.print("\n[dim]All agents deliberating simultaneously…[/]\n")

    r1_results = await asyncio.gather(
        *[_agent_round1(agent, session) for agent in agents]
    )

    round1_responses = [res for res, _ in r1_results]
    session.rounds.append(round1_responses)
    _print_async_responses(round1_responses)

    for _, dm in r1_results:
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    # ── ROUND 2: CROSS-DEBATE I (sequential, streaming) ───────────────────
    console.print()
    console.rule(Text("  ROUND 2  ·  CROSS-DEBATE I  ", style="bold yellow"), style="yellow")

    round2_responses: list[AgentResponse] = []
    for agent in agents:
        response, dm = await _agent_cross_debate(agent, session, 2, round2_responses)
        round2_responses.append(response)
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    session.rounds.append(round2_responses)

    # ── ROUND 3: PRIVATE DELIBERATION (async parallel, DM-only) ───────────
    console.print()
    console.rule(
        Text("  ROUND 3  ·  PRIVATE DELIBERATION  ", style="bold magenta"), style="magenta"
    )
    console.print("\n[dim]Agents exchanging private messages…[/]\n")

    dm_batches = await asyncio.gather(
        *[_dm_only_round(agent, session) for agent in agents]
    )

    round3_dms: list[DM] = []
    for batch in dm_batches:
        for dm in batch:
            round3_dms.append(dm)
            # Deliver to inbox — agents will see these in Cross-Debate II (also records dm once)
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                console.print()
                console.print(f"  [dim]🔒  {dm.sender}  →  {dm.recipient}[/]")
                for line in dm.content.splitlines():
                    console.print(f"  [dim]│  {line}[/]", markup=False)
                console.print()

    if not round3_dms:
        console.print("  [dim]No private messages exchanged.[/]")

    # ── ROUND 4: CROSS-DEBATE II (sequential, streaming) ──────────────────
    console.print()
    console.rule(Text("  ROUND 4  ·  CROSS-DEBATE II  ", style="bold yellow"), style="yellow")

    round4_responses: list[AgentResponse] = []
    for agent in agents:
        response, dm = await _agent_cross_debate(agent, session, 4, round4_responses)
        round4_responses.append(response)
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    session.rounds.append(round4_responses)

    # ── EACH AGENT PROPOSES A RESOLUTION ───────────────────────────────────
    console.print()
    console.rule(
        Text("  PROPOSE RESOLUTIONS  ", style="bold white on dark_magenta"),
        style="magenta",
    )
    console.print()

    for agent in agents:
        resolution = await _agent_propose_resolution(agent, session)
        session.resolutions[agent.name] = resolution
        console.print(f"  [{agent.rich_color}]{agent.name}[/]:")
        console.print(Panel(resolution, border_style="dim", padding=(0, 2)))
        console.print()

    # ── VOTE FOR ONE RESOLUTION (with tie-breaker loop) ──────────────────────
    MAX_TIEBREAKER_ROUNDS = 5
    active_resolutions = list(session.resolutions.keys())
    tiebreaker_round = 5
    final_winner: str | None = None

    while True:
        console.rule(
            Text(
                f"  VOTE  ·  Pick one resolution  "
                + ("(tie-breaker)" if len(active_resolutions) < len(session.resolutions) else ""),
                style="bold yellow",
            ),
            style="yellow",
        )
        console.print()

        resolutions_in_play = [(p, session.resolutions[p]) for p in active_resolutions]
        votes: dict[str, str] = {}

        for voter in agents:
            voted_for = await _agent_vote_for_one_resolution(
                voter, session, resolutions_in_play
            )
            if voted_for:
                votes[voter.name] = voted_for
                console.print(
                    f"  [{voter.rich_color}]{voter.name}[/]: [bold]{voted_for}[/]"
                )
            else:
                console.print(
                    f"  [{voter.rich_color}]{voter.name}[/]: [dim](invalid vote, skipped)[/]"
                )

        session.vote_rounds.append(votes)
        counts = _compute_vote_counts(votes)
        winners = _get_tied_winners(counts)

        for p, c in sorted(counts.items(), key=lambda x: -x[1]):
            console.print(f"  [dim]→ {p}: {c} vote(s)[/]")
        console.print()

        if len(winners) == 1:
            final_winner = winners[0]
            break

        # No valid votes: keep current set and run tie-breaker
        if not winners:
            winners = active_resolutions

        # Tie: run tie-breaker debate
        if tiebreaker_round - 5 >= MAX_TIEBREAKER_ROUNDS:
            console.print(
                "[dim]Max tie-breaker rounds reached. Picking first tied resolution.[/]"
            )
            final_winner = winners[0]
            break

        active_resolutions = winners
        console.rule(
            Text(f"  TIE-BREAKER  ·  Debate round {tiebreaker_round - 4}  ", style="bold magenta"),
            style="magenta",
        )
        console.print(
            f"\n[dim]Resolutions still in contention: {', '.join(active_resolutions)}[/]\n"
        )

        tiebreaker_responses: list[AgentResponse] = []
        for agent in agents:
            response = await _agent_tiebreaker_debate(
                agent, session, tiebreaker_round, active_resolutions, tiebreaker_responses
            )
            tiebreaker_responses.append(response)
        session.rounds.append(tiebreaker_responses)
        tiebreaker_round += 1

    # ── FINAL RESOLUTION ────────────────────────────────────────────────────
    console.rule(Text("  COUNCIL CONSENSUS  ", style="bold white on dark_blue"), style="blue")
    console.print()
    if final_winner:
        final_resolution = session.resolutions[final_winner]
        console.print(
            Panel(
                final_resolution,
                title=f"[bold green]Final Resolution[/] (proposed by {final_winner})",
                border_style="green",
                padding=(1, 2),
            )
        )
        console.print()
    console.rule(Text("  SESSION COMPLETE  ", style="bold white on dark_blue"), style="blue")
    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_agents(config_path: Path) -> None:
    agents, _ = load_config(config_path)
    console.print()
    console.print(Panel("[bold]Configured Agents[/]", border_style="blue"))
    for a in agents:
        console.print(f"  [{a.rich_color}]▸ {a.name}[/]  [dim]{a.role}[/]")
    console.print()


def interactive_mode(config_path: Path) -> None:
    console.print()
    console.print(
        Panel(
            "[bold]Council — Interactive Mode[/]\n"
            "[dim]Type your question and press Enter. Type [bold]quit[/] to exit.[/]",
            border_style="blue",
        )
    )
    while True:
        console.print()
        try:
            question = console.input("[bold blue]Council >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/]")
            break

        if question.lower() in ("quit", "exit", "q"):
            console.print("[dim]Exiting.[/]")
            break
        if not question:
            continue

        asyncio.run(run_council(question, config_path))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Council — Multi-agent expert debate system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python council.py "Is this JWT auth design secure?"
              python council.py "Should I use PostgreSQL or MongoDB?"
              python council.py --config my_panel.yaml "What tech stack should I choose?"
              python council.py --list-agents
            """
        ),
    )
    parser.add_argument("question", nargs="?", help="Question to put to the expert panel")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        metavar="FILE",
        help="Path to agents YAML config (default: agents.yaml)",
    )
    parser.add_argument("--list-agents", action="store_true", help="List configured agents")

    args = parser.parse_args()

    if args.list_agents:
        list_agents(args.config)
        return

    if args.question:
        asyncio.run(run_council(args.question, args.config))
    else:
        interactive_mode(args.config)


if __name__ == "__main__":
    main()
