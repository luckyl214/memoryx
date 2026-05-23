from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .repository import MemoryRecord, MemoryRepository


class ImportExportManager:
    async def export_json(self, repository: MemoryRepository, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = await repository.list_memories(limit=10000)
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        await asyncio.to_thread(output_path.write_text, payload, encoding="utf-8")
        return output_path

    async def import_json(self, repository: MemoryRepository, input_path: Path) -> int:
        payload = await asyncio.to_thread(input_path.read_text, encoding="utf-8")
        items = json.loads(payload)
        records = [
            MemoryRecord(
                memory_id=item["memory_id"],
                memory_type=item["memory_type"],
                content=item["content"],
                importance_score=item.get("importance_score", 0.5),
                confidence_score=item.get("confidence_score", 0.5),
                decay_score=item.get("decay_score", 0.0),
                recency_score=item.get("recency_score", 0.0),
                access_count=item.get("access_count", 0),
                checksum=item.get("checksum", ""),
                superseded_by=item.get("superseded_by"),
                valid_from=item.get("valid_from"),
                valid_to=item.get("valid_to"),
                active_state=item.get("active_state", 1),
                reinforcement_score=item.get("reinforcement_score", 0.0),
                safety_score=item.get("safety_score", 1.0),
                scope=item.get("scope", "global"),
                source_message_id=item.get("source_message_id"),
                entities_json=item.get("entities_json", "[]"),
                tags_json=item.get("tags_json", "[]"),
            )
            for item in items
        ]
        return await repository.store_memories(records)
