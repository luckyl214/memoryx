from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError


EXPLICIT_SAVE_MARKERS = (
    "记住",
    "你要记住",
    "请记住",
    "以后",
    "从现在开始",
    "我的偏好",
    "我喜欢",
    "我不喜欢",
    "默认",
    "约定",
    "规则",
)

TEMPORARY_MARKERS = (
    "今天",
    "刚才",
    "现在有点",
    "临时",
    "随便",
    "哈哈",
    "笑死",
)

SENSITIVE_MARKERS = (
    "身份证",
    "银行卡",
    "密码",
    "token",
    "api key",
    "secret",
    "私钥",
    "住址",
    "手机号",
)


class ExtractedMemory(BaseModel):
    should_save: bool = False
    memory_type: str = "OBSERVATION"
    content: str = ""
    importance_score: float = Field(default=0.4, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
    tags: list[str] = Field(default_factory=list)
    source_type: str = "agent_inferred"


@dataclass(slots=True)
class MemoryDecision:
    should_save: bool
    memory_type: str = "OBSERVATION"
    content: str = ""
    importance_score: float = 0.4
    confidence_score: float = 0.5
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    source_type: str = "agent_inferred"
    used_llm: bool = False
    blocked_reason: str = ""


class MemoryDecisionService:
    """
    适配小模型的长期记忆判断器。

    规则：
    - 明确要求记住：优先保存。
    - 临时闲聊：不保存。
    - 敏感信息：默认不自动保存。
    - LLM 只提取候选；最终必须通过本地规则校验。
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client

    async def decide(
        self,
        *,
        user_message: str,
        assistant_response: str = "",
        source: str = "hermes.post_llm_call",
    ) -> MemoryDecision:
        text = self._normalize(f"User: {user_message}\nAssistant: {assistant_response}")

        if not text.strip():
            return MemoryDecision(False, blocked_reason="empty_content")

        if self._looks_sensitive(text):
            return MemoryDecision(False, blocked_reason="sensitive_content")

        rule_decision = self._rule_based_decision(
            user_message=user_message,
            assistant_response=assistant_response,
            source=source,
        )

        if rule_decision.should_save:
            return rule_decision

        if self.llm_client is None:
            return rule_decision

        try:
            llm_decision = await self._llm_decide(
                user_message=user_message,
                assistant_response=assistant_response,
                source=source,
            )
        except Exception:
            return rule_decision

        return self._merge_and_guard(rule_decision, llm_decision)

    def _rule_based_decision(
        self,
        *,
        user_message: str,
        assistant_response: str,
        source: str,
    ) -> MemoryDecision:
        user = user_message.strip()
        whole = f"{user_message}\n{assistant_response}".strip()

        if self._looks_temporary(user):
            return MemoryDecision(False, blocked_reason="temporary_or_chitchat")

        explicit = any(marker in user for marker in EXPLICIT_SAVE_MARKERS)

        if explicit:
            memory_type = self._infer_type(user)
            content = self._clean_explicit_content(user)
            return MemoryDecision(
                should_save=True,
                memory_type=memory_type,
                content=content,
                importance_score=0.75,
                confidence_score=0.9,
                reason="user_explicit_memory_marker",
                tags=self._infer_tags(content),
                source_type="user_explicit",
                used_llm=False,
            )

        project_like = self._looks_project_fact(whole)
        if project_like:
            return MemoryDecision(
                should_save=True,
                memory_type="PROJECT",
                content=self._summarize_locally(whole),
                importance_score=0.65,
                confidence_score=0.75,
                reason="project_or_workflow_fact",
                tags=self._infer_tags(whole),
                source_type="agent_inferred",
                used_llm=False,
            )

        return MemoryDecision(False, blocked_reason="not_worth_long_term_memory")

    async def _llm_decide(
        self,
        *,
        user_message: str,
        assistant_response: str,
        source: str,
    ) -> MemoryDecision:
        system = (
            "你是 MemoryX 的长期记忆提取器。"
            "你只能输出 JSON。不要输出 markdown。"
            "只提取未来多次会话仍然有用的稳定事实、偏好、项目约束、工作流、错误教训。"
            "不要保存闲聊、短期情绪、一次性信息、敏感身份信息、密码、token。"
        )

        user = f"""
请判断下面对话是否值得写入长期记忆。

用户消息:
{user_message}

助手回复:
{assistant_response}

输出 JSON，字段必须是:
{{
  "should_save": true/false,
  "memory_type": "PREFERENCE|PROJECT|LESSON|FACT|OBSERVATION",
  "content": "一句话记忆内容",
  "importance_score": 0.0到1.0,
  "confidence_score": 0.0到1.0,
  "reason": "为什么保存或不保存",
  "tags": ["tag1", "tag2"],
  "source_type": "user_explicit|agent_inferred|tool_verified"
}}
"""

        data = await self.llm_client.complete_json(
            system=system,
            user=user,
            schema_hint=ExtractedMemory.model_json_schema(),
        )

        try:
            parsed = ExtractedMemory.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid memory extraction JSON: {exc}") from exc

        return MemoryDecision(
            should_save=parsed.should_save,
            memory_type=parsed.memory_type,
            content=parsed.content.strip(),
            importance_score=parsed.importance_score,
            confidence_score=parsed.confidence_score,
            reason=parsed.reason,
            tags=[self._safe_tag(t) for t in parsed.tags if self._safe_tag(t)],
            source_type=parsed.source_type,
            used_llm=True,
        )

    def _merge_and_guard(
        self,
        rule_decision: MemoryDecision,
        llm_decision: MemoryDecision,
    ) -> MemoryDecision:
        if not llm_decision.should_save:
            return rule_decision

        if not llm_decision.content or len(llm_decision.content) < 6:
            return rule_decision

        if self._looks_sensitive(llm_decision.content):
            return MemoryDecision(False, blocked_reason="llm_extracted_sensitive_content")

        if llm_decision.confidence_score < 0.68:
            return MemoryDecision(False, blocked_reason="llm_confidence_too_low")

        if llm_decision.memory_type not in {
            "PREFERENCE",
            "PROJECT",
            "LESSON",
            "FACT",
            "OBSERVATION",
        }:
            llm_decision.memory_type = "OBSERVATION"

        llm_decision.importance_score = min(max(llm_decision.importance_score, 0.0), 1.0)
        llm_decision.confidence_score = min(max(llm_decision.confidence_score, 0.0), 1.0)
        return llm_decision

    def content_hash(self, content: str) -> str:
        normalized = self._normalize(content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _infer_type(self, text: str) -> str:
        lower = text.lower()
        if any(x in text for x in ("喜欢", "不喜欢", "偏好")) or "prefer" in lower:
            return "PREFERENCE"
        if any(x in text for x in ("项目", "MemoryX", "Hermes", "数据库", "架构", "代码")):
            return "PROJECT"
        if any(x in text for x in ("不要再", "以后避免", "教训", "错误")):
            return "LESSON"
        return "FACT"

    def _infer_tags(self, text: str) -> list[str]:
        tags: set[str] = set()
        lower = text.lower()
        if "memoryx" in lower:
            tags.add("memoryx")
        if "hermes" in lower:
            tags.add("hermes")
        if "sqlite" in lower:
            tags.add("sqlite")
        if "api" in lower:
            tags.add("api")
        if "偏好" in text or "喜欢" in text:
            tags.add("preference")
        if "项目" in text or "架构" in text:
            tags.add("project")
        return sorted(tags)

    def _looks_sensitive(self, text: str) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in SENSITIVE_MARKERS)

    def _looks_temporary(self, text: str) -> bool:
        if len(text.strip()) < 8:
            return True
        return any(marker in text for marker in TEMPORARY_MARKERS)

    def _looks_project_fact(self, text: str) -> bool:
        patterns = (
            r"项目.*(使用|采用|基于|依赖)",
            r"(MemoryX|Hermes).*(使用|采用|依赖|需要|必须|不要)",
            r"(数据库|架构|接口|模型|服务).*(使用|采用|必须|不要|默认)",
            r"(以后|默认|约定).*(使用|采用|不要|必须)",
        )
        return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)

    def _clean_explicit_content(self, text: str) -> str:
        cleaned = text.strip()
        for marker in ("请记住", "你要记住", "记住"):
            cleaned = cleaned.replace(marker, "").strip(" ：:，,。")
        return cleaned[:800]

    def _summarize_locally(self, text: str) -> str:
        text = self._normalize(text)
        return text[:800]

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _safe_tag(self, tag: str) -> str:
        tag = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", str(tag).strip().lower())
        return tag[:40]
