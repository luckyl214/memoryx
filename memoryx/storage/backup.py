from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class BackupManager:
    async def create_backup(self, source_db_path: Path, backup_dir: Path) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = backup_dir / f"memoryx_{stamp}.sqlite3"
        await asyncio.to_thread(self._backup_sqlite, source_db_path, destination)
        return destination

    async def restore_backup(self, backup_path: Path, destination_db_path: Path) -> Path:
        destination_db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._backup_sqlite, backup_path, destination_db_path)
        return destination_db_path

    def _backup_sqlite(self, source: Path, destination: Path) -> None:
        with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            dst.commit()
