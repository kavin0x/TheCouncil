"""Sandbox features for TheCouncil using Docker.

Two sandbox modes:
  1. Code execution sandbox (Docker): run a bounded shell command in a container.
  2. Desktop sandbox (Docker + noVNC): Optional Ubuntu container with VNC/noVNC for computer-use.
     Not implemented by default; users can add custom implementation.

Both modes are available in self-hosted deployments.
"""

from __future__ import annotations

import asyncio
import base64
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
    "wc", "sort", "uniq", "grep", "find", "pip", "pip3",
    # curl and wget intentionally excluded: containers run with network_mode="none",
    # making network tools non-functional. Removing them also eliminates the SSRF
    # attack surface (VULN-04) should network isolation ever be relaxed.
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


# Desktop sandbox defaults
_DESKTOP_RESOLUTION = (1024, 720)
_DESKTOP_TIMEOUT_SECS = 300


class SandboxDisabledError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Session-scoped Desktop sandbox registry
# One container per active session_id; killed on session end/timeout.
# ---------------------------------------------------------------------------
_desktop_sandboxes: dict[str, Any] = {}
_desktop_sandbox_lock = asyncio.Lock()


async def get_or_create_desktop_sandbox(session_id: str) -> Any:
    """Return the existing Desktop sandbox for *session_id*, or create one.

    Docker + noVNC-based desktop sandbox. Not implemented by default; this is
    a placeholder showing the integration pattern for users who want to add VNC
    desktop support to their deployment.

    To implement:
      1. Spin up an Ubuntu container with XFCE desktop environment
      2. Install and start VNC server (e.g., tigervnc)
      3. Install and configure noVNC for web-based access
      4. Return container object with stream.get_url() method

    Raises SandboxDisabledError until custom integration is added.
    """
    raise SandboxDisabledError(
        "Desktop sandbox (computer-use with VNC) is not implemented by default. "
        "To enable, integrate Docker + XFCE + noVNC following the pattern in "
        "council/features/sandbox.py:get_or_create_desktop_sandbox()."
    )


async def kill_desktop_sandbox(session_id: str) -> None:
    """Kill and remove the Desktop sandbox for *session_id* (no-op if none)."""
    async with _desktop_sandbox_lock:
        sandbox = _desktop_sandboxes.pop(session_id, None)
    if sandbox is not None:
        try:
            # Placeholder: call container.kill() when implemented
            logger.debug("Desktop sandbox cleanup placeholder for session %r", session_id)
        except Exception as exc:
            logger.warning("Failed to cleanup Desktop sandbox for session %r: %s", session_id, exc)


async def get_desktop_sandbox_stream_url(session_id: str) -> str:
    """Return the VNC stream URL for the active Desktop sandbox.

    Creates the sandbox if it doesn't exist yet. Placeholder implementation.
    """
    await get_or_create_desktop_sandbox(session_id)


async def run_computer_use_step(
    sandbox: Any,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single computer-use action on the Desktop sandbox (placeholder).

    Supported action types:
      left_click, right_click, double_click, write, press, scroll, drag, screenshot

    Returns a dict with the outcome.
    """
    raise SandboxDisabledError(
        "Desktop sandbox is not implemented. See get_or_create_desktop_sandbox() for integration details."
    )


async def run_sandbox_task(*, question: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Code execution sandbox using Docker.

    Spins up a temporary Docker container, runs a bounded command, and returns output.
    Uses python:3.11-slim as the default image.
    """
    try:
        import docker  # type: ignore[import]
    except ImportError:
        raise SandboxDisabledError(
            "Docker SDK not installed. Install with: pip install docker"
        )

    cfg = config or {}
    start = time.monotonic()

    raw_cmd = str(cfg.get("sandbox_cmd") or "")
    try:
        cmd = _validate_sandbox_cmd(raw_cmd)
    except ValueError as exc:
        raise ValueError(f"Invalid sandbox_cmd: {exc}") from exc

    timeout_s = int(cfg.get("sandbox_timeout_s") or 60)

    try:
        client = docker.from_env()
    except Exception as exc:
        raise SandboxDisabledError(f"Failed to connect to Docker daemon: {exc}") from exc

    try:
        result = client.containers.run(
            "python:3.11-slim",
            cmd,
            remove=True,
            timeout=timeout_s,
            network_mode="none",           # block all outbound network access (SSRF prevention)
            security_opt=["no-new-privileges:true"],  # prevent privilege escalation
        )
        stdout = result.decode() if isinstance(result, bytes) else str(result)
        stderr = ""
        exit_code = 0
    except Exception:
        # For simplicity, return the result as-is; adjust error handling as needed
        try:
            import docker
            if isinstance(Exception, docker.errors.ContainerError):
                stdout = str(getattr(Exception, "stdout", ""))
                stderr = str(getattr(Exception, "stderr", ""))
                exit_code = getattr(Exception, "exit_status", 1)
            else:
                raise
        except Exception:
            raise SandboxDisabledError(f"Docker command execution failed") from None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "kind": "sandbox",
        "cmd": cmd,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "meta": {
            "elapsed_ms": elapsed_ms,
            "generated_at": time.time(),
            "cua_model": os.getenv("SANDBOX_CUA_MODEL") or None,
        },
    }

