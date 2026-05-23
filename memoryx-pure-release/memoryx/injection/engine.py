from __future__ import annotations

from collections.abc import Callable

from memoryx.context import ContextAssemblyEngine
from memoryx.routing import RoutePlan

from .models import InjectedPrompt


class PromptInjectionEngine:
    def __init__(self, *, context_engine: ContextAssemblyEngine, max_token_budget: int = 1200) -> None:
        self.context_engine = context_engine
        self.max_token_budget = max_token_budget
        self._middleware: list[Callable[[str], str]] = []

    def register_middleware(self, middleware: Callable[[str], str]) -> None:
        self._middleware.append(middleware)

    def build_prompt(
        self,
        *,
        system_prompt: str,
        soul_prompt: str,
        current_task: str,
        route_plan: RoutePlan,
        recent_conversation: list[str],
    ) -> InjectedPrompt:
        bundle = self.context_engine.assemble(
            system_prompt=system_prompt,
            soul_prompt=soul_prompt,
            current_task=current_task,
            route_plan=route_plan,
            recent_conversation=recent_conversation,
        )
        rendered = bundle.rendered
        for middleware in self._middleware:
            rendered = middleware(rendered)
        rendered = self._enforce_budget(rendered)
        return InjectedPrompt(
            rendered=rendered,
            token_count=len(rendered.split()),
            truncated=len(rendered.split()) >= self.max_token_budget and bundle.truncated,
            used_summary_fallback=bundle.used_summary_fallback,
        )

    def inject_text(self, base_prompt: str) -> InjectedPrompt:
        rendered = base_prompt
        for middleware in self._middleware:
            rendered = middleware(rendered)
        if not rendered.endswith("\n"):
            rendered += "\n"
        rendered = self._enforce_budget(rendered)
        return InjectedPrompt(rendered=rendered, token_count=len(rendered.split()))

    def _enforce_budget(self, rendered: str) -> str:
        tokens = rendered.split()
        if len(tokens) <= self.max_token_budget:
            if not rendered.endswith("\n"):
                return rendered + "\n"
            return rendered
        trimmed = " ".join(tokens[: self.max_token_budget])
        return trimmed + "\n"
