from __future__ import annotations

from pathlib import Path
from typing import Any

from memoryx.api import MemoryQueryAPI
from memoryx.config import MemoryXSettings
from memoryx.hermes_bridge import HermesMemoryBridge
from memoryx.logging import configure_logging
from memoryx.plugin import register
from memoryx.storage import MemoryRepository


class HermesIntegrationRuntime:
    """Hermes runtime bootstrap with first-class MemoryX bridge.

    This creates the repository/query_api/bridge before registering hooks so
    hook calls can return context and guard decisions, not just enqueue events.
    """

    def __init__(self, *, home: Path, settings: MemoryXSettings | None = None) -> None:
        self.home = Path(home)
        self.settings = settings or MemoryXSettings(home=self.home)
        self._ctx: Any | None = None
        self.repository: MemoryRepository | None = None
        self.query_api: MemoryQueryAPI | None = None
        self.bridge: HermesMemoryBridge | None = None
        self.is_running = False

    async def bootstrap(self, ctx: Any) -> None:
        self.settings.ensure_directories()
        configure_logging(
            self.settings.logs_dir,
            self.settings.log_level,
            max_bytes=self.settings.log_rotation_bytes,
            backup_count=self.settings.log_backup_count,
        )

        self.repository = MemoryRepository(self.settings.db_path)
        await self.repository.open()
        self.query_api = MemoryQueryAPI(repository=self.repository, vector_store=None)
        self.bridge = HermesMemoryBridge(repository=self.repository, query_api=self.query_api)

        ctx.memoryx_settings = self.settings
        ctx.memoryx_repository = self.repository
        ctx.memoryx_query_api = self.query_api
        ctx.memoryx_bridge = self.bridge

        register(ctx)
        ctx.memoryx_listener = getattr(ctx.memoryx_manager, "listener", None)
        self._ctx = ctx
        self.is_running = True

    async def shutdown(self) -> None:
        if self._ctx is not None and getattr(self._ctx, "hooks", None) and "on_session_finalize" in self._ctx.hooks:
            await self._ctx.hooks["on_session_finalize"]()
        elif self._ctx is not None and getattr(self._ctx, "memoryx_manager", None) is not None:
            await self._ctx.memoryx_manager.stop()

        if self.repository is not None:
            await self.repository.close()
        self.is_running = False

    def startup_flow(self) -> list[str]:
        return [
            "1. Load MEMORYX_* environment configuration and bootstrap directories.",
            "2. Configure rotating structlog logging for MemoryX runtime.",
            "3. Open MemoryRepository and build MemoryQueryAPI.",
            "4. Build HermesMemoryBridge for context injection, tool guard, claim guard, and narrative reflection.",
            "5. Run plugin register() to bind Hermes hooks and middleware.",
            "6. Start MemoryHookManager background workers for async event handling.",
            "7. Shutdown drains events and closes repository.",
        ]

    def render_deployment_artifacts(self, *, service_name: str = "memoryx-hermes") -> dict[str, str]:
        project_root = self.home
        systemd_service = f"""[Unit]
Description={service_name}
After=network.target

[Service]
Type=simple
WorkingDirectory={project_root}
Environment=MEMORYX_ENV_FILE={project_root / '.env'}
ExecStart={project_root / '.venv' / 'bin' / 'python'} -m memoryx.plugin
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        deploy_script = f"""#!/usr/bin/env bash
set -euo pipefail
cd {project_root}
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p {project_root / 'logs'}
sudo cp deploy/{service_name}.service /etc/systemd/system/{service_name}.service
sudo systemctl daemon-reload
sudo systemctl enable --now {service_name}
"""
        return {"systemd_service": systemd_service, "deploy_script": deploy_script}
