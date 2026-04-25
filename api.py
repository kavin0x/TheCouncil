"""Compatibility ASGI entrypoint for local dev commands.

Allows `uvicorn api:app --reload` to work while the canonical app lives in
`council.api.app`.
"""

from council.api.app import app

__all__ = ["app"]
