from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.conversation_log import ConversationLogStore
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_conversation_log_logs_and_retrieves_turns(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "l0-conversation.db")
    await repo.open()
    store = ConversationLogStore(repository=repo)

    log_id = await store.log_turn(session_id="s1", role="user", content="hello world")
    await store.log_turn(session_id="s1", role="assistant", content="hi there")

    history = await store.session_history("s1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello world"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "hi there"
    assert history[0]["log_id"] == log_id
    await repo.close()


@pytest.mark.asyncio
async def test_conversation_log_fts_search(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "l0-fts.db")
    await repo.open()
    store = ConversationLogStore(repository=repo)

    await store.log_turn(session_id="s1", role="user", content="async python queue worker")
    await store.log_turn(session_id="s1", role="assistant", content="use asyncio.Queue with backpressure")
    await store.log_turn(session_id="s2", role="user", content="unrelated topic")

    results = await store.search("async queue", session_id="s1")
    assert len(results) >= 1
    assert "async python queue" in results[0]["content"] or "asyncio.Queue" in results[0]["content"]

    all_results = await store.search("queue")
    assert len(all_results) >= 1
    await repo.close()


@pytest.mark.asyncio
async def test_conversation_log_counts_and_isolation(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "l0-count.db")
    await repo.open()
    store = ConversationLogStore(repository=repo)

    await store.log_turn(session_id="s1", role="user", content="a")
    await store.log_turn(session_id="s1", role="assistant", content="b")
    await store.log_turn(session_id="s2", role="user", content="c")

    assert await store.count_by_session("s1") == 2
    assert await store.count_by_session("s2") == 1
    assert await store.count_by_session("missing") == 0
    await repo.close()
