from __future__ import annotations

from fastapi.testclient import TestClient

from memoryx.api.app_factory import create_app


class FakeDB:
    async def fetchone(self, sql, params=()):
        return {"ok": 1}

    async def fetchall(self, sql, params=()):
        return [{"name": "memories"}, {"name": "memory_versions"}, {"name": "memories_fts"}, {"name": "conversation_logs"}]


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()
        self.closed = False

    async def get_memory(self, memory_id):
        return None

    async def close(self):
        self.closed = True


def test_app_factory_lifespan_uses_injected_repo_and_ready():
    repo = FakeRepo()
    app = create_app(repository=repo, query_api=None, auto_open=False)

    with TestClient(app) as client:
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    assert repo.closed is False
