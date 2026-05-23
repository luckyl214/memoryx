from __future__ import annotations

import pytest

from memoryx.tool_memory import ToolInteractionMemory


@pytest.mark.asyncio
async def test_tool_memory_tracks_shell_and_debugging_history() -> None:
    memory = ToolInteractionMemory()

    await memory.record(
        session_id="s1",
        tool_name="shell",
        action_type="debug",
        command="pytest -q tests/test_api.py",
        success=False,
        metadata={"exit_code": 1},
    )
    await memory.record(
        session_id="s1",
        tool_name="shell",
        action_type="debug",
        command="pytest -q tests/test_api.py -k retry",
        success=True,
        metadata={"exit_code": 0},
    )

    history = await memory.history(session_id="s1", action_type="debug")

    assert len(history) == 2
    assert history[0].command == "pytest -q tests/test_api.py"
    assert history[1].success is True


@pytest.mark.asyncio
async def test_tool_memory_tracks_file_ops_and_deployments() -> None:
    memory = ToolInteractionMemory()

    await memory.record(
        session_id="s2",
        tool_name="file",
        action_type="file_op",
        command="write README.md",
        success=True,
        metadata={"path": "README.md"},
    )
    await memory.record(
        session_id="s2",
        tool_name="shell",
        action_type="deployment",
        command="systemctl restart memoryx-hermes",
        success=True,
        metadata={"service": "memoryx-hermes"},
    )

    file_ops = await memory.history(session_id="s2", action_type="file_op")
    deployments = await memory.history(session_id="s2", action_type="deployment")

    assert file_ops[0].metadata["path"] == "README.md"
    assert deployments[0].command == "systemctl restart memoryx-hermes"


@pytest.mark.asyncio
async def test_tool_memory_reports_success_failure_stats() -> None:
    memory = ToolInteractionMemory()

    await memory.record(session_id="s3", tool_name="shell", action_type="debug", command="cmd-1", success=False)
    await memory.record(session_id="s3", tool_name="shell", action_type="debug", command="cmd-2", success=True)
    await memory.record(session_id="s3", tool_name="file", action_type="file_op", command="cmd-3", success=True)

    stats = await memory.stats(session_id="s3")

    assert stats["total"] == 3
    assert stats["success"] == 2
    assert stats["failure"] == 1
    assert stats["by_tool"]["shell"] == 2


@pytest.mark.asyncio
async def test_tool_memory_replays_workflow_in_order() -> None:
    memory = ToolInteractionMemory()

    await memory.record(session_id="s4", tool_name="shell", action_type="debug", command="run tests", success=False)
    await memory.record(session_id="s4", tool_name="file", action_type="file_op", command="patch api.py", success=True)
    await memory.record(session_id="s4", tool_name="shell", action_type="debug", command="run tests again", success=True)

    replay = await memory.replay(session_id="s4")

    assert replay == ["run tests", "patch api.py", "run tests again"]
