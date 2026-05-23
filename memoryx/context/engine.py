from __future__ import annotations

from memoryx.retrieval import RetrievalResult
from memoryx.routing import RoutePlan

from .models import ContextBundle


class ContextAssemblyEngine:
    def __init__(self, max_token_budget: int = 1200) -> None:
        self.max_token_budget = max_token_budget

    def assemble(
        self,
        *,
        system_prompt: str,
        soul_prompt: str,
        current_task: str,
        route_plan: RoutePlan,
        recent_conversation: list[str],
        progressive: bool = False,
    ) -> ContextBundle:
        deduped = self._deduplicate(route_plan.results)
        if progressive:
            deduped = self._auto_page(deduped)
        grouped = self._group_memories(deduped, progressive=progressive)

        sections: list[tuple[str, list[str]]] = [
            ("System Prompt", [system_prompt]),
            ("SOUL", [soul_prompt]),
            ("Current Task", [current_task]),
            ("Relevant Long-Term Memory", grouped["long_term"]),
            ("Project Context", grouped["project"]),
            ("User Preferences", grouped["user"]),
            ("Relevant Episodes", grouped["episodic"]),
            ("Recent Conversation", recent_conversation),
        ]

        rendered, token_count, truncated, used_summary_fallback, section_map = self._render_with_budget(sections)
        return ContextBundle(
            rendered=rendered,
            token_count=token_count,
            truncated=truncated,
            used_summary_fallback=used_summary_fallback,
            sections=section_map,
        )

    def _deduplicate(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        seen: set[str] = set()
        deduped: list[RetrievalResult] = []
        for result in sorted(results, key=lambda item: item.final_score, reverse=True):
            normalized = result.content.strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(result)
        return deduped

    def _group_memories(self, results: list[RetrievalResult], progressive: bool = False) -> dict[str, list[str]]:
        grouped = {
            "long_term": [],
            "project": [],
            "user": [],
            "episodic": [],
        }
        for result in results:
            if progressive:
                line = f"- [{result.memory_id}] ({result.memory_type}, scope={result.scope}, score={result.final_score:.2f})"
            else:
                line = f"- ({result.memory_id}) {result.content}"
            if result.memory_type == "EPISODIC":
                grouped["episodic"].append(line)
            elif result.scope == "user" or result.memory_type == "PREFERENCE":
                grouped["user"].append(line)
            elif result.scope == "project":
                grouped["project"].append(line)
            else:
                grouped["long_term"].append(line)
        return grouped

    def _render_with_budget(self, sections: list[tuple[str, list[str]]]) -> tuple[str, int, bool, bool, dict[str, list[str]]]:
        used_summary_fallback = False
        truncated = False
        parts: list[str] = []
        section_map: dict[str, list[str]] = {}

        for title, lines in sections:
            chosen_lines = list(lines)
            if lines and not self._fits(parts, title, chosen_lines):
                summarized = self._summarize_lines(lines)
                if summarized != chosen_lines:
                    chosen_lines = summarized
                    used_summary_fallback = True
            if chosen_lines and not self._fits(parts, title, chosen_lines):
                allowed = self._fit_lines(parts, title, chosen_lines)
                chosen_lines = allowed
                truncated = True
            section_map[title] = chosen_lines
            parts.append(f"[{title}]")
            parts.extend(chosen_lines)
            parts.append("")

        rendered = "\n".join(parts).strip() + "\n"
        token_count = self._token_count(rendered)
        if token_count > self.max_token_budget:
            truncated = True
            rendered = self._trim_rendered(rendered)
            token_count = self._token_count(rendered)
        return rendered, token_count, truncated, used_summary_fallback, section_map

    def _fits(self, existing_parts: list[str], title: str, lines: list[str]) -> bool:
        candidate = "\n".join([*existing_parts, f"[{title}]", *lines, ""])
        return self._token_count(candidate) <= self.max_token_budget

    def _fit_lines(self, existing_parts: list[str], title: str, lines: list[str]) -> list[str]:
        kept: list[str] = []
        for line in lines:
            candidate = [*kept, line]
            if not self._fits(existing_parts, title, candidate):
                break
            kept.append(line)
        return kept

    def _summarize_lines(self, lines: list[str]) -> list[str]:
        if not lines:
            return []
        summaries: list[str] = []
        for line in lines[:3]:
            tokens = line.split()
            summaries.append(" ".join(tokens[:8]))
        return [f"- Summary: {' | '.join(summaries)}"]

    def _trim_rendered(self, rendered: str) -> str:
        tokens = rendered.split()
        return " ".join(tokens[: self.max_token_budget])

    def _token_count(self, text: str) -> int:
        return len(text.split())

    def _auto_page(self, results: list) -> list:
        """自动分页：当结果超过预算时，低分记忆进入 paged_out。"""
        if not results:
            return results
        total = sum(self._estimate_tokens(r.content) for r in results)
        if total <= self.max_token_budget:
            return results
        paged = sorted(results, key=lambda r: r.final_score, reverse=True)
        budget_left = self.max_token_budget
        kept: list = []
        for r in paged:
            cost = self._estimate_tokens(r.content)
            if cost <= budget_left:
                kept.append(r)
                budget_left -= cost
            else:
                break
        return kept if kept else paged[:3]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text.split()))
