"""P3: 权重配置 — YAML 热加载，替换硬编码 _intent_weights()。

mtime 检测：每 30 秒自动重新加载 weights.yaml。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@dataclass
class WeightConfig:
    """检索权重配置，支持意图感知覆盖。"""

    semantic: float = 1.0
    keyword: float = 1.0
    temporal: float = 0.45
    entity: float = 0.35
    importance: float = 0.6
    episodic: float = 0.4
    intents: dict[str, dict[str, float]] = field(default_factory=dict)

    def get_weights(self, intent: str | None = None) -> dict[str, float]:
        """返回 base 权重，如果指定 intent 则合并覆盖。"""
        base = {
            "semantic": self.semantic,
            "keyword": self.keyword,
            "temporal": self.temporal,
            "entity": self.entity,
            "importance": self.importance,
            "episodic": self.episodic,
        }
        if intent and intent in self.intents:
            base.update(self.intents[intent])
        return base

    @classmethod
    def from_yaml(cls, path: Path) -> "WeightConfig":
        if not path.exists():
            return cls()
        if not _HAS_YAML:
            return cls()  # no yaml → use defaults
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            semantic=float(data.get("semantic", 1.0)),
            keyword=float(data.get("keyword", 1.0)),
            temporal=float(data.get("temporal", 0.45)),
            entity=float(data.get("entity", 0.35)),
            importance=float(data.get("importance", 0.6)),
            episodic=float(data.get("episodic", 0.4)),
            intents=data.get("intents", {}),
        )


class WeightLoader:
    """热加载权重配置。

    - 首次加载从 weights.yaml 读取
    - 每 30 秒检查 mtime，变化则自动重新加载
    """

    def __init__(self, path: Path, *, reload_interval: float = 30.0) -> None:
        self.path = path
        self.reload_interval = reload_interval
        self._config: WeightConfig = WeightConfig.from_yaml(path)
        self._mtime: float = self._file_mtime()
        self._lock = threading.Lock()
        self._start_reloader()

    @property
    def config(self) -> WeightConfig:
        self._maybe_reload()
        return self._config

    def get_weights(self, intent: str | None = None) -> dict[str, float]:
        return self.config.get_weights(intent)

    def _maybe_reload(self) -> None:
        mtime = self._file_mtime()
        if mtime > self._mtime:
            with self._lock:
                if mtime > self._mtime:
                    self._config = WeightConfig.from_yaml(self.path)
                    self._mtime = mtime

    def _file_mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def _start_reloader(self) -> None:
        """Background thread: check mtime every reload_interval seconds."""
        def _loop():
            import time
            while True:
                time.sleep(self.reload_interval)
                self._maybe_reload()

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
