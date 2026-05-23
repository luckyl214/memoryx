from __future__ import annotations

from memoryx.retrieval import RetrievalIntent

from .models import RoutePlan, RoutingIntent


class MemoryRouter:
    def __init__(self, *, retrieval_engine) -> None:
        self.retrieval_engine = retrieval_engine

    async def route(self, *, query: str, query_vector: list[float], limit: int = 5) -> RoutePlan:
        intent = self._analyze_intent(query)
        route_scores = self._score_routes(query)
        primary_route = max(route_scores, key=lambda route: route_scores[route])
        retrieval_intent = self._to_retrieval_intent(intent)
        scope_filter = self._scope_filter(primary_route)
        results = await self.retrieval_engine.retrieve(
            query=query,
            query_vector=query_vector,
            limit=limit,
            intent=retrieval_intent,
            scope_filter=scope_filter,
        )
        return RoutePlan(
            intent=intent,
            primary_route=primary_route,
            route_scores=route_scores,
            results=results,
        )

    def _analyze_intent(self, query: str) -> RoutingIntent:
        lowered = query.lower()
        if any(token in lowered for token in ("debug", "bug", "traceback", "timeout", "failing", "error")):
            return RoutingIntent.DEBUGGING
        if any(token in lowered for token in ("plan", "planning", "milestone", "roadmap", "next step")):
            return RoutingIntent.PLANNING
        if any(token in lowered for token in ("feel", "emotion", "mood", "upset", "sad")):
            return RoutingIntent.EMOTIONAL
        if any(token in lowered for token in ("project", "architecture", "milestone", "decision")):
            return RoutingIntent.PROJECT
        if any(token in lowered for token in ("troubleshoot", "investigate", "incident", "rollback")):
            return RoutingIntent.TROUBLESHOOTING
        return RoutingIntent.CODING

    def _score_routes(self, query: str) -> dict[str, float]:
        lowered = query.lower()
        base = {
            "coding": 0.1,
            "planning": 0.1,
            "emotional": 0.1,
            "project": 0.1,
            "troubleshooting": 0.1,
            "debugging": 0.1,
            "user": 0.1,
        }
        keyword_map = {
            "debugging": ("debug", "bug", "traceback", "timeout", "error", "failing"),
            "planning": ("plan", "roadmap", "milestone", "schedule", "next step"),
            "emotional": ("feel", "emotion", "mood", "sad", "happy"),
            "project": ("project", "architecture", "decision", "stack"),
            "troubleshooting": ("incident", "rollback", "recover", "investigate"),
            "coding": ("code", "python", "function", "worker", "async"),
            "user": ("preference", "prefer", "my style", "my habit", "remember my"),
        }
        for route, tokens in keyword_map.items():
            score = sum(1 for token in tokens if token in lowered)
            base[route] += score * 0.35
        if "remember my" in lowered or "preference" in lowered:
            base["user"] += 0.5
        if "deployment" in lowered or "incident" in lowered:
            base["project"] += 0.2
            base["troubleshooting"] += 0.2
        return base

    def _to_retrieval_intent(self, intent: RoutingIntent) -> RetrievalIntent:
        mapping = {
            RoutingIntent.CODING: RetrievalIntent.CODING,
            RoutingIntent.PLANNING: RetrievalIntent.PLANNING,
            RoutingIntent.EMOTIONAL: RetrievalIntent.EMOTIONAL,
            RoutingIntent.PROJECT: RetrievalIntent.PROJECT,
            RoutingIntent.TROUBLESHOOTING: RetrievalIntent.TROUBLESHOOTING,
            RoutingIntent.DEBUGGING: RetrievalIntent.DEBUGGING,
        }
        return mapping[intent]

    def _scope_filter(self, primary_route: str) -> str | None:
        if primary_route == "user":
            return "user"
        if primary_route in {"project", "planning", "debugging", "troubleshooting", "coding"}:
            return "project"
        return None
