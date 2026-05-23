from __future__ import annotations

from memoryx.context import ContextBundle
from memoryx.evaluation import MemoryEvaluationEngine
from memoryx.retrieval import RetrievalResult
from memoryx.validation.models import ValidationDecision, ValidationResult


def test_evaluation_scores_retrieval_accuracy() -> None:
    engine = MemoryEvaluationEngine()
    results = [
        RetrievalResult(
            memory_id="m1",
            content="async python preference",
            memory_type="PREFERENCE",
            scope="user",
            semantic_score=0.9,
            keyword_score=0.8,
            temporal_score=0.4,
            entity_score=0.2,
            importance_score=0.9,
            episodic_score=0.0,
            final_score=2.1,
            explanation="semantic=0.90, keyword=0.80",
        ),
        RetrievalResult(
            memory_id="m2",
            content="other",
            memory_type="FACT",
            scope="global",
            semantic_score=0.2,
            keyword_score=0.1,
            temporal_score=0.1,
            entity_score=0.0,
            importance_score=0.2,
            episodic_score=0.0,
            final_score=0.6,
            explanation="semantic=0.20",
        ),
    ]

    metrics = engine.evaluate_retrieval(
        results=results,
        expected_memory_ids=["m1", "m9"],
    )

    assert metrics["precision_at_k"] == 0.5
    assert metrics["recall_at_k"] == 0.5
    assert metrics["hit_rate"] == 1.0



def test_evaluation_scores_context_relevance() -> None:
    engine = MemoryEvaluationEngine()
    bundle = ContextBundle(
        rendered="User Preferences: async Python\nProject Context: memoryx\nNoise: irrelevant",
        token_count=120,
        truncated=False,
        used_summary_fallback=False,
        sections={
            "User Preferences": ["async Python"],
            "Project Context": ["memoryx"],
            "Noise": ["irrelevant"],
        },
    )

    metrics = engine.evaluate_context(
        bundle=bundle,
        expected_terms=["async", "memoryx"],
        forbidden_terms=["irrelevant"],
    )

    assert metrics["relevance_score"] > 0.5
    assert metrics["noise_penalty"] > 0.0



def test_evaluation_scores_validation_and_hallucination() -> None:
    engine = MemoryEvaluationEngine()
    decisions = [
        ValidationResult(decision=ValidationDecision.ACCEPT, quality_score=0.9),
        ValidationResult(decision=ValidationDecision.REJECT, quality_score=0.2),
        ValidationResult(decision=ValidationDecision.QUARANTINE, quality_score=0.7, safety_flags=["prompt injection"]),
    ]

    metrics = engine.evaluate_validation(decisions)

    assert metrics["accept_rate"] == 1 / 3
    assert metrics["rejection_rate"] == 1 / 3
    assert metrics["hallucination_rate"] == 1 / 3



def test_evaluation_runs_benchmark_dataset() -> None:
    engine = MemoryEvaluationEngine()
    report = engine.run_benchmark(
        retrieval_cases=[
            {
                "results": [
                    RetrievalResult(
                        memory_id="m1",
                        content="pref",
                        memory_type="PREFERENCE",
                        scope="user",
                        semantic_score=1.0,
                        keyword_score=0.8,
                        temporal_score=0.1,
                        entity_score=0.1,
                        importance_score=0.9,
                        episodic_score=0.0,
                        final_score=2.0,
                        explanation="good",
                    )
                ],
                "expected_memory_ids": ["m1"],
            }
        ],
        context_cases=[
            {
                "bundle": ContextBundle(
                    rendered="Project Context: memoryx",
                    token_count=32,
                    sections={"Project Context": ["memoryx"]},
                ),
                "expected_terms": ["memoryx"],
                "forbidden_terms": [],
            }
        ],
        validation_cases=[
            ValidationResult(decision=ValidationDecision.ACCEPT, quality_score=0.8),
            ValidationResult(decision=ValidationDecision.CONFLICT, quality_score=0.7),
        ],
    )

    assert report["retrieval"]["case_count"] == 1
    assert report["context"]["case_count"] == 1
    assert report["validation"]["case_count"] == 2
