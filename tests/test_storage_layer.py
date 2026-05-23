from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.storage import BackupManager, ImportExportManager, MemoryRecord, MemoryRepository, StorageMaintenance


@pytest.mark.asyncio
async def test_batch_store_memories_roundtrip(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "batch.db")
    await repo.open()

    records = [
        MemoryRecord(memory_id=f"m{i}", memory_type="TASK", content=f"task {i}")
        for i in range(10)
    ]
    inserted = await repo.store_memories(records)

    assert inserted == 10
    rows = await repo.list_active_memories(limit=20)
    assert len(rows) == 10
    await repo.close()


@pytest.mark.asyncio
async def test_backup_and_restore_export(tmp_path: Path) -> None:
    db_path = tmp_path / "backup.db"
    repo = MemoryRepository(db_path)
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="keep this memory"))

    backup_manager = BackupManager()
    backup_path = await backup_manager.create_backup(db_path, tmp_path / "backups")
    assert backup_path.exists()

    export_manager = ImportExportManager()
    export_path = await export_manager.export_json(repo, tmp_path / "exports" / "memories.json")
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported[0]["memory_id"] == "m1"

    await repo.close()


@pytest.mark.asyncio
async def test_import_json_into_fresh_repository(tmp_path: Path) -> None:
    source = tmp_path / "import.json"
    source.write_text(
        json.dumps([
            {
                "memory_id": "import-1",
                "memory_type": "FACT",
                "content": "imported memory",
                "importance_score": 0.7,
                "confidence_score": 0.8,
                "decay_score": 0.0,
                "recency_score": 0.0,
                "access_count": 0,
                "checksum": "",
                "superseded_by": None,
                "valid_from": None,
                "valid_to": None,
                "active_state": 1,
                "reinforcement_score": 0.0,
                "safety_score": 1.0,
                "scope": "global",
                "source_message_id": "src-1",
                "entities_json": "[]",
                "tags_json": "[]"
            }
        ]),
        encoding="utf-8",
    )

    repo = MemoryRepository(tmp_path / "import.db")
    await repo.open()
    manager = ImportExportManager()
    count = await manager.import_json(repo, source)

    assert count == 1
    fetched = await repo.get_memory("import-1")
    assert fetched is not None
    assert fetched["content"] == "imported memory"
    await repo.close()


@pytest.mark.asyncio
async def test_storage_maintenance_runs_integrity_and_compaction(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "maint.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="compact me"))

    maintenance = StorageMaintenance()
    integrity = await maintenance.check_integrity(repo.db)
    assert integrity == "ok"

    compacted = await maintenance.compact(repo.db)
    assert compacted is True
    await repo.close()
