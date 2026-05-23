from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from ..events import MemoryEvent, MemoryEventType


class QueueManager:
    def __init__(self, queue_dir: Path, queue_size: int, enqueue_timeout: float) -> None:
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.queue: asyncio.Queue[MemoryEvent | None] = asyncio.Queue(maxsize=queue_size)
        self.enqueue_timeout = enqueue_timeout

    def put_nowait(self, event: MemoryEvent | None) -> None:
        self.queue.put_nowait(event)

    async def put(self, event: MemoryEvent) -> None:
        await asyncio.wait_for(self.queue.put(event), timeout=self.enqueue_timeout)

    async def get(self) -> MemoryEvent | None:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()

    def depth(self) -> int:
        return self.queue.qsize()

    def maxsize(self) -> int:
        return self.queue.maxsize

    def can_drop(self, event: MemoryEvent) -> bool:
        return event.event_type in {MemoryEventType.ON_ASSISTANT_RESPONSE, MemoryEventType.ON_TOOL_RESULT}

    async def persist(self, event: MemoryEvent) -> None:
        path = self._event_path(event.event_id)
        payload = event.model_dump(mode="json")
        await asyncio.to_thread(
            path.write_text,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    async def delete(self, event_id: str) -> None:
        await asyncio.to_thread(self._event_path(event_id).unlink, True)

    async def recover(self) -> list[MemoryEvent]:
        recovered: list[MemoryEvent] = []
        for path in sorted(self.queue_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                recovered.append(MemoryEvent.model_validate(payload))
            except Exception:
                pass
        return recovered

    def _event_path(self, event_id: str) -> Path:
        return self.queue_dir / f"{event_id}.json"
