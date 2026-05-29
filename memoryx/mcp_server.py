"""
MCP 服务器 — 将 memoryx 暴露为 MCP 原生工具。

兼容 Claude Code、Gemini CLI 等 MCP 客户端。
"""
from __future__ import annotations

import json
from typing import Any

from .api import MemoryQueryAPI


class MCPServer:
    """轻量 MCP 服务器，暴露 memoryx 工具。"""
    def __init__(self, api, embedding_manager=None, *, allow_embedding_fallback: bool = False) -> None:
        self.api = api
        self.embedding_manager = embedding_manager
        self.allow_embedding_fallback = allow_embedding_fallback
        self._tools: dict[str, dict] = {}

        # P8: instrument MCP tools for observability
        try:
            from memoryx.mcp.observed import instrument_mcp_server
            instrument_mcp_server(
                self,
                tool_names=["memoryx_search", "memoryx_feedback"],
            )
        except ImportError:
            pass

    async def _query_vector(self, query: str) -> list[float]:
        """Generate query vector using embedding_manager if available.

        Falls back to empty vector when no embedding_manager is configured.
        Controlled by allow_embedding_fallback flag.
        """
        if self.embedding_manager is not None:
            try:
                return await self.embedding_manager.embed_text(query)
            except Exception:
                pass
        # strict: require_embeddings=False, allow_fts_fallback=True
        return []

    def list_tools(self) -> list[dict]:
        """返回 MCP 工具列表。"""
        return [
            {
                "name": "memoryx_search",
                "description": "搜索结构化长期记忆",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询"},
                        "limit": {"type": "integer", "default": 5},
                        "tag_filter": {"type": "array", "items": {"type": "string"}, "description": "标签过滤"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memoryx_conversation_search",
                "description": "搜索原始对话历史",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "session_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memoryx_reflect",
                "description": "跨记忆 LLM 合成推理",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memoryx_feedback",
                "description": "为记忆提供纠正反馈",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "positive": {"type": "boolean"},
                    },
                    "required": ["memory_id", "positive"],
                },
            },
            {
                "name": "memoryx_store",
                "description": "手动存储一条记忆",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "memory_type": {"type": "string", "default": "FACT"},
                        "scope": {"type": "string", "default": "global"},
                    },
                    "required": ["content"],
                },
            },
        ]

    async def handle_call(self, tool_name: str, arguments: dict) -> Any:
        """处理 MCP 工具调用。"""
        if tool_name == "memoryx_search":
            query = arguments["query"]
            query_vector = await self._query_vector(query)
            return await self.api.search(
                query=query,
                query_vector=query_vector,
                limit=arguments.get("limit", 5),
                tag_filter=arguments.get("tag_filter"),
            )
        elif tool_name == "memoryx_conversation_search":
            return await self.api.conversation_search(
                query=arguments["query"],
                session_id=arguments.get("session_id"),
                limit=arguments.get("limit", 5),
            )
        elif tool_name == "memoryx_reflect":
            query = arguments["query"]
            query_vector = await self._query_vector(query)
            result = await self.api.reflect_synthesis(
                query=query,
                query_vector=query_vector,
                limit=arguments.get("limit", 10),
            )
            return result
        elif tool_name == "memoryx_feedback":
            return await self.api.feedback(
                memory_id=arguments["memory_id"],
                positive=arguments["positive"],
            )
        elif tool_name == "memoryx_store":
            return {"memory_id": await self.api.store(
                content=arguments["content"],
                memory_type=arguments.get("memory_type", "FACT"),
                scope=arguments.get("scope", "global"),
            )}
        return {"error": f"Unknown tool: {tool_name}"}
