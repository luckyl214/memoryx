from __future__ import annotations

import pytest

from memoryx.hermes_bridge import HermesMemoryBridge


class FakeDB:
    async def fetchone(self, sql, params=()):
        return {"next_turn": 0}

    async def fetchall(self, sql, params=()):
        return []

    async def execute(self, sql, params=()):
        return None


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


class FakeAPI:
    async def search(self, **kwargs):
        return [
            {
                "memory_id": "m1",
                "content": "Never deploy production with --force without dry-run.",
                "memory_type": "LESSON",
                "final_score": 0.99,
            }
        ]


@pytest.mark.asyncio
async def test_hermes_bridge_returns_context_and_tool_guard():
    bridge = HermesMemoryBridge(repository=FakeRepo(), query_api=FakeAPI())

    context = await bridge.on_user_message(session_id="s1", content="deploy production")
    assert "MemoryX Safety Contract" in context.context_block
    assert context.memories

    guard = await bridge.on_tool_call(session_id="s1", tool_name="shell", args={"cmd": "deploy production --force"})
    assert guard.requires_user is True
    assert guard.decision in {"require_dry_run", "require_confirmation", "require_tool_verification", "block"}
