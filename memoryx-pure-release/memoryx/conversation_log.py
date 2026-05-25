from __future__ import annotations

from typing import Any
from uuid import uuid4


class ConversationLogStore:
    """L0 append-only conversation evidence layer.

    This implementation matches the authoritative schema:
    conversation_logs(id, session_id, scope, turn_index, role, content,
    token_count, timestamp, created_at, metadata_json)

    FTS joins use rowid because conversation_logs_fts is defined with
    content_rowid='rowid'.
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    async def log_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        scope: str = "global",
        turn_index: int | None = None,
        token_count: int | None = None,
        metadata_json: str = "{}",
    ) -> str:
        log_id = uuid4().hex
        if turn_index is None:
            row = await self.repository.db.fetchone(
                "SELECT COALESCE(MAX(turn_index), -1) + 1 AS next_turn FROM conversation_logs WHERE session_id = ?;",
                (session_id,),
            )
            turn_index = int(row["next_turn"]) if row else 0

        await self.repository.db.execute(
            """
            INSERT INTO conversation_logs(
                id, session_id, scope, turn_index, role, content, token_count, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (log_id, session_id, scope, int(turn_index), role, content, token_count, metadata_json),
        )
        return log_id

    async def log(self, session_id: str, role: str, content: str, **kwargs: Any) -> str:
        return await self.log_turn(session_id=session_id, role=role, content=content, **kwargs)

    async def session_history(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.repository.db.fetchall(
            """
            SELECT id, session_id, scope, turn_index, role, content, token_count, timestamp, created_at, metadata_json
            FROM conversation_logs
            WHERE session_id = ?
            ORDER BY turn_index ASC, timestamp ASC
            LIMIT ?;
            """,
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        tokens = self._normalize_query(query)
        if not tokens:
            return []

        params: list[Any] = [tokens]
        where = ""
        if session_id:
            where = "AND c.session_id = ?"
            params.append(session_id)
        params.append(limit)

        try:
            rows = await self.repository.db.fetchall(
                f"""
                SELECT
                    c.id, c.session_id, c.scope, c.turn_index, c.role,
                    c.content, c.token_count, c.timestamp, c.created_at, c.metadata_json,
                    bm25(conversation_logs_fts) AS rank
                FROM conversation_logs_fts f
                JOIN conversation_logs c ON c.rowid = f.rowid
                WHERE conversation_logs_fts MATCH ?
                {where}
                ORDER BY rank
                LIMIT ?;
                """,
                tuple(params),
            )
        except Exception:
            like = f"%{query[:80]}%"
            params = [like]
            where = ""
            if session_id:
                where = "AND session_id = ?"
                params.append(session_id)
            params.append(limit)
            rows = await self.repository.db.fetchall(
                f"""
                SELECT id, session_id, scope, turn_index, role, content, token_count, timestamp, created_at, metadata_json
                FROM conversation_logs
                WHERE content LIKE ?
                {where}
                ORDER BY timestamp DESC
                LIMIT ?;
                """,
                tuple(params),
            )
        return [dict(row) for row in rows]

    def _normalize_query(self, query: str) -> str:
        tokens = [
            token.strip('"\':;,.!?()[]{}')
            for token in (query or "").split()
            if token.strip('"\':;,.!?()[]{}')
        ]
        return " OR ".join(tokens[:12])
