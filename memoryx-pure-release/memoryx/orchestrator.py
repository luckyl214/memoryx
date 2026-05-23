from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ModuleStatus(StrEnum):
    UNKNOWN = "unknown"
    INITIALIZED = "initialized"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ModuleEntry:
    """模块注册条目。"""
    name: str
    instance: Any
    status: ModuleStatus = ModuleStatus.UNKNOWN
    depends_on: list[str] = field(default_factory=list)
    health_check: Callable[[], bool] | None = None
    error: str = ""


class ModuleRegistry:
    """
    轻量模块注册中心。

    不是服务发现，不是 DI 容器。
    只是一个让所有模块可以被统一访问和健康检查的地方。
    """

    def __init__(self) -> None:
        self._modules: dict[str, ModuleEntry] = {}
        self._lock = asyncio.Lock()

    def register(
        self,
        name: str,
        instance: Any,
        *,
        depends_on: list[str] | None = None,
        health_check: Callable[[], bool] | None = None,
    ) -> None:
        """注册一个模块。"""
        self._modules[name] = ModuleEntry(
            name=name,
            instance=instance,
            status=ModuleStatus.INITIALIZED,
            depends_on=depends_on or [],
            health_check=health_check,
        )

    def get(self, name: str) -> Any | None:
        """获取模块实例。"""
        entry = self._modules.get(name)
        return entry.instance if entry else None

    def status(self, name: str) -> ModuleStatus:
        entry = self._modules.get(name)
        return entry.status if entry else ModuleStatus.UNKNOWN

    def mark(self, name: str, status: ModuleStatus, error: str = "") -> None:
        entry = self._modules.get(name)
        if entry:
            entry.status = status
            entry.error = error

    def all_status(self) -> dict[str, dict]:
        """全模块状态快照。"""
        return {
            name: {"status": entry.status.value, "depends_on": entry.depends_on, "error": entry.error}
            for name, entry in self._modules.items()
        }

    def check_health(self) -> dict[str, str]:
        """运行所有模块的健康检查。"""
        results: dict[str, str] = {}
        for name, entry in self._modules.items():
            if entry.health_check:
                try:
                    ok = entry.health_check()
                    results[name] = "ok" if ok else "failed"
                except Exception as e:
                    results[name] = f"error: {e}"
            else:
                results[name] = "unknown"
        return results

    def list_by_status(self, status: ModuleStatus) -> list[str]:
        return [name for name, e in self._modules.items() if e.status == status]


class SystemOrchestrator:
    """
    系统编排器 — 统一管理模块生命周期。

    处理：启动顺序 → 依赖等待 → 健康检查 → 降级策略
    """

    def __init__(self, registry: ModuleRegistry) -> None:
        self.registry = registry

    async def initialize_all(self) -> dict[str, str]:
        """按依赖顺序初始化所有已注册模块。"""
        results: dict[str, str] = {}
        entries = list(self.registry._modules.items())
        resolved: set[str] = set()

        for _ in range(len(entries) * 2):  # 最多两倍模块数的迭代
            progress = False
            for name, entry in entries:
                if name in resolved:
                    continue
                deps = set(entry.depends_on)
                if deps.issubset(resolved):
                    try:
                        instance = entry.instance
                        if hasattr(instance, "start") and callable(instance.start):
                            await instance.start()
                        self.registry.mark(name, ModuleStatus.RUNNING)
                        results[name] = "running"
                        resolved.add(name)
                        progress = True
                    except Exception as e:
                        self.registry.mark(name, ModuleStatus.FAILED, str(e))
                        results[name] = f"failed: {e}"
                        resolved.add(name)
                        progress = True
            if not progress:
                break

        # 剩余未解析的标记为失败
        for name, entry in entries:
            if name not in resolved:
                self.registry.mark(name, ModuleStatus.FAILED, "unresolved dependency")
                results[name] = "failed: unresolved dependencies"
        return results

    async def shutdown_all(self) -> dict[str, str]:
        """逆序关闭所有模块。"""
        results: dict[str, str] = {}
        for name in reversed(list(self.registry._modules.keys())):
            entry = self.registry._modules[name]
            try:
                instance = entry.instance
                if hasattr(instance, "stop") and callable(instance.stop):
                    await instance.stop()
                self.registry.mark(name, ModuleStatus.STOPPED)
                results[name] = "stopped"
            except Exception as e:
                results[name] = f"error: {e}"
        return results

    async def health_report(self) -> dict:
        """完整的系统健康报告。"""
        checks = self.registry.check_health()
        statuses = self.registry.all_status()
        failed_modules = [n for n, s in statuses.items() if s["status"] in ("failed", "degraded")]
        return {
            "total_modules": len(statuses),
            "statuses": statuses,
            "health_checks": checks,
            "failed_modules": failed_modules,
            "healthy": len(failed_modules) == 0,
        }
