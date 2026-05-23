from __future__ import annotations

import pytest

from memoryx.project_state import ProjectStateEngine


@pytest.mark.asyncio
async def test_project_state_tracks_goals_tasks_and_blocks() -> None:
    engine = ProjectStateEngine()

    await engine.set_goal(project_id="mnx", goal="build production-grade cognitive memory OS")
    await engine.add_active_task(project_id="mnx", task="implement project state engine")
    await engine.add_blocked_issue(project_id="mnx", issue="missing deployment health check")

    state = await engine.get_state(project_id="mnx")

    assert state.goal == "build production-grade cognitive memory OS"
    assert state.active_tasks == ["implement project state engine"]
    assert state.blocked_issues == ["missing deployment health check"]


@pytest.mark.asyncio
async def test_project_state_tracks_architecture_and_stack() -> None:
    engine = ProjectStateEngine()

    await engine.record_architecture_decision(project_id="mnx", decision="use sqlite plus lancedb")
    await engine.set_tech_stack(project_id="mnx", stack=["python", "sqlite", "lancedb"])

    state = await engine.get_state(project_id="mnx")

    assert state.architecture_decisions == ["use sqlite plus lancedb"]
    assert state.tech_stack == ["python", "sqlite", "lancedb"]


@pytest.mark.asyncio
async def test_project_state_tracks_deployment_milestones_and_timeline() -> None:
    engine = ProjectStateEngine()

    await engine.set_deployment_state(project_id="mnx", deployment_state="staging")
    await engine.set_milestone(project_id="mnx", milestone="phase-27")
    await engine.add_timeline_event(project_id="mnx", event="phase 27 completed")

    state = await engine.get_state(project_id="mnx")
    timeline = await engine.timeline(project_id="mnx")

    assert state.deployment_state == "staging"
    assert state.current_milestone == "phase-27"
    assert timeline[-1].endswith("phase 27 completed")


@pytest.mark.asyncio
async def test_project_state_updates_do_not_leak_between_projects() -> None:
    engine = ProjectStateEngine()

    await engine.set_goal(project_id="mnx", goal="memory os")
    await engine.set_goal(project_id="other", goal="different project")

    mnx = await engine.get_state(project_id="mnx")
    other = await engine.get_state(project_id="other")

    assert mnx.goal == "memory os"
    assert other.goal == "different project"
