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
from council.models.state import run_store  # noqa: E402


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
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class TestAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cors_preflight_allows_loopback_frontend_origin(self, client):
        resp = await client.options(
            "/runs",
            headers={
                "Origin": "http://127.0.2.2:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,x-requested-with",
            },
        )

        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://127.0.2.2:3000"

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"}, headers=BAD_AUTH)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_auth_header_returns_401(self, client):
        resp = await client.post("/runs", json={"question": "hi"}, headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_shape_does_not_fall_through_to_api_secret(self, client, monkeypatch):
        """A JWT-shaped token that fails verification must not authenticate as the dev secret."""
        jwt_like_token = "eyJ.invalid-but-secret"
        monkeypatch.setenv("API_SECRET_KEY", "test-secret-key")

        resp = await client.post(
            "/runs",
            json={"question": "hi"},
            headers={"Authorization": f"Bearer {jwt_like_token}"},
        )

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

    @pytest.mark.asyncio
    async def test_create_run_snapshots_selected_persona_models(self, client):
        persona_resp = await client.post(
            "/me/personas",
            json={
                "name": "Modelled Persona",
                "mode": "custom",
                "system_prompt": "You are concise and analytical.",
                "model": "x-ai/grok-4.3",
            },
            headers=AUTH,
        )
        assert persona_resp.status_code == 201
        persona_id = persona_resp.json()["persona_id"]

        resp = await client.post(
            "/runs",
            json={
                "question": "Should we change the model wiring?",
                "config": {"selected_persona_ids": [persona_id]},
            },
            headers=AUTH,
        )
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        run = await run_store.get(run_id)
        assert run.config["selected_personas"][0]["persona_id"] == persona_id
        assert run.config["selected_personas"][0]["model"] == "x-ai/grok-4.3"


class TestPersonas:
    @pytest.mark.asyncio
    async def test_prebuilt_personas_include_model(self, client):
        resp = await client.get("/me/personas", headers=AUTH)
        assert resp.status_code == 200
        personas = resp.json()
        prebuilt = [p for p in personas if p["is_prebuilt"]]
        assert prebuilt
        assert all(isinstance(p["model"], str) and p["model"] for p in prebuilt)


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
        """A token that does not match API_SECRET_KEY and does not match a DB API key returns 401."""
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
# Entitlements and feature access
# ---------------------------------------------------------------------------


class TestEntitlements:
    @pytest.mark.asyncio
    async def test_entitlements_endpoint_returns_open_source_features(self, client):
        resp = await client.get("/me/entitlements", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "open-source"
        assert body["display_name"] == "Open Source"
        assert body["limits"]["runs_per_month"] is None
        assert body["limits"]["max_agents"] is None
        assert body["limits"]["max_rounds"] is None
        assert body["limits"]["max_input_tokens"] is None
        assert body["limits"]["max_saved_personas"] is None
        assert body["features"]["mcp_enabled"] is True
        assert body["features"]["computer_use_enabled"] is True
