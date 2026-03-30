"""Deliberation event emission: Redis stream + in-process WebSocket when Redis is off."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from council.bus.redis_bus import bus as _bus

_ws_broadcast: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None


def register_ws_broadcast(
    fn: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    """Register FastAPI ``_ws_broadcast`` so NullBus dev mode still pushes to WebSockets."""
    global _ws_broadcast
    _ws_broadcast = fn


def _uses_redis_stream() -> bool:
    return hasattr(_bus, "_redis")


async def emit_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Publish to Redis when configured; mirror to in-process WS subscribers when not."""
    ts = time.time()
    await _bus.publish_event(run_id, event_type, payload)
    if not _uses_redis_stream() and _ws_broadcast is not None:
        body: dict[str, Any] = {
            "type": event_type,
            "run_id": run_id,
            "ts": ts,
            **payload,
        }
        await _ws_broadcast(run_id, body)
