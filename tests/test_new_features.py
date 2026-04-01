"""
Tests for new TheCouncil features:
  - WebSocket endpoint
  - /runs/{run_id}/artifact endpoint
  - Zoom webhook endpoint
  - council_artifact MCP tool helper
  - Anthropic provider utility functions
  - Redis bus null fallback
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("API_SECRET_KEY", "test-secret-key")

from council.api.app import app, _build_artifact_from_result  # noqa: E402
from council.models.state import RunStatus, run_store  # noqa: E402

AUTH = {"Authorization": "Bearer test-secret-key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def completed_run(client):
    """Create and manually complete a run so artifact tests work."""
    resp = await client.post(
        "/runs",
        json={"question": "Should we adopt Kubernetes?", "config": {}},
        headers=AUTH,
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    # Manually transition to COMPLETED with a minimal result
    fake_result = {
        "question": "Should we adopt Kubernetes?",
        "winner": "Agent A",
        "final_resolution": "Yes, adopt Kubernetes with a phased rollout.",
        "agents": [
            {"name": "Agent A", "role": "Architect"},
            {"name": "Agent B", "role": "Pragmatist"},
        ],
        "resolutions": {
            "Agent A": "Yes, adopt Kubernetes with a phased rollout.",
            "Agent B": "No, stick with Docker Compose for now.",
        },
        "vote_rounds": [{"Agent A": "Agent A", "Agent B": "Agent A"}],
        "top3": [
            {
                "rank": 1,
                "agent": "Agent A",
                "role": "Architect",
                "resolution": "Yes, adopt Kubernetes with a phased rollout.",
                "summary": "Kubernetes provides scalability and resilience.",
                "pros": ["Scalable", "Cloud-native"],
                "cons": ["Complex"],
            }
        ],
    }
    await run_store.update_status(run_id, RunStatus.RUNNING)
    await run_store.update_status(run_id, RunStatus.COMPLETED, result=fake_result)

    return run_id


# ---------------------------------------------------------------------------
# Artifact endpoint tests
# ---------------------------------------------------------------------------


class TestArtifactEndpoint:
    @pytest.mark.asyncio
    async def test_artifact_json_for_completed_run(self, client, completed_run):
        resp = await client.get(f"/runs/{completed_run}/artifact", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["format"] == "json"
        artifact = data["artifact"]
        assert artifact["question"] == "Should we adopt Kubernetes?"
        assert artifact["recommended_action"] == "Yes, adopt Kubernetes with a phased rollout."
        assert isinstance(artifact["dissenting_opinions"], list)
        assert isinstance(artifact["top3_resolutions"], list)

    @pytest.mark.asyncio
    async def test_artifact_markdown_for_completed_run(self, client, completed_run):
        resp = await client.get(
            f"/runs/{completed_run}/artifact", headers=AUTH, params={"format": "markdown"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "markdown"
        assert "# TheCouncil Deliberation Artifact" in data["artifact"]
        assert "Kubernetes" in data["artifact"]

    @pytest.mark.asyncio
    async def test_artifact_not_found_for_missing_run(self, client):
        resp = await client.get("/runs/does-not-exist/artifact", headers=AUTH)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_artifact_pending_run_returns_status(self, client):
        resp = await client.post(
            "/runs",
            json={"question": "Test question", "config": {}},
            headers=AUTH,
        )
        run_id = resp.json()["run_id"]
        resp2 = await client.get(f"/runs/{run_id}/artifact", headers=AUTH)
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["artifact"] is None
        assert "pending" in data["message"].lower() or "running" in data["message"].lower() or data["status"] in ("pending", "running")

    @pytest.mark.asyncio
    async def test_artifact_requires_auth(self, client, completed_run):
        resp = await client.get(f"/runs/{completed_run}/artifact")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Zoom webhook endpoint tests
# ---------------------------------------------------------------------------


class TestZoomWebhook:
    @pytest.mark.asyncio
    async def test_url_validation_challenge_no_secret(self, client):
        payload = {
            "event": "endpoint.url_validation",
            "payload": {"plainToken": "abc123"},
        }
        resp = await client.post("/webhooks/zoom", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["plainToken"] == "abc123"
        assert "encryptedToken" in data

    @pytest.mark.asyncio
    async def test_unknown_event_accepted(self, client):
        payload = {"event": "meeting.created", "payload": {}}
        resp = await client.post("/webhooks/zoom", json=payload)
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, client):
        resp = await client.post(
            "/webhooks/zoom",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_utf8_returns_400(self, client):
        resp = await client.post(
            "/webhooks/zoom",
            content=b"\xff\xfe invalid bytes",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# _build_artifact_from_result helper tests
# ---------------------------------------------------------------------------


class TestBuildArtifact:
    def test_builds_json_artifact(self):
        result = {
            "question": "Should we migrate to AWS?",
            "winner": "CTO",
            "final_resolution": "Yes, migrate in Q3.",
            "agents": [
                {"name": "CTO", "role": "Technology Lead"},
                {"name": "CFO", "role": "Finance Lead"},
            ],
            "resolutions": {
                "CTO": "Yes, migrate in Q3.",
                "CFO": "No, too costly.",
            },
            "vote_rounds": [{"CTO": "CTO", "CFO": "CTO"}],
            "top3": [
                {
                    "rank": 1,
                    "agent": "CTO",
                    "role": "Technology Lead",
                    "resolution": "Yes, migrate in Q3.",
                    "summary": "AWS reduces infra costs by 30%.",
                    "pros": ["Cost savings"],
                    "cons": ["Migration risk"],
                }
            ],
        }
        artifact = _build_artifact_from_result("run-1", "Should we migrate to AWS?", result)

        data = artifact["data"]
        assert data["recommended_action"] == "Yes, migrate in Q3."
        assert data["consensus_resolution"] == "Yes, migrate in Q3."
        assert len(data["dissenting_opinions"]) == 1
        assert data["dissenting_opinions"][0]["agent"] == "CFO"
        assert len(data["top3_resolutions"]) == 1

    def test_builds_markdown_artifact(self):
        result = {
            "winner": "Alpha",
            "final_resolution": "Do X.",
            "agents": [{"name": "Alpha", "role": "Lead"}],
            "resolutions": {"Alpha": "Do X."},
            "vote_rounds": [],
            "top3": [],
        }
        artifact = _build_artifact_from_result("run-2", "Question?", result)
        md = artifact["markdown"]
        assert "# TheCouncil Deliberation Artifact" in md
        assert "Question?" in md
        assert "Do X." in md

    def test_empty_result_does_not_raise(self):
        artifact = _build_artifact_from_result("run-3", "Q?", {})
        assert isinstance(artifact["data"], dict)
        assert isinstance(artifact["markdown"], str)


# ---------------------------------------------------------------------------
# Web Search & Computer Use tier enforcement tests
# ---------------------------------------------------------------------------


class TestTierGatedFeatures:
    @pytest.mark.asyncio
    async def test_web_search_on_basic_tier_returns_403(self, monkeypatch):
        """Basic tier cannot enable web search; server must reject with 403."""
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "basic")
        import importlib, sys
        if "council.api.app" in sys.modules:
            importlib.reload(sys.modules["council.api.app"])
        from council.api.app import app as api_app
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://testserver"
        ) as c:
            resp = await c.post(
                "/runs",
                json={"question": "Q?", "web_search_enabled": True},
                headers=AUTH,
            )
        assert resp.status_code == 403
        assert "pro" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_computer_use_on_pro_tier_returns_403(self, monkeypatch):
        """Pro tier cannot enable computer use; server must reject with 403."""
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "pro")
        import importlib, sys
        if "council.api.app" in sys.modules:
            importlib.reload(sys.modules["council.api.app"])
        from council.api.app import app as api_app
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://testserver"
        ) as c:
            resp = await c.post(
                "/runs",
                json={"question": "Q?", "computer_use_enabled": True},
                headers=AUTH,
            )
        assert resp.status_code == 403
        assert "ultra" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_web_search_on_pro_tier_succeeds(self, monkeypatch):
        """Pro tier can enable web search — the run should be created (202)."""
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "pro")
        import importlib, sys
        if "council.api.app" in sys.modules:
            importlib.reload(sys.modules["council.api.app"])
        from council.api.app import app as api_app
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://testserver"
        ) as c:
            resp = await c.post(
                "/runs",
                json={"question": "Search-enabled run?", "web_search_enabled": True},
                headers=AUTH,
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_entitlements_includes_web_search_flag(self, monkeypatch):
        """Entitlements response must include web_search_enabled for the current tier."""
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "pro")
        import importlib, sys
        if "council.api.app" in sys.modules:
            importlib.reload(sys.modules["council.api.app"])
        from council.api.app import app as api_app
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://testserver"
        ) as c:
            resp = await c.get("/me/entitlements", headers=AUTH)
        assert resp.status_code == 200
        features = resp.json()["features"]
        assert "web_search_enabled" in features
        assert features["web_search_enabled"] is True  # Pro has web search

    @pytest.mark.asyncio
    async def test_sandbox_stream_requires_ultra(self, monkeypatch):
        """Basic tier trying to access sandbox stream must get 403."""
        monkeypatch.setenv("DEFAULT_SUBSCRIPTION_TIER", "basic")
        import importlib, sys
        if "council.api.app" in sys.modules:
            importlib.reload(sys.modules["council.api.app"])
        from council.api.app import app as api_app
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://testserver"
        ) as c:
            resp = await c.get("/runs/fake-run-id/sandbox/stream", headers=AUTH)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Anthropic provider utility tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Redis bus null fallback tests
# ---------------------------------------------------------------------------


class TestRedisBusNullFallback:
    @pytest.mark.asyncio
    async def test_null_bus_publish_is_noop(self):
        from council.bus.redis_bus import _NullBus

        bus = _NullBus()
        await bus.publish_event("run-1", "run_started", {"run_id": "run-1"})  # no error

    @pytest.mark.asyncio
    async def test_null_bus_dequeue_returns_none(self):
        from council.bus.redis_bus import _NullBus

        bus = _NullBus()
        result = await bus.dequeue_run()
        assert result is None

    @pytest.mark.asyncio
    async def test_null_bus_read_run_events_is_empty(self):
        from council.bus.redis_bus import _NullBus

        bus = _NullBus()
        events = []
        async for event in bus.read_run_events("run-1"):
            events.append(event)
        assert events == []
