from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class NarrativeReflection:
    reflection_id: str
    window_start: str
    window_end: str
    reflection_type: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    entity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NarrativeReflectionEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def generate(self, *, window_start: str, window_end: str, session_id: str | None = None, entity_id: str | None = None, reflection_type: str = "periodic", store: bool = True) -> NarrativeReflection:
        task_rows = await self._task_durations(window_start, window_end, session_id, entity_id)
        shift_rows = await self._opinion_shifts(window_start, window_end, entity_id)
        lesson_rows = await self._lessons(window_start, window_end, session_id)
        claim_rows = await self._claim_runs(window_start, window_end, session_id)

        metrics = {
            "task_count": len(task_rows),
            "total_duration_seconds": sum(int(r.get("duration_seconds") or 0) for r in task_rows),
            "opinion_shift_count": len(shift_rows),
            "new_lesson_count": len(lesson_rows),
            "claim_verification_count": len(claim_rows),
            "claim_risk_avg": self._avg([float(r.get("risk_score") or 0.0) for r in claim_rows]),
        }
        lines = [
            f"时间窗口 {window_start} 到 {window_end} 的认知总结：",
            self._task_summary(task_rows),
            self._opinion_summary(shift_rows),
            self._lesson_summary(lesson_rows),
            self._claim_summary(claim_rows),
        ]
        summary = "\n".join(x for x in lines if x)
        evidence: list[dict[str, Any]] = []
        evidence.extend({"type": "task_duration", **dict(r)} for r in task_rows[:10])
        evidence.extend({"type": "opinion_shift", **dict(r)} for r in shift_rows[:10])
        evidence.extend({"type": "lesson", **dict(r)} for r in lesson_rows[:10])
        evidence.extend({"type": "claim_verification", **dict(r)} for r in claim_rows[:10])
        reflection = NarrativeReflection(uuid4().hex, window_start, window_end, reflection_type, summary, evidence, metrics, session_id, entity_id)
        if store:
            await self.persist(reflection)
        return reflection

    async def _task_durations(self, start: str, end: str, session_id: str | None, entity_id: str | None):
        clauses = ["start_time >= ?", "end_time <= ?"]
        params: list[Any] = [start, end]
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        return await self.repository.db.fetchall(f"SELECT * FROM task_durations WHERE {' AND '.join(clauses)} ORDER BY duration_seconds DESC LIMIT 50;", tuple(params))

    async def _opinion_shifts(self, start: str, end: str, entity_id: str | None):
        clauses = ["from_time >= ?", "to_time <= ?"]
        params: list[Any] = [start, end]
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        return await self.repository.db.fetchall(f"SELECT * FROM opinion_shifts WHERE {' AND '.join(clauses)} ORDER BY ABS(delta) DESC LIMIT 50;", tuple(params))

    async def _lessons(self, start: str, end: str, session_id: str | None):
        return await self.repository.db.fetchall(
            "SELECT * FROM lesson_memories WHERE created_at >= ? AND created_at <= ? AND active_state = 'active' ORDER BY severity DESC, evidence_count DESC LIMIT 50;",
            (start, end),
        )

    async def _claim_runs(self, start: str, end: str, session_id: str | None):
        clauses = ["created_at >= ?", "created_at <= ?"]
        params: list[Any] = [start, end]
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        return await self.repository.db.fetchall(f"SELECT * FROM claim_verification_runs WHERE {' AND '.join(clauses)} ORDER BY risk_score DESC LIMIT 50;", tuple(params))

    def _task_summary(self, rows) -> str:
        if not rows:
            return "任务耗时：本窗口没有记录到显式任务耗时。"
        total = sum(int(r.get("duration_seconds") or 0) for r in rows)
        return f"任务耗时：共记录 {len(rows)} 项任务，累计约 {total / 3600.0:.2f} 小时。"

    def _opinion_summary(self, rows) -> str:
        if not rows:
            return "观点变化：本窗口没有检测到显著观点变化。"
        strongest = rows[0]
        return f"观点变化：检测到 {len(rows)} 个显著变化；最大变化为 {float(strongest.get('delta') or 0.0):+.2f}，从「{strongest.get('before_summary', '')}」转向「{strongest.get('after_summary', '')}」。"

    def _lesson_summary(self, rows) -> str:
        if not rows:
            return "学习教训：本窗口没有新增高置信 LESSON。"
        return f"学习教训：新增/活跃 {len(rows)} 条 LESSON；最高优先级教训是「{rows[0].get('lesson_text', '')}」。"

    def _claim_summary(self, rows) -> str:
        if not rows:
            return "事实校验：本窗口没有记录回答事实校验。"
        avg = self._avg([float(r.get("risk_score") or 0.0) for r in rows])
        blocked = sum(1 for r in rows if r.get("action") == "block")
        warned = sum(1 for r in rows if r.get("action") == "warn")
        return f"事实校验：共 {len(rows)} 次回答校验，平均风险 {avg:.2f}，warn={warned}，block={blocked}。"

    def _avg(self, values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    async def persist(self, reflection: NarrativeReflection) -> None:
        await self.repository.db.execute(
            """
            INSERT INTO narrative_reflections(id, session_id, entity_id, window_start, window_end, reflection_type, summary, evidence_json, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (reflection.reflection_id, reflection.session_id, reflection.entity_id, reflection.window_start, reflection.window_end, reflection.reflection_type, reflection.summary, json.dumps(reflection.evidence, ensure_ascii=False, default=str), json.dumps(reflection.metrics, ensure_ascii=False, sort_keys=True)),
        )
