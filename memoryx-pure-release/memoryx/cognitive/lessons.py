"""Backward-compatible import path for LESSON policy matching.

New code should import from memoryx.cognitive.lesson_policy.
"""

from __future__ import annotations

from .lesson_policy import LessonPolicyEngine, sync_lesson_triggers

__all__ = ["LessonPolicyEngine", "sync_lesson_triggers"]
