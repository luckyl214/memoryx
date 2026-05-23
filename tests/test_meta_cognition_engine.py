from __future__ import annotations

import pytest

from memoryx.meta_cognition import MetaCognitiveReflectionEngine


@pytest.mark.asyncio
async def test_meta_cognition_tracks_confidence_and_assumptions() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="s1",
        task="debug hook bootstrap",
        strategy="inspect plugin registration",
        confidence=0.35,
        outcome="failed",
        notes="initial assumption about hook name was wrong",
        corrected_assumption="hook registration uses on_user_message",
    )
    await engine.record_observation(
        session_id="s1",
        task="debug hook bootstrap",
        strategy="read runtime integration",
        confidence=0.82,
        outcome="succeeded",
        notes="found exact hook surface",
        corrected_assumption="read real exports before patching",
    )

    profile = await engine.get_profile(session_id="s1")

    assert profile.current_task == "debug hook bootstrap"
    assert profile.average_confidence == pytest.approx(0.585, rel=1e-3)
    assert profile.confidence_trend == "rising"
    assert "hook registration uses on_user_message" in profile.corrected_assumptions
    assert "read real exports before patching" in profile.corrected_assumptions


@pytest.mark.asyncio
async def test_meta_cognition_detects_strategy_pivots_after_failures() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="s2",
        task="implement phase 28",
        strategy="guess interface from naming",
        confidence=0.4,
        outcome="failed",
    )
    await engine.record_observation(
        session_id="s2",
        task="implement phase 28",
        strategy="guess interface from naming",
        confidence=0.38,
        outcome="failed",
    )
    await engine.record_observation(
        session_id="s2",
        task="implement phase 28",
        strategy="inspect real module exports",
        confidence=0.78,
        outcome="succeeded",
    )

    profile = await engine.get_profile(session_id="s2")

    assert profile.failed_strategies == ["guess interface from naming"]
    assert profile.successful_strategies == ["inspect real module exports"]
    assert any("pivot" in signal for signal in profile.adaptation_signals)


@pytest.mark.asyncio
async def test_meta_cognition_summarizes_reflection_state() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="s3",
        task="ship phase 28",
        strategy="write failing targeted test",
        confidence=0.72,
        outcome="succeeded",
        notes="red-green-regression kept scope tight",
    )
    await engine.record_observation(
        session_id="s3",
        task="ship phase 28",
        strategy="minimal additive implementation",
        confidence=0.8,
        outcome="succeeded",
        notes="avoided touching validated storage layer",
    )

    summary = await engine.summarize_session(session_id="s3")

    assert "ship phase 28" in summary
    assert "write failing targeted test" in summary
    assert "rising" in summary or "steady" in summary
    assert "validated storage layer" in summary


@pytest.mark.asyncio
async def test_meta_cognition_keeps_sessions_isolated() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="left",
        task="left task",
        strategy="left strategy",
        confidence=0.6,
        outcome="succeeded",
    )
    await engine.record_observation(
        session_id="right",
        task="right task",
        strategy="right strategy",
        confidence=0.3,
        outcome="failed",
    )

    left = await engine.get_profile(session_id="left")
    right = await engine.get_profile(session_id="right")

    assert left.current_task == "left task"
    assert right.current_task == "right task"
    assert left.successful_strategies == ["left strategy"]
    assert right.failed_strategies == ["right strategy"]


@pytest.mark.asyncio
async def test_meta_cognition_analyzes_reasoning_quality_and_repeated_failures() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="quality",
        task="continue phase 28",
        strategy="guess from stale context",
        confidence=0.86,
        outcome="failed",
        notes="skipped current phase checkpoint and restarted wrong phase",
        corrected_assumption="resume active phase from verified repo state",
    )
    await engine.record_observation(
        session_id="quality",
        task="continue phase 28",
        strategy="guess from stale context",
        confidence=0.82,
        outcome="failed",
        notes="ignored user instruction to keep developing phase 28",
        corrected_assumption="do not switch phases during active development",
    )
    await engine.record_observation(
        session_id="quality",
        task="continue phase 28",
        strategy="recover active phase from README and tests",
        confidence=0.74,
        outcome="succeeded",
        notes="verified phase 28 implementation before patching",
    )

    profile = await engine.get_profile(session_id="quality")

    assert profile.reasoning_quality == "needs_correction"
    assert "guess from stale context" in profile.repeated_failures
    assert "recover active phase from README and tests" in profile.recommended_strategies
    assert any("resume active phase" in lesson for lesson in profile.self_improvement_lessons)


@pytest.mark.asyncio
async def test_meta_cognition_builds_self_improvement_summary() -> None:
    engine = MetaCognitiveReflectionEngine()

    await engine.record_observation(
        session_id="summary",
        task="phase 28 hardening",
        strategy="read verified tests before editing",
        confidence=0.7,
        outcome="succeeded",
        notes="protected validated layers",
        corrected_assumption="source-backed checkpoints prevent drift",
    )
    await engine.record_observation(
        session_id="summary",
        task="phase 28 hardening",
        strategy="write targeted red test",
        confidence=0.84,
        outcome="succeeded",
        notes="kept implementation minimal",
    )

    improvement = await engine.self_improvement_summary(session_id="summary")

    assert "phase 28 hardening" in improvement
    assert "reasoning_quality=strong" in improvement
    assert "read verified tests before editing" in improvement
    assert "source-backed checkpoints prevent drift" in improvement
