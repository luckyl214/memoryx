from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4


class ConversationLogStore:
    """
    L0 对话历史存储 — append-only 原始对话记录。

    每次对话轮次自动写入，支持按 session/关键词搜索原始文本。
    这是记忆系统最底层的"证据层"。
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    async def log_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
    ) -> str:
        """写入一条对话记录。"""
        log_id = uuid4().hex
        await self.repository.db.execute(
            "INSERT INTO conversation_logs(log_id, session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (log_id, session_id, role, content),
        )
        return log_id

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """搜索原始对话记录（FTS5 + session 过滤）。"""
        tokens = self._normalize_query(query)
        if not tokens:
            return []

        sql = """
            SELECT c.log_id, c.session_id, c.role, c.content, c.created_at
            FROM conversation_logs_fts f
            JOIN conversation_logs c ON c.log_id = f.log_id
            WHERE conversation_logs_fts MATCH ?
        """
        params: list[Any] = [tokens]

        if session_id:
            sql += " AND c.session_id = ?"
            params.append(session_id)

        sql += " ORDER BY bm25(conversation_logs_fts) LIMIT ?;"
        params.append(limit)

        rows = await self.repository.db.fetchall(sql, params)
        return [dict(row) for row in rows]

    async def session_history(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取某次会话的完整对话历史（按时间正序）。"""
        rows = await self.repository.db.fetchall(
            "SELECT log_id, session_id, role, content, created_at "
            "FROM conversation_logs "
            "WHERE session_id = ? "
            "ORDER BY created_at ASC LIMIT ?;",
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    async def count_by_session(self, session_id: str) -> int:
        """统计某次会话的对话轮次数。"""
        row = await self.repository.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM conversation_logs WHERE session_id = ?;",
            (session_id,),
        )
        return int(row["cnt"]) if row else 0

    def _normalize_query(self, query: str) -> str:
        tokens = [
            token
            for token in "".join(ch.lower() if ch.isalnum() else " " for ch in query).split()
            if token
        ]
        return " OR ".join(tokens)
