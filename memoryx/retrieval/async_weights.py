from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WeightConfig:
    semantic: float = 1.0
    keyword: float = 1.0
    temporal: float = 0.45
    entity: float = 0.35
    importance: float = 0.6
    episodic: float = 0.4
    lesson: float = 1.0
    intents: dict[str, dict[str, float]] = field(default_factory=dict)

    def get_weights(self, intent: str | None = None) -> dict[str, float]:
        base = {
            "semantic": self.semantic,
            "keyword": self.keyword,
            "temporal": self.temporal,
            "entity": self.entity,
            "importance": self.importance,
            "episodic": self.episodic,
            "lesson": self.lesson,
        }
        if intent and intent in self.intents:
            base.update({k: float(v) for k, v in self.intents[intent].items()})
        return base

    @classmethod
    def from_yaml(cls, path: Path) -> "WeightConfig":
        if not path.exists():
            return cls()
        text = path.read_text(encoding="utf-8")
        data = _tiny_yaml_weights(text)
        return cls(
            semantic=float(data.get("semantic", 1.0)),
            keyword=float(data.get("keyword", 1.0)),
            temporal=float(data.get("temporal", 0.45)),
            entity=float(data.get("entity", 0.35)),
            importance=float(data.get("importance", 0.6)),
            episodic=float(data.get("episodic", 0.4)),
            lesson=float(data.get("lesson", 1.0)),
            intents=data.get("intents", {}) or {},
        )


def _tiny_yaml_weights(text: str) -> dict[str, Any]:
    """Small parser for config/weights.yaml; avoids adding PyYAML dependency."""
    root: dict[str, Any] = {}
    current_intent: str | None = None
    in_intents = False
    key_value_re = re.compile(r"^([A-Za-z_][\w\-]*):\s*(.*?)\s*$")
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        match = key_value_re.match(stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if indent == 0 and key == "intents":
            root.setdefault("intents", {})
            in_intents = True
            current_intent = None
            continue
        if indent == 0:
            in_intents = False
            root[key] = _parse_scalar(value)
            continue
        if in_intents and indent == 2:
            current_intent = key
            root.setdefault("intents", {}).setdefault(current_intent, {})
            continue
        if in_intents and indent >= 4 and current_intent:
            root.setdefault("intents", {}).setdefault(current_intent, {})[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    if value == "":
        return {}
    try:
        return float(value)
    except ValueError:
        return value.strip('"\'')


class AsyncWeightProvider:
    """Async-safe hot loader with runtime DB overrides.

    Replaces daemon-thread polling. Call start() during orchestrator startup and
    stop() during shutdown. asyncio.Lock protects shared config inside one event
    loop; no OS-thread synchronization is used.
    """

    def __init__(self, path: Path, *, repository=None, reload_interval: float = 30.0) -> None:
        self.path = path
        self.repository = repository
        self.reload_interval = reload_interval
        self._config = WeightConfig.from_yaml(path)
        self._mtime = self._file_mtime()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopped.clear()
            self._task = asyncio.create_task(self._reload_loop(), name="memoryx-weight-loader")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def weights_for(
        self,
        *,
        intent: str | None = None,
        session_id: str | None = None,
        query: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        await self._maybe_reload()
        async with self._lock:
            weights = self._config.get_weights(intent)
        runtime = await self._runtime_overrides(intent=intent, session_id=session_id)
        for override in runtime:
            for key, value in override.items():
                if key in weights:
                    weights[key] = float(value)
        return weights

    async def get_weights(self, intent: str | None = None) -> dict[str, float]:
        return await self.weights_for(intent=intent)

    async def _reload_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.reload_interval)
            except asyncio.TimeoutError:
                await self._maybe_reload()

    async def _maybe_reload(self) -> None:
        mtime = self._file_mtime()
        if mtime <= self._mtime:
            return
        async with self._lock:
            if mtime > self._mtime:
                self._config = await asyncio.to_thread(WeightConfig.from_yaml, self.path)
                self._mtime = mtime

    def _file_mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    async def _runtime_overrides(self, *, intent: str | None, session_id: str | None) -> list[dict[str, float]]:
        if self.repository is None:
            return []
        clauses = ["active_state = 'active'", "(expires_at IS NULL OR expires_at > datetime('now'))"]
        params: list[Any] = []
        if session_id:
            clauses.append("(session_id IS NULL OR session_id = ?)")
            params.append(session_id)
        else:
            clauses.append("session_id IS NULL")
        if intent:
            clauses.append("(intent IS NULL OR intent = ?)")
            params.append(intent)
        else:
            clauses.append("intent IS NULL")
        try:
            rows = await self.repository.db.fetchall(
                f"""
                SELECT weights_json FROM retrieval_weight_overrides
                WHERE {' AND '.join(clauses)}
                ORDER BY priority ASC, created_at ASC;
                """,
                tuple(params),
            )
        except Exception:
            return []
        overrides: list[dict[str, float]] = []
        for row in rows:
            try:
                data = json.loads(row["weights_json"])
            except Exception:
                continue
            if isinstance(data, dict):
                overrides.append({str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))})
        return overrides
