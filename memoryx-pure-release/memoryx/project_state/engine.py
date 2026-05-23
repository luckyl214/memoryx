from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .models import ProjectState


class ProjectStateEngine:
    def __init__(self) -> None:
        self._states: dict[str, ProjectState] = {}
        self._lock = asyncio.Lock()

    async def get_state(self, *, project_id: str) -> ProjectState:
        async with self._lock:
            return self._states.setdefault(project_id, ProjectState(project_id=project_id))

    async def set_goal(self, *, project_id: str, goal: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.goal = goal
        self._touch(state)

    async def add_active_task(self, *, project_id: str, task: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.active_tasks.append(task)
        self._touch(state)

    async def add_blocked_issue(self, *, project_id: str, issue: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.blocked_issues.append(issue)
        self._touch(state)

    async def record_architecture_decision(self, *, project_id: str, decision: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.architecture_decisions.append(decision)
        self._touch(state)

    async def set_tech_stack(self, *, project_id: str, stack: list[str]) -> None:
        state = await self.get_state(project_id=project_id)
        state.tech_stack = list(stack)
        self._touch(state)

    async def set_deployment_state(self, *, project_id: str, deployment_state: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.deployment_state = deployment_state
        self._touch(state)

    async def set_milestone(self, *, project_id: str, milestone: str) -> None:
        state = await self.get_state(project_id=project_id)
        state.current_milestone = milestone
        self._touch(state)

    async def add_timeline_event(self, *, project_id: str, event: str) -> None:
        state = await self.get_state(project_id=project_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        state.evolution_timeline.append(f"{timestamp} {event}")
        self._touch(state)

    async def timeline(self, *, project_id: str) -> list[str]:
        state = await self.get_state(project_id=project_id)
        return list(state.evolution_timeline)

    def _touch(self, state: ProjectState) -> None:
        state.updated_at = datetime.now(timezone.utc)
