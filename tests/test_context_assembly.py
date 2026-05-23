from __future__ import annotations

from memoryx.context import ContextAssemblyEngine
from memoryx.retrieval import RetrievalResult
from memoryx.routing import RoutePlan, RoutingIntent


def _result(memory_id: str, content: str, scope: str = "project", memory_type: str = "PROJECT", final_score: float = 0.8) -> RetrievalResult:
    return RetrievalResult(
        memory_id=memory_id,
        content=content,
        memory_type=memory_type,
        scope=scope,
        semantic_score=0.8,
        keyword_score=0.7,
        temporal_score=0.6,
        entity_score=0.1,
        importance_score=0.9,
        episodic_score=0.0,
        final_score=final_score,
        explanation="test",
    )


def test_context_assembly_builds_prompt_sections() -> None:
    engine = ContextAssemblyEngine(max_token_budget=120)
    plan = RoutePlan(
        intent=RoutingIntent.PROJECT,
        primary_route="project",
        results=[
            _result("m1", "Project uses async SQLite storage", scope="project"),
            _result("m2", "User prefers concise replies", scope="user", memory_type="PREFERENCE"),
            _result("m3", "Deployment incident rollback timeline", scope="project", memory_type="EPISODIC"),
        ],
    )

    bundle = engine.assemble(
        system_prompt="You are Hermes.",
        soul_prompt="Stay careful.",
        current_task="Help debug memory context assembly.",
        route_plan=plan,
        recent_conversation=["user: continue", "assistant: working on phase 9"],
    )

    assert "[System Prompt]" in bundle.rendered
    assert "[SOUL]" in bundle.rendered
    assert "[Current Task]" in bundle.rendered
    assert "[Relevant Long-Term Memory]" in bundle.rendered
    assert "[User Preferences]" in bundle.rendered
    assert "[Relevant Episodes]" in bundle.rendered


def test_context_assembly_respects_token_budget() -> None:
    engine = ContextAssemblyEngine(max_token_budget=40)
    plan = RoutePlan(
        intent=RoutingIntent.PROJECT,
        primary_route="project",
        results=[
            _result("m1", "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu", final_score=0.95),
            _result("m2", "another high value memory for the same task with many tokens", final_score=0.80),
        ],
    )

    bundle = engine.assemble(
        system_prompt="sys",
        soul_prompt="soul",
        current_task="task",
        route_plan=plan,
        recent_conversation=["recent line one", "recent line two"],
    )

    assert bundle.token_count <= 40
    assert bundle.truncated is True


def test_context_assembly_deduplicates_memory_content() -> None:
    engine = ContextAssemblyEngine(max_token_budget=120)
    plan = RoutePlan(
        intent=RoutingIntent.PROJECT,
        primary_route="project",
        results=[
            _result("m1", "Same content repeated", final_score=0.9),
            _result("m2", "Same content repeated", final_score=0.8),
        ],
    )

    bundle = engine.assemble(
        system_prompt="sys",
        soul_prompt="soul",
        current_task="task",
        route_plan=plan,
        recent_conversation=[],
    )

    assert bundle.rendered.count("Same content repeated") == 1


def test_context_assembly_uses_summary_fallback_when_needed() -> None:
    engine = ContextAssemblyEngine(max_token_budget=24)
    plan = RoutePlan(
        intent=RoutingIntent.DEBUGGING,
        primary_route="debugging",
        results=[
            _result("m1", "Queue timeout debugging history with worker restart and retry tuning", memory_type="EPISODIC", final_score=0.95),
        ],
    )

    bundle = engine.assemble(
        system_prompt="sys",
        soul_prompt="soul",
        current_task="debug queue",
        route_plan=plan,
        recent_conversation=["recent conversation line"],
    )

    assert bundle.used_summary_fallback is True
