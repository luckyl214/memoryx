from __future__ import annotations

import pytest

from memoryx.cognition import RuntimeCognitiveStateEngine


@pytest.mark.asyncio
async def test_runtime_cognitive_state_tracks_focus_phase_and_depth() -> None:
    engine = RuntimeCognitiveStateEngine()

    state = await engine.update_state(
        session_id="s1",
        focus="phase 32 implementation",
        task_phase="red-green-refactor",
        reasoning_depth=4,
    )

    assert state.focus == "phase 32 implementation"
    assert state.task_phase == "red-green-refactor"
    assert state.reasoning_depth == 4
    assert state.cognitive_load == "moderate"


@pytest.mark.asyncio
async def test_runtime_cognitive_state_estimates_risk_and_load() -> None:
    engine = RuntimeCognitiveStateEngine()

    state = await engine.update_state(
        session_id="risk",
        focus="production migration",
        task_phase="verification",
        reasoning_depth=8,
        risk_signals=["schema change", "full regression pending", "public export change"],
        emotional_intensity=0.82,
    )

    assert state.risk_level == "high"
    assert state.emotional_intensity == 0.82
    assert state.cognitive_load == "high"


@pytest.mark.asyncio
async def test_runtime_cognitive_state_keeps_sessions_isolated_and_summarizes() -> None:
    engine = RuntimeCognitiveStateEngine()

    await engine.update_state(session_id="left", focus="left focus", task_phase="inspect", reasoning_depth=2)
    await engine.update_state(session_id="right", focus="right focus", task_phase="verify", reasoning_depth=5)

    left = await engine.get_state("left")
    right_summary = await engine.summarize("right")

    assert left is not None
    assert left.focus == "left focus"
    assert "right focus" in right_summary
    assert "verify" in right_summary


@pytest.mark.asyncio
async def test_runtime_cognitive_state_clamps_intensity_and_depth() -> None:
    engine = RuntimeCognitiveStateEngine()

    state = await engine.update_state(
        session_id="bounds",
        focus="bounds",
        task_phase="test",
        reasoning_depth=99,
        emotional_intensity=4.2,
    )

    assert state.reasoning_depth == 10
    assert state.emotional_intensity == 1.0
