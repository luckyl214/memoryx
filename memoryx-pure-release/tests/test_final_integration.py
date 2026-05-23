from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.integration import HermesIntegrationRuntime


class DummyContext:
    def __init__(self) -> None:
        self.hooks = {}
        self.middlewares = []
        self.memoryx_manager = None
        self.memoryx_listener = None

    def register_hook(self, name, handler) -> None:
        self.hooks[name] = handler

    def register_middleware(self, middleware) -> None:
        self.middlewares.append(middleware)


@pytest.mark.asyncio
async def test_runtime_bootstrap_registers_plugin_and_starts(tmp_path: Path) -> None:
    runtime = HermesIntegrationRuntime(home=tmp_path)
    ctx = DummyContext()

    await runtime.bootstrap(ctx)

    assert ctx.memoryx_manager is not None
    assert ctx.memoryx_listener is not None
    assert "on_user_message" in ctx.hooks
    assert runtime.is_running is True

    await runtime.shutdown()
    assert runtime.is_running is False


@pytest.mark.asyncio
async def test_runtime_renders_deployment_artifacts(tmp_path: Path) -> None:
    runtime = HermesIntegrationRuntime(home=tmp_path)

    artifacts = runtime.render_deployment_artifacts(service_name="memoryx-hermes")

    assert "systemd_service" in artifacts
    assert "deploy_script" in artifacts
    assert "ExecStart" in artifacts["systemd_service"]
    assert "memoryx-hermes" in artifacts["systemd_service"]
    assert "#!/usr/bin/env bash" in artifacts["deploy_script"]


@pytest.mark.asyncio
async def test_runtime_reports_startup_flow() -> None:
    runtime = HermesIntegrationRuntime(home=Path("/tmp/memoryx-runtime"))

    flow = runtime.startup_flow()

    assert flow[0].startswith("1.")
    assert any("plugin register" in step.lower() for step in flow)
    assert any("background workers" in step.lower() for step in flow)
