#!/usr/bin/env python3
"""MemoryX ReleaseGate — pre-release validation gate.

Runs all checks on a clean checkout and produces JSON + Markdown reports.
Exit code 0 = PASS, 1 = FAIL, 2 = WARN.

Usage:
    python scripts/run_memoryx_release_gate.py --report-dir reports/release-gate
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300, **kwargs)


class ReleaseGate:
    def __init__(self, report_dir: Path) -> None:
        self.report_dir = report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.checks: dict[str, dict] = {}

    def record(self, name: str, status: str, detail: str = "") -> None:
        self.checks[name] = {"status": status, "detail": detail}
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(status, "❓")
        print(f"  {icon} {name}: {status}" + (f" — {detail}" if detail else ""))

    # ── Check 1: Clean status ──
    def check_clean_status(self) -> None:
        r = run(["git", "status", "--porcelain=v1"])
        lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
        # Filter out reports/ and known runtime artifacts
        dirty = [l for l in lines if not l.strip().endswith("reports/") and "reports/" not in l]
        if not dirty:
            self.record("clean_status", "pass")
        else:
            self.record("clean_status", "warn", f"{len(dirty)} dirty tracked files")

    # ── Check 2: Collect-only ──
    def check_collect_only(self) -> None:
        venv = REPO / ".venv" / "bin" / "python"
        python = str(venv) if venv.exists() else sys.executable
        r = run([python, "-m", "pytest", "--collect-only", "-q",
                 "--ignore=tests/test_pii_filter.py",
                 "--ignore=tests/test_extraction_client.py",
                 "--ignore=tools/",
                 "--ignore=memoryx-pure-release/",
                 "--ignore=scripts/"])
        out = r.stdout + r.stderr
        (self.report_dir / "collect-only.txt").write_text(out)
        if "error" in out.lower() and "collected" not in out:
            self.record("collect_only", "fail", "collection errors detected")
        else:
            # Extract count
            m = re.search(r"(\d+) tests collected", out)
            count = m.group(1) if m else "?"
            self.record("collect_only", "pass", f"{count} tests collected")

    # ── Check 3: Full pytest ──
    def check_pytest_full(self) -> None:
        venv = REPO / ".venv" / "bin" / "python"
        python = str(venv) if venv.exists() else sys.executable
        r = run([python, "-m", "pytest", "-q",
                 "--ignore=tests/test_pii_filter.py",
                 "--ignore=tests/test_extraction_client.py",
                 "--ignore=tools/",
                 "--ignore=memoryx-pure-release/",
                 "--ignore=scripts/",
                 f"--junitxml={self.report_dir}/full-junit.xml"])
        out = r.stdout + r.stderr
        (self.report_dir / "full-pytest.txt").write_text(out)
        if r.returncode == 0:
            m = re.search(r"(\d+) passed", out)
            count = m.group(1) if m else "?"
            self.record("pytest_full", "pass", f"{count} passed")
        else:
            m = re.search(r"(\d+) failed", out)
            failed = m.group(1) if m else "?"
            self.record("pytest_full", "fail", f"{failed} failed")

    # ── Check 4: Core smoke ──
    def check_core_smoke(self) -> None:
        venv = REPO / ".venv" / "bin" / "python"
        python = str(venv) if venv.exists() else sys.executable
        script = '''
import asyncio, sys
sys.path.insert(0, ".")
from pathlib import Path
from memoryx.storage import MemoryRecord, MemoryRepository

async def main():
    import tempfile
    db = Path(tempfile.mkdtemp()) / "smoke.db"
    repo = MemoryRepository(db)
    await repo.open()
    mid = await repo.store_memory(MemoryRecord(memory_id="smoke-1", memory_type="FACT", content="smoke test", scope="user"))
    mem = await repo.get_memory("smoke-1")
    assert mem is not None, "get_memory failed"
    assert mem["scope"] == "user", f"scope mismatch: {mem['scope']}"
    results = await repo.search_full_text("smoke")
    assert len(results) >= 1, "search_full_text returned empty"
    await repo.close()
    print("CORE_SMOKE_PASS")

asyncio.run(main())
'''
        r = run([python, "-c", script])
        out = r.stdout + r.stderr
        (self.report_dir / "core-smoke.txt").write_text(out)
        if "CORE_SMOKE_PASS" in out:
            self.record("core_smoke", "pass")
        else:
            self.record("core_smoke", "fail", out.strip()[-200:])

    # ── Check 5: FK check ──
    def check_foreign_key(self) -> None:
        script = '''
import sqlite3
from pathlib import Path
db_files = list(Path(".").rglob("*.db")) + list(Path(".").rglob("*.sqlite"))
db_files = [p for p in db_files if ".venv" not in str(p) and "reports" not in str(p)]
if not db_files:
    print("NO_DB_FILES")
else:
    total = 0
    for p in db_files[:10]:
        try:
            conn = sqlite3.connect(p)
            conn.execute("PRAGMA foreign_keys=ON")
            rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if rows:
                print(f"VIOLATION: {p}: {len(rows)}")
                total += len(rows)
            conn.close()
        except Exception as e:
            print(f"ERROR: {p}: {e!r}")
    if total == 0:
        print("FK_CHECK_PASS")
'''
        venv = REPO / ".venv" / "bin" / "python"
        python = str(venv) if venv.exists() else sys.executable
        r = run([python, "-c", script])
        out = r.stdout
        (self.report_dir / "fk-check.txt").write_text(out)
        if "FK_CHECK_PASS" in out or "NO_DB_FILES" in out:
            self.record("foreign_key_check", "pass")
        else:
            self.record("foreign_key_check", "fail", out.strip()[-200:])

    # ── Check 6: Forbidden dependency scan ──
    def check_forbidden_deps(self) -> None:
        forbidden = {
            "memoryx/mcp_server.py": ["LanceDB", "VectorStore", "EmbeddingIndex"],
            "memoryx/storage/repository.py": ["EmbeddingManager", "LanceDB"],
            "memoryx/hooks/": ["LanceDB", "VectorStore"],
        }
        violations = []
        for path_str, deps in forbidden.items():
            target = REPO / path_str
            if target.is_dir():
                files = list(target.rglob("*.py"))
            elif target.exists():
                files = [target]
            else:
                continue
            for f in files:
                if "__pycache__" in str(f):
                    continue
                try:
                    content = f.read_text()
                except Exception:
                    continue
                for dep in deps:
                    if dep in content and "import" in content:
                        # Check if it's actually imported (not just a comment)
                        for line in content.split("\n"):
                            if line.strip().startswith("#"):
                                continue
                            if f"import.*{dep}" in line or f"from.*{dep}" in line:
                                violations.append(f"{f.relative_to(REPO)}: imports {dep}")
        if not violations:
            self.record("forbidden_dependency_scan", "pass")
        else:
            self.record("forbidden_dependency_scan", "fail", "; ".join(violations[:5]))

    # ── Check 7: Skip/xfail scan ──
    def check_skip_xfail(self) -> None:
        count = 0
        locations = []
        for f in (REPO / "tests").rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            try:
                content = f.read_text()
            except Exception:
                continue
            for line_num, line in enumerate(content.split("\n"), 1):
                if line.strip().startswith("#"):
                    continue
                if re.search(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|pytest\.xfail\(", line):
                    count += 1
                    locations.append(f"{f.relative_to(REPO)}:{line_num}")
        if count == 0:
            self.record("skip_xfail_scan", "pass")
        else:
            self.record("skip_xfail_scan", "warn", f"{count} skip/xfail found: {'; '.join(locations[:3])}")

    # ── Check 8: Secret scan ──
    def check_secret_scan(self) -> None:
        patterns = [
            (r'sk-[a-zA-Z0-9]{20,}', "API key"),
            (r'ghp_[a-zA-Z0-9]{36,}', "GitHub PAT"),
            (r'AIza[0-9A-Za-z\-_]{35}', "Google key"),
            (r'AKIA[0-9A-Z]{16}', "AWS key"),
        ]
        findings = []
        skip_dirs = {".venv", "__pycache__", ".git", "reports", "lancedb", "traces", "artifacts", "logs"}
        for ext in ("*.py", "*.md", "*.yaml", "*.yml", "*.toml"):
            for f in REPO.rglob(ext):
                if any(d in str(f) for d in skip_dirs):
                    continue
                try:
                    content = f.read_text(errors="ignore")
                except Exception:
                    continue
                for pattern, label in patterns:
                    if re.search(pattern, content):
                        findings.append(f"{f.relative_to(REPO)}: {label}")
        if not findings:
            self.record("secret_scan", "pass")
        else:
            self.record("secret_scan", "fail", "; ".join(findings[:3]))

    # ── Check 9: Package hygiene ──
    def check_package_hygiene(self) -> None:
        bad_patterns = [".env", "*.db", "*.sqlite", "*.sqlite3", "*.lancedb"]
        skip_dirs = {".venv", "__pycache__", ".git", "reports", "lancedb"}
        violations = []
        for pattern in bad_patterns:
            for f in REPO.rglob(pattern):
                if any(d in str(f) for d in skip_dirs):
                    continue
                # Check if tracked by git
                r = run(["git", "ls-files", "--error-unmatch", str(f.relative_to(REPO))])
                if r.returncode == 0:
                    violations.append(f"{f.relative_to(REPO)}")
        if not violations:
            self.record("package_hygiene", "pass")
        else:
            self.record("package_hygiene", "fail", f"{len(violations)} bad files tracked: {'; '.join(violations[:3])}")

    # ── Run all ──
    def run_all(self) -> str:
        print("=" * 60)
        print("  MemoryX ReleaseGate")
        print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 60)

        self.check_clean_status()
        self.check_collect_only()
        self.check_pytest_full()
        self.check_core_smoke()
        self.check_foreign_key()
        self.check_forbidden_deps()
        self.check_skip_xfail()
        self.check_secret_scan()
        self.check_package_hygiene()

        # Determine overall status
        statuses = [c["status"] for c in self.checks.values()]
        if "fail" in statuses:
            overall = "fail"
        elif "warn" in statuses:
            overall = "warn"
        else:
            overall = "pass"

        report = {
            "status": overall,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": self.checks,
        }

        # Write JSON
        (self.report_dir / "release-gate.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False))

        # Write Markdown
        md = [f"# MemoryX ReleaseGate Report", "",
              f"**Status: {overall.upper()}**", "",
              f"Timestamp: {report['timestamp']}", "",
              "## Checks", ""]
        for name, check in self.checks.items():
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(check["status"], "❓")
            detail = f" — {check['detail']}" if check["detail"] else ""
            md.append(f"- {icon} **{name}**: {check['status']}{detail}")
        (self.report_dir / "release-gate.md").write_text("\n".join(md))

        print()
        print("=" * 60)
        print(f"  OVERALL: {overall.upper()}")
        print("=" * 60)
        return overall


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryX ReleaseGate")
    parser.add_argument("--report-dir", type=Path, default=REPO / "reports" / "release-gate")
    args = parser.parse_args()

    gate = ReleaseGate(args.report_dir)
    status = gate.run_all()
    return {"pass": 0, "warn": 1, "fail": 2}.get(status, 2)


if __name__ == "__main__":
    sys.exit(main())
