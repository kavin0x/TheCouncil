from __future__ import annotations

import os
import time
from typing import Any


class SandboxDisabledError(RuntimeError):
    pass


async def run_sandbox_task(*, question: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ultra-only sandbox pipeline (E2B).

    For the prototype we keep this intentionally small: spin up a sandbox, run a bounded
    command, and return stdout/stderr. A CUA-capable model can be invoked by a later step
    using `SANDBOX_CUA_MODEL`, but we keep the initial demo deterministic and bounded.
    """
    if os.getenv("E2B_API_KEY", "") == "":
        raise SandboxDisabledError("E2B_API_KEY is not set.")

    try:
        from e2b import Sandbox  # type: ignore[import]
    except Exception as exc:  # pragma: no cover
        raise SandboxDisabledError(f"E2B SDK unavailable: {exc}") from exc

    cfg = config or {}
    start = time.monotonic()

    # Small bounded demo command. (Optionally pass a URL in config in future.)
    cmd = str(cfg.get("sandbox_cmd") or "python -c \"print('TheCouncil sandbox ready')\"")
    timeout_s = int(cfg.get("sandbox_timeout_s") or 60)

    with Sandbox.create() as sb:
        res = sb.commands.run(cmd, timeout=timeout_s)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "kind": "sandbox",
        "cmd": cmd,
        "stdout": getattr(res, "stdout", ""),
        "stderr": getattr(res, "stderr", ""),
        "exit_code": getattr(res, "exit_code", None),
        "meta": {
            "elapsed_ms": elapsed_ms,
            "generated_at": time.time(),
            "cua_model": os.getenv("SANDBOX_CUA_MODEL") or None,
        },
    }

