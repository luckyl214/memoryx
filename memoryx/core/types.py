from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    FACT = "FACT"
    EXPERIENCE = "EXPERIENCE"
    OBSERVATION = "OBSERVATION"
    OPINION = "OPINION"
    PREFERENCE = "PREFERENCE"
    PROJECT = "PROJECT"
    TASK = "TASK"
    RELATION = "RELATION"
    EPISODIC = "EPISODIC"
    ENT_RELATION = "ENT_RELATION"
    PERSONA = "PERSONA"


class MemoryCategory(StrEnum):
    """记忆类别 — 参考 Mem0 多类别设计"""
    USER = "user"
    SESSION = "session"
    AGENT = "agent"


class MemoryLayer(StrEnum):
    """记忆层级 — 参考 Letta 分层记忆设计"""
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ARCHIVE = "archive"
    SELF_EDIT = "self_edit"


class MemorySource(StrEnum):
    """记忆来源"""
    DIALOGUE = "dialogue"
    TOOL_RESULT = "tool_result"
    MANUAL = "manual"
    SYSTEM = "system"
