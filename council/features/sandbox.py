"""Sandbox features for TheCouncil.

Two sandbox modes:
  1. Code execution sandbox (e2b): run a bounded shell command (original).
  2. Desktop sandbox (e2b-desktop): Ubuntu 22.04 + XFCE, used for computer-use
     agent loops. One sandbox per session (session-scoped singleton).

Access is tier-gated: computer-use requires Ultra or Enterprise.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sandbox command validation
# ---------------------------------------------------------------------------

_ALLOWED_SANDBOX_COMMANDS = frozenset({
    "python", "python3", "node", "bash", "sh", "echo", "cat", "ls", "pwd",
    "env", "printenv", "uname", "whoami", "date", "which", "head", "tail",
    "wc", "sort", "uniq", "grep", "find", "curl", "wget", "pip", "pip3",
    "npm", "npx", "java", "javac", "go", "ruby", "perl", "r",
})

# Shell metacharacters that allow command chaining or redirection
_SHELL_METACHAR_RE = re.compile(r"[|;&`$<>{}()\n\r]|\$\(|&&|\|\|")


def _validate_sandbox_cmd(cmd: str) -> str:
    """Validate a sandbox command string against an allowlist and reject shell metacharacters.

    Raises ValueError if the command is unsafe.
    """
    cmd = cmd.strip()
    if not cmd:
        return "python -c \"print('TheCouncil sandbox ready')\""

    if _SHELL_METACHAR_RE.search(cmd):
        raise ValueError(
            "sandbox_cmd contains disallowed shell metacharacters. "
            "Use a simple command without pipes, semicolons, redirects, or subshells."
        )

    base_command = cmd.split()[0].lower()
    # Strip any path prefix (e.g., /usr/bin/python → python)
    base_command = base_command.rsplit("/", 1)[-1]

    if base_command not in _ALLOWED_SANDBOX_COMMANDS:
        raise ValueError(
            f"sandbox_cmd base command {base_command!r} is not in the allowed command list. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SANDBOX_COMMANDS))}"
        )

    return cmd

# Desktop sandbox defaults (configurable via env if needed in future).
_DESKTOP_RESOLUTION = (1024, 720)
_DESKTOP_TIMEOUT_SECS = 300


class SandboxDisabledError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Session-scoped Desktop sandbox registry
# One Sandbox instance per active session_id; killed on session end/timeout.
# ---------------------------------------------------------------------------
_desktop_sandboxes: dict[str, Any] = {}
_desktop_sandbox_lock = asyncio.Lock()


async def get_or_create_desktop_sandbox(session_id: str) -> Any:
    """Return the existing Desktop sandbox for *session_id*, or create one.

    Uses e2b-desktop (``e2b_desktop.Sandbox``). Requires E2B_API_KEY.
    The sandbox streams its XFCE desktop over VNC; call
    ``sandbox.stream.get_url()`` to obtain the viewer URL.
    """
    api_key = os.getenv("E2B_API_KEY", "")
    if not api_key:
        raise SandboxDisabledError("E2B_API_KEY is not set.")

    try:
        from e2b_desktop import Sandbox  # type: ignore[import]
    except Exception as exc:  # pragma: no cover
        raise SandboxDisabledError(f"e2b-desktop SDK unavailable: {exc}") from exc

    async with _desktop_sandbox_lock:
        if session_id in _desktop_sandboxes:
            return _desktop_sandboxes[session_id]

        # Create a new Ubuntu 22.04 + XFCE desktop sandbox with VNC streaming.
        sandbox = Sandbox(api_key=api_key, resolution=_DESKTOP_RESOLUTION, timeout=_DESKTOP_TIMEOUT_SECS)
        await sandbox.stream.start()
        _desktop_sandboxes[session_id] = sandbox
        return sandbox


async def kill_desktop_sandbox(session_id: str) -> None:
    """Kill and remove the Desktop sandbox for *session_id* (no-op if none)."""
    async with _desktop_sandbox_lock:
        sandbox = _desktop_sandboxes.pop(session_id, None)
    if sandbox is not None:
        try:
            await sandbox.kill()
        except Exception as exc:
            logger.warning("Failed to kill Desktop sandbox for session %r: %s", session_id, exc)


async def get_desktop_sandbox_stream_url(session_id: str) -> str:
    """Return the VNC stream URL for the active Desktop sandbox.

    Creates the sandbox if it doesn't exist yet.
    """
    sandbox = await get_or_create_desktop_sandbox(session_id)
    return sandbox.stream.get_url()


async def run_computer_use_step(
    sandbox: Any,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single computer-use action on the Desktop sandbox.

    Supported action types (matching the E2B Desktop SDK):
      left_click, right_click, double_click, write, press, scroll, drag, screenshot

    Returns a dict with the outcome (e.g. screenshot bytes encoded as base64 for
    screenshot actions, or a confirmation for other actions).
    """
    import base64

    action_type = action.get("type", "screenshot")

    if action_type == "screenshot":
        img_bytes = await sandbox.screenshot()
        return {"type": "screenshot", "data": base64.b64encode(img_bytes).decode()}

    if action_type == "left_click":
        await sandbox.left_click(action["x"], action["y"])
    elif action_type == "right_click":
        await sandbox.right_click(action["x"], action["y"])
    elif action_type == "double_click":
        await sandbox.double_click(action["x"], action["y"])
    elif action_type == "write":
        await sandbox.write(action["text"])
    elif action_type == "press":
        await sandbox.press(action["key"])
    elif action_type == "scroll":
        await sandbox.scroll(action["x"], action["y"], action.get("direction", "down"), action.get("amount", 3))
    elif action_type == "drag":
        await sandbox.drag(action["start_x"], action["start_y"], action["end_x"], action["end_y"])
    else:
        return {"type": "error", "message": f"Unknown action type: {action_type!r}"}

    return {"type": action_type, "status": "ok"}


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

    raw_cmd = str(cfg.get("sandbox_cmd") or "")
    try:
        cmd = _validate_sandbox_cmd(raw_cmd)
    except ValueError as exc:
        raise ValueError(f"Invalid sandbox_cmd: {exc}") from exc
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


