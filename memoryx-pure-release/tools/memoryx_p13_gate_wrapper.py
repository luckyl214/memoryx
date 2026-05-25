#!/usr/bin/env python3
"""
P13 Gate Wrapper — lightweight subprocess-based semantic readiness check.

Used by the MemoryX Runtime Plugin to verify MemoryX health before Hermes
operations.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


MEMORYX_ROOT = os.getenv("MEMORYX_ROOT", "${HOME}/memoryx")
MEMORYX_DB_PATH = os.getenv("MEMORYX_DB_PATH", f"{MEMORYX_ROOT}./data/memoryx.db")
P13_GATE = f"{MEMORYX_ROOT}/tools/memoryx_semantic_integrity_gate.py"
PYTHON = f"{MEMORYX_ROOT}/.venv/bin/python"


def check() -> dict:
    """Run the P13 gate and return structured results."""
    env = os.environ.copy()
    env["MEMORYX_DB_PATH"] = MEMORYX_DB_PATH

    cmd = [
        PYTHON,
        P13_GATE,
        "--db",
        MEMORYX_DB_PATH,
        "--include-conversations",
        "--check-systemd",
    ]

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=MEMORYX_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "P13 gate timed out after 25s",
            "duration_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"P13 gate crashed: {exc}",
            "duration_ms": int((time.time() - started) * 1000),
        }

    duration_ms = int((time.time() - started) * 1000)
    combined_output = (proc.stdout or "") + (proc.stderr or "")

    # The P13 gate prints "ALL CHECKS PASSED" on success
    ok = "ALL CHECKS PASSED" in combined_output and proc.returncode == 0

    return {
        "ok": ok,
        "checked_at": time.time(),
        "duration_ms": duration_ms,
        "returncode": proc.returncode,
        "summary": combined_output.strip()[-500:] if not ok else "P13 gate passed",
    }


def main() -> None:
    result = check()
    status = "ok" if result["ok"] else "FAIL"
    print(f"[p13-gate-wrapper] status={status} duration={result['duration_ms']}ms")
    if not result["ok"]:
        print(f"[p13-gate-wrapper] summary: {result.get('summary', '')[-300:]}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()