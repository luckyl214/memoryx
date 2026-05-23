"""
迁移适配器 — 双向：从其他记忆系统导入到 memoryx / 从 memoryx 恢复到其他系统。

支持的源/目标系统（共 10 个）：
- tencentdb:  TencentDB Agent Memory (L0→L3)
- holographic: Hermes Holographic Memory
- hermes:      Hermes 默认记忆文件 (MEMORY.md / USER.md)
- mem0:        Mem0 记忆层 (JSON 格式)
- hindsight:   Hindsight 记忆系统
- letta:       Letta / MemGPT 分层记忆
- zep:         Zep 长期记忆
- cognee:      Cognee 认知记忆框架
- gbrain:      GBrain 本地化记忆
- json:        通用 JSON / JSONL / CSV
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """适配器注册表 — 按名称发现适配器。"""

    _adapters: dict[str, type["BaseAdapter"]] = {}

    @classmethod
    def register(cls, name: str):
        """注册适配器的装饰器。"""
        def wrapper(adapter_cls: type["BaseAdapter"]) -> type["BaseAdapter"]:
            cls._adapters[name] = adapter_cls
            return adapter_cls
        return wrapper

    @classmethod
    def get(cls, name: str) -> type["BaseAdapter"]:
        if name not in cls._adapters:
            raise ValueError(f"Unknown adapter: {name}. Available: {list(cls._adapters.keys())}")
        return cls._adapters[name]

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._adapters.keys())


class BaseAdapter(ABC):
    """适配器基类 — 所有迁移适配器必须实现的两个方向。"""

    source_name: str = ""
    target_name: str = ""

    # ── 导入方向：从源系统 → memoryx ──

    @abstractmethod
    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        """扫描源系统，返回归一化的记忆记录列表。"""
        ...

    @abstractmethod
    def describe(self) -> str:
        """返回适配器描述。"""

    # ── 导出方向：从 memoryx → 目标系统 ──

    async def export(self, records: list[dict[str, Any]], target_path: str) -> int:
        """将 memoryx 记录导出为目标系统的格式。
        返回导出的记录数。默认输出 JSONL。"""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        exported = 0
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                converted = self._to_target(rec)
                f.write(json.dumps(converted, ensure_ascii=False) + "\n")
                exported += 1
        logger.info("%s export: %d records → %s", self.target_name, exported, path)
        return exported

    @abstractmethod
    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        """将归一化记录转换为目标系统格式。"""
        ...

    # ── 归一化 ──

    @staticmethod
    def normalize(record: dict[str, Any]) -> dict[str, Any]:
        """将源记录归一化为 memoryx MemoryRecord 兼容格式。"""
        return {
            "memory_id": record.get("memory_id", uuid4().hex),
            "memory_type": record.get("memory_type", "FACT"),
            "content": record.get("content", ""),
            "scope": record.get("scope", "imported"),
            "importance_score": float(record.get("importance_score", 0.5)),
            "confidence_score": float(record.get("confidence_score", 0.5)),
            "tags_json": json.dumps(record.get("tags", []), ensure_ascii=False),
            "source_message_id": record.get("source_message_id", ""),
        }


# ═══════════════════════════════════════════
#  现 有 适 配 器（已增加 export 能力）
# ═══════════════════════════════════════════

@AdapterRegistry.register("tencentdb")
class TencentDBAdapter(BaseAdapter):
    source_name = "tencentdb"
    target_name = "tencentdb"

    def describe(self) -> str:
        return "TencentDB Agent Memory (L0→L3)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        db_path = Path(source_path)
        if not db_path.exists():
            raise FileNotFoundError(f"TencentDB database not found: {db_path}")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        records: list[dict[str, Any]] = []

        for table in ["l1_records", "l0_conversations"]:
            try:
                if table == "l1_records":
                    rows = conn.execute(
                        "SELECT record_id, content, type, priority, scene_name, session_key, "
                        "session_id, metadata_json, created_time, updated_time FROM l1_records ORDER BY updated_time DESC LIMIT 5000;"
                    ).fetchall()
                    for r in rows:
                        d = dict(r)
                        records.append({"memory_id": d["record_id"], "memory_type": str(d.get("type", "FACT")).upper(),
                            "content": str(d.get("content", "")), "scope": d.get("scene_name", "imported") or "imported",
                            "importance_score": min(1.0, max(0.0, int(d.get("priority", 50)) / 100.0)),
                            "confidence_score": 0.7, "tags": [], "source_message_id": d.get("session_key", ""), "_source": "tencentdb_l1"})
                else:
                    rows = conn.execute(
                        "SELECT record_id, role, message_text, session_key, session_id, recorded_at FROM l0_conversations ORDER BY recorded_at DESC LIMIT 5000;"
                    ).fetchall()
                    for r in rows:
                        d = dict(r)
                        content = str(d.get("message_text", "")).strip()
                        if not content: continue
                        records.append({"memory_id": d["record_id"], "memory_type": "OBSERVATION" if d["role"] == "assistant" else "EXPERIENCE",
                            "content": content, "scope": "conversation", "importance_score": 0.3, "confidence_score": 0.5,
                            "tags": [], "source_message_id": d.get("session_key", ""), "_source": "tencentdb_l0"})
            except sqlite3.OperationalError:
                continue

        try:
            for r in conn.execute("SELECT entity_id, name, entity_type, aliases FROM entities ORDER BY entity_id LIMIT 2000;"):
                d = dict(r)
                records.append({"memory_id": f"ent_{d['entity_id']}", "memory_type": "ENT_RELATION",
                    "content": f"Entity: {d['name']} ({d.get('entity_type', 'unknown')})", "scope": "entity",
                    "importance_score": 0.5, "confidence_score": 0.8, "tags": [d.get('entity_type', 'unknown')],
                    "source_message_id": "", "_source": "tencentdb_entity"})
        except sqlite3.OperationalError:
            pass
        conn.close()

        data_dir = db_path.parent
        for p, mt, scope, tag in [
            (data_dir.parent / "persona.md", "PERSONA", "persona", ["persona", "l3"]),
        ]:
            if p.exists():
                c = p.read_text(encoding="utf-8").strip()
                if c:
                    records.append({"memory_id": "tencentdb_persona", "memory_type": mt, "content": c, "scope": scope,
                        "importance_score": 0.95, "confidence_score": 0.9, "tags": tag, "source_message_id": "", "_source": "tencentdb_" + mt.lower()})

        scenes_dir = data_dir.parent / "scene_blocks"
        if scenes_dir.is_dir():
            for sf in sorted(scenes_dir.glob("*.md")):
                c = sf.read_text(encoding="utf-8").strip()
                if c:
                    records.append({"memory_id": f"scene_{sf.stem[:40]}", "memory_type": "OBSERVATION", "content": c,
                        "scope": "scene", "importance_score": 0.8, "confidence_score": 0.7,
                        "tags": ["scene", "l2", sf.stem], "source_message_id": "", "_source": "tencentdb_scene"})

        logger.info("TencentDB scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": record.get("memory_id"), "content": record.get("content", ""),
                "type": record.get("memory_type", "FACT").lower(),
                "priority": int(float(record.get("importance_score", 0.5)) * 100),
                "scene_name": record.get("scope", "imported"),
                "metadata_json": "{}"}


@AdapterRegistry.register("holographic")
class HolographicAdapter(BaseAdapter):
    source_name = "holographic"
    target_name = "holographic"

    def describe(self) -> str:
        return "Holographic Memory (SQLite facts + entities)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        db_path = Path(source_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Holographic DB not found: {db_path}")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        records = []
        for r in conn.execute("SELECT fact_id, content, category, tags, trust_score, retrieval_count, helpful_count, created_at FROM facts ORDER BY trust_score DESC LIMIT 5000;"):
            d = dict(r)
            type_map = {"user_pref": "PREFERENCE", "project": "PROJECT", "tool": "EXPERIENCE", "general": "FACT"}
            records.append({"memory_id": f"holo_{d['fact_id']}", "memory_type": type_map.get(d.get("category", "general"), "FACT"),
                "content": str(d.get("content", "")), "scope": d.get("category", "general"),
                "importance_score": float(d.get("trust_score", 0.5)), "confidence_score": float(d.get("trust_score", 0.5)),
                "tags": [t.strip() for t in str(d.get("tags", "")).split(",") if t.strip()], "source_message_id": "", "_source": "holographic"})
        try:
            for r in conn.execute(
                "SELECT e.entity_id, e.name, e.entity_type, e.aliases, GROUP_CONCAT(f.content, ' | ') AS facts "
                "FROM entities e LEFT JOIN fact_entities fe ON fe.entity_id=e.entity_id LEFT JOIN facts f ON f.fact_id=fe.fact_id GROUP BY e.entity_id LIMIT 2000;"
            ):
                d = dict(r)
                content = f"Entity: {d['name']} ({d.get('entity_type', 'unknown')})"
                if d.get("aliases"): content += f" aliases: {d['aliases']}"
                if d.get("facts"): content += f" | {d['facts'][:200]}"
                records.append({"memory_id": f"holo_ent_{d['entity_id']}", "memory_type": "ENT_RELATION", "content": content,
                    "scope": "entity", "importance_score": 0.5, "confidence_score": 0.8,
                    "tags": [d.get('entity_type', 'unknown')], "source_message_id": "", "_source": "holographic_entity"})
        except sqlite3.OperationalError:
            pass
        conn.close()
        logger.info("Holographic scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"fact_id": 0, "content": record.get("content", ""),
                "category": record.get("scope", "general"),
                "tags": record.get("tags_json", "[]"),
                "trust_score": record.get("confidence_score", 0.5)}


@AdapterRegistry.register("hermes")
class HermesBuiltinAdapter(BaseAdapter):
    source_name = "hermes"
    target_name = "hermes"

    def describe(self) -> str:
        return "Hermes Builtin Memory (MEMORY.md / USER.md)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        mem_dir = Path(source_path)
        if not mem_dir.is_dir():
            raise NotADirectoryError(f"Hermes memory dir not found: {mem_dir}")
        records = []
        idx = 0
        for fname in ["MEMORY.md", "USER.md"]:
            fp = mem_dir / fname
            if not fp.exists(): continue
            for entry in fp.read_text(encoding="utf-8").split("§"):
                entry = entry.strip()
                if not entry: continue
                idx += 1
                records.append({"memory_id": f"hermes_{idx}", "memory_type": "FACT", "content": entry,
                    "scope": "memory" if fname == "MEMORY.md" else "user",
                    "importance_score": 0.5, "confidence_score": 0.5, "tags": [],
                    "source_message_id": fname, "_source": "hermes_builtin"})
        logger.info("Hermes scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return record

    async def export(self, records: list[dict[str, Any]], target_path: str) -> int:
        """Hermes 导出为 MEMORY.md / USER.md 格式。"""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mem_lines, user_lines = [], []
        for rec in records:
            content = rec.get("content", "").strip()
            if not content: continue
            if rec.get("scope") == "user":
                user_lines.append(content)
            else:
                mem_lines.append(content)
        sections = {}
        if mem_lines:
            sections["MEMORY.md"] = "\n§\n".join(mem_lines)
        if user_lines:
            sections["USER.md"] = "\n§\n".join(user_lines)
        for fname, text in sections.items():
            (path / fname).write_text(text, encoding="utf-8")
        logger.info("Hermes export: %d files → %s", len(sections), path)
        return len(records)


# ═══════════════════════════════════════════
#  新 增 适 配 器
# ═══════════════════════════════════════════

@AdapterRegistry.register("mem0")
class Mem0Adapter(BaseAdapter):
    source_name = "mem0"
    target_name = "mem0"

    def describe(self) -> str:
        return "Mem0 Memory Layer (JSON — user/session/agent memories)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        path = Path(source_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        memories = data if isinstance(data, list) else data.get("memories", data.get("results", []))
        records = []
        for item in memories:
            content = item.get("content", item.get("text", "")).strip()
            if not content: continue
            records.append({"memory_id": item.get("id", uuid4().hex), "memory_type": "FACT",
                "content": content, "scope": item.get("category", item.get("memory_type", "mem0")),
                "importance_score": float(item.get("importance", item.get("score", 0.5))),
                "confidence_score": float(item.get("confidence", 0.5)),
                "tags": item.get("categories", item.get("tags", [])),
                "source_message_id": item.get("user_id", item.get("session_id", "")), "_source": "mem0"})
        logger.info("Mem0 scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": record.get("memory_id"), "content": record.get("content", ""),
                "category": record.get("scope", "general"),
                "importance": record.get("importance_score", 0.5),
                "tags": json.loads(record.get("tags_json", "[]")),
                "metadata": {"source": "memoryx_migration"}}


@AdapterRegistry.register("hindsight")
class HindsightAdapter(BaseAdapter):
    source_name = "hindsight"
    target_name = "hindsight"

    def describe(self) -> str:
        return "Hindsight Memory (memory bank format)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        path = Path(source_path)
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        banks = data if isinstance(data, list) else data.get("banks", data.get("memories", []))
        records = []
        for bank in banks:
            memories = bank if isinstance(bank, dict) else {"content": str(bank)}
            content = memories.get("content", memories.get("text", "")).strip()
            if not content: continue
            records.append({"memory_id": memories.get("id", uuid4().hex), "memory_type": "EXPERIENCE",
                "content": content, "scope": memories.get("bank", memories.get("scope", "hindsight")),
                "importance_score": float(memories.get("importance", 0.5)),
                "confidence_score": float(memories.get("confidence", 0.5)),
                "tags": memories.get("tags", []),
                "source_message_id": memories.get("session_id", ""), "_source": "hindsight"})
        logger.info("Hindsight scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": record.get("memory_id"), "content": record.get("content", ""),
                "bank": record.get("scope", "imported"),
                "importance": record.get("importance_score", 0.5),
                "tags": json.loads(record.get("tags_json", "[]"))}


@AdapterRegistry.register("letta")
class LettaAdapter(BaseAdapter):
    source_name = "letta"
    target_name = "letta"

    def describe(self) -> str:
        return "Letta / MemGPT Memory (archival + core memory)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        path = Path(source_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        blocks = data if isinstance(data, list) else data.get("core_memory", data.get("archival_memory", [data]))
        records = []
        for block in blocks:
            content = block.get("content", block.get("value", block.get("text", ""))).strip()
            if not content: continue
            records.append({"memory_id": block.get("id", uuid4().hex), "memory_type": "FACT",
                "content": content, "scope": block.get("label", block.get("name", "letta")),
                "importance_score": float(block.get("importance", 0.5)),
                "confidence_score": 0.5, "tags": block.get("tags", []),
                "source_message_id": "", "_source": "letta"})
        logger.info("Letta scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": record.get("memory_id"), "content": record.get("content", ""),
                "name": record.get("scope", "imported"),
                "importance": record.get("importance_score", 0.5)}


@AdapterRegistry.register("zep")
class ZepAdapter(BaseAdapter):
    source_name = "zep"
    target_name = "zep"

    def describe(self) -> str:
        return "Zep Long-term Memory (session summaries + entities)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        path = Path(source_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions = data if isinstance(data, list) else data.get("sessions", data.get("summaries", []))
        records = []
        for ses in sessions:
            content = ses.get("summary", ses.get("content", ses.get("text", ""))).strip()
            if not content: continue
            records.append({"memory_id": ses.get("uuid", ses.get("id", uuid4().hex)), "memory_type": "OBSERVATION",
                "content": content, "scope": "zep",
                "importance_score": float(ses.get("importance", 0.5)),
                "confidence_score": 0.5, "tags": [],
                "source_message_id": ses.get("session_id", ""), "_source": "zep"})
        logger.info("Zep scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"uuid": record.get("memory_id"), "content": record.get("content", ""),
                "summary": record.get("content", "")[:200],
                "importance": record.get("importance_score", 0.5)}


@AdapterRegistry.register("cognee")
class CogneeAdapter(BaseAdapter):
    source_name = "cognee"
    target_name = "cognee"

    def describe(self) -> str:
        return "Cognee Cognitive Memory (graph + knowledge units)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        path = Path(source_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        units = data if isinstance(data, list) else data.get("cognition", data.get("knowledge", []))
        records = []
        for unit in units:
            content = unit.get("text", unit.get("content", unit.get("statement", ""))).strip()
            if not content: continue
            records.append({"memory_id": unit.get("id", uuid4().hex), "memory_type": "OBSERVATION",
                "content": content, "scope": unit.get("layer", unit.get("type", "cognee")),
                "importance_score": float(unit.get("confidence", unit.get("importance", 0.5))),
                "confidence_score": float(unit.get("confidence", 0.5)),
                "tags": unit.get("entities", unit.get("tags", [])),
                "source_message_id": "", "_source": "cognee"})
        logger.info("Cognee scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": record.get("memory_id"), "text": record.get("content", ""),
                "type": record.get("memory_type", "FACT").lower(),
                "confidence": record.get("confidence_score", 0.5)}


@AdapterRegistry.register("gbrain")
class GBrainAdapter(BaseAdapter):
    source_name = "gbrain"
    target_name = "gbrain"

    def describe(self) -> str:
        return "GBrain Memory (Markdown files with Git)"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        mem_dir = Path(source_path)
        if not mem_dir.is_dir():
            raise NotADirectoryError(f"GBrain memory dir not found: {mem_dir}")
        records = []
        for md_file in sorted(mem_dir.rglob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            if not content: continue
            records.append({"memory_id": f"gbrain_{md_file.stem[:40]}", "memory_type": "FACT",
                "content": content, "scope": "gbrain",
                "importance_score": 0.5, "confidence_score": 0.5, "tags": [],
                "source_message_id": md_file.name, "_source": "gbrain"})
        logger.info("GBrain scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return record

    async def export(self, records: list[dict[str, Any]], target_path: str) -> int:
        """GBrain 导出为 Markdown 文件。"""
        out_dir = Path(target_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for rec in records:
            content = rec.get("content", "").strip()
            if not content: continue
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in content[:60])
            (out_dir / f"memoryx_{safe_name}.md").write_text(content, encoding="utf-8")
            count += 1
        logger.info("GBrain export: %d files → %s", count, out_dir)
        return count


@AdapterRegistry.register("json")
class JsonAdapter(BaseAdapter):
    source_name = "json"
    target_name = "json"

    def describe(self) -> str:
        return "Generic JSON / JSONL / CSV"

    async def scan(self, source_path: str) -> list[dict[str, Any]]:
        fpath = Path(source_path)
        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")
        suffix = fpath.suffix.lower()
        records = []
        if suffix in (".json", ".jsonl"):
            raw = fpath.read_text(encoding="utf-8")
            data = [json.loads(line) for line in raw.split("\n") if line.strip()] if suffix == ".jsonl" else json.loads(raw)
            if isinstance(data, dict): data = data.get("memories", data.get("records", [data]))
            for item in data:
                records.append(self._map_record(item))
        elif suffix == ".csv":
            with open(fpath, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    records.append(self._map_record(dict(row)))
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
        logger.info("JSON scan: %d records", len(records))
        return records

    def _to_target(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"memory_id": record.get("memory_id"), "content": record.get("content", ""),
                "type": record.get("memory_type", "FACT"),
                "scope": record.get("scope", "imported"),
                "importance": record.get("importance_score", 0.5),
                "tags": json.loads(record.get("tags_json", "[]"))}

    @staticmethod
    def _map_record(item: dict[str, Any]) -> dict[str, Any]:
        content = (item.get("content") or item.get("text") or item.get("message") or "").strip()
        return {"memory_id": item.get("memory_id", item.get("id", uuid4().hex)),
            "memory_type": str(item.get("memory_type", item.get("type", "FACT"))).upper(),
            "content": content, "scope": item.get("scope", item.get("category", item.get("scene_name", "imported"))),
            "importance_score": float(item.get("importance_score", item.get("trust_score", item.get("priority", 0.5)))),
            "confidence_score": float(item.get("confidence_score", item.get("trust_score", 0.5))),
            "tags": item.get("tags", []),
            "source_message_id": item.get("source_message_id", item.get("session_key", "")), "_source": "generic_json"}
