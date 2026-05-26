import pytest
from pathlib import Path

from memoryx.services.auto_store_service import AutoStoreService
from memoryx.services.memory_decision import MemoryDecisionService
from memoryx.storage import MemoryRepository


@pytest.mark.asyncio
async def test_auto_store_explicit_memory(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "memoryx.db")
    await repo.open()

    try:
        service = AutoStoreService(
            repository=repo,
            decision_service=MemoryDecisionService(llm_client=None),
        )

        result = await service.store_conversation_turn(
            session_id="s1",
            user_message="请记住，我喜欢简洁但结构清晰的回答。",
            assistant_response="好的。",
        )

        assert result.stored is True
        assert result.id

        memory = await repo.get_memory(result.id)
        assert memory is not None
        assert "结构清晰" in memory["content"]
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_auto_store_ignores_noise(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "memoryx.db")
    await repo.open()

    try:
        service = AutoStoreService(
            repository=repo,
            decision_service=MemoryDecisionService(llm_client=None),
        )

        result = await service.store_conversation_turn(
            session_id="s1",
            user_message="哈哈今天有点困",
            assistant_response="休息一下。",
        )

        assert result.stored is False
    finally:
        await repo.close()
