"""Deliberation event emission: Redis stream + in-process WebSocket when Redis is off."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from council.bus.redis_bus import bus as _bus

log = logging.getLogger(__name__)

_ws_broadcast: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None


def register_ws_broadcast(
    fn: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    """Register FastAPI ``_ws_broadcast`` so NullBus dev mode still pushes to WebSockets."""
    global _ws_broadcast
    _ws_broadcast = fn


def _uses_redis_stream() -> bool:
    return hasattr(_bus, "_redis")


async def _post_event_bridge(body: dict[str, Any]) -> None:
    """When events are emitted from a separate process (e.g. Celery) with no Redis, forward to the API."""
    url = os.getenv("COUNCIL_API_EVENT_BRIDGE_URL", "").strip()
    secret = os.getenv("API_SECRET_KEY", "").strip()
    if not url or not secret:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {secret}"},
            )
            r.raise_for_status()
    except Exception as exc:
        log.debug("Event bridge POST failed (non-fatal): %s", exc)


async def emit_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Publish to Redis when configured; mirror to in-process WS subscribers when not."""
    ts = time.time()
    await _bus.publish_event(run_id, event_type, payload)
    body: dict[str, Any] = {
        "type": event_type,
        "run_id": run_id,
        "ts": ts,
        **payload,
    }
    if _uses_redis_stream():
        return
    if _ws_broadcast is not None:
        await _ws_broadcast(run_id, body)
    else:
        await _post_event_bridge(body)
