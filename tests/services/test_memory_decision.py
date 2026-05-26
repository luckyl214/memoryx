import pytest

from memoryx.services.memory_decision import MemoryDecisionService


@pytest.mark.asyncio
async def test_explicit_memory_is_saved():
    service = MemoryDecisionService(llm_client=None)

    decision = await service.decide(
        user_message="请记住，我以后希望 MemoryX 默认使用 SQLite。",
        assistant_response="好的。",
    )

    assert decision.should_save is True
    assert decision.memory_type in {"PROJECT", "FACT"}
    assert "SQLite" in decision.content
    assert decision.source_type == "user_explicit"
    assert decision.confidence_score >= 0.8


@pytest.mark.asyncio
async def test_chitchat_is_not_saved():
    service = MemoryDecisionService(llm_client=None)

    decision = await service.decide(
        user_message="哈哈今天有点困",
        assistant_response="休息一下吧。",
    )

    assert decision.should_save is False


@pytest.mark.asyncio
async def test_sensitive_content_is_blocked():
    service = MemoryDecisionService(llm_client=None)

    decision = await service.decide(
        user_message="记住我的密码是 123456",
        assistant_response="",
    )

    assert decision.should_save is False
    assert decision.blocked_reason == "sensitive_content"


class FakeLLM:
    async def complete_json(self, *, system, user, schema_hint=None):
        return {
            "should_save": True,
            "memory_type": "PROJECT",
            "content": "MemoryX 项目使用商汤 Lite 模型作为低成本提取器。",
            "importance_score": 0.7,
            "confidence_score": 0.82,
            "reason": "stable project configuration",
            "tags": ["memoryx", "sensenova"],
            "source_type": "agent_inferred",
        }


@pytest.mark.asyncio
async def test_llm_candidate_can_be_saved_when_confident():
    service = MemoryDecisionService(llm_client=FakeLLM())

    decision = await service.decide(
        user_message="我们这个项目商汤 Lite 模型主要做记忆提取。",
        assistant_response="明白。",
    )

    assert decision.should_save is True
    assert decision.used_llm is True
    assert decision.memory_type == "PROJECT"
