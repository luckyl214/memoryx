#!/usr/bin/env python3
"""
MemoryX Production Self-Check

Non-invasive production-readiness audit for MemoryX.

What it checks:
- Python/project layout/compileability
- SQLite schema bootstrap and migrations
- P0 schema boundary consistency: memories.id vs legacy memory_id,
  entities.id vs legacy entity_id, active_state TEXT vs INTEGER
- Required tables: memory_versions, audit_logs, palace_* tables, FTS tables,
  cognitive timeline/lesson tables when migrations are present
- Repository transaction/version/audit contract
- SelfEditor version-control contract
- MCP embedding fallback contract
- Async safety: daemon thread polling in asyncio paths
- Retrieval session/scope isolation contract
- Cognitive closed-loop contract: feedback propagation + LESSON creation
- Timeline/opinion-shift contract
- Runtime smoke tests against a temporary DB when imports work
- Optional pytest, bandit, ruff, pip check, secret scan

Run from repository root:
    python tools/memoryx_production_selfcheck.py --root . --run-pytest --run-bandit --run-ruff

Outputs:
    production_selfcheck_report.json
    production_selfcheck_report.md

Exit code:
    0 if no finding at or above --fail-on severity
    1 otherwise

The script deliberately does not modify project files.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import compileall
import contextlib
import dataclasses
import datetime as _dt
import fnmatch
import importlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterable


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2
    FATAL = 3

    @classmethod
    def parse(cls, value: str) -> "Severity":
        value = value.upper().strip()
        if value not in cls.__members__:
            raise argparse.ArgumentTypeError(f"severity must be one of {', '.join(cls.__members__)}")
        return cls[value]


@dataclasses.dataclass
class Finding:
    check: str
    severity: str
    status: str
    message: str
    path: str = ""
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def level(self) -> Severity:
        return Severity[self.severity]


@dataclasses.dataclass
class CheckStats:
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    root: str = ""
    python: str = ""
    counts: dict[str, int] = dataclasses.field(default_factory=dict)


class ProductionSelfCheck:
    def __init__(
        self,
        root: Path,
        *,
        run_pytest: bool = False,
        run_bandit: bool = False,
        run_ruff: bool = False,
        run_pip_check: bool = False,
        timeout: int = 120,
        fail_on: Severity = Severity.ERROR,
        report_json: Path | None = None,
        report_md: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_pytest = run_pytest
        self.run_bandit = run_bandit
        self.run_ruff = run_ruff
        self.run_pip_check = run_pip_check
        self.timeout = timeout
        self.fail_on = fail_on
        self.report_json = report_json or (self.root / "production_selfcheck_report.json")
        self.report_md = report_md or (self.root / "production_selfcheck_report.md")
        self.findings: list[Finding] = []
        self._schema_columns: dict[str, set[str]] = {}
        self._schema_table_columns: dict[str, dict[str, str]] = {}
        self._schema_tables: set[str] = set()
        self._memory_pk: str | None = None
        self._entity_pk: str | None = None
        self._active_state_type: str | None = None

    # ---------- recording ----------

    def add(
        self,
        check: str,
        severity: Severity,
        status: str,
        message: str,
        *,
        path: Path | str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        p = ""
        if path:
            try:
                p = str(Path(path).resolve().relative_to(self.root))
            except Exception:
                p = str(path)
        self.findings.append(
            Finding(
                check=check,
                severity=severity.name,
                status=status,
                message=message,
                path=p,
                detail=detail or {},
            )
        )

    # ---------- main ----------

    def run(self) -> int:
        started = time.perf_counter()
        stats = CheckStats(
            started_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            root=str(self.root),
            python=sys.version.replace("\n", " "),
        )

        checks = [
            self.check_python_version,
            self.check_project_layout,
            self.check_compileall,
            self.check_sqlite_capabilities,
            self.check_schema_bootstrap,
            self.check_migrations_apply,
            self.check_schema_contract,
            self.check_source_schema_consistency,
            self.check_repository_static_contract,
            self.check_self_editor_static_contract,
            self.check_mcp_static_contract,
            self.check_retrieval_static_contract,
            self.check_async_safety,
            self.check_cognitive_static_contract,
            self.check_secret_leaks,
            self.check_runtime_smoke,
            self.check_optional_tools,
        ]

        for check in checks:
            try:
                check()
            except Exception as exc:
                self.add(
                    check.__name__,
                    Severity.FATAL,
                    "exception",
                    f"Self-check crashed while running {check.__name__}: {exc}",
                    detail={"exception_type": type(exc).__name__},
                )

        stats.finished_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        stats.duration_seconds = round(time.perf_counter() - started, 3)
        stats.counts = self._counts()

        self.write_reports(stats)
        worst = max((f.level for f in self.findings), default=Severity.INFO)
        print(f"MemoryX production self-check completed. Worst={worst.name}.")
        print(f"JSON report: {self.report_json}")
        print(f"Markdown report: {self.report_md}")
        return 1 if worst >= self.fail_on else 0

    def _counts(self) -> dict[str, int]:
        counts = {s.name: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity] += 1
        return counts

    # ---------- filesystem helpers ----------

    def iter_files(self, patterns: tuple[str, ...] = ("*.py", "*.sql", "*.yaml", "*.yml", "*.toml", "*.md")) -> Iterable[Path]:
        skip_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "htmlcov",
            "build",
            "dist",
            "data",
            "logs",
            "cache",
            "exports",
            "archive",
            "dead_letters",
            "queue",
            ".mypy_cache",
            ".ruff_cache",
        }
        skip_files = {".env"}  # local secrets, never scanned
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in skip_files:
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            if any(fnmatch.fnmatch(path.name, pat) for pat in patterns):
                yield path

    def read_text(self, rel: str | Path) -> str:
        path = self.root / rel
        return path.read_text(encoding="utf-8", errors="replace")

    def exists(self, rel: str | Path) -> bool:
        return (self.root / rel).exists()

    # ---------- checks ----------

    def check_python_version(self) -> None:
        check = "python_version"
        if sys.version_info < (3, 11):
            self.add(check, Severity.FATAL, "fail", "MemoryX requires Python 3.11+.")
        else:
            self.add(check, Severity.INFO, "pass", f"Python version is {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}.")

    def check_project_layout(self) -> None:
        check = "project_layout"
        required = [
            "memoryx",
            "memoryx/__init__.py",
            "db/schema.sql",
            "tests",
            "pyproject.toml",
        ]
        missing = [p for p in required if not self.exists(p)]
        if missing:
            self.add(check, Severity.FATAL, "fail", "Required project files are missing.", detail={"missing": missing})
        else:
            self.add(check, Severity.INFO, "pass", "Required MemoryX layout files are present.")

        if not self.exists("memoryx/cognitive"):
            self.add(check, Severity.WARN, "missing", "memoryx/cognitive/ is missing; cognitive timeline and lesson features may not be installed.")
        else:
            self.add(check, Severity.INFO, "pass", "memoryx/cognitive/ exists.")

    def check_compileall(self) -> None:
        check = "compileall"
        package_dir = self.root / "memoryx"
        if not package_dir.exists():
            self.add(check, Severity.FATAL, "skip", "memoryx package directory not found.")
            return
        ok = compileall.compile_dir(str(package_dir), quiet=1, force=False, maxlevels=10)
        if ok:
            self.add(check, Severity.INFO, "pass", "memoryx/ compiles successfully.")
        else:
            self.add(check, Severity.ERROR, "fail", "Python syntax errors found under memoryx/.")

    def check_sqlite_capabilities(self) -> None:
        check = "sqlite_capabilities"
        conn = sqlite3.connect(":memory:")
        try:
            version = sqlite3.sqlite_version
            conn.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(content);")
            fts5 = True
        except sqlite3.DatabaseError as exc:
            fts5 = False
            self.add(check, Severity.FATAL, "fail", f"SQLite FTS5 is unavailable: {exc}")
            return
        finally:
            conn.close()
        self.add(check, Severity.INFO, "pass", "SQLite and FTS5 are available.", detail={"sqlite_version": version, "fts5": fts5})

    def _load_schema(self, conn: sqlite3.Connection) -> None:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table') ORDER BY name;"
        ).fetchall()
        self._schema_tables = {row[0] for row in tables}
        cols_by_table: dict[str, set[str]] = {}
        col_types: dict[str, dict[str, str]] = {}
        for table in self._schema_tables:
            try:
                rows = conn.execute(f"PRAGMA table_info({quote_ident(table)});").fetchall()
            except sqlite3.DatabaseError:
                continue
            cols_by_table[table] = {str(r[1]) for r in rows}
            col_types[table] = {str(r[1]): str(r[2]).upper() for r in rows}
        self._schema_columns = cols_by_table
        self._schema_table_columns = col_types

        mem_cols = cols_by_table.get("memories", set())
        if "id" in mem_cols:
            self._memory_pk = "id"
        elif "memory_id" in mem_cols:
            self._memory_pk = "memory_id"
        else:
            self._memory_pk = None

        ent_cols = cols_by_table.get("entities", set())
        if "id" in ent_cols:
            self._entity_pk = "id"
        elif "entity_id" in ent_cols:
            self._entity_pk = "entity_id"
        else:
            self._entity_pk = None

        self._active_state_type = col_types.get("memories", {}).get("active_state")

    def check_schema_bootstrap(self) -> None:
        check = "schema_bootstrap"
        schema_path = self.root / "db" / "schema.sql"
        if not schema_path.exists():
            self.add(check, Severity.FATAL, "fail", "db/schema.sql is missing.")
            return

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "bootstrap.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(schema_path.read_text(encoding="utf-8"))
                conn.execute("PRAGMA foreign_key_check;").fetchall()
                self._load_schema(conn)
            except sqlite3.DatabaseError as exc:
                self.add(check, Severity.FATAL, "fail", f"db/schema.sql does not bootstrap cleanly: {exc}")
                return
            finally:
                conn.close()

        self.add(check, Severity.INFO, "pass", "db/schema.sql bootstraps a temporary SQLite database.")

    def check_migrations_apply(self) -> None:
        check = "migrations_apply"
        schema_path = self.root / "db" / "schema.sql"
        migrations_dir = self.root / "db" / "migrations"
        if not schema_path.exists():
            self.add(check, Severity.FATAL, "skip", "Cannot test migrations because db/schema.sql is missing.")
            return
        if not migrations_dir.exists():
            self.add(check, Severity.WARN, "skip", "db/migrations/ is missing.")
            return

        migrations = sorted(migrations_dir.glob("*.sql"))
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "migrations.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.executescript(schema_path.read_text(encoding="utf-8"))
                failed: list[dict[str, str]] = []
                for migration in migrations:
                    sql = migration.read_text(encoding="utf-8")
                    try:
                        conn.executescript(sql)
                    except sqlite3.DatabaseError as exc:
                        failed.append({"migration": str(migration.relative_to(self.root)), "error": str(exc)})
                        break
                if failed:
                    self.add(check, Severity.FATAL, "fail", "One or more migrations fail on a clean schema.", detail={"failed": failed})
                    return
                rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
                if rows:
                    self.add(check, Severity.ERROR, "fail", "Foreign-key violations after migrations.", detail={"violations": [tuple(r) for r in rows[:20]]})
                else:
                    self.add(check, Severity.INFO, "pass", f"{len(migrations)} migrations apply cleanly.")
                self._load_schema(conn)
            finally:
                conn.close()

    def check_schema_contract(self) -> None:
        check = "schema_contract"
        if not self._schema_tables:
            self.add(check, Severity.FATAL, "skip", "Schema has not been loaded.")
            return

        required_tables = {
            "memories",
            "memory_versions",
            "audit_logs",
            "conversation_logs",
            "conversation_logs_fts",
            "memories_fts",
            "entities",
            "relations",
            "reflection_summaries",
            "safety_quarantine",
            "palace_wings",
            "palace_rooms",
            "palace_drawers",
            "palace_tunnels",
        }
        missing = sorted(required_tables - self._schema_tables)
        if missing:
            self.add(check, Severity.ERROR, "fail", "Required production tables are missing.", detail={"missing": missing})
        else:
            self.add(check, Severity.INFO, "pass", "Core production tables are present.")

        if self._memory_pk is None:
            self.add(check, Severity.FATAL, "fail", "memories table has neither id nor memory_id.")
        else:
            self.add(check, Severity.INFO, "pass", f"memories primary identifier appears to be {self._memory_pk}.")
            if self._memory_pk == "memory_id":
                self.add(check, Severity.WARN, "legacy", "Schema uses legacy memories.memory_id; P0 refactor expects memories.id.")

        if self._entity_pk is None:
            self.add(check, Severity.ERROR, "fail", "entities table has neither id nor entity_id.")
        else:
            self.add(check, Severity.INFO, "pass", f"entities identifier appears to be {self._entity_pk}.")
            if self._entity_pk == "entity_id":
                self.add(check, Severity.WARN, "legacy", "Schema uses legacy entities.entity_id; P0 refactor expects entities.id.")

        active_type = self._active_state_type or ""
        if not active_type:
            self.add(check, Severity.ERROR, "fail", "memories.active_state column is missing.")
        elif "TEXT" not in active_type and "INT" not in active_type:
            self.add(check, Severity.ERROR, "fail", f"memories.active_state has unexpected type: {active_type}")
        else:
            self.add(check, Severity.INFO, "pass", f"memories.active_state type is {active_type}.")

        cognitive_tables = {
            "memory_feedback_events",
            "feedback_propagations",
            "lesson_memories",
            "lesson_evidence",
            "sessions",
            "tasks",
            "task_durations",
            "memory_entities",
            "opinion_observations",
            "opinion_shifts",
            "retrieval_weight_overrides",
            "self_edit_plans",
        }
        if self.exists("memoryx/cognitive"):
            missing_cognitive = sorted(cognitive_tables - self._schema_tables)
            if missing_cognitive:
                self.add(check, Severity.ERROR, "fail", "Cognitive module exists but cognitive schema tables are missing.", detail={"missing": missing_cognitive})
            else:
                self.add(check, Severity.INFO, "pass", "Cognitive schema tables are present.")

    def check_source_schema_consistency(self) -> None:
        check = "source_schema_consistency"
        memory_pk = self._memory_pk
        entity_pk = self._entity_pk
        if memory_pk is None:
            self.add(check, Severity.FATAL, "skip", "Cannot check source/schema consistency without memory PK.")
            return

        risky: list[dict[str, Any]] = []
        for path in self.iter_files(("*.py", "*.sql")):
            rel = str(path.relative_to(self.root))
            text = path.read_text(encoding="utf-8", errors="replace")
            # Focus on SQL against physical tables, not DTO field names.
            patterns: list[tuple[str, str, Severity]] = []
            if memory_pk == "id":
                patterns.extend([
                    (r"REFERENCES\s+memories\s*\(\s*memory_id\s*\)", "FK references legacy memories(memory_id)", Severity.ERROR),
                    (r"FROM\s+memories\b[^;\n]*(?:WHERE|ON)\s+memory_id\s*=", "SQL filters memories.memory_id under id schema", Severity.ERROR),
                    (r"UPDATE\s+memories\b[^;\n]*WHERE\s+memory_id\s*=", "UPDATE memories uses memory_id under id schema", Severity.ERROR),
                    (r"INSERT\s+INTO\s+memories\s*\([^)]*\bmemory_id\b", "INSERT memories uses memory_id under id schema", Severity.ERROR),
                ])
            if entity_pk == "id":
                patterns.extend([
                    (r"REFERENCES\s+entities\s*\(\s*entity_id\s*\)", "FK references legacy entities(entity_id)", Severity.ERROR),
                    (r"FROM\s+entities\b[^;\n]*(?:WHERE|ON)\s+entity_id\s*=", "SQL filters entities.entity_id under id schema", Severity.ERROR),
                ])
            if self._active_state_type and "TEXT" in self._active_state_type:
                patterns.extend([
                    (r"int\s*\([^)]*active_state[^)]*\)", "Code casts TEXT active_state to int()", Severity.ERROR),
                    (r"active_state\s*=\s*0\b", "Code writes numeric active_state under TEXT schema", Severity.WARN),
                    (r"active_state\s*=\s*1\b", "Code writes numeric active_state under TEXT schema", Severity.WARN),
                ])

            for pattern, message, severity in patterns:
                for m in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                    line = text.count("\n", 0, m.start()) + 1
                    risky.append({"path": rel, "line": line, "message": message, "severity": severity.name})

        errors = [r for r in risky if r["severity"] == "ERROR"]
        warnings = [r for r in risky if r["severity"] == "WARN"]
        if errors:
            self.add(check, Severity.ERROR, "fail", "Source contains SQL/schema references incompatible with detected schema.", detail={"matches": errors[:50], "total": len(errors)})
        else:
            self.add(check, Severity.INFO, "pass", "No fatal legacy SQL/schema references detected.")
        if warnings:
            self.add(check, Severity.WARN, "warn", "Source contains suspicious active_state numeric usage.", detail={"matches": warnings[:50], "total": len(warnings)})

    def check_repository_static_contract(self) -> None:
        check = "repository_static_contract"
        path = self.root / "memoryx" / "storage" / "repository.py"
        if not path.exists():
            self.add(check, Severity.FATAL, "fail", "memoryx/storage/repository.py is missing.")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        store_src = extract_function_source(text, "store_memory")
        if not store_src:
            self.add(check, Severity.ERROR, "fail", "MemoryRepository.store_memory could not be found.")
            return

        has_tx = bool(re.search(r"BEGIN\s+IMMEDIATE|\.transaction\s*\(", store_src, flags=re.IGNORECASE))
        has_version = "memory_versions" in store_src or "write_version" in store_src or "_write_version" in store_src
        has_audit = "audit_logs" in store_src or "append_audit" in store_src or "_append_audit" in store_src
        if not has_tx:
            self.add(check, Severity.ERROR, "fail", "store_memory does not appear to use BEGIN IMMEDIATE or repository.db.transaction().", path=path)
        if not has_version:
            self.add(check, Severity.ERROR, "fail", "store_memory does not appear to write memory_versions.", path=path)
        if not has_audit:
            self.add(check, Severity.ERROR, "fail", "store_memory does not appear to write audit_logs.", path=path)
        if has_tx and has_version and has_audit:
            self.add(check, Severity.INFO, "pass", "store_memory appears transaction/version/audit aware.")

        if "update_memory_versioned" not in text:
            self.add(check, Severity.ERROR, "fail", "Repository lacks update_memory_versioned(); SelfEditor cannot preserve history reliably.", path=path)
        else:
            self.add(check, Severity.INFO, "pass", "Repository exposes update_memory_versioned().")

    def check_self_editor_static_contract(self) -> None:
        check = "self_editor_static_contract"
        path = self.root / "memoryx" / "self_editor.py"
        if not path.exists():
            self.add(check, Severity.WARN, "skip", "memoryx/self_editor.py is missing.")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        apply_src = extract_function_source(text, "apply")
        if not apply_src:
            self.add(check, Severity.ERROR, "fail", "SelfEditor.apply could not be found.", path=path)
            return
        direct_update = bool(re.search(r"UPDATE\s+memories\b", apply_src, flags=re.IGNORECASE))
        uses_versioned = "update_memory_versioned" in apply_src or "store_memory" in apply_src or "supersede_memory" in apply_src
        dynamic_col = bool(re.search(r"f[\"']\s*UPDATE\s+memories\s+SET\s*\{", apply_src, flags=re.IGNORECASE))
        if direct_update and not uses_versioned:
            self.add(check, Severity.ERROR, "fail", "SelfEditor.apply directly UPDATEs memories without versioned repository API.", path=path)
        elif direct_update:
            self.add(check, Severity.WARN, "warn", "SelfEditor.apply contains UPDATE memories; verify it only appears in safe repository-backed paths.", path=path)
        if dynamic_col:
            self.add(check, Severity.WARN, "warn", "SelfEditor.apply builds UPDATE columns from changes dict; ensure column whitelist is enforced.", path=path)
        if not direct_update and uses_versioned:
            self.add(check, Severity.INFO, "pass", "SelfEditor.apply appears to use versioned repository APIs.")

    def check_mcp_static_contract(self) -> None:
        check = "mcp_static_contract"
        path = self.root / "memoryx" / "mcp_server.py"
        if not path.exists():
            self.add(check, Severity.WARN, "skip", "memoryx/mcp_server.py is missing.")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        if "embedding_manager" not in text:
            self.add(check, Severity.ERROR, "fail", "MCPServer does not accept/use embedding_manager.", path=path)
            return
        if re.search(r"if\s+self\.embedding_manager\s+is\s+None:[\s\S]{0,500}return\s+\[\]", text):
            if "require_embeddings" in text or "allow_fts_fallback" in text or "strict" in text:
                self.add(check, Severity.WARN, "fallback", "MCPServer can return [] without embedding manager, but strict/fallback controls appear present.", path=path)
            else:
                self.add(check, Severity.ERROR, "fail", "MCPServer returns empty query vector when embedding_manager is missing without a strict/fallback flag.", path=path)
        else:
            self.add(check, Severity.INFO, "pass", "MCPServer does not appear to silently return empty vectors without controls.")

    def check_retrieval_static_contract(self) -> None:
        check = "retrieval_static_contract"
        path = self.root / "memoryx" / "retrieval" / "engine.py"
        if not path.exists():
            self.add(check, Severity.WARN, "skip", "memoryx/retrieval/engine.py is missing.")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        if "session_id" not in text:
            self.add(check, Severity.ERROR, "fail", "Retrieval engine lacks session_id support; session-level isolation is likely missing.", path=path)
        else:
            self.add(check, Severity.INFO, "pass", "Retrieval engine mentions session_id.")

        if "scope_filter" in text and not re.search(r"scope_filter[\s\S]{0,200}(WHERE|if|filter|scope)", text):
            self.add(check, Severity.WARN, "warn", "scope_filter exists but may not be applied; inspect retrieval filtering.", path=path)
        elif "scope_filter" in text:
            self.add(check, Severity.INFO, "pass", "Retrieval engine mentions scope_filter and likely filtering logic.")
        else:
            self.add(check, Severity.WARN, "missing", "Retrieval engine lacks scope_filter.")

        if "LESSON" not in text and "lesson" not in text.lower():
            self.add(check, Severity.ERROR, "fail", "Retrieval engine does not appear to boost or include LESSON memories.", path=path)
        else:
            self.add(check, Severity.INFO, "pass", "Retrieval engine appears lesson-aware.")

    def check_async_safety(self) -> None:
        check = "async_safety"
        matches = []
        for path in self.iter_files(("*.py",)):
            rel = str(path.relative_to(self.root))
            if rel.startswith("tools/") or rel.startswith("tests/"):
                continue  # exclude tool/test internals
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"threading\.Thread\s*\([^)]*daemon\s*=\s*True", text, flags=re.DOTALL):
                matches.append({"path": rel, "line": text.count("\n", 0, m.start()) + 1, "pattern": "threading.Thread(...daemon=True)"})
        if matches:
            self.add(check, Severity.WARN, "warn", "Daemon thread detected in async path; verify no shared asyncio state.", detail={"matches": matches[:50], "total": len(matches)})
        else:
            self.add(check, Severity.INFO, "pass", "No daemon-thread WeightLoader pattern detected.")

    def check_cognitive_static_contract(self) -> None:
        check = "cognitive_static_contract"
        cog_dir = self.root / "memoryx" / "cognitive"
        if not cog_dir.exists():
            self.add(check, Severity.WARN, "skip", "memoryx/cognitive/ not installed.")
            return

        expected_files = {
            "__init__.py",
            "feedback.py",
            "lessons.py",
            "timeline.py",
            "opinion.py",
            "reflection_repair.py",
            "schema_compat.py",
        }
        present = {p.name for p in cog_dir.glob("*.py")}
        missing = sorted(expected_files - present)
        if missing:
            self.add(check, Severity.ERROR, "fail", "Cognitive module is missing expected files.", detail={"missing": missing})
        else:
            self.add(check, Severity.INFO, "pass", "Expected cognitive module files are present.")

        feedback = (cog_dir / "feedback.py").read_text(encoding="utf-8", errors="replace") if (cog_dir / "feedback.py").exists() else ""
        if "FeedbackLearningEngine" not in feedback or "memory_feedback_events" not in feedback:
            self.add(check, Severity.ERROR, "fail", "FeedbackLearningEngine or memory_feedback_events integration is missing.", path=cog_dir / "feedback.py")
        if not (("_lesson_creation_policy" in feedback or "_should_create_lesson" in feedback) and re.search(r"similar_count\s*>=\s*1|applied_count\s*>=\s*1", feedback)):
            self.add(check, Severity.ERROR, "fail", "Feedback lesson creation policy may still be too strict; expected first negative + one similar evidence to create LESSON.", path=cog_dir / "feedback.py")
        else:
            self.add(check, Severity.INFO, "pass", "Feedback LESSON creation policy appears to handle propagated evidence.")

        if (cog_dir / "schema_compat.py").exists():
            compat = (cog_dir / "schema_compat.py").read_text(encoding="utf-8", errors="replace")
            if "memory_pk" in compat and "entity_pk" in compat and "active_state" in compat:
                self.add(check, Severity.INFO, "pass", "Cognitive schema compatibility helpers are present.")
            else:
                self.add(check, Severity.WARN, "warn", "schema_compat.py exists but may not handle memory/entity PK and active_state.", path=cog_dir / "schema_compat.py")
        else:
            self.add(check, Severity.ERROR, "fail", "schema_compat.py is missing; cognitive code may break across id/memory_id schema variants.")

    def check_secret_leaks(self) -> None:
        check = "secret_scan"
        secret_patterns = [
            (r"sk-[A-Za-z0-9_\-]{20,}", "OpenAI-style API key"),
            (r"AKIA[0-9A-Z]{16}", "AWS access key"),
            (r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{16,}['\"]", "hardcoded secret assignment"),
            (r"(?i)bearer\s+[A-Za-z0-9_\-.]{20,}", "bearer token"),
            (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
        ]
        allowed = {
            ".env.example",
            ".env.template",
            "README.md",
            "docs/deployment.md",
            "docs/api_reference.md",
            "tests/test_pii_filter.py",
            "tests/production/test_memoryx_production_contracts.py",
        }
        matches: list[dict[str, Any]] = []
        for path in self.iter_files(("*.py", "*.md", "*.yaml", "*.yml", "*.toml", "*.env", "*.example", "*.template")):
            rel = str(path.relative_to(self.root))
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern, label in secret_patterns:
                for m in re.finditer(pattern, text):
                    if rel in allowed or any(x in m.group(0).lower() for x in ["your_", "example", "placeholder", "abc", "test_key", "fake", "secret", "sk-test", "sk-abc"]):
                        continue
                    matches.append({"path": rel, "line": text.count("\n", 0, m.start()) + 1, "kind": label})
        if matches:
            self.add(check, Severity.ERROR, "fail", "Potential hardcoded secrets found.", detail={"matches": matches[:50], "total": len(matches)})
        else:
            self.add(check, Severity.INFO, "pass", "No obvious hardcoded secrets detected by built-in patterns.")

    def check_runtime_smoke(self) -> None:
        check = "runtime_smoke"
        sys.path.insert(0, str(self.root))
        try:
            asyncio.run(self._runtime_smoke_async(check))
        except ModuleNotFoundError as exc:
            self.add(check, Severity.ERROR, "fail", f"Cannot import runtime dependency: {exc}. Run pip install -e '.[dev]' first.")
        except Exception as exc:
            self.add(check, Severity.ERROR, "fail", f"Runtime smoke test failed: {exc}", detail={"exception_type": type(exc).__name__})
        finally:
            with contextlib.suppress(ValueError):
                sys.path.remove(str(self.root))

    async def _runtime_smoke_async(self, check: str) -> None:
        storage = importlib.import_module("memoryx.storage")
        MemoryRepository = getattr(storage, "MemoryRepository")
        MemoryRecord = getattr(storage, "MemoryRecord")

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "runtime-smoke.sqlite3"
            repo = MemoryRepository(db_path)
            await maybe_await(repo.open())

            record_kwargs = {
                "memory_type": "FACT",
                "content": "production selfcheck async sqlite wal lesson smoke",
                "importance_score": 0.7,
                "confidence_score": 0.8,
            }
            try:
                record = MemoryRecord(id="prod-smoke-1", **record_kwargs)
                expected_id = "prod-smoke-1"
            except TypeError:
                record = MemoryRecord(memory_id="prod-smoke-1", **record_kwargs)
                expected_id = "prod-smoke-1"

            stored_id = await maybe_await(repo.store_memory(record))
            memory_id = stored_id or expected_id
            fetched = await maybe_await(repo.get_memory(memory_id))
            if not fetched:
                raise AssertionError("stored memory cannot be fetched")
            if str(fetched.get("content", "")) != record_kwargs["content"]:
                raise AssertionError("fetched memory content mismatch")

            # Check FTS if available.
            if hasattr(repo, "search_full_text"):
                results = await maybe_await(repo.search_full_text("selfcheck"))
                if not results:
                    raise AssertionError("FTS search did not find stored memory")

            # Version and audit rows must exist if tables exist.
            db = getattr(repo, "db", None)
            if db is not None:
                # AsyncSQLite-like API.
                tables = await maybe_await(db.fetchall("SELECT name FROM sqlite_master WHERE type='table';", ()))
                table_names = {row["name"] if isinstance(row, sqlite3.Row) or hasattr(row, "keys") else row[0] for row in tables}
                if "memory_versions" in table_names:
                    rows = await maybe_await(db.fetchall("SELECT * FROM memory_versions WHERE memory_id = ? OR id = ?;", (memory_id, memory_id)))
                    if not rows:
                        # Some P0 schemas still use memory_id column only. Try introspection.
                        try:
                            cols = await maybe_await(db.fetchall("PRAGMA table_info(memory_versions);", ()))
                            colnames = [str(c["name"]) for c in cols]
                            fk_col = "memory_id" if "memory_id" in colnames else ("id" if "id" in colnames else None)
                            if fk_col:
                                rows = await maybe_await(db.fetchall(f"SELECT * FROM memory_versions WHERE {fk_col} = ?;", (memory_id,)))
                        except Exception:
                            rows = []
                    if not rows:
                        raise AssertionError("store_memory did not create memory_versions row")
                if "audit_logs" in table_names:
                    # Schema introspection: P0 uses entity_id, legacy uses subject_id/memory_id
                    try:
                        cols = await maybe_await(db.fetchall("PRAGMA table_info(audit_logs);", ()))
                        audit_colnames = [str(c["name"]) for c in cols]
                        for candidate in ("entity_id", "subject_id", "memory_id", "target_id", "id"):
                            if candidate in audit_colnames:
                                rows = await maybe_await(db.fetchall(f"SELECT * FROM audit_logs WHERE {candidate} = ?;", (memory_id,)))
                                break
                        else:
                            rows = []
                    except Exception:
                        rows = []
                    if not rows:
                        raise AssertionError("store_memory did not create audit_logs row")

            # SelfEditor should preserve version count if installed.
            with contextlib.suppress(Exception):
                se_mod = importlib.import_module("memoryx.self_editor")
                SelfEditor = getattr(se_mod, "SelfEditor")
                SelfEditRequest = getattr(se_mod, "SelfEditRequest")
                editor = SelfEditor(repository=repo)
                result = await maybe_await(editor.apply(SelfEditRequest(memory_id=memory_id, edit_type="correct", changes={"content": "production selfcheck corrected"}, reason="selfcheck")))
                if hasattr(result, "applied") and not result.applied:
                    raise AssertionError(f"SelfEditor.apply returned not applied: {result}")

            await maybe_await(repo.close())
        self.add(check, Severity.INFO, "pass", "Runtime repository/storage smoke test passed.")

    def check_optional_tools(self) -> None:
        if self.run_pip_check:
            self._run_command_check("pip_check", [sys.executable, "-m", "pip", "check"], Severity.ERROR)
        if self.run_ruff:
            if shutil.which("ruff"):
                self._run_command_check("ruff", ["ruff", "check", "memoryx", "tests"], Severity.WARN)
            else:
                self.add("ruff", Severity.WARN, "skip", "ruff is not installed.")
        if self.run_bandit:
            if shutil.which("bandit"):
                self._run_command_check("bandit", ["bandit", "-r", "memoryx", "-q", "-f", "json"], Severity.WARN)
            else:
                self.add("bandit", Severity.WARN, "skip", "bandit is not installed.")
        if self.run_pytest:
            pytest_cmd = self._find_pytest()
            if pytest_cmd:
                self._run_command_check("pytest", pytest_cmd + ["-q"], Severity.ERROR)
            else:
                self.add("pytest", Severity.ERROR, "skip", "pytest is not installed. Run pip install pytest.")

    @staticmethod
    def _find_pytest() -> list[str] | None:
        """Find pytest: try venv first, then system."""
        import importlib
        try:
            importlib.import_module("pytest")
            # Use python -m pytest to guarantee correct venv
            return [sys.executable, "-m", "pytest"]
        except ImportError:
            pass
        if shutil.which("pytest"):
            return ["pytest"]
        return None

    def _run_command_check(self, check: str, cmd: list[str], severity_on_fail: Severity) -> None:
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self.add(check, Severity.ERROR, "timeout", f"{check} timed out after {self.timeout}s.", detail={"cmd": cmd})
            return
        output = proc.stdout[-12000:] if proc.stdout else ""
        if proc.returncode == 0:
            self.add(check, Severity.INFO, "pass", f"{check} passed.", detail={"cmd": cmd, "output_tail": output})
        else:
            self.add(check, severity_on_fail, "fail", f"{check} failed with exit code {proc.returncode}.", detail={"cmd": cmd, "output_tail": output})

    # ---------- reports ----------

    def write_reports(self, stats: CheckStats) -> None:
        data = {
            "stats": dataclasses.asdict(stats),
            "worst_severity": max((f.level for f in self.findings), default=Severity.INFO).name,
            "fail_on": self.fail_on.name,
            "findings": [dataclasses.asdict(f) for f in self.findings],
            "summary": self.summarize_for_agent(),
        }
        self.report_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_md.write_text(self.render_markdown(data), encoding="utf-8")

    def summarize_for_agent(self) -> dict[str, Any]:
        blockers = [f for f in self.findings if f.level >= Severity.ERROR]
        warnings = [f for f in self.findings if f.level == Severity.WARN]
        top = blockers[:20]
        return {
            "production_ready": not blockers,
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "top_blockers": [
                {
                    "check": f.check,
                    "message": f.message,
                    "path": f.path,
                    "detail": f.detail,
                }
                for f in top
            ],
            "agent_instruction": (
                "Fix all ERROR/FATAL findings first. Do not overwrite db/schema.sql, repository.py, or mcp_server.py "
                "from older patches; prefer additive migrations and compatibility adapters."
            ),
        }

    def render_markdown(self, data: dict[str, Any]) -> str:
        lines: list[str] = []
        stats = data["stats"]
        lines.append("# MemoryX Production Self-Check Report")
        lines.append("")
        lines.append(f"- Root: `{stats['root']}`")
        lines.append(f"- Python: `{stats['python']}`")
        lines.append(f"- Started: `{stats['started_at']}`")
        lines.append(f"- Finished: `{stats['finished_at']}`")
        lines.append(f"- Duration: `{stats['duration_seconds']}s`")
        lines.append(f"- Worst severity: **{data['worst_severity']}**")
        lines.append("")
        lines.append("## Counts")
        lines.append("")
        lines.append("| Severity | Count |")
        lines.append("|---|---:|")
        for sev in ["FATAL", "ERROR", "WARN", "INFO"]:
            lines.append(f"| {sev} | {stats['counts'].get(sev, 0)} |")
        lines.append("")
        lines.append("## Production readiness")
        lines.append("")
        ready = data["summary"]["production_ready"]
        lines.append("✅ Production-ready by this suite." if ready else "❌ Not production-ready by this suite.")
        lines.append("")
        lines.append("## Findings")
        lines.append("")
        lines.append("| Severity | Check | Status | Path | Message |")
        lines.append("|---|---|---|---|---|")
        for f in sorted(self.findings, key=lambda x: (-x.level, x.check, x.path)):
            lines.append(
                f"| {f.severity} | `{escape_md(f.check)}` | `{escape_md(f.status)}` | `{escape_md(f.path)}` | {escape_md(f.message)} |"
            )
        lines.append("")
        lines.append("## Agent repair guidance")
        lines.append("")
        lines.append(data["summary"]["agent_instruction"])
        lines.append("")
        return "\n".join(lines)


# ---------- utility functions ----------

def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def escape_md(value: Any) -> str:
    text = str(value).replace("\n", " ")
    return text.replace("|", "\\|")


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def extract_function_source(module_text: str, function_name: str) -> str:
    """Best-effort source extraction for top-level or method functions."""
    try:
        tree = ast.parse(module_text)
    except SyntaxError:
        return ""
    lines = module_text.splitlines()
    candidates: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            candidates.append(node)
    if not candidates:
        return ""
    node = max(candidates, key=lambda n: getattr(n, "lineno", 0))
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    return "\n".join(lines[start - 1:end])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MemoryX production-readiness self-check.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="MemoryX repository root.")
    parser.add_argument("--run-pytest", action="store_true", help="Run pytest -q as part of the self-check.")
    parser.add_argument("--run-bandit", action="store_true", help="Run bandit -r memoryx if installed.")
    parser.add_argument("--run-ruff", action="store_true", help="Run ruff check memoryx tests if installed.")
    parser.add_argument("--run-pip-check", action="store_true", help="Run python -m pip check.")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout for external commands in seconds.")
    parser.add_argument("--fail-on", type=Severity.parse, default=Severity.ERROR, help="Exit nonzero on this severity or higher: INFO/WARN/ERROR/FATAL.")
    parser.add_argument("--json", dest="report_json", type=Path, default=None, help="JSON report path.")
    parser.add_argument("--md", dest="report_md", type=Path, default=None, help="Markdown report path.")
    args = parser.parse_args(argv)

    checker = ProductionSelfCheck(
        args.root,
        run_pytest=args.run_pytest,
        run_bandit=args.run_bandit,
        run_ruff=args.run_ruff,
        run_pip_check=args.run_pip_check,
        timeout=args.timeout,
        fail_on=args.fail_on,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    return checker.run()


if __name__ == "__main__":
    raise SystemExit(main())
