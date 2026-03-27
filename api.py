"""
TheCouncil API — FastAPI skeleton.

Endpoints:
  POST /runs          Create a new council run (enqueues it)
  GET  /runs/{run_id} Poll the status of a run
  GET  /runs          List runs for the authenticated user
  POST /webhooks/stripe  Handle Stripe subscription lifecycle events

Auth:
  Bearer token in the Authorization header.
  Token is validated against the API_SECRET_KEY environment variable
  for single-key dev mode, or against a user table in production.

Usage (dev):
  uvicorn api:app --reload
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from run_state import (
    Run,
    RunNotFoundError,
    run_queue,
    run_store,
)
from subscriptions import (
    TierName,
    parse_webhook_event,
    resolve_tier_from_webhook,
)

app = FastAPI(
    title="TheCouncil API",
    description="REST API for creating, queuing, and polling council debate runs.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


def _get_api_secret() -> str:
    """Return the configured API secret key, raising if absent."""
    secret = os.getenv("API_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "API_SECRET_KEY environment variable is not set. "
            "Set it before starting the server."
        )
    return secret


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Extract and validate the Bearer token from the Authorization header.

    Returns the token (used as the owner_id for run scoping).
    Raises HTTP 401 if the token is missing or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Use 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        expected = _get_api_secret()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4096, description="The debate question.")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional run configuration forwarded to DebateSession.",
    )


class RunResponse(BaseModel):
    run_id: str
    question: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunResponse":
        data = run.to_dict()
        # owner_id is an internal principal identifier; exclude it from responses
        # to avoid echoing the bearer token (used as owner_id in dev mode) back to clients.
        data.pop("owner_id", None)
        return cls(**data)


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create and enqueue a new council run",
)
async def create_run(
    body: CreateRunRequest,
    owner_id: Annotated[str, Depends(require_auth)],
) -> RunResponse:
    """Create a new council debate run and place it on the worker queue.

    Returns the run record in PENDING status immediately.
    Poll ``GET /runs/{run_id}`` to track progress.
    """
    run = await run_store.create(
        question=body.question,
        config=body.config,
        owner_id=owner_id,
    )
    await run_queue.enqueue(run.run_id)
    return RunResponse.from_run(run)


@app.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="Poll the status of a council run",
)
async def get_run(
    run_id: str,
    owner_id: Annotated[str, Depends(require_auth)],
) -> RunResponse:
    """Return the current state of a run.

    Returns HTTP 404 if the run does not exist or belongs to a different user.
    """
    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return RunResponse.from_run(run)


@app.get(
    "/runs",
    response_model=list[RunResponse],
    summary="List council runs for the authenticated user",
)
async def list_runs(
    owner_id: Annotated[str, Depends(require_auth)],
) -> list[RunResponse]:
    """Return all runs owned by the authenticated user, newest first."""
    runs = await run_store.list_runs(owner_id=owner_id)
    return [RunResponse.from_run(r) for r in runs]


# ---------------------------------------------------------------------------
# Stripe webhook endpoint
# ---------------------------------------------------------------------------


@app.post(
    "/webhooks/stripe",
    include_in_schema=False,
    summary="Stripe webhook receiver",
)
async def stripe_webhook(request: Request) -> JSONResponse:
    """Receive and process Stripe webhook events.

    Verifies the Stripe-Signature header using STRIPE_WEBHOOK_SECRET.
    Currently handles:
      - ``checkout.session.completed`` → record the tier for the customer
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        # Accept without verification in local dev when secret is not configured.
        # In production, STRIPE_WEBHOOK_SECRET must always be set.
        import json as _json

        try:
            event: dict[str, Any] = _json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
    else:
        try:
            event = parse_webhook_event(payload, sig_header, webhook_secret)
        except (ValueError, ImportError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    event_type = event.get("type")

    if event_type == "checkout.session.completed":
        tier: TierName | None = resolve_tier_from_webhook(event)
        customer_email = (
            (event.get("data") or {}).get("object", {}).get("customer_email") or ""
        )
        # In a real system, persist tier → customer_email/customer_id mapping here.
        # For now, log and acknowledge.
        _ = tier  # used in future persistence layer
        _ = customer_email

    return JSONResponse(content={"received": True})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
