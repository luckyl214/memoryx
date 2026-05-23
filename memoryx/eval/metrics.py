"""P3: 标准化检索评估指标。

支持 Recall@k、Precision@k、NDCG@k、MRR@k。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    """单条 query 的评估结果。"""
    query: str
    recall_at_k: dict[int, float] = field(default_factory=dict)
    precision_at_k: dict[int, float] = field(default_factory=dict)
    ndcg_at_k: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0


@dataclass
class EvalSuite:
    """聚合评估结果。"""
    results: list[EvalResult] = field(default_factory=list)

    def mean(self, metric: str, k: int = 0) -> float:
        values = []
        for r in self.results:
            d = getattr(r, metric, 0.0)
            if isinstance(d, dict):
                if k in d:
                    values.append(d[k])
            elif isinstance(d, (int, float)):
                values.append(float(d))
        return sum(values) / len(values) if values else 0.0


def evaluate_query(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    *,
    k_values: tuple[int, ...] = (5, 10),
) -> EvalResult:
    """计算单条 query 的 Recall/Precision/NDCG/MRR。

    Args:
        retrieved_ids: 检索返回的 memory_id 列表（按 rank 排序）
        relevant_ids: 真实相关的 memory_id 集合
        k_values: 评估的 k 值
    """
    result = EvalResult(query="")

    for k in k_values:
        top_k = retrieved_ids[:k]
        hits = [1 if rid in relevant_ids else 0 for rid in top_k]
        hit_count = sum(hits)
        total_relevant = len(relevant_ids)

        # Recall@k
        result.recall_at_k[k] = hit_count / total_relevant if total_relevant > 0 else 0.0

        # Precision@k
        result.precision_at_k[k] = hit_count / k if k > 0 else 0.0

        # NDCG@k
        dcg = _dcg(hits)
        ideal_hits = sorted(hits + [0] * (k - len(hits)), reverse=True)[:k]
        idcg = _dcg(ideal_hits)
        result.ndcg_at_k[k] = dcg / idcg if idcg > 0 else 0.0

    # MRR
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            result.mrr = 1.0 / rank
            break

    return result


def _dcg(hits: list[int]) -> float:
    """Discounted Cumulative Gain."""
    dcg = 0.0
    for i, hit in enumerate(hits):
        if i == 0:
            dcg += hit
        else:
            dcg += hit / math.log2(i + 2)
    return dcg
