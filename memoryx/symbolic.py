from __future__ import annotations

"""
符号化索引层 — 参考 MemPalace AAAK 设计。

将记忆内容压缩为 LLM 可直接阅读的结构化摘要，
作为记忆检索的排名信号而非门。
"""

import re
from typing import Any
from uuid import uuid4


class SymbolicIndex:
    """
    符号化索引：每条记忆对应一个结构化摘要，
    存储在独立的索引表中，搜索时作为排名信号。
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    async def build_index(self, content: str, *, memory_id: str | None = None) -> str:
        """为一段内容构建符号化索引条目。"""
        entities = self._extract_entities(content)
        topics = self._extract_topics(content)
        key_sentences = self._key_sentences(content)
        emotion = self._detect_emotion(content)
        flags = self._detect_flags(content)

        summary = self._format(entities, topics, key_sentences, emotion, flags)
        index_id = uuid4().hex
        await self.repository.db.execute(
            "INSERT INTO reflection_summaries(reflection_id, summary, created_at, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (index_id, summary),
        )
        return index_id

    async def search(
        self,
        query: str,
        *,
        memory_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """在符号化索引中搜索。返回匹配条目。"""
        query_lower = query.lower()
        rows = await self.repository.db.fetchall(
            "SELECT reflection_id, summary, created_at FROM reflection_summaries ORDER BY created_at DESC LIMIT ?;",
            (limit * 5,),
        )
        scored = []
        for row in rows:
            summary = str(row["summary"])
            score = self._match_score(query_lower, summary)
            if score > 0:
                scored.append((score, {"index_id": str(row["reflection_id"]),
                                       "summary": summary, "score": score,
                                       "created_at": str(row.get("created_at", ""))}))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]

    def _extract_entities(self, text: str) -> list[str]:
        """提取实体（大写词/专有名词）。"""
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        seen: set[str] = set()
        result = []
        for w in words:
            if w.lower() not in seen:
                seen.add(w.lower())
                result.append(w)
        return result[:5]

    def _extract_topics(self, text: str) -> list[str]:
        """提取主题关键词。"""
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "this", "that",
                      "it", "to", "in", "of", "for", "with", "on", "at", "by", "from"}
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        seen: set[str] = set()
        result = []
        for w in words:
            if w not in stop_words and w not in seen:
                seen.add(w)
                result.append(w)
        return result[:8]

    def _key_sentences(self, text: str) -> list[str]:
        """提取关键句（含决策、否定、偏好词）。"""
        signals = {"decided", "chose", "prefer", "preferred", "not", "yes", "no",
                   "important", "must", "never", "always", "fix", "bug", "error"}
        sentences = re.split(r'[.!?]+', text)
        scored = []
        for s in sentences:
            s = s.strip()
            if len(s) < 10:
                continue
            words = set(s.lower().split())
            score = sum(1 for sig in signals if sig in words)
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:2]]

    def _detect_emotion(self, text: str) -> str:
        """检测情绪强度。"""
        positive = {"great", "excellent", "awesome", "good", "happy", "love", "excited"}
        negative = {"bad", "terrible", "awful", "angry", "sad", "frustrated", "error", "bug"}
        words = set(text.lower().split())
        pos = sum(1 for w in positive if w in words)
        neg = sum(1 for w in negative if w in words)
        if pos > neg and pos >= 2:
            return "positive"
        if neg > pos and neg >= 2:
            return "negative"
        return "neutral"

    def _detect_flags(self, text: str) -> list[str]:
        """检测标志（决策/问题/计划）。"""
        flags = []
        lower = text.lower()
        if any(w in lower for w in {"decided", "chose", "choose", "select"}):
            flags.append("DECISION")
        if any(w in lower for w in {"bug", "error", "fail", "issue", "problem"}):
            flags.append("ISSUE")
        if any(w in lower for w in {"plan", "todo", "next", "will", "going to"}):
            flags.append("PLAN")
        return flags

    def _format(self, entities: list[str], topics: list[str],
                sentences: list[str], emotion: str, flags: list[str]) -> str:
        """格式化为 compact 符号化摘要。"""
        parts = []
        if entities:
            parts.append(f"ENT:{'|'.join(entities)}")
        if topics:
            parts.append(f"TOP:{'|'.join(topics[:5])}")
        if sentences:
            parts.append(f"KEY:{'; '.join(s[:60] for s in sentences)}")
        parts.append(f"EMO:{emotion}")
        if flags:
            parts.append(f"FLG:{'|'.join(flags)}")
        return " | ".join(parts)

    def _match_score(self, query_lower: str, summary: str) -> float:
        """计算查询与符号摘要的匹配分数。"""
        summary_lower = summary.lower()
        query_words = set(query_lower.split())
        if not query_words:
            return 0.0
        matched = sum(1 for w in query_words if w in summary_lower)
        return matched / len(query_words)
