from __future__ import annotations

import asyncio
import pytest

from memoryx.orchestrator import ModuleRegistry, ModuleStatus, SystemOrchestrator


class FakeModule:
    def __init__(self, name: str, fail_start: bool = False, check_healthy: bool = True):
        self.name = name
        self.fail_start = fail_start
        self.check_healthy = check_healthy
        self.started = False
        self.stopped = False

    async def start(self):
        if self.fail_start:
            raise RuntimeError(f"{self.name} failed to start")
        self.started = True

    async def stop(self):
        self.stopped = True

    def is_healthy(self) -> bool:
        return self.check_healthy


@pytest.mark.asyncio
async def test_module_registry_register_and_get():
    reg = ModuleRegistry()
    mod = FakeModule("test")
    reg.register("test", mod)
    assert reg.get("test") is mod
    assert reg.status("test") == ModuleStatus.INITIALIZED


@pytest.mark.asyncio
async def test_orchestrator_initializes_modules_in_order():
    reg = ModuleRegistry()
    a = FakeModule("a")
    b = FakeModule("b")
    reg.register("a", a)
    reg.register("b", b, depends_on=["a"])
    orch = SystemOrchestrator(reg)
    results = await orch.initialize_all()
    assert results["a"] == "running"
    assert results["b"] == "running"
    assert a.started is True
    assert b.started is True


@pytest.mark.asyncio
async def test_orchestrator_shuts_down_in_reverse():
    reg = ModuleRegistry()
    a = FakeModule("a")
    b = FakeModule("b")
    reg.register("a", a)
    reg.register("b", b)
    orch = SystemOrchestrator(reg)
    await orch.initialize_all()
    await orch.shutdown_all()
    assert a.stopped is True
    assert b.stopped is True


@pytest.mark.asyncio
async def test_orchestrator_handles_failed_modules():
    reg = ModuleRegistry()
    ok_mod = FakeModule("ok")
    bad_mod = FakeModule("bad", fail_start=True)
    reg.register("ok", ok_mod)
    reg.register("bad", bad_mod)
    orch = SystemOrchestrator(reg)
    results = await orch.initialize_all()
    assert results["ok"] == "running"
    assert "failed" in results["bad"]
    assert ok_mod.started is True


@pytest.mark.asyncio
async def test_orchestrator_health_report():
    reg = ModuleRegistry()
    healthy = FakeModule("healthy_check", check_healthy=True)
    reg.register("healthy_check", healthy, health_check=healthy.is_healthy)
    orch = SystemOrchestrator(reg)
    report = await orch.health_report()
    assert report["total_modules"] == 1
    assert report["healthy"] is True
