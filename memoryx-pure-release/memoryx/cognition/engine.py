from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class RuntimeCognitiveState:
    session_id: str
    focus: str = ""
    task_phase: str = ""
    reasoning_depth: int = 0
    risk_level: str = "low"
    emotional_intensity: float = 0.0
    cognitive_load: str = "low"
    risk_signals: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RuntimeCognitiveStateEngine:
    def __init__(self) -> None:
        self._states: dict[str, RuntimeCognitiveState] = {}
        self._lock = asyncio.Lock()

    async def update_state(
        self,
        *,
        session_id: str,
        focus: str = "",
        task_phase: str = "",
        reasoning_depth: int = 0,
        risk_signals: list[str] | None = None,
        emotional_intensity: float = 0.0,
    ) -> RuntimeCognitiveState:
        normalized_depth = self._clamp_int(reasoning_depth, 0, 10)
        normalized_intensity = self._clamp_float(emotional_intensity, 0.0, 1.0)
        normalized_signals = list(risk_signals or [])
        state = RuntimeCognitiveState(
            session_id=session_id,
            focus=focus,
            task_phase=task_phase,
            reasoning_depth=normalized_depth,
            risk_level=self._risk_level(normalized_signals, normalized_depth, normalized_intensity),
            emotional_intensity=normalized_intensity,
            cognitive_load=self._cognitive_load(normalized_depth, normalized_intensity, len(normalized_signals)),
            risk_signals=normalized_signals,
        )
        async with self._lock:
            self._states[session_id] = state
        return state

    async def get_state(self, session_id: str) -> RuntimeCognitiveState | None:
        async with self._lock:
            return self._states.get(session_id)

    async def summarize(self, session_id: str) -> str:
        state = await self.get_state(session_id)
        if state is None:
            return "No runtime cognitive state recorded."
        parts = []
        if state.focus:
            parts.append(f"focus={state.focus}")
        if state.task_phase:
            parts.append(f"phase={state.task_phase}")
        parts.append(f"depth={state.reasoning_depth}")
        parts.append(f"risk={state.risk_level}")
        parts.append(f"load={state.cognitive_load}")
        if state.emotional_intensity:
            parts.append(f"emotion={state.emotional_intensity:.2f}")
        if state.risk_signals:
            parts.append("signals=" + ", ".join(state.risk_signals[:3]))
        return " | ".join(parts)

    def _risk_level(self, signals: list[str], reasoning_depth: int, emotional_intensity: float) -> str:
        if len(signals) >= 3 or emotional_intensity >= 0.8 or reasoning_depth >= 8:
            return "high"
        if len(signals) >= 1 or emotional_intensity >= 0.45 or reasoning_depth >= 5:
            return "medium"
        return "low"

    def _cognitive_load(self, reasoning_depth: int, emotional_intensity: float, risk_signal_count: int) -> str:
        score = reasoning_depth + int(emotional_intensity * 4) + risk_signal_count
        if score >= 10:
            return "high"
        if score >= 4:
            return "moderate"
        return "low"

    def _clamp_int(self, value: int, lower: int, upper: int) -> int:
        return max(lower, min(int(value), upper))

    def _clamp_float(self, value: float, lower: float, upper: float) -> float:
        return max(lower, min(float(value), upper))
