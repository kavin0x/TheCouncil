"""
Integration tests for the FastAPI application (api.py).

Uses httpx.AsyncClient with ASGITransport so no real server is started.
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


# Force the API key so tests are hermetic regardless of the calling environment.
os.environ["API_SECRET_KEY"] = "test-secret-key"

from council.api import app  # noqa: E402  (import after env setup)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


AUTH = {"Authorization": "Bearer test-secret-key"}
BAD_AUTH = {"Authorization": "Bearer wrong-token"}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class TestAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"}, headers=BAD_AUTH)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_auth_header_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"}, headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_proceeds(self, client):
        resp = await client.post("/runs", json={"question": "Is this valid?"}, headers=AUTH)
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# POST /runs — create and enqueue
# ---------------------------------------------------------------------------


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_create_run_returns_pending(self, client):
        resp = await client.post("/runs", json={"question": "Should we adopt TDD?"}, headers=AUTH)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert data["question"] == "Should we adopt TDD?"
        assert data["run_id"]

    @pytest.mark.asyncio
    async def test_create_run_empty_question_rejected(self, client):
        resp = await client.post("/runs", json={"question": ""}, headers=AUTH)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_run_with_config(self, client):
        body = {"question": "Q?", "config": {"mode": "canned", "rounds": 2}}
        resp = await client.post("/runs", json=body, headers=AUTH)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_run_does_not_expose_owner_id(self, client):
        """owner_id must not appear in the API response (it carries the bearer token in dev mode)."""
        resp = await client.post("/runs", json={"question": "Secret check?"}, headers=AUTH)
        assert resp.status_code == 202
        assert "owner_id" not in resp.json()

    @pytest.mark.asyncio
    async def test_create_run_question_too_long_rejected(self, client):
        resp = await client.post(
            "/runs", json={"question": "x" * 4097}, headers=AUTH
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_run_rejects_malformed_config(self, client):
        resp = await client.post(
            "/runs",
            json={"question": "Q?", "config": {"num_rounds": "not-a-number"}},
            headers=AUTH,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /runs/{run_id} — poll
# ---------------------------------------------------------------------------


class TestGetRun:
    @pytest.mark.asyncio
    async def test_poll_returns_run(self, client):
        # Create a run first
        resp = await client.post("/runs", json={"question": "Polling test?"}, headers=AUTH)
        run_id = resp.json()["run_id"]

        resp2 = await client.get(f"/runs/{run_id}", headers=AUTH)
        assert resp2.status_code == 200
        assert resp2.json()["run_id"] == run_id
        assert resp2.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_poll_unknown_run_returns_404(self, client):
        resp = await client.get("/runs/no-such-id", headers=AUTH)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_poll_requires_auth(self, client):
        resp = await client.post("/runs", json={"question": "Q?"}, headers=AUTH)
        run_id = resp.json()["run_id"]
        resp2 = await client.get(f"/runs/{run_id}")
        assert resp2.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client, monkeypatch):
        """A token that does not match API_SECRET_KEY, is not a valid Clerk JWT,
        and does not match a DB API key returns 401."""
        monkeypatch.setenv("API_SECRET_KEY", "token-a")
        resp = await client.get(
            "/runs/some-run-id",
            headers={"Authorization": "Bearer completely-wrong-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /runs — list
# ---------------------------------------------------------------------------


class TestListRuns:
    @pytest.mark.asyncio
    async def test_list_runs_returns_created(self, client):
        await client.post("/runs", json={"question": "Q1?"}, headers=AUTH)
        await client.post("/runs", json={"question": "Q2?"}, headers=AUTH)
        resp = await client.get("/runs", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        questions = {r["question"] for r in data}
        assert "Q1?" in questions
        assert "Q2?" in questions

    @pytest.mark.asyncio
    async def test_list_requires_auth(self, client):
        resp = await client.get("/runs")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /webhooks/stripe — basic handling
# ---------------------------------------------------------------------------


class TestStripeWebhook:
    @pytest.mark.asyncio
    async def test_webhook_without_secret_accepts_valid_json(self, client, monkeypatch):
        """When STRIPE_WEBHOOK_SECRET is unset, valid JSON events are accepted."""
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"tier": "pro"},
                    "customer_email": "user@example.com",
                }
            },
        }
        import json
        resp = await client.post(
            "/webhooks/stripe",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    @pytest.mark.asyncio
    async def test_webhook_invalid_json_returns_400(self, client, monkeypatch):
        """Malformed JSON payload returns HTTP 400."""
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        resp = await client.post(
            "/webhooks/stripe",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Entitlements and tier enforcement
# ---------------------------------------------------------------------------


class TestEntitlements:
    @pytest.mark.asyncio
    async def test_entitlements_endpoint_returns_tier_limits(self, client, monkeypatch):
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "pro")
        resp = await client.get("/me/entitlements", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "pro"
        assert body["limits"]["max_saved_personas"] == 10
        assert body["features"]["mcp_enabled"] is True

    @pytest.mark.asyncio
    async def test_create_run_enforces_max_agents(self, client, monkeypatch):
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "basic")
        resp = await client.post(
            "/runs",
            json={"question": "Q?", "config": {"num_agents": 999}},
            headers=AUTH,
        )
        assert resp.status_code == 400
        assert "exceeds tier limit" in resp.json()["detail"]
