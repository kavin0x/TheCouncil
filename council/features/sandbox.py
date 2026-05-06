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
    "wc", "sort", "uniq", "grep", "find", "curl", "wget", "pip", "pip3",
    "npm", "npx", "java", "javac", "go", "ruby", "perl", "r",
})

# Shell metacharacters tha# Shell metacharacters tha# Shell metan
_SHELL_METACHAR_RE = re.compile(r"[|;&`$<>_SHELL_METACHAR_RE = re.compile(r"[|;&`$<>_SHELL_METACHAR_RE = re.compile(r"[|;&`$<>_SHELL_METox command string against an allowlist and reject shell metacharacters.

                                                    """
                                     
             n "p            ri             l         ready')\""

    if _SHEL    if _SHEL    if _Scmd    if _SHEL    if _SHEL    if _Scm       if _SHEL    if _SHEL    if _Scmd    if _SHEL    if _SHEL    if _Scm      a    if _SHEL    if _SHEL ipes, semicolons, redirects, or subshells."
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
# --------------------------# --------------------------# --------------------------# --------------------------# --------------------------# --------------------------# --------------------------# --------------------------# ---------------------ing Docker desktop sandbox for *session_id*, or create # --------------------------# --------------------------# ---rs# --------------------------# -----------------ndboxDisabledError with instructions.

    To implement:
                          ma                          ma                          ma                          ma          3. Expose VNC via noVNC (typically localhost:6080/vnc.html)
      4. Return container object with stream.get_url() method
                               edError                           (co                               edError   "To enable,                                edError                           (co        ation logic. "
        "See documentation in        "See documentation in        "See documentation in        c de        "See documentation in        "See documentation in        "See documentation in        c de        "See documentation in        "See documentation in        "See documentation in        c de        "See documentation in        "See documentation in        "See documentation in        c de        "See documentation in        "See documentation in        "See documentation in        c de        "See documentation in        "See doc", session_id, exc)


async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async ""async async async async async async esktop_sandbox(session_id)async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async ""async async async asyboxasync async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async ""async async async async async async esktop_sandbox(session_id)async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async async ""async async async asyboxasync async async async async async async async async async async async async async async asynsk(*, question: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Code execution sandbox using Docker.

    Spins up a temporary Docker container, runs a bounded command, and returns output.
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

    # Get Docker client (uses DOCKER_HOST env var if set, otherwise local socket)
    try:
        client = docker.from_env()
    except Exception as exc:
        raise SandboxDisabledError(f"Failed to connect to Docker daemon: {exc}") from exc

    stdout_text = ""
    stderr_text = ""
    exit_code = N    exit_code = N    exit_code = N    exit_code = N    exit_code = N  on    exit_code = N    exit_code = N    exittry    exit_code = N    exit_code = N    exit_code = N    exit_code = N    exit_code = Nag    ex     except    exit_code = N    exit_code = N    exir.war    exit_code = N    es:    exit_code = N    exit_code age,     exit_code = N    exit_code = N    exit_code = N    exit_code = N   r_    ex
                                                      ve container after execution
            timeout=timeout_s,
            timeout=timeout_s,
            te            te            t = result.decode("utf-8", errors="replace")
        else:
            stdout_text = str(result)

        exit_code = 0  # Assu        exit_code = 0  # Assu        exit_code = 0  # Assu        exit_code = 0 r(                 exit_code = 0  # Assu   s =        exit_code = 0  # star        exit_code = 0  # Assu        exit_code = 0  # Assu        exit_code = 0  # Assu  st        exit_code ="stderr": stderr_text,
        "exit_code": exit_code,
        "meta": {
            "elapsed_ms": elapsed_ms,
            "generated_at": time.time(),
            "cua_model": os.getenv("SANDBOX_CUA_MODEL") or None,
        },
    }
