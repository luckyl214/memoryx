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

    def __init__(self, api: MemoryQueryAPI) -> None:
        self.api = api
        self._tools: dict[str, dict] = {}

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
            return await self.api.search(
                query=arguments["query"],
                query_vector=[],  # caller provides vector or uses FTS only
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
            result = await self.api.reflect_synthesis(
                query=arguments["query"],
                query_vector=[],
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
