"""P0-E: REST API authentication and rate limiting tests."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures to control env-based auth ──────────────────────────

@pytest.fixture(autouse=True)
def _clear_env():
    """Ensure MEMORYX_API_KEY is not set between tests."""
    old = os.environ.pop("MEMORYX_API_KEY", None)
    yield
    if old is not None:
        os.environ["MEMORYX_API_KEY"] = old
    else:
        os.environ.pop("MEMORYX_API_KEY", None)


def _fresh_app():
    """Return a fresh FastAPI app with current env state for auth."""
    # Re-import to pick up env changes
    import importlib
    import memoryx.api.auth
    importlib.reload(memoryx.api.auth)
    import memoryx.api.rest_app
    importlib.reload(memoryx.api.rest_app)
    return memoryx.api.rest_app.app


# ── Auth tests ──────────────────────────────────────────────────

def test_health_route_works():
    """GET /health should always return 200."""
    app = _fresh_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_auth_skipped_when_no_env_key():
    """When MEMORYX_API_KEY is not set, auth is skipped (local dev)."""
    app = _fresh_app()
    client = TestClient(app)
    resp = client.get("/health/auth-required")
    assert resp.status_code == 200


def test_auth_required_when_env_key_set():
    """When MEMORYX_API_KEY is set, requests without header get 401."""
    os.environ["MEMORYX_API_KEY"] = "test-secret-key"
    app = _fresh_app()
    client = TestClient(app)
    resp = client.get("/health/auth-required")
    assert resp.status_code == 401


def test_auth_passes_with_correct_key():
    """When MEMORYX_API_KEY is set, correct header passes auth."""
    os.environ["MEMORYX_API_KEY"] = "test-secret-key"
    app = _fresh_app()
    client = TestClient(app)
    resp = client.get(
        "/health/auth-required",
        headers={"X-MemoryX-API-Key": "test-secret-key"},
    )
    assert resp.status_code == 200


def test_auth_rejects_wrong_key():
    """Wrong API key returns 401 even when auth is enforced."""
    os.environ["MEMORYX_API_KEY"] = "correct-key"
    app = _fresh_app()
    client = TestClient(app)
    resp = client.get(
        "/health/auth-required",
        headers={"X-MemoryX-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_auth_uses_constant_time_comparison():
    """secrets.compare_digest is used (no timing attack)."""
    import memoryx.api.auth as auth_mod
    os.environ["MEMORYX_API_KEY"] = "secret"
    importlib = __import__("importlib")
    importlib.reload(auth_mod)

    with patch("memoryx.api.auth.secrets.compare_digest", wraps=auth_mod.secrets.compare_digest) as mock_cmp:
        auth_mod.verify_api_key(x_memoryx_api_key="secret")
        mock_cmp.assert_called_once_with("secret", "secret")


# ── Rate limiter tests ──────────────────────────────────────────

def test_rate_limiter_allows_up_to_max():
    """SlidingWindowRateLimiter allows max_requests within window."""
    from memoryx.api.rate_limit import SlidingWindowRateLimiter
    rl = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
    assert rl.allow("client-a")
    assert rl.allow("client-a")
    assert rl.allow("client-a")
    assert not rl.allow("client-a")  # 4th exceeds limit


def test_rate_limiter_tracks_by_key():
    """Rate limits are per client key, not global."""
    from memoryx.api.rate_limit import SlidingWindowRateLimiter
    rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    assert rl.allow("client-a")
    assert rl.allow("client-b")  # different key, not limited
    assert not rl.allow("client-a")


# ── Embedding gate tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_embedding_gate_limits_concurrency():
    """EmbeddingConcurrencyGate enforces max_concurrent."""
    from memoryx.api.rate_limit import EmbeddingConcurrencyGate
    gate = EmbeddingConcurrencyGate(max_concurrent=2)

    # Acquire both slots
    await gate.acquire()
    await gate.acquire()

    # Third acquire should block → use a short timeout
    acquired = False

    async def try_acquire():
        nonlocal acquired
        await gate.acquire()
        acquired = True

    import asyncio
    task = asyncio.create_task(try_acquire())
    await asyncio.sleep(0.1)
    assert not acquired, "Third acquire should be blocked"

    gate.release()
    await asyncio.sleep(0.1)
    assert acquired, "Third acquire should succeed after release"
    gate.release()
    gate.release()
