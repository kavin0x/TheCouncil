"""
Celery tasks for TheCouncil background workers.

Tasks:
  execute_council_run — picks up a queued run, executes the debate,
                        persists result/artifact, publishes events to
                        the Redis Streams bus.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery import Task  # type: ignore[import]

from council.worker.celery_app import celery_app

log = logging.getLogger(__name__)


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="council.worker.tasks.execute_council_run",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def execute_council_run(self: Task, run_id: str) -> dict[str, Any]:
    """Execute a council debate run identified by *run_id*.

    Transitions: PENDING → RUNNING → COMPLETED | FAILED.
    Publishes structured events to the Redis Streams bus on each transition.
    """
    return _run_async(_execute_run_async(self, run_id))


async def _execute_run_async(task: Task, run_id: str) -> dict[str, Any]:
    from council.models.state import RunStatus, run_store
    from council.core.runner import CouncilRunBlockedError, run_council_for_api
    from council.features.sandbox import SandboxDisabledError, run_sandbox_task
    from council.models.subscriptions import get_tier, TierName
    from council.bus.redis_bus import bus

    start = time.monotonic()

    try:
        run = await run_store.update_status(run_id, RunStatus.RUNNING)
    except Exception as exc:
        log.error("Could not transition run %s to RUNNING: %s", run_id, exc)
        raise

    await bus.publish_event(run_id, "run_started", {"run_id": run_id})

    try:
        run_kind = str((run.config or {}).get("run_kind") or "council").strip().lower()

        if run_kind == "sandbox":
            tier_raw = (run.config or {}).get("tier", TierName.BASIC.value)
            try:
                tier = TierName(tier_raw)
            except ValueError:
                tier = TierName.BASIC
            if not get_tier(tier).limits.computer_use_enabled:
                raise SandboxDisabledError("Computer-use sandbox requires Ultra or Enterprise.")
            result = await run_sandbox_task(question=run.question, config=run.config)
        else:
            result = await run_council_for_api(
                question=run.question,
                config=run.config,
                owner_id=run.owner_id,
            )

        await run_store.update_status(run_id, RunStatus.COMPLETED, result=result)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        await bus.publish_event(
            run_id,
            "run_completed",
            {
                "run_id": run_id,
                "winner": result.get("winner"),
                "final_resolution": result.get("final_resolution", ""),
                "elapsed_ms": elapsed_ms,
            },
        )

        # Build and persist artifact
        await _persist_artifact(run_id, run.owner_id, run.question, result)

        return result

    except (CouncilRunBlockedError, SandboxDisabledError) as exc:
        error_msg = str(exc)
        await run_store.update_status(run_id, RunStatus.FAILED, error=error_msg)
        await bus.publish_event(run_id, "run_failed", {"run_id": run_id, "error": error_msg})
        return {"error": error_msg}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("Run %s failed with unhandled exception", run_id)

        # Retry if we haven't exhausted retries — do NOT mark FAILED yet
        if task.request.retries < task.max_retries:
            raise task.retry(exc=exc)

        await run_store.update_status(run_id, RunStatus.FAILED, error=error_msg)
        await bus.publish_event(run_id, "run_failed", {"run_id": run_id, "error": error_msg})
        return {"error": error_msg}


async def _persist_artifact(
    run_id: str, owner_id: str, question: str, result: dict[str, Any]
) -> None:
    """Build a structured Artifact record from the run result."""
    try:
        from council.db.session import get_engine
        if get_engine() is None:
            return  # no DB configured, skip

        from council.db.session import _session_factory  # type: ignore[attr-defined]
        if _session_factory is None:
            return

        from council.db.models import Artifact

        # Extract structured data from the result
        top3 = result.get("top3", [])
        resolutions = result.get("resolutions", {})
        vote_rounds = result.get("vote_rounds", [])
        winner = result.get("winner", "")
        final_resolution = result.get("final_resolution", "")

        # Build dissenting opinions from agents who didn't win
        agents_in_run = result.get("agents", [])
        dissenting = []
        for agent_info in agents_in_run:
            agent_name = agent_info.get("name", "")
            if agent_name == winner:
                continue
            agent_resolution = resolutions.get(agent_name, "")
            if agent_resolution and agent_resolution != final_resolution:
                dissenting.append({
                    "agent": agent_name,
                    "role": agent_info.get("role", ""),
                    "opinion": agent_resolution,
                })

        # Build decision rationale from top3 analyses
        rationale_parts = []
        for res in top3:
            rationale_parts.append(
                f"**{res.get('agent')} ({res.get('role')})**: {res.get('summary', '')}"
            )
        decision_rationale = "\n\n".join(rationale_parts)

        artifact = Artifact(
            id=f"art-{run_id}",
            deliberation_id=run_id,
            owner_id=owner_id,
            question=question,
            decision_rationale=decision_rationale,
            recommended_action=final_resolution,
            dissenting_opinions=dissenting,
            consensus_resolution=final_resolution,
            agent_votes={"rounds": vote_rounds, "winner": winner},
            top3_resolutions=top3,
            full_result=result,
        )

        async with _session_factory() as session:
            session.add(artifact)
            await session.commit()

    except Exception as exc:
        # Artifact persistence is non-critical — log and continue
        log.warning("Artifact persistence failed for run %s: %s", run_id, exc)
