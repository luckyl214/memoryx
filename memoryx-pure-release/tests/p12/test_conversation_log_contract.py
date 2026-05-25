from __future__ import annotations

import pytest

from memoryx.conversation_log import ConversationLogStore


class FakeDB:
    def __init__(self):
        self.sql = []

    async def fetchone(self, sql, params=()):
        return {"next_turn": 0}

    async def fetchall(self, sql, params=()):
        return []

    async def execute(self, sql, params=()):
        self.sql.append(sql)


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


@pytest.mark.asyncio
async def test_conversation_log_uses_schema_id_not_log_id():
    repo = FakeRepo()
    store = ConversationLogStore(repo)

    await store.log_turn(session_id="s1", role="user", content="hello")

    assert repo.db.sql
    assert "conversation_logs(" in repo.db.sql[0]
    assert "log_id" not in repo.db.sql[0]
    assert "id, session_id" in repo.db.sql[0]
