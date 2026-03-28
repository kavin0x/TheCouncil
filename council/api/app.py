"""
TheCouncil API — FastAPI skeleton.

Endpoints:
  POST /runs               Create a new council run (enqueues it)
  GET  /runs/{run_id}      Poll the status of a run
  GET  /runs               List runs for the authenticated user
  GET  /me/entitlements    Current subscription tier and limits
  GET  /me/usage           Month-to-date usage vs limits
  GET  /me/billing         Billing summary (tier, trial, next renewal)
  POST /me/billing/checkout  Create a Stripe Checkout session URL
  POST /me/billing/portal    Create a Stripe Customer Portal session URL
  GET  /me/personas        List saved personas for the authenticated user
  POST /me/personas        Create a persona (respects max_saved_personas cap)
  GET  /me/personas/{id}   Get a single persona
  PUT  /me/personas/{id}   Update a persona
  DELETE /me/personas/{id} Delete a persona
  POST /webhooks/stripe    Handle Stripe Payment Links subscription lifecycle events

Auth:
  Bearer token in the Authorization header.
  Token is validated against the API_SECRET_KEY environment variable
  for single-key dev mode, or against a user table in production.

Usage (dev):
  uvicorn council.api.app:app --reload
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from council.core.runner import CouncilRunBlockedError, run_council_for_api
from council.models.state import (
    Run,
    RunNotFoundError,
    RunStatus,
    run_queue,
    run_store,
)
from council.features.sandbox import SandboxDisabledError, run_sandbox_task
from council.models.subscriptions import (
    TierName,
    get_tier,
    is_within_run_limit,
    parse_webhook_event,
    resolve_tier_from_webhook,
)

app = FastAPI(
    title="TheCouncil API",
    description="REST API for creating, queuing, and polling council debate runs.",
    version="0.1.0",
)

_mcp = FastMCP("TheCouncil")

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if hasattr(_mcp, "http_app"):
    _mcp_app = _mcp.http_app(path="/")
else:
    streamable_http_app = getattr(_mcp, "streamable_http_app")
    _mcp_app = streamable_http_app()

app.mount("/mcp", _mcp_app)

_worker_task: asyncio.Task[None] | None = None


async def _run_worker_loop() -> None:
    while True:
        run_id = await run_queue.dequeue()
        try:
            run = await run_store.update_status(run_id, RunStatus.RUNNING)
            run_kind = str((run.config or {}).get("run_kind") or "council").strip().lower()
            if run_kind == "sandbox":
                tier = _resolve_request_tier()
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
        except CouncilRunBlockedError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
        except SandboxDisabledError as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=str(exc))
        except Exception as exc:
            await run_store.update_status(run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        finally:
            run_queue.task_done()


@app.on_event("startup")
async def _startup_worker() -> None:
    global _worker_task
    if os.getenv("COUNCIL_DISABLE_WORKER", ""):
        return
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_run_worker_loop())


@app.on_event("shutdown")
async def _shutdown_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None


def _require_mcp_enabled(owner_id: str) -> None:
    tier = _resolve_request_tier()
    limits = get_tier(tier).limits
    if not limits.mcp_enabled:
        raise RuntimeError("MCP integrations require Pro, Ultra, or Enterprise.")
    expected = _get_api_secret()
    if not secrets.compare_digest(owner_id, expected):
        raise RuntimeError("Invalid API token.")


@_mcp.tool()
async def council_run(question: str, config: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """Create and enqueue a council run. Returns the run_id and initial status."""
    owner_id = api_key or ""
    _require_mcp_enabled(owner_id)
    run = await run_store.create(question=question, config=config or {}, owner_id=owner_id)
    await run_queue.enqueue(run.run_id)
    return {"run_id": run.run_id, "status": run.status.value, "question": run.question, "created_at": run.created_at}


@_mcp.tool()
async def sandbox_run(question: str, config: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """Create and enqueue an Ultra-only sandbox run."""
    owner_id = api_key or ""
    _require_mcp_enabled(owner_id)
    tier = _resolve_request_tier()
    if not get_tier(tier).limits.computer_use_enabled:
        raise RuntimeError("Computer-use sandbox requires Ultra or Enterprise.")
    run_cfg = dict(config or {})
    run_cfg["run_kind"] = "sandbox"
    run = await run_store.create(question=question, config=run_cfg, owner_id=owner_id)
    await run_queue.enqueue(run.run_id)
    return {"run_id": run.run_id, "status": run.status.value, "question": run.question, "created_at": run.created_at}


@_mcp.tool()
async def council_poll(run_id: str, api_key: str | None = None) -> dict[str, Any]:
    """Poll a run created via council_run."""
    owner_id = api_key or ""
    _require_mcp_enabled(owner_id)
    run = await run_store.get(run_id)
    if run.owner_id != owner_id:
        raise RuntimeError("Run not found.")
    return run.to_dict()


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
) -> "AuthContext":
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
    return AuthContext(owner_id=token, tier=_resolve_request_tier())


@dataclass(frozen=True)
class AuthContext:
    owner_id: str
    tier: TierName


def _resolve_request_tier() -> TierName:
    """Resolve caller tier from env for now; DB-backed mapping comes next."""
    raw = os.getenv("DEFAULT_SUBSCRIPTION_TIER", TierName.BASIC.value).strip().lower()
    try:
        return TierName(raw)
    except ValueError:
        return TierName.BASIC


def _count_runs_this_month(runs: list[Run]) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for run in runs:
        created = datetime.fromtimestamp(run.created_at, tz=timezone.utc)
        if created.year == now.year and created.month == now.month:
            count += 1
    return count


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
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> RunResponse:
    """Create a new council debate run and place it on the worker queue.

    Returns the run record in PENDING status immediately.
    Poll ``GET /runs/{run_id}`` to track progress.
    """
    limits = get_tier(auth.tier).limits
    current_runs = _count_runs_this_month(await run_store.list_runs(owner_id=auth.owner_id))
    if not is_within_run_limit(auth.tier, current_runs):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly run limit reached for tier '{auth.tier.value}'. "
                f"Limit: {limits.runs_per_month}."
            ),
        )

    requested_agents = int(body.config.get("num_agents", 0) or 0)
    if requested_agents and requested_agents > limits.max_agents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"num_agents={requested_agents} exceeds tier limit "
                f"({limits.max_agents}) for '{auth.tier.value}'."
            ),
        )

    requested_rounds = int(body.config.get("num_rounds", 0) or 0)
    if requested_rounds and requested_rounds > limits.max_rounds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"num_rounds={requested_rounds} exceeds tier limit "
                f"({limits.max_rounds}) for '{auth.tier.value}'."
            ),
        )

    requested_tokens = int(body.config.get("max_input_tokens", 0) or 0)
    if requested_tokens and requested_tokens > limits.max_input_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"max_input_tokens={requested_tokens} exceeds tier limit "
                f"({limits.max_input_tokens}) for '{auth.tier.value}'."
            ),
        )

    run = await run_store.create(
        question=body.question,
        config=body.config,
        owner_id=auth.owner_id,
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
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> RunResponse:
    """Return the current state of a run.

    Returns HTTP 404 if the run does not exist or belongs to a different user.
    """
    try:
        run = await run_store.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.owner_id != auth.owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return RunResponse.from_run(run)


@app.get(
    "/runs",
    response_model=list[RunResponse],
    summary="List council runs for the authenticated user",
)
async def list_runs(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[RunResponse]:
    """Return all runs owned by the authenticated user, newest first."""
    runs = await run_store.list_runs(owner_id=auth.owner_id)
    return [RunResponse.from_run(r) for r in runs]


@app.get(
    "/me/entitlements",
    summary="Get current subscription tier and limits",
)
async def get_entitlements(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    tier = get_tier(auth.tier)
    return {
        "tier": tier.name.value,
        "display_name": tier.display_name,
        "limits": {
            "runs_per_month": tier.limits.runs_per_month,
            "max_agents": tier.limits.max_agents,
            "max_rounds": tier.limits.max_rounds,
            "max_input_tokens": tier.limits.max_input_tokens,
            "max_saved_personas": tier.limits.max_saved_personas,
        },
        "features": {
            "api_access": tier.limits.api_access,
            "mcp_enabled": tier.limits.mcp_enabled,
            "custom_mcp_enabled": tier.limits.custom_mcp_enabled,
            "ide_plugins_enabled": tier.limits.ide_plugins_enabled,
            "computer_use_enabled": tier.limits.computer_use_enabled,
            "sso_enabled": tier.limits.sso_enabled,
            "centralized_billing_enabled": tier.limits.centralized_billing_enabled,
        },
    }


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
          - ``checkout.session.completed`` (including Payment Links) → record tier/customer
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
# Usage endpoint
# ---------------------------------------------------------------------------


@app.get(
    "/me/usage",
    summary="Get month-to-date usage vs subscription limits",
)
async def get_usage(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    runs = await run_store.list_runs(owner_id=auth.owner_id)
    month_runs = _count_runs_this_month(runs)
    limits = get_tier(auth.tier).limits
    return {
        "period": "monthly",
        "runs": {"used": month_runs, "limit": limits.runs_per_month},
    }


# ---------------------------------------------------------------------------
# Billing endpoints (stub — real Stripe integration follows Postgres migration)
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    tier: str = Field(..., description="Target tier: basic | pro | ultra")
    success_url: str = Field(..., description="Redirect URL after successful checkout")
    cancel_url: str = Field(..., description="Redirect URL if checkout is cancelled")


class PortalRequest(BaseModel):
    return_url: str = Field(..., description="URL to return to after portal session")


@app.get(
    "/me/billing",
    summary="Billing summary for the authenticated user",
)
async def get_billing(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    tier = get_tier(auth.tier)
    return {
        "tier": tier.name.value,
        "display_name": tier.display_name,
        "price_usd_monthly": tier.price_usd_monthly,
        "status": "active",
        "trial_end": None,
        "next_renewal": None,
        "stripe_customer_id": None,
    }


@app.post(
    "/me/billing/checkout",
    summary="Create a Stripe Checkout session for upgrading/subscribing",
)
async def create_checkout(
    body: CheckoutRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    try:
        target = TierName(body.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {body.tier!r}")
    if target is TierName.TRIAL:
        raise HTTPException(status_code=400, detail="Trial tier cannot be purchased.")

    tier = get_tier(target)
    price_id = tier.stripe_price_id
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Stripe price for '{target.value}' is not yet configured.",
        )

    try:
        import stripe as _stripe  # type: ignore[import]
    except ImportError:
        raise HTTPException(status_code=503, detail="Stripe SDK not installed.")

    session = _stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        metadata={"tier": target.value, "owner_id": auth.owner_id},
    )
    return {"url": session.url}


@app.post(
    "/me/billing/portal",
    summary="Create a Stripe Customer Portal session",
)
async def create_portal(
    body: PortalRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    customer_id = os.getenv("STRIPE_DEV_CUSTOMER_ID", "")
    if not customer_id:
        raise HTTPException(
            status_code=503,
            detail="No Stripe customer associated with this account yet.",
        )

    try:
        import stripe as _stripe  # type: ignore[import]
    except ImportError:
        raise HTTPException(status_code=503, detail="Stripe SDK not installed.")

    session = _stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=body.return_url,
    )
    return {"url": session.url}


# ---------------------------------------------------------------------------
# Personas — in-memory store (migrates to Postgres in Phase 1 DB work)
# ---------------------------------------------------------------------------


class PersonaRecord(BaseModel):
    persona_id: str
    name: str
    mode: str
    system_prompt: str
    description: str | None = None
    owner_id: str
    created_at: float


_persona_store: dict[str, PersonaRecord] = {}


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(default="custom", description="canned | mbti | custom")
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    description: str | None = None


class UpdatePersonaRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    description: str | None = None


def _get_owned_persona(persona_id: str, owner_id: str) -> PersonaRecord:
    p = _persona_store.get(persona_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Persona not found.")
    return p


@app.get("/me/personas", summary="List saved personas")
async def list_personas(
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[dict[str, Any]]:
    owned = sorted(
        (p for p in _persona_store.values() if p.owner_id == auth.owner_id),
        key=lambda p: p.created_at,
        reverse=True,
    )
    return [p.model_dump(exclude={"owner_id"}) for p in owned]


@app.post(
    "/me/personas",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new persona (tier cap enforced)",
)
async def create_persona(
    body: CreatePersonaRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    limits = get_tier(auth.tier).limits
    owned_count = sum(1 for p in _persona_store.values() if p.owner_id == auth.owner_id)
    if limits.max_saved_personas is not None and owned_count >= limits.max_saved_personas:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Persona limit ({limits.max_saved_personas}) reached "
                f"for tier '{auth.tier.value}'. Upgrade to save more."
            ),
        )
    persona = PersonaRecord(
        persona_id=str(uuid.uuid4()),
        name=body.name,
        mode=body.mode,
        system_prompt=body.system_prompt,
        description=body.description,
        owner_id=auth.owner_id,
        created_at=time.time(),
    )
    _persona_store[persona.persona_id] = persona
    return persona.model_dump(exclude={"owner_id"})


@app.get("/me/personas/{persona_id}", summary="Get a single persona")
async def get_persona(
    persona_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    p = _get_owned_persona(persona_id, auth.owner_id)
    return p.model_dump(exclude={"owner_id"})


@app.put("/me/personas/{persona_id}", summary="Update a persona")
async def update_persona(
    persona_id: str,
    body: UpdatePersonaRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict[str, Any]:
    p = _get_owned_persona(persona_id, auth.owner_id)
    updated = p.model_copy(
        update={k: v for k, v in body.model_dump().items() if v is not None}
    )
    _persona_store[persona_id] = updated
    return updated.model_dump(exclude={"owner_id"})


@app.delete(
    "/me/personas/{persona_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a persona",
)
async def delete_persona(
    persona_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> None:
    _get_owned_persona(persona_id, auth.owner_id)
    del _persona_store[persona_id]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
