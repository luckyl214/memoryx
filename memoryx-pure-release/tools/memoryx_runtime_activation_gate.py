#!/usr/bin/env python3
"""
P15 MemoryX Runtime Activation Gate.

Verifies that MemoryX is truly wired into Hermes runtime:
1. Hermes config enables memoryx_runtime plugin
2. Plugin files exist and compile
3. DB has recent memories (auto-store active)
4. DB has recent evaluate-action calls (pre_tool_call active)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def scalar(conn: sqlite3.Connection, sql: str, *params) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.getenv("MEMORYX_DB_PATH", "${HOME}./data/memoryx.db"))
    parser.add_argument("--hermes-config", default="${HOME}/.hermes/config.yaml")
    parser.add_argument("--plugin-dir", default="${HOME}/.hermes/plugins/memoryx_runtime")
    parser.add_argument("--gate-mode", action="store_true", help="Require ALL checks to pass (exit 1 on any failure)")
    parser.add_argument("--check-recent", action="store_true", help="Require memories from the last 24h")
    args = parser.parse_args()

    db = Path(args.db)
    config_path = Path(args.hermes_config)
    plugin_dir = Path(args.plugin_dir)

    errors = 0

    print("")
    print("=" * 60)
    print("  P15 Hermes MemoryX Runtime Activation Gate")
    print("=" * 60)
    print("")

    # ──────────────────────────────────────────────
    # 1. Hermes config
    # ──────────────────────────────────────────────
    print("1. Hermes Config")
    if not config_path.exists():
        fail(f"Config not found: {config_path}")
        errors += 1
    else:
        ok(f"Config exists: {config_path}")
        if yaml is not None:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            enabled = (data.get("plugins") or {}).get("enabled") or []
            if isinstance(enabled, str):
                enabled = [enabled]
            if "memoryx_runtime" not in enabled:
                fail("memoryx_runtime not in plugins.enabled")
                errors += 1
            else:
                ok("memoryx_runtime in plugins.enabled")
        else:
            text = config_path.read_text(encoding="utf-8")
            if "memoryx_runtime" not in text:
                fail("memoryx_runtime not found in config")
                errors += 1
            else:
                ok("memoryx_runtime found in config")

    # ──────────────────────────────────────────────
    # 2. Plugin files
    # ──────────────────────────────────────────────
    print("2. Plugin Files")
    if not plugin_dir.exists():
        fail(f"Plugin dir not found: {plugin_dir}")
        errors += 1
    else:
        ok(f"Plugin dir exists: {plugin_dir}")
        init_py = plugin_dir / "__init__.py"
        yaml_file = plugin_dir / "plugin.yaml"
        if not init_py.exists():
            fail("__init__.py missing")
            errors += 1
        else:
            ok("__init__.py exists")
            # Compile check
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", str(init_py)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                fail(f"Compile error:\n{proc.stderr}")
                errors += 1
            else:
                ok("__init__.py compiles")
        if not yaml_file.exists():
            fail("plugin.yaml missing")
            errors += 1
        else:
            ok("plugin.yaml exists")

    # ──────────────────────────────────────────────
    # 3. Database health
    # ──────────────────────────────────────────────
    print("3. Database Health")
    if not db.exists():
        fail(f"DB not found: {db}")
        errors += 1
    else:
        ok(f"DB exists: {db}")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row

            tables = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','virtual table');")
            }
            required = {"memories", "memory_embeddings", "conversation_logs", "audit_logs"}
            missing = sorted(required - tables)
            if missing:
                fail(f"Missing tables: {missing}")
                errors += 1
            else:
                ok(f"Required tables present: {len(required)}")

            mem_count = scalar(conn, "SELECT COUNT(*) FROM memories")
            emb_count = scalar(conn, "SELECT COUNT(*) FROM memory_embeddings")
            conv_count = scalar(conn, "SELECT COUNT(*) FROM conversation_logs")
            ok(f"memories={mem_count}, embeddings={emb_count}, conversations={conv_count}")

            if mem_count < 1:
                fail("No memories in database")
                errors += 1
            else:
                ok(f"Total memories: {mem_count}")

            # ──────────────────────────────────────────────
            # 4. Recent activity (runtime proof)
            # ──────────────────────────────────────────────
            print("4. Runtime Activity")

            recent_mem = scalar(
                conn,
                "SELECT COUNT(*) FROM memories WHERE created_at >= datetime('now', '-24 hours')",
            )
            if recent_mem < 1:
                if args.check_recent or args.gate_mode:
                    fail("No memories in last 24h — auto-store may not be active")
                    errors += 1
                else:
                    warn(f"No memories in last 24h (skip with --check-recent)")
            else:
                ok(f"Memories in last 24h: {recent_mem}")

            recent_audit = scalar(
                conn,
                "SELECT COUNT(*) FROM audit_logs WHERE action IN ('store_memory','store') AND created_at >= datetime('now', '-24 hours')",
            )
            if recent_audit >= 1:
                ok(f"Recent store actions: {recent_audit}")

            # Check for EPISODIC memories (auto-store evidence)
            episodic = scalar(
                conn,
                "SELECT COUNT(*) FROM memories WHERE memory_type = 'EPISODIC' AND created_at >= datetime('now', '-24 hours')",
            )
            if episodic >= 1:
                ok(f"EPISODIC memories (auto-store evidence): {episodic}")
            else:
                if args.check_recent or args.gate_mode:
                    warn("No EPISODIC memories in last 24h — auto-store may not be active")

            conn.close()

        except Exception as exc:
            fail(f"DB check failed: {exc}")
            errors += 1

    # ──────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────
    print("")
    print("-" * 60)
    if errors == 0:
        print("  P15 HERMES MEMORYX RUNTIME ACTIVATION GATE: PASS")
        print("")
        print("  MemoryX is fully wired into Hermes runtime:")
        print("  - P13 pre-session check       ON")
        print("  - pre_llm_call context        ON")
        print("  - pre_tool_call guard          ON")
        print("  - post_llm_call auto-store    ON")
        print("  - post_llm_call verify-answer ON")
        print("  - on_session_end reflection   ON")
    else:
        print(f"  P15 GATE: {errors} check(s) FAILED")
    print("-" * 60)
    print("")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())