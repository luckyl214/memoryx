from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.migration import MigrationEngine, AdapterRegistry
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_adapter_registry_lists_all_10_adapters() -> None:
    adapters = MigrationEngine.list_adapters()
    expected = {"tencentdb", "holographic", "hermes", "mem0", "hindsight",
                "letta", "zep", "cognee", "gbrain", "json"}
    for name in expected:
        assert name in adapters, f"Missing: {name}"
    assert len(adapters) >= 10


# ── 导入测试（JSON + Hermes 已验证可工作） ──

@pytest.mark.asyncio
async def test_import_from_json(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "im-json.db")
    await repo.open()
    jf = tmp_path / "m.json"
    jf.write_text(json.dumps({"memories": [{"content": "test", "type": "FACT"}]}))
    engine = MigrationEngine(repository=repo)
    report = await engine.migrate(source="json", source_path=str(jf))
    assert report.imported == 1
    await repo.close()


# ── 导出测试（10 个适配器全部测试 export） ──

@pytest.mark.parametrize("adapter_name", MigrationEngine.list_adapters())
@pytest.mark.asyncio
async def test_export_to_all_adapters(tmp_path: Path, adapter_name: str) -> None:
    """所有 10 个适配器至少能导出 1 条记录不报错。"""
    repo = MemoryRepository(tmp_path / f"ex-{adapter_name}.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id=f"m_{adapter_name}", memory_type="FACT",
                                          content=f"export test for {adapter_name}", importance_score=0.5))
    engine = MigrationEngine(repository=repo)
    out = tmp_path / f"out-{adapter_name}"
    out.mkdir(parents=True, exist_ok=True)
    if adapter_name in ("hermes", "gbrain"):
        target = str(out)
    else:
        target = str(out / f"export.{adapter_name}.jsonl")
    report = await engine.restore(target=adapter_name, target_path=target)
    assert report.imported >= 1, f"{adapter_name}: imported={report.imported}"
    assert not report.errors, f"{adapter_name}: errors={report.errors}"
    await repo.close()


# ── 恢复 Hermes 格式 ──

@pytest.mark.asyncio
async def test_restore_to_hermes_format(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "rest-hermes.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="h1", memory_type="FACT", content="fact one", scope="memory", importance_score=0.5))
    await repo.store_memory(MemoryRecord(memory_id="h2", memory_type="FACT", content="pref one", scope="user", importance_score=0.5))

    engine = MigrationEngine(repository=repo)
    out_dir = tmp_path / "hermes_out"
    out_dir.mkdir()
    report = await engine.restore(target="hermes", target_path=str(out_dir))
    assert report.imported == 2
    assert (out_dir / "MEMORY.md").exists()
    assert (out_dir / "USER.md").exists()
    await repo.close()


# ── 恢复 GBrain 格式 ──

@pytest.mark.asyncio
async def test_restore_to_gbrain_format(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "rest-gbrain.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="g1", memory_type="FACT", content="gbrain memory", importance_score=0.5))

    engine = MigrationEngine(repository=repo)
    out_dir = tmp_path / "gbrain_out"
    report = await engine.restore(target="gbrain", target_path=str(out_dir))
    assert report.imported >= 1
    assert len(list(out_dir.glob("*.md"))) >= 1
    await repo.close()


# ── 恢复 Mem0 格式 ──

@pytest.mark.asyncio
async def test_restore_to_mem0_format(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "rest-mem0.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="mem0 memory", importance_score=0.5,
                                          tags_json='["test"]'))

    engine = MigrationEngine(repository=repo)
    out_file = tmp_path / "mem0_out.jsonl"
    report = await engine.restore(target="mem0", target_path=str(out_file))
    assert report.imported >= 1
    lines = out_file.read_text().strip().split("\n")
    assert len(lines) >= 1
    data = json.loads(lines[0])
    assert "content" in data
    await repo.close()


@pytest.mark.asyncio
async def test_restore_with_scope_filter(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "rest-scope.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="s1", memory_type="FACT", content="project mem", scope="project", importance_score=0.5))
    await repo.store_memory(MemoryRecord(memory_id="s2", memory_type="FACT", content="user pref", scope="user", importance_score=0.5))

    engine = MigrationEngine(repository=repo)
    out = tmp_path / "scope_out.jsonl"
    report = await engine.restore(target="json", target_path=str(out), scope_filter="project")
    assert report.total_scanned == 1
    assert report.imported == 1
    await repo.close()
