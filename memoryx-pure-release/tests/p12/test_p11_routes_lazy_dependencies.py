from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryx.api.p11_routes import create_p11_router


class FakeDB:
    async def fetchall(self, sql, params=()):
        return []

    async def execute(self, sql, params=()):
        return None


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


def test_p11_router_resolves_repository_lazily():
    app = FastAPI()
    repo = FakeRepo()
    app.include_router(create_p11_router(get_repository=lambda: repo, prefix="/v1/cognitive"))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/cognitive/verify-answer",
            json={"question": "q", "answer": "MemoryX has a guard layer.", "store": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert "verification" in payload or "claims" in payload or "result" in payload
