from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..events import MemoryEvent


class DeadLetterQueue:
    def __init__(self, dead_letters_dir: Path) -> None:
        self.dead_letters_dir = dead_letters_dir
        self.dead_letters_dir.mkdir(parents=True, exist_ok=True)

    async def write(self, event: MemoryEvent, error: str) -> None:
        path = self.dead_letters_dir / f"{event.event_id}.json"
        payload = {"event": event.model_dump(mode="json"), "error": error}
        await asyncio.to_thread(
            path.write_text,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    async def write_raw(self, source_path: Path, error: str) -> None:
        target = self.dead_letters_dir / f"corrupt-{source_path.stem}.json"
        payload = {"source_path": str(source_path), "error": error}
        await asyncio.to_thread(
            target.write_text,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def list_letters(self) -> list[Path]:
        return sorted(self.dead_letters_dir.glob("*.json"))
