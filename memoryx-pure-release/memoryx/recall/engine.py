from __future__ import annotations

from memoryx.retrieval import HybridRetrievalEngine
from memoryx.routing import MemoryRouter


class ActiveRecallEngine:
    def __init__(self, *, repository, vector_store) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.retrieval_engine = HybridRetrievalEngine(repository=repository, vector_store=vector_store)
        self.router = MemoryRouter(retrieval_engine=self.retrieval_engine)

    async def recall(self, *, query: str, query_vector: list[float], limit: int = 5) -> dict:
        plan = await self.router.route(query=query, query_vector=query_vector, limit=limit)
        memories = []
        for item in plan.results:
            await self.repository.record_access(item.memory_id)
            memories.append(
                {
                    "memory_id": item.memory_id,
                    "content": item.content,
                    "memory_type": item.memory_type,
                    "scope": item.scope,
                    "final_score": item.final_score,
                    "explanation": item.explanation,
                }
            )
        return {
            "intent": plan.intent.value,
            "route": plan.primary_route,
            "route_scores": plan.route_scores,
            "memories": memories,
        }

    async def project_recall(self, *, query: str, query_vector: list[float], limit: int = 5) -> dict:
        result = await self.recall(query=query, query_vector=query_vector, limit=limit)
        filtered = [item for item in result["memories"] if item.get("scope") == "project"]
        result["route"] = "project"
        result["memories"] = filtered[:limit]
        return result
