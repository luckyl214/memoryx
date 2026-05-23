from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class ProjectState:
    project_id: str
    goal: str = ""
    architecture_decisions: list[str] = field(default_factory=list)
    active_tasks: list[str] = field(default_factory=list)
    blocked_issues: list[str] = field(default_factory=list)
    deployment_state: str = ""
    current_milestone: str = ""
    tech_stack: list[str] = field(default_factory=list)
    evolution_timeline: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
