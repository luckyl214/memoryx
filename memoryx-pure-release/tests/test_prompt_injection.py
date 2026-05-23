from __future__ import annotations

from memoryx.context import ContextAssemblyEngine
from memoryx.injection import PromptInjectionEngine
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


def test_prompt_injection_builds_merged_prompt() -> None:
    context_engine = ContextAssemblyEngine(max_token_budget=120)
    injector = PromptInjectionEngine(context_engine=context_engine, max_token_budget=120)
    plan = RoutePlan(
        intent=RoutingIntent.PROJECT,
        primary_route="project",
        results=[
            _result("m1", "Project uses async SQLite storage"),
            _result("m2", "User prefers concise replies", scope="user", memory_type="PREFERENCE"),
        ],
    )

    prompt = injector.build_prompt(
        system_prompt="System base.",
        soul_prompt="Stay careful.",
        current_task="Implement prompt injection.",
        route_plan=plan,
        recent_conversation=["user: continue"],
    )

    assert "[System Prompt]" in prompt.rendered
    assert "[Relevant Long-Term Memory]" in prompt.rendered
    assert "[User Preferences]" in prompt.rendered
    assert prompt.truncated is False


def test_prompt_injection_falls_back_when_budget_is_small() -> None:
    context_engine = ContextAssemblyEngine(max_token_budget=30)
    injector = PromptInjectionEngine(context_engine=context_engine, max_token_budget=30)
    plan = RoutePlan(
        intent=RoutingIntent.DEBUGGING,
        primary_route="debugging",
        results=[_result("m1", "A very long memory that will not fit into the token budget and should be summarized")],
    )

    prompt = injector.build_prompt(
        system_prompt="System base.",
        soul_prompt="Stay careful.",
        current_task="Fix bug.",
        route_plan=plan,
        recent_conversation=["user: help"],
    )

    assert prompt.used_summary_fallback is True
    assert prompt.token_count <= 30


def test_prompt_injection_supports_middleware_hooks() -> None:
    context_engine = ContextAssemblyEngine(max_token_budget=120)
    injector = PromptInjectionEngine(context_engine=context_engine, max_token_budget=120)

    def add_suffix(prompt_text: str) -> str:
        return prompt_text + "\n[Injected] demo"

    injector.register_middleware(add_suffix)
    prompt = injector.inject_text("base prompt")

    assert prompt.rendered.endswith("[Injected] demo\n")


def test_prompt_injection_deduplicates_context_sections() -> None:
    context_engine = ContextAssemblyEngine(max_token_budget=120)
    injector = PromptInjectionEngine(context_engine=context_engine, max_token_budget=120)
    plan = RoutePlan(
        intent=RoutingIntent.PROJECT,
        primary_route="project",
        results=[
            _result("m1", "Same memory"),
            _result("m2", "Same memory"),
        ],
    )

    prompt = injector.build_prompt(
        system_prompt="System base.",
        soul_prompt="Stay careful.",
        current_task="Implement prompt injection.",
        route_plan=plan,
        recent_conversation=[],
    )

    assert prompt.rendered.count("Same memory") == 1
