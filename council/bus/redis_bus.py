"""
Redis Streams message bus for TheCouncil deliberation engine.

Architecture:
  - One Redis Stream per deliberation run: `council:run:{run_id}:events`
  - A shared work queue stream: `council:work:queue`
  - Consumer groups for work queue: `council_workers`
  - Dead-letter stream: `council:work:dlq` (after max_retries failures)

Message types published to a run's event stream:
  run_started      — worker claimed the run
  agents_announced — panel roster for UI bootstrap
  agent_response   — an agent produced a response in a debate round
  agent_delta      — token chunk while streaming a cross-debate reply
  agent_dm         — private DM between two agents
  resolution_vote  — agent cast a vote for a resolution
  run_completed    — run finished successfully; includes artifact summary
  run_failed       — run terminated with an error

The bus degrades gracefully: when REDIS_URL is unset it silently no-ops all
publishes and returns empty reads, allowing tests and local dev without Redis.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")

# Stream / group names
_WORK_STREAM = "council:work:queue"
_WORK_GROUP = "council_workers"
_DLQ_STREAM = "council:work:dlq"
_CONSUMER_NAME = f"worker-{os.getpid()}"

_MAX_STREAM_LEN = 10_000  # approximate cap per run stream (MAXLEN ~)
_BLOCK_MS = 2_000         # blocking read timeout in ms
_MAX_RETRIES = 3          # before dead-lettering


def _run_stream(run_id: str) -> str:
    return f"council:run:{run_id}:events"


class _NullBus:
    """No-op bus used when Redis is not configured."""

    async def publish_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        pass

    async def read_run_events(
        self, run_id: str, last_id: str = "0-0"
    ) -> AsyncGenerator[dict[str, Any], None]:
        return
        yield  # make it an async generator

    async def enqueue_run(self, run_id: str) -> None:
        pass

    async def dequeue_run(self) -> tuple[str, str] | None:
        return None

    async def ack_run(self, msg_id: str) -> None:
        pass

    async def dead_letter_run(self, run_id: str, msg_id: str, reason: str) -> None:
        pass

    async def close(self) -> None:
        pass


class RedisBus:
    """Redis Streams-backed message bus."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # type: ignore[import]

        self._redis = aioredis.from_url(url, decode_responses=True)
        self._initialized_groups: set[str] = set()

    async def _ensure_work_group(self) -> None:
        if _WORK_GROUP in self._initialized_groups:
            return
        try:
            await self._redis.xgroup_create(
                _WORK_STREAM, _WORK_GROUP, id="0", mkstream=True
            )
        except Exception as exc:
            # BUSYGROUP means group already exists — that's fine
            if "BUSYGROUP" not in str(exc):
                log.warning("xgroup_create warning: %s", exc)
        self._initialized_groups.add(_WORK_GROUP)

    async def publish_event(
        self, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Publish a structured event to the run's dedicated event stream."""
        stream = _run_stream(run_id)
        fields = {
            "type": event_type,
            "run_id": run_id,
            "ts": str(time.time()),
            "payload": json.dumps(payload, default=str),
        }
        try:
            await self._redis.xadd(stream, fields, maxlen=_MAX_STREAM_LEN, approximate=True)
        except Exception as exc:
            log.warning("Failed to publish event %s for run %s: %s", event_type, run_id, exc)

    async def read_run_events(
        self, run_id: str, last_id: str = "0-0"
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator that yields events from a run's stream since last_id.

        Blocking reads time out periodically with no rows; the loop continues
        until a terminal event is yielded (run_completed / run_failed).
        """
        stream = _run_stream(run_id)
        current_id = last_id
        while True:
            try:
                entries = await self._redis.xread(
                    {stream: current_id}, count=100, block=_BLOCK_MS
                )
            except Exception as exc:
                log.warning("xread error for run %s: %s", run_id, exc)
                break

            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, fields in messages:
                    current_id = msg_id
                    event: dict[str, Any] = {"id": msg_id, "type": fields.get("type", "")}
                    raw_payload = fields.get("payload", "{}")
                    try:
                        event.update(json.loads(raw_payload))
                    except json.JSONDecodeError:
                        event["raw"] = raw_payload
                    event["ts"] = float(fields.get("ts", 0))
                    event["run_id"] = fields.get("run_id", run_id)
                    yield event
                    if event.get("type") in ("run_completed", "run_failed"):
                        return

    async def enqueue_run(self, run_id: str) -> None:
        """Push a run_id onto the shared work queue stream."""
        await self._ensure_work_group()
        try:
            await self._redis.xadd(
                _WORK_STREAM,
                {"run_id": run_id, "enqueued_at": str(time.time())},
                maxlen=50_000,
                approximate=True,
            )
        except Exception as exc:
            log.error("Failed to enqueue run %s: %s", run_id, exc)
            raise

    async def dequeue_run(self) -> tuple[str, str] | None:
        """Block up to BLOCK_MS and return (msg_id, run_id) or None."""
        await self._ensure_work_group()
        try:
            result = await self._redis.xreadgroup(
                _WORK_GROUP,
                _CONSUMER_NAME,
                {_WORK_STREAM: ">"},
                count=1,
                block=_BLOCK_MS,
            )
        except Exception as exc:
            log.warning("xreadgroup error: %s", exc)
            return None

        if not result:
            return None

        for _stream, messages in result:
            for msg_id, fields in messages:
                return msg_id, fields.get("run_id", "")
        return None

    async def ack_run(self, msg_id: str) -> None:
        """Acknowledge successful processing of a work message."""
        try:
            await self._redis.xack(_WORK_STREAM, _WORK_GROUP, msg_id)
        except Exception as exc:
            log.warning("xack failed for msg %s: %s", msg_id, exc)

    async def dead_letter_run(self, run_id: str, msg_id: str, reason: str) -> None:
        """Move a failed run to the dead-letter stream after exhausting retries."""
        try:
            await self._redis.xadd(
                _DLQ_STREAM,
                {
                    "run_id": run_id,
                    "original_msg_id": msg_id,
                    "reason": reason,
                    "failed_at": str(time.time()),
                },
                maxlen=10_000,
                approximate=True,
            )
            await self._redis.xack(_WORK_STREAM, _WORK_GROUP, msg_id)
        except Exception as exc:
            log.error("Dead-letter failed for run %s: %s", run_id, exc)

    async def close(self) -> None:
        await self._redis.aclose()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

def _build_bus() -> RedisBus | _NullBus:
    if not REDIS_URL:
        log.debug("REDIS_URL not set — using in-process null bus.")
        return _NullBus()
    try:
        return RedisBus(REDIS_URL)
    except Exception as exc:
        log.warning("Redis bus unavailable (%s) — falling back to null bus.", exc)
        return _NullBus()


bus: RedisBus | _NullBus = _build_bus()
