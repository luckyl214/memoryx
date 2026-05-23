from __future__ import annotations

from fastapi.testclient import TestClient


def test_patch_memory_uses_update_memory_versioned():
    from memoryx.api import rest_app

    calls = {}

    class FakeRepo:
        async def get_memory(self, memory_id):
            return {"id": memory_id, "content": "old"}

        async def update_memory_versioned(self, memory_id, changes, *, actor, reason):
            calls["memory_id"] = memory_id
            calls["changes"] = changes
            calls["actor"] = actor
            calls["reason"] = reason
            return memory_id

    rest_app.configure(repository=FakeRepo(), query_api=None)
    client = TestClient(rest_app.app)

    resp = client.patch("/v1/memories/m1", json={"content": "new", "confidence_score": 0.9})

    assert resp.status_code == 200
    assert resp.json()["updated_fields"] == ["confidence_score", "content"]
    assert calls == {
        "memory_id": "m1",
        "changes": {"content": "new", "confidence_score": 0.9},
        "actor": "rest_api",
        "reason": "PATCH /v1/memories/{memory_id}",
    }


def test_uniform_404_error_response():
    from memoryx.api import rest_app

    class FakeRepo:
        async def get_memory(self, memory_id):
            return None

    rest_app.configure(repository=FakeRepo(), query_api=None)
    client = TestClient(rest_app.app)

    resp = client.get("/v1/memories/missing")

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "not found"


def test_live_probe_always_ok():
    from memoryx.api import rest_app

    client = TestClient(rest_app.app)
    resp = client.get("/live")

    assert resp.status_code == 200
    assert resp.json()["live"] is True
