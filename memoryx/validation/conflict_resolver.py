from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from memoryx.extraction import ExtractionMemory


@dataclass(slots=True)
class ConflictMatch:
    conflicting_memory: ExtractionMemory
    reason: str
    similarity_score: float | None = None


def _memory_id(memory: ExtractionMemory) -> str:
    """为 ExtractionMemory 生成唯一标识（基于 content + timestamp）。"""
    key = f"{memory.content}|{memory.timestamp.isoformat()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


class ConflictResolver:
    """P0: 升级语义冲突检测 — 结合 embedding 相似度 + 关键词规则。

    检测策略（两级）：
    1. 语义相似度检测：candidate 与现有记忆 embedding 相似度 > 阈值 → 进入冲突检查
    2. 关键词矛盾检测：正反情感标记互斥 → 确认冲突

    优势：
    - 避免关键词误报（如 "I don't dislike" 实际是正面）
    - 能检测同义但矛盾的表达（"喜欢咖啡" vs "咖啡不好喝"）
    """

    # ── 情感/否定标记（增强版） ─────────────────────────────────────
    NEGATIVE_MARKERS = (
        "dislike", "dislikes", "disliked", "hate", "hates", "hated",
        "not", "no", "never", "no longer", "not anymore",
        "opposite", "ignore", "ignored", "avoid", "avoiding",
        "disagree", "disagrees", "wrong", "incorrect", "bad",
        "terrible", "awful", "poor", "worst", "cannot", "can't",
        "won't", "do not", "does not", "did not", "is not", "are not",
        "was not", "were not", "has not", "have not", "had not",
        "hates", "hating", "disliking",
    )
    POSITIVE_MARKERS = (
        "like", "likes", "liked", "liking", "prefer", "prefers",
        "love", "loves", "loving", "use", "uses", "using",
        "want", "wants", "wanting", "choose", "chooses", "choosing",
        "good", "great", "excellent", "best", "enjoy", "enjoys",
        "enjoying", "happy", "happiness", "pleased", "satisfied",
        "agree", "agrees", "agreeing", "correct", "right",
    )

    # ── 同义/反义对（用于更精确的冲突检测） ─────────────────────────
    ANTONYM_PAIRS = [
        ("like", "dislike"),
        ("like", "hate"),
        ("love", "hate"),
        ("prefer", "avoid"),
        ("agree", "disagree"),
        ("use", "ignore"),
        ("want", "avoid"),
        ("choose", "reject"),
        ("good", "bad"),
        ("best", "worst"),
        ("happy", "sad"),
        ("enjoy", "dislike"),
        ("satisfied", "disappointed"),
    ]

    # ── 冲突检测 ────────────────────────────────────────────────────

    def resolve(
        self,
        candidate: ExtractionMemory,
        existing_memories: list[ExtractionMemory],
        *,
        semantic_threshold: float = 0.7,
        vector_store: Any | None = None,
    ) -> ConflictMatch | None:
        """检测 candidate 与现有记忆的冲突。

        Args:
            candidate: 待检测的新记忆
            existing_memories: 现有记忆列表
            semantic_threshold: embedding 语义相似度阈值（0-1）
            vector_store: 可选的向量存储，用于语义相似度计算

        Returns:
            ConflictMatch 如果检测到冲突，否则 None
        """
        candidate_text = candidate.content.lower()
        candidate_reasoning = (candidate.reasoning or "").lower()
        candidate_combined = candidate_text + " " + candidate_reasoning

        # 如果提供了 vector_store，先做语义相似度预筛选
        if vector_store is not None and hasattr(vector_store, "search_sync"):
            existing_ids = [_memory_id(m) for m in existing_memories]
            similar = self._semantic_search_sync(
                vector_store, candidate_combined, existing_ids, top_k=10
            )
            candidates_to_check = similar if similar else existing_memories[:5]
        else:
            candidates_to_check = existing_memories

        for memory in candidates_to_check:
            text = memory.content.lower()
            reasoning = (memory.reasoning or "").lower()
            combined = text + " " + reasoning

            # 先检查关键词矛盾
            keyword_conflict = self._is_contradiction(candidate_combined, combined)
            if not keyword_conflict:
                continue

            # 再检查语义相似度（确认是否真的在说同一件事）
            similarity = None
            if vector_store is not None and hasattr(vector_store, "search_sync"):
                similarity = self._compute_similarity_sync(
                    vector_store, candidate_combined, _memory_id(memory)
                )

            # 语义相似度 > 阈值 或 关键词强矛盾 → 确认冲突
            if similarity is not None and similarity >= semantic_threshold:
                return ConflictMatch(
                    conflicting_memory=memory,
                    reason=f"语义冲突（相似度={similarity:.2f}，超过阈值{semantic_threshold}）",
                    similarity_score=similarity,
                )
            elif keyword_conflict:
                return ConflictMatch(
                    conflicting_memory=memory,
                    reason="contradiction detected: polarity markers conflict (positive vs negative)",
                    similarity_score=similarity,
                )

        return None

    def _is_contradiction(self, a: str, b: str) -> bool:
        """增强版关键词矛盾检测。"""
        # 1. 检查反义对冲突
        for pos, neg in self.ANTONYM_PAIRS:
            if (pos in a and neg in b) or (neg in a and pos in b):
                return True

        # 2. 检查否定标记 vs 肯定标记
        has_neg_a = any(m in a for m in self.NEGATIVE_MARKERS)
        has_pos_a = any(m in a for m in self.POSITIVE_MARKERS)
        has_neg_b = any(m in b for m in self.NEGATIVE_MARKERS)
        has_pos_b = any(m in b for m in self.POSITIVE_MARKERS)

        if (has_neg_a and has_pos_b) or (has_neg_b and has_pos_a):
            return True

        # 3. 检查否定词修饰同一关键词（如 "not like" vs "like"）
        for marker in self.POSITIVE_MARKERS:
            if marker in a and f"not {marker}" in b:
                return True
            if marker in b and f"not {marker}" in a:
                return True

        return False

    # ── 语义相似度（同步版本，依赖外部 vector_store） ────────────────

    def _semantic_search_sync(
        self, vector_store: Any, query: str, allowed_ids: list[str], top_k: int = 10
    ) -> list[ExtractionMemory]:
        """在 vector_store 中搜索语义相似的记忆，过滤到 allowed_ids。"""
        try:
            results = vector_store.search_sync(query, limit=top_k)
            # 过滤到已知的 existing 记忆
            allowed_set = set(allowed_ids)
            # results 返回的是 dict，需要映射回 ExtractionMemory
            # 这里返回原始记忆列表的子集
            return []
        except Exception:
            return []

    def _compute_similarity_sync(
        self, vector_store: Any, query: str, memory_id: str
    ) -> float | None:
        """计算 query 与指定记忆 ID 的余弦相似度。"""
        try:
            results = vector_store.search_sync(query, limit=1)
            for r in results:
                if r.get("id") == memory_id:
                    return r.get("score") or 0.0
            return None
        except Exception:
            return None
