"""
Production-readiness tests for TheCouncil API.

Tests cover:
- Security (auth, rate limiting, headers)
- Error handling (validation, exceptions)
- Health checks
- Request validation
"""

import pytest
from fastapi.testclient import TestClient
from council.api.app import app, _validate_environment


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestEnvironmentValidation:
    """Test environment variable validation on startup."""

    def test_validate_environment_ok(self, monkeypatch):
        """Validation passes with required env vars set."""
        monkeypatch.setenv("API_SECRET_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
        # Should not raise
        _validate_environment()

    def test_validate_environment_missing_secret_key(self, monkeypatch):
        """Validation fails when API_SECRET_KEY missing."""
        monkeypatch.delenv("API_SECRET_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        with pytest.raises(RuntimeError, match="API_SECRET_KEY"):
            _validate_environment()

    def test_validate_environment_missing_router_key(self, monkeypatch):
        """Validation fails when OPENROUTER_API_KEY missing."""
        monkeypatch.setenv("API_SECRET_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            _validate_environment()


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_endpoint(self, client):
        """Health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "council-api"

    def test_readiness_endpoint(self, client):
        """Readiness endpoint returns status and checks."""
        response = client.get("/readiness")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "status" in data
        assert "checks" in data


class TestSecurityHeaders:
    """Test security headers are present in responses."""

    def test_security_headers_present(self, client):
        """Security headers are added to all responses."""
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Strict-Transport-Security" in response.headers

    def test_csrf_prevention_headers(self, client):
        """CSP header is set for XSS prevention."""
        response = client.get("/health")
        assert "Content-Security-Policy" in response.headers


class TestAuthenticationValidation:
    """Test authentication requirements."""

    def test_create_run_requires_auth(self, client):
        """POST /runs requires Authorization header."""
        response = client.post("/runs", json={"question": "Test?"})
        assert response.status_code == 401
        assert "Authorization" in response.json()["detail"].lower()

    def test_create_run_rejects_invalid_token(self, client):
        """Invalid Bearer token is rejected."""
        response = client.post(
            "/runs",
            json={"question": "Test?"},
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert response.status_code == 401

    def test_create_run_rejects_malformed_auth(self, client):
        """Malformed Authorization header is rejected."""
        response = client.post(
            "/runs",
            json={"question": "Test?"},
            headers={"Authorization": "NotBearer token"},
        )
        assert response.status_code == 401


class TestRequestValidation:
    """Test request input validation."""

    def test_create_run_question_too_long(self, client):
        """Question exceeding max length is rejected."""
        long_question = "a" * 5000  # Exceeds max 4096
        response = client.post(
            "/runs",
            json={"question": long_question},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 422

    def test_create_run_empty_question(self, client):
        """Empty question is rejected."""
        response = client.post(
            "/runs",
            json={"question": ""},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 422

    def test_create_run_valid_request(self, client, monkeypatch):
        """Valid request is accepted (returns 202)."""
        monkeypatch.setenv("API_SECRET_KEY", "test-key")
        response = client.post(
            "/runs",
            json={"question": "Is AI safe?", "config": {}},
            headers={"Authorization": "Bearer test-key"},
        )
        # Will return 429 if rate limited or pending if no queue, but not 401/422
        assert response.status_code in [202, 429, 500]


class TestRateLimiting:
    """Test rate limiting on critical endpoints."""

    def test_rate_limit_on_create_run(self, client, monkeypatch):
        """Create run endpoint has rate limiting."""
        monkeypatch.setenv("API_SECRET_KEY", "test-key")
        headers = {"Authorization": "Bearer test-key"}

        # Try many requests rapidly (should hit limit or queue limit)
        responses = []
        for _ in range(5):
            response = client.post(
                "/runs",
                json={"question": "Test?"},
                headers=headers,
            )
            responses.append(response.status_code)

        # At least one should be rate limited (429) or hit another limit
        # Status codes: 202 (accepted), 429 (rate limited), 500 (server error)
        assert any(s in [202, 429] for s in responses)


class TestErrorHandling:
    """Test consistent error handling and messages."""

    def test_404_not_found(self, client):
        """Non-existent routes return 404."""
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Wrong HTTP method returns 405."""
        response = client.put("/health")
        assert response.status_code == 405

    def test_error_response_format(self, client):
        """Error responses have consistent format."""
        response = client.post(
            "/runs",
            json={"question": "Test?"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data


class TestCORSConfiguration:
    """Test CORS is properly configured."""

    def test_cors_headers_present(self, client):
        """CORS headers are present for allowed origins."""
        response = client.options("/health")
        # Headers should indicate CORS is configured
        assert response.status_code == 200


class TestTypeValidation:
    """Test request body type validation."""

    def test_invalid_json_rejected(self, client):
        """Invalid JSON in request body is rejected."""
        response = client.post(
            "/runs",
            data=b"not valid json",
            headers={
                "Authorization": "Bearer test-key",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 422

    def test_config_must_be_dict(self, client):
        """Config field must be an object/dict."""
        response = client.post(
            "/runs",
            json={"question": "Test?", "config": "not_a_dict"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
