#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/home/lucky/memoryx")
DEFAULT_MEMORYX_DB = DEFAULT_ROOT / "data" / "memoryx.db"
DEFAULT_FEISHU_DB = DEFAULT_ROOT / "data" / "feishu_queue.db"
DEFAULT_REST = "http://127.0.0.1:8080"


@dataclass
class Finding:
    level: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class SelfCheck:
    def __init__(
        self,
        *,
        root: Path,
        memoryx_db: Path,
        feishu_db: Path,
        rest_base: str,
        full: bool,
        json_output: bool,
    ) -> None:
        self.root = root
        self.memoryx_db = memoryx_db
        self.feishu_db = feishu_db
        self.rest_base = rest_base.rstrip("/")
        self.full = full
        self.json_output = json_output
        self.findings: list[Finding] = []

    def add(self, level: str, code: str, message: str, **detail: Any) -> None:
        self.findings.append(Finding(level=level, code=code, message=message, detail=detail))

    def fatal(self, code: str, message: str, **detail: Any) -> None:
        self.add("FATAL", code, message, **detail)

    def error(self, code: str, message: str, **detail: Any) -> None:
        self.add("ERROR", code, message, **detail)

    def warn(self, code: str, message: str, **detail: Any) -> None:
        self.add("WARN", code, message, **detail)

    def info(self, code: str, message: str, **detail: Any) -> None:
        self.add("INFO", code, message, **detail)

    def run(self) -> int:
        self.check_filesystem()
        self.check_systemd()
        self.check_rest()
        self.check_memoryx_db()
        self.check_embeddings()
        self.check_cognitive_tables()
        self.check_p_gates()
        self.check_hermes_runtime()
        self.check_feishu_runtime()
        self.check_learning_and_skills()
        self.check_search_efficiency()
        self.check_recent_logs()

        return self.report()

    def check_filesystem(self) -> None:
        if not self.root.exists():
            self.fatal("root_missing", "MemoryX root 不存在", root=str(self.root))
            return

        if not self.memoryx_db.exists():
            self.fatal("memoryx_db_missing", "canonical MemoryX DB 不存在", db=str(self.memoryx_db))
        else:
            self.info("memoryx_db_found", "canonical MemoryX DB 存在", db=str(self.memoryx_db))

        root_db = self.root / "memoryx.db"
        if root_db.exists() and root_db.resolve() != self.memoryx_db.resolve():
            self.error(
                "duplicate_db_path",
                "发现根目录 memoryx.db，可能导致 API 挂错库",
                root_db=str(root_db),
                canonical=str(self.memoryx_db),
            )

        if self.feishu_db.exists():
            self.info("feishu_db_found", "Feishu queue DB 存在", db=str(self.feishu_db))
        else:
            self.warn("feishu_db_missing", "Feishu queue DB 不存在；如果未启用飞书可忽略", db=str(self.feishu_db))

    def check_systemd(self) -> None:
        services = [
            "memoryx-rest.service",
            "hermes-gateway.service",
        ]

        for svc in services:
            if not shutil.which("systemctl"):
                self.warn("systemctl_missing", "systemctl 不可用，跳过 systemd 检查")
                return

            proc = self.cmd(["systemctl", "is-active", svc])
            if proc.returncode == 0 and proc.stdout.strip() == "active":
                self.info("service_active", f"{svc} active", service=svc)
            else:
                if svc == "memoryx-rest.service":
                    self.error("service_inactive", f"{svc} 未运行", service=svc, output=proc.stdout + proc.stderr)
                else:
                    self.warn("service_inactive", f"{svc} 未运行或不存在", service=svc, output=proc.stdout + proc.stderr)

        timers = [
            "memoryx-semantic-maintenance.timer",
            "memoryx-trust-maintenance.timer",
            "memoryx-learning-daily-review.timer",
        ]

        for timer in timers:
            proc = self.cmd(["systemctl", "is-active", timer])
            if proc.returncode == 0 and proc.stdout.strip() == "active":
                self.info("timer_active", f"{timer} active", timer=timer)
            else:
                self.warn("timer_inactive", f"{timer} 未 active", timer=timer)

    def check_rest(self) -> None:
        for path in ["/live", "/ready"]:
            ok, body, status = self.http_get(path, timeout=5)
            if ok:
                self.info("rest_endpoint_ok", f"{path} OK", status=status)
            else:
                self.error("rest_endpoint_failed", f"{path} 不可用", status=status, body=body[:500])

        ok, body, status = self.http_get("/metrics", timeout=5)
        if not ok:
            self.error("metrics_failed", "/metrics 不可用", status=status, body=body[:500])
        else:
            if "# HELP" in body or "# TYPE" in body or "memoryx" in body.lower():
                self.info("metrics_ok", "/metrics 暴露 Prometheus 文本指标", status=status)
            else:
                self.warn("metrics_weak", "/metrics 可访问但不像 Prometheus 文本格式", preview=body[:300])

    def check_memoryx_db(self) -> None:
        if not self.memoryx_db.exists():
            return

        try:
            conn = sqlite3.connect(str(self.memoryx_db))
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            self.fatal("memoryx_db_open_failed", "无法打开 MemoryX DB", error=str(exc))
            return

        try:
            journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            if str(journal).lower() == "wal":
                self.info("sqlite_wal_ok", "SQLite journal_mode=WAL")
            else:
                self.error("sqlite_wal_not_enabled", "SQLite 未启用 WAL", journal_mode=journal)

            quick = conn.execute("PRAGMA quick_check;").fetchone()[0]
            if quick == "ok":
                self.info("sqlite_quick_check_ok", "SQLite quick_check OK")
            else:
                self.error("sqlite_quick_check_failed", "SQLite quick_check 失败", result=quick)

            tables = self.tables(conn)

            required = {
                "memories",
                "memory_versions",
                "audit_logs",
                "conversation_logs",
                "lesson_memories",
                "lesson_triggers",
                "task_durations",
                "entities",
                "memory_entities",
                "entity_memory_links",
                "opinion_observations",
                "opinion_shifts",
                "claim_verification_runs",
                "claims",
                "claim_evidence",
                "hallucination_events",
                "llm_safety_events",
                "narrative_reflections",
                "learning_projects",
                "learning_sessions",
                "learning_artifacts",
                "mastery_checks",
                "skill_atoms",
                "skill_candidates",
                "skill_drafts",
            }

            missing = sorted(required - tables)
            if missing:
                self.error("memoryx_tables_missing", "MemoryX 必需表缺失", missing=missing)
            else:
                self.info("memoryx_tables_ok", "MemoryX 核心/认知/学习表齐全", count=len(required))

            self.check_runtime_identity(conn)
            self.check_counts(conn)

        finally:
            conn.close()

    def check_runtime_identity(self, conn: sqlite3.Connection) -> None:
        tables = self.tables(conn)
        if "runtime_identity" not in tables:
            self.error("runtime_identity_missing", "runtime_identity 表缺失，无法确认 canonical DB instance")
            return

        try:
            rows = conn.execute("SELECT * FROM runtime_identity LIMIT 3;").fetchall()
            if rows:
                self.info("runtime_identity_ok", "runtime_identity 存在", rows=len(rows))
            else:
                self.warn("runtime_identity_empty", "runtime_identity 表为空")
        except Exception as exc:
            self.warn("runtime_identity_read_failed", "runtime_identity 读取失败", error=str(exc))

    def check_counts(self, conn: sqlite3.Connection) -> None:
        for table in ["memories", "conversation_logs", "lesson_memories", "task_durations", "learning_sessions"]:
            if table in self.tables(conn):
                try:
                    n = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                    self.info("table_count", f"{table} count={n}", table=table, count=n)
                except Exception as exc:
                    self.warn("table_count_failed", f"{table} 计数失败", table=table, error=str(exc))

    def check_embeddings(self) -> None:
        if not self.memoryx_db.exists():
            return

        conn = sqlite3.connect(str(self.memoryx_db))
        conn.row_factory = sqlite3.Row

        try:
            tables = self.tables(conn)
            if "memory_embeddings" not in tables:
                self.error("embedding_table_missing", "memory_embeddings 表缺失")
                return

            memory_count = self.scalar(
                conn,
                "SELECT COUNT(*) FROM memories WHERE COALESCE(active_state, 'active') IN ('active', '1', 1);",
            )

            conv_count = 0
            if "conversation_logs" in tables:
                conv_count = self.scalar(conn, "SELECT COUNT(*) FROM conversation_logs;")

            emb_count = self.scalar(conn, "SELECT COUNT(*) FROM memory_embeddings;")
            expected_min = memory_count

            if emb_count < expected_min:
                self.error(
                    "embedding_coverage_low",
                    "embedding 覆盖率不足，语义检索可能失效",
                    memories=memory_count,
                    conversations=conv_count,
                    embeddings=emb_count,
                )
            else:
                self.info(
                    "embedding_coverage_ok",
                    "embedding 覆盖率满足最低要求",
                    memories=memory_count,
                    conversations=conv_count,
                    embeddings=emb_count,
                )

            cols = self.columns(conn, "memory_embeddings")
            vector_col = "vector_json" if "vector_json" in cols else None
            if vector_col:
                sample = conn.execute(
                    f"SELECT {vector_col} FROM memory_embeddings WHERE {vector_col} IS NOT NULL LIMIT 5;"
                ).fetchall()

                bad = 0
                dims = set()
                for row in sample:
                    try:
                        vec = json.loads(row[0])
                        dims.add(len(vec))
                        if not vec or all(abs(float(x)) < 1e-12 for x in vec):
                            bad += 1
                    except Exception:
                        bad += 1

                if bad:
                    self.error("embedding_bad_vectors", "发现空向量或非法向量", bad=bad, dims=sorted(dims))
                else:
                    self.info("embedding_vectors_ok", "embedding 样本向量正常", dims=sorted(dims))

        finally:
            conn.close()

    def check_cognitive_tables(self) -> None:
        conn = sqlite3.connect(str(self.memoryx_db))
        conn.row_factory = sqlite3.Row

        try:
            tables = self.tables(conn)

            if "memories" in tables:
                cols = self.columns(conn, "memories")
                needed = {"source_type", "verification_status", "trust_score"}
                missing = sorted(needed - cols)
                if missing:
                    self.error("trust_columns_missing", "P15.1 trust 列缺失", missing=missing)
                else:
                    self.info("trust_columns_ok", "P15.1 trust/source/verification 列存在")

                try:
                    bad_reflections = conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM memories
                        WHERE source_type='agent_reflection'
                          AND verification_status!='verified'
                          AND COALESCE(trust_score, 0.0) >= 0.55;
                        """
                    ).fetchone()[0]
                    if bad_reflections:
                        self.error(
                            "agent_reflection_trust_too_high",
                            "未验证 agent_reflection trust 过高，可能污染 context",
                            count=bad_reflections,
                        )
                    else:
                        self.info("agent_reflection_filtered", "未验证 agent_reflection 默认低可信")
                except Exception as exc:
                    self.warn("agent_reflection_check_failed", "agent_reflection trust 检查失败", error=str(exc))

            if "skill_drafts" in tables:
                auto_installed = self.scalar(
                    conn,
                    "SELECT COUNT(*) FROM skill_drafts WHERE status IN ('approved', 'installed') OR COALESCE(installed_path, '') != '';",
                )
                if auto_installed:
                    self.warn(
                        "skill_drafts_installed",
                        "存在已安装/批准 skill draft；确认是否人工审批",
                        count=auto_installed,
                    )
                else:
                    self.info("skill_drafts_draft_only", "skill draft 未自动安装，符合 P16 安全边界")

        finally:
            conn.close()

    def check_p_gates(self) -> None:
        gate_scripts = [
            "tools/memoryx_semantic_integrity_gate.py",
            "tools/memoryx_p15_runtime_gate.py",
            "tools/memoryx_p151_trust_gate.py",
            "tools/memoryx_p152_temporal_gate.py",
            "tools/memoryx_p16_learning_skill_gate.py",
            "tools/feishu_p1442_single_card_live_ux_gate.py",
            "tools/feishu_p1443_card_ownership_gate.py",
        ]

        env = os.environ.copy()
        env["MEMORYX_DB_PATH"] = str(self.memoryx_db)
        env["QUEUE_DB"] = str(self.feishu_db)

        for rel in gate_scripts:
            path = self.root / rel
            if not path.exists():
                self.warn("gate_missing", f"{rel} 不存在，跳过", script=rel)
                continue

            cmd = [sys.executable, str(path)]
            if "semantic_integrity" in rel:
                cmd = [sys.executable, str(path), "--db", str(self.memoryx_db), "--include-conversations", "--json"]
            if "feishu_p1443_card_ownership" in rel:
                cmd = [sys.executable, str(path), "--allow-empty"]

            proc = self.cmd(cmd, cwd=self.root, env=env, timeout=60)
            output = (proc.stdout + proc.stderr)[-4000:]
            if proc.returncode == 0:
                if "WARN:" in output:
                    self.warn("gate_warn", f"{rel} WARN", script=rel, output=output[:500])
                else:
                    self.info("gate_pass", f"{rel} PASS", script=rel)
            else:
                self.add("ERROR", "gate_failed", f"{rel} FAIL", script=rel, output=output)

    def check_hermes_runtime(self) -> None:
        hermes_home = Path(os.getenv("HERMES_HOME", "/home/lucky/.hermes"))
        plugin_dir = hermes_home / "plugins" / "memoryx_runtime"

        if plugin_dir.exists():
            self.info("hermes_memoryx_plugin_found", "Hermes memoryx_runtime plugin 存在", path=str(plugin_dir))
        else:
            self.error("hermes_memoryx_plugin_missing", "Hermes memoryx_runtime plugin 缺失", path=str(plugin_dir))

        proc = self.cmd(["systemctl", "show", "memoryx-rest.service", "-p", "Environment"])
        env_text = proc.stdout + proc.stderr

        required_env = {
            "FEISHU_OUTPUT_MODE=card_only",
            "FEISHU_SEND_TEXT_FALLBACK=false",
            "FEISHU_STREAM_TEXT_MESSAGES=false",
        }

        for item in required_env:
            if item in env_text:
                self.info("service_env_ok", f"{item} 已生效")
            else:
                self.warn("service_env_missing", f"{item} 未在 memoryx-rest.service 环境中发现")

        if "HERMES_FEISHU_CLI_PROVIDER=sensenova" in env_text:
            self.error("bad_cli_provider_forced", "仍然强制 HERMES_FEISHU_CLI_PROVIDER=sensenova，可能复现 Unknown provider")

        if shutil.which("hermes"):
            proc = self.cmd(["hermes", "model"], timeout=15)
            if proc.returncode == 0:
                self.info("hermes_model_ok", "hermes model 可运行")
            else:
                self.warn("hermes_model_failed", "hermes model 运行失败", output=(proc.stdout + proc.stderr)[-1000:])
        else:
            self.warn("hermes_cli_missing", "PATH 中找不到 hermes CLI")

    def check_feishu_runtime(self) -> None:
        if not self.feishu_db.exists():
            return

        conn = sqlite3.connect(str(self.feishu_db))
        conn.row_factory = sqlite3.Row

        try:
            journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            if str(journal).lower() == "wal":
                self.info("feishu_sqlite_wal_ok", "Feishu queue DB journal_mode=WAL")
            else:
                self.warn("feishu_sqlite_wal_not_enabled", "Feishu queue DB 未启用 WAL", journal_mode=journal)

            tables = self.tables(conn)
            required = {"feishu_jobs", "feishu_dead_letters", "feishu_trace_events"}
            missing = sorted(required - tables)
            if missing:
                self.error("feishu_tables_missing", "Feishu queue 必需表缺失", missing=missing)
                return

            dlq = self.scalar(conn, "SELECT COUNT(*) FROM feishu_dead_letters;")
            if dlq:
                self.error("feishu_dlq_not_empty", "Feishu DLQ 非空", dlq=dlq)
            else:
                self.info("feishu_dlq_empty", "Feishu DLQ=0")

            running = self.scalar(
                conn,
                "SELECT COUNT(*) FROM feishu_jobs WHERE state IN ('running', 'thinking') AND updated_at < strftime('%s','now') - 180;",
            )
            if running:
                self.error("feishu_stale_jobs", "存在 stale running/thinking job", count=running)
            else:
                self.info("feishu_no_stale_jobs", "无 stale running/thinking job")

            row = conn.execute(
                """
                SELECT job_id, state, visible_state, phase, revision, card_message_id, attempts,
                       created_at, updated_at
                FROM feishu_jobs
                ORDER BY created_at DESC
                LIMIT 1;
                """
            ).fetchone()

            if not row:
                self.warn("feishu_no_jobs", "Feishu jobs 为空，无法验证卡片链路")
                return

            latest = dict(row)
            self.info("feishu_latest_job", "Feishu latest job", **latest)

            if latest["state"] == "done":
                if latest.get("visible_state") != "done":
                    self.error("feishu_visible_not_done", "最新 job state=done 但 visible_state 非 done", **latest)
                if latest.get("phase") != "done":
                    self.error("feishu_phase_not_done", "最新 job state=done 但 phase 非 done，final transition 未落库", **latest)
                if not latest.get("card_message_id"):
                    self.error("feishu_card_message_id_empty", "最新 job card_message_id 为空，卡片无法动态 patch", **latest)
                if int(latest.get("revision") or 0) < 5:
                    self.warn("feishu_revision_low", "最新 job revision 偏低，动态状态 patch 可能不足", **latest)

                events = [
                    r["event_type"]
                    for r in conn.execute(
                        "SELECT event_type FROM feishu_trace_events WHERE job_id=? ORDER BY created_at ASC;",
                        (latest["job_id"],),
                    ).fetchall()
                ]

                needed = ["event_accepted", "job_queued", "job_claimed", "card_initial_sent", "state_transition", "card_patch_done", "job_done"]
                missing_events = [e for e in needed if e not in events]
                if missing_events:
                    self.error("feishu_trace_incomplete", "最新 Feishu job trace 不完整", missing=missing_events, events=events)
                else:
                    self.info("feishu_trace_complete", "最新 Feishu job trace 完整", event_count=len(events))

                patch_count = events.count("card_patch_done")
                if patch_count < 3:
                    self.error("feishu_patch_count_low", "card_patch_done 次数过少，卡片可能未动态更新", patch_count=patch_count)
                else:
                    self.info("feishu_patch_count_ok", "card_patch_done 次数满足动态更新要求", patch_count=patch_count)

        finally:
            conn.close()

    def check_learning_and_skills(self) -> None:
        if not self.memoryx_db.exists():
            return

        conn = sqlite3.connect(str(self.memoryx_db))
        conn.row_factory = sqlite3.Row

        try:
            tables = self.tables(conn)
            if "learning_sessions" in tables:
                recent = self.scalar(
                    conn,
                    "SELECT COUNT(*) FROM learning_sessions WHERE started_at >= datetime('now', '-24 hours');",
                )
                if recent:
                    self.info("learning_recent_sessions", "24h 内有 learning session", count=recent)
                else:
                    self.warn("learning_no_recent_sessions", "24h 内没有 learning session；如果今天未学习可忽略")

            if "mastery_checks" in tables:
                recent_checks = self.scalar(
                    conn,
                    "SELECT COUNT(*) FROM mastery_checks WHERE created_at >= datetime('now', '-24 hours');",
                )
                if recent_checks:
                    self.info("mastery_recent_checks", "24h 内有 mastery check", count=recent_checks)
                else:
                    self.warn("mastery_no_recent_checks", "24h 内没有 mastery check；学习闭环可能未跑完")

        finally:
            conn.close()

    def check_search_efficiency(self) -> None:
        """P18: session search index existence and coverage."""
        if not self.memoryx_db.exists():
            return

        conn = sqlite3.connect(str(self.memoryx_db))
        conn.row_factory = sqlite3.Row
        try:
            tables = self.tables(conn)
            if "session_search_index" not in tables:
                self.error("p18_search_index_missing", "session_search_index 表缺失")
                return
            if "session_search_fts" not in tables:
                self.error("p18_search_fts_missing", "session_search_fts 表缺失")

            n_indexed = self.scalar(conn, "SELECT COUNT(*) FROM session_search_index;")
            if n_indexed == 0:
                self.error("p18_search_index_empty", "session_search_index 为空，需要跑 maintenance")
            else:
                self.info("p18_search_index_ok", f"session_search_index 非空", count=n_indexed)

            try:
                import time
                started = time.perf_counter()
                conn.execute(
                    "SELECT idx.session_id FROM session_search_fts "
                    "JOIN session_search_index idx ON idx.session_id=session_search_fts.session_id "
                    "WHERE session_search_fts MATCH ? LIMIT 1",
                    ("memoryx OR hermes OR 小红书",),
                ).fetchall()
                elapsed_ms = (time.perf_counter() - started) * 1000
                if elapsed_ms > 50:
                    self.warn("p18_search_fts_slow", f"FTS 查询较慢: {elapsed_ms:.2f}ms")
                else:
                    self.info("p18_search_fts_latency", f"FTS 查询正常: {elapsed_ms:.2f}ms")
            except Exception as exc:
                self.warn("p18_search_fts_query_failed", "FTS 查询异常", error=str(exc))

            if "session_search_cache" in tables:
                cached = self.scalar(conn, "SELECT COUNT(*) FROM session_search_cache;")
                expired = self.scalar(
                    conn,
                    "SELECT COUNT(*) FROM session_search_cache WHERE expires_at < CURRENT_TIMESTAMP;",
                )
                if cached > 0:
                    self.info("p18_search_cache_ok", f"session_search_cache 有 {cached} 条", total=cached, expired=expired)
                else:
                    self.warn("p18_search_cache_empty", "session_search_cache 为空（新部署正常）")

            # Check session_search_events for recent activity
            if "session_search_events" in tables:
                recent = self.scalar(
                    conn,
                    "SELECT COUNT(*) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                )
                if recent > 0:
                    total_planned = self.scalar(
                        conn,
                        "SELECT SUM(llm_planned_sessions) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    total_actual = self.scalar(
                        conn,
                        "SELECT SUM(llm_actual_calls) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    total_cache = self.scalar(
                        conn,
                        "SELECT SUM(cache_hits) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    total_fallback = self.scalar(
                        conn,
                        "SELECT SUM(fallback_count) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    total_timeout = self.scalar(
                        conn,
                        "SELECT SUM(timeout_count) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    total_rate_limit = self.scalar(
                        conn,
                        "SELECT SUM(rate_limit_count) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    avg_ms = self.scalar(
                        conn,
                        "SELECT AVG(duration_ms) FROM session_search_events WHERE created_at >= datetime('now','-1 hour');",
                    )
                    self.info("p18_search_events",
                        f"1h 搜索 {recent} 次，planned LLM {total_planned or 0} 次，actual LLM {total_actual or 0} 次，缓存命中 {total_cache or 0} 次，降级 {total_fallback or 0} 次，timeout {total_timeout or 0} 次，限频 {total_rate_limit or 0} 次，avg {avg_ms:.1f}ms" if avg_ms else "1h 搜索无数据",
                        searches=recent, planned_llm=total_planned, actual_llm=total_actual, cache_hits=total_cache,
                        fallbacks=total_fallback, timeouts=total_timeout, rate_limits=total_rate_limit,
                        avg_ms=avg_ms)
                else:
                    self.warn("p18_search_events_empty", "1h 内无搜索事件记录")
        finally:
            conn.close()

    def check_recent_logs(self) -> None:
        if not shutil.which("journalctl"):
            return

        # 只检查最近 30 分钟的错误信号；更早的日志视为 stale，仅 WARN
        stale_cutoff = time.time() - 1800  # 30 min
        fresh_only = ["--since", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stale_cutoff))]

        for svc in ["memoryx-rest.service", "hermes-gateway.service"]:
            proc = self.cmd(
                ["journalctl", "-u", svc, "-n", "200", "--no-pager"] + fresh_only,
                timeout=15,
            )
            text = proc.stdout + proc.stderr
            if not text.strip():
                self.warn("journal_empty_or_denied", f"{svc} journal 无输出或权限不足", service=svc)
                continue

            bad = []
            for line in text.splitlines():
                lower = line.lower()
                if any(x in lower for x in ["traceback", "exception", "card_patch_failed", "unknown provider", "fatal"]):
                    bad.append(line[-500:])

            if bad:
                self.error("journal_errors_found", f"{svc} 最近 30 分钟日志有错误信号", service=svc, samples=bad[-10:])
            else:
                # 再查一次不限制时间，检测是否只有旧日志问题
                full_proc = self.cmd(
                    ["journalctl", "-u", svc, "-n", "200", "--no-pager"],
                    timeout=15,
                )
                full_text = full_proc.stdout + full_proc.stderr
                old_bad = 0
                for line in full_text.splitlines():
                    lower = line.lower()
                    if any(x in lower for x in ["traceback", "exception", "card_patch_failed", "unknown provider", "fatal"]):
                        old_bad += 1
                if old_bad:
                    self.warn("journal_stale_errors", f"{svc} 有 {old_bad} 条旧日志错误信号（>30 分钟前），不影响当前运行", service=svc, stale_count=old_bad)
                else:
                    self.info("journal_clean", f"{svc} 最近日志无明显错误信号", service=svc)

    def report(self) -> int:
        counts = {"FATAL": 0, "ERROR": 0, "WARN": 0, "INFO": 0}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1

        worst = "OK"
        if counts["FATAL"]:
            worst = "FATAL"
        elif counts["ERROR"]:
            worst = "ERROR"
        elif counts["WARN"]:
            worst = "WARN"

        payload = {
            "status": "pass" if worst in {"OK", "WARN"} and counts["FATAL"] == 0 and counts["ERROR"] == 0 else "fail",
            "worst": worst,
            "counts": counts,
            "findings": [
                {"level": f.level, "code": f.code, "message": f.message, "detail": f.detail}
                for f in self.findings
            ],
        }

        if self.json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== MemoryX / Hermes Unified SelfCheck ===")
            print(f"status={payload['status']} worst={worst} FATAL={counts['FATAL']} ERROR={counts['ERROR']} WARN={counts['WARN']} INFO={counts['INFO']}")
            print()
            for f in self.findings:
                prefix = {"FATAL": "🔴", "ERROR": "🟥", "WARN": "🟨", "INFO": "✅"}.get(f.level, "•")
                print(f"{prefix} [{f.level}] {f.code}: {f.message}")
                if f.detail and f.level in {"FATAL", "ERROR", "WARN"}:
                    detail_str = json.dumps(f.detail, ensure_ascii=False)[:1200]
                    print(f"    {detail_str}")

            if payload["status"] == "pass":
                print(f"\nMemoryX Ready: Hermes Cognitive Spine Online")
            else:
                print(f"\nMemoryX NOT READY: fix FATAL/ERROR before entering learning or Feishu real mode.")

        return 0 if payload["status"] == "pass" else 2

    def http_get(self, path: str, *, timeout: int = 5) -> tuple[bool, str, int | None]:
        url = self.rest_base + path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "memoryx-p17-selfcheck"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return True, body, resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return False, body, exc.code
        except Exception as exc:
            return False, str(exc), None

    def cmd(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
        except Exception as exc:
            return subprocess.CompletedProcess(args=args, returncode=99, stdout="", stderr=str(exc))

    def tables(self, conn: sqlite3.Connection) -> set[str]:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view', 'virtual table');").fetchall()
        }

    def columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}

    def scalar(self, conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
        try:
            row = conn.execute(sql, params).fetchone()
            if not row:
                return 0
            return int(row[0] or 0)
        except Exception:
            return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--memoryx-db", default=os.getenv("MEMORYX_DB_PATH", str(DEFAULT_MEMORYX_DB)))
    parser.add_argument("--feishu-db", default=os.getenv("QUEUE_DB", str(DEFAULT_FEISHU_DB)))
    parser.add_argument("--rest", default=os.getenv("MEMORYX_REST", DEFAULT_REST))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checker = SelfCheck(
        root=Path(args.root),
        memoryx_db=Path(args.memoryx_db),
        feishu_db=Path(args.feishu_db),
        rest_base=args.rest,
        full=args.full,
        json_output=args.json,
    )
    return checker.run()


if __name__ == "__main__":
    raise SystemExit(main())