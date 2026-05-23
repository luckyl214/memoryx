from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from memoryx.context import ContextBundle
from memoryx.retrieval import RetrievalResult
from memoryx.validation.models import ValidationDecision, ValidationResult


class MemoryEvaluationEngine:
    def evaluate_retrieval(
        self,
        *,
        results: list[RetrievalResult],
        expected_memory_ids: list[str],
    ) -> dict[str, float]:
        expected = set(expected_memory_ids)
        if not results:
            return {
                "precision_at_k": 0.0,
                "recall_at_k": 0.0,
                "hit_rate": 0.0,
                "result_count": 0.0,
            }
        hit_ids = [item.memory_id for item in results if item.memory_id in expected]
        precision = len(hit_ids) / len(results)
        recall = len(set(hit_ids)) / len(expected) if expected else 1.0
        hit_rate = 1.0 if hit_ids else 0.0
        return {
            "precision_at_k": round(precision, 6),
            "recall_at_k": round(recall, 6),
            "hit_rate": hit_rate,
            "result_count": float(len(results)),
        }

    def evaluate_context(
        self,
        *,
        bundle: ContextBundle,
        expected_terms: list[str],
        forbidden_terms: list[str],
    ) -> dict[str, float]:
        rendered = bundle.rendered.lower()
        expected_hits = sum(1 for term in expected_terms if term.lower() in rendered)
        forbidden_hits = sum(1 for term in forbidden_terms if term.lower() in rendered)
        relevance = expected_hits / max(len(expected_terms), 1)
        noise_penalty = forbidden_hits / max(len(forbidden_terms), 1) if forbidden_terms else 0.0
        section_density = sum(len(items) for items in bundle.sections.values()) / max(len(bundle.sections), 1)
        return {
            "relevance_score": round(max(0.0, relevance - (noise_penalty * 0.25)), 6),
            "noise_penalty": round(noise_penalty, 6),
            "section_density": round(section_density, 6),
            "token_count": float(bundle.token_count),
        }

    def evaluate_validation(self, decisions: Iterable[ValidationResult]) -> dict[str, float]:
        items = list(decisions)
        total = len(items)
        if total == 0:
            return {
                "accept_rate": 0.0,
                "rejection_rate": 0.0,
                "conflict_rate": 0.0,
                "hallucination_rate": 0.0,
                "case_count": 0.0,
            }
        accept = sum(1 for item in items if item.decision == ValidationDecision.ACCEPT)
        reject = sum(1 for item in items if item.decision == ValidationDecision.REJECT)
        conflict = sum(1 for item in items if item.decision == ValidationDecision.CONFLICT)
        hallucination = sum(
            1
            for item in items
            if item.decision == ValidationDecision.QUARANTINE
            or any("halluc" in flag.lower() or "prompt injection" in flag.lower() for flag in item.safety_flags)
        )
        return {
            "accept_rate": accept / total,
            "rejection_rate": reject / total,
            "conflict_rate": conflict / total,
            "hallucination_rate": hallucination / total,
            "case_count": float(total),
        }

    def run_benchmark(
        self,
        *,
        retrieval_cases: list[dict[str, Any]],
        context_cases: list[dict[str, Any]],
        validation_cases: list[ValidationResult],
    ) -> dict[str, dict[str, float]]:
        retrieval_metrics = [
            self.evaluate_retrieval(
                results=case["results"],
                expected_memory_ids=case["expected_memory_ids"],
            )
            for case in retrieval_cases
        ]
        context_metrics = [
            self.evaluate_context(
                bundle=case["bundle"],
                expected_terms=case["expected_terms"],
                forbidden_terms=case["forbidden_terms"],
            )
            for case in context_cases
        ]
        validation_metrics = self.evaluate_validation(validation_cases)
        return {
            "retrieval": self._aggregate(retrieval_metrics, case_count=len(retrieval_cases)),
            "context": self._aggregate(context_metrics, case_count=len(context_cases)),
            "validation": {**validation_metrics, "case_count": float(len(validation_cases))},
        }

    def serialize_dataset(self, items: Iterable[Any]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for item in items:
            if is_dataclass(item) and not isinstance(item, type):
                serialized.append(asdict(item))
            elif isinstance(item, dict):
                serialized.append(dict(item))
            else:
                serialized.append({"value": repr(item)})
        return serialized

    def _aggregate(self, metrics: list[dict[str, float]], *, case_count: int) -> dict[str, float]:
        if not metrics:
            return {"case_count": float(case_count)}
        keys = {key for metric in metrics for key in metric.keys()}
        summary: dict[str, float] = {"case_count": float(case_count)}
        for key in keys:
            values = [metric[key] for metric in metrics if key in metric]
            summary[key] = sum(values) / len(values)
        return summary
