from __future__ import annotations


class EpisodicMemoryEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def record_episode(self, session_id: str, title: str, events: list[str], importance_score: float = 0.5) -> str:
        content = self.summarize_events(events)
        return await self.repository.add_episodic_memory(
            session_id=session_id,
            title=title,
            content=content,
            importance_score=importance_score,
        )

    def summarize_events(self, events: list[str]) -> str:
        cleaned = [item.strip() for item in events if item and item.strip()]
        return " -> ".join(cleaned)

    async def session_timeline(self, session_id: str) -> list[dict]:
        rows = await self.repository.db.fetchall(
            "SELECT id AS episodic_id, session_id, summary AS title, content, importance_score, created_at, created_at AS updated_at FROM episodic_memories WHERE session_id = ? ORDER BY created_at ASC;",
            (session_id,),
        )
        return [dict(item) for item in rows]

    async def top_episodes(self, limit: int = 10) -> list[dict]:
        rows = await self.repository.db.fetchall(
            "SELECT id AS episodic_id, session_id, summary AS title, content, importance_score, created_at, created_at AS updated_at FROM episodic_memories ORDER BY importance_score DESC, created_at DESC LIMIT ?;",
            (limit,),
        )
        return [dict(item) for item in rows]

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        token = f"%{query.lower()}%"
        rows = await self.repository.db.fetchall(
            "SELECT id AS episodic_id, session_id, summary AS title, content, importance_score, created_at, created_at AS updated_at FROM episodic_memories WHERE lower(summary) LIKE ? OR lower(content) LIKE ? ORDER BY importance_score DESC, created_at DESC LIMIT ?;",
            (token, token, limit),
        )
        return [dict(item) for item in rows]
