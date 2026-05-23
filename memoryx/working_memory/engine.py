from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from .models import WorkingMemoryState


class WorkingMemoryEngine:
    def __init__(self, *, default_ttl_seconds: float = 900.0) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._states: dict[str, WorkingMemoryState] = {}
        self._lock = asyncio.Lock()

    async def update_task_state(
        self,
        *,
        session_id: str,
        task: str,
        reasoning_chain: list[str] | None = None,
        todos: list[str] | None = None,
        workflow_state: dict | None = None,
    ) -> WorkingMemoryState:
        async with self._lock:
            state = self._states.get(session_id) or self._new_state(session_id)
            state.current_task = task
            if reasoning_chain is not None:
                state.reasoning_chain = list(reasoning_chain)
            if todos is not None:
                state.active_todos = list(todos)
            if workflow_state is not None:
                state.workflow_state = dict(workflow_state)
            self._touch(state)
            self._states[session_id] = state
            return state

    async def update_debug_state(
        self,
        *,
        session_id: str,
        debug_session: dict | None = None,
        temporary_context: dict | None = None,
    ) -> WorkingMemoryState:
        async with self._lock:
            state = self._states.get(session_id) or self._new_state(session_id)
            if debug_session is not None:
                state.debug_session = dict(debug_session)
            if temporary_context is not None:
                state.temporary_context = dict(temporary_context)
            self._touch(state)
            self._states[session_id] = state
            return state

    async def get_state(self, session_id: str) -> WorkingMemoryState | None:
        async with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return None
            if self._is_expired(state):
                self._states.pop(session_id, None)
                return None
            return state

    async def expire_stale(self) -> int:
        async with self._lock:
            stale_ids = [session_id for session_id, state in self._states.items() if self._is_expired(state)]
            for session_id in stale_ids:
                self._states.pop(session_id, None)
            return len(stale_ids)

    async def compress_state(self, session_id: str, *, max_reasoning_items: int = 3, max_todos: int = 3) -> str:
        async with self._lock:
            state = self._states.get(session_id)
            if state is None or self._is_expired(state):
                self._states.pop(session_id, None)
                return ""
            state.reasoning_chain = state.reasoning_chain[:max_reasoning_items]
            state.active_todos = state.active_todos[:max_todos]
            self._touch(state)
            summary_parts = []
            if state.current_task:
                summary_parts.append(f"task={state.current_task}")
            if state.reasoning_chain:
                summary_parts.append("reasoning=" + " -> ".join(state.reasoning_chain))
            if state.active_todos:
                summary_parts.append("todos=" + ", ".join(state.active_todos))
            return " | ".join(summary_parts)

    def _new_state(self, session_id: str) -> WorkingMemoryState:
        state = WorkingMemoryState(session_id=session_id)
        self._touch(state)
        return state

    def _touch(self, state: WorkingMemoryState) -> None:
        now = datetime.now(timezone.utc)
        state.updated_at = now
        state.expires_at = now + timedelta(seconds=self.default_ttl_seconds)

    def _is_expired(self, state: WorkingMemoryState) -> bool:
        return datetime.now(timezone.utc) >= state.expires_at
