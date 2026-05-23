#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, text=True)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryX P8 E2E gate.")
    parser.add_argument("--skip-docker", action="store_true")
    parser.add_argument("--skip-benchmark", action="store_true")
    parser.add_argument("--benchmark-report", type=Path, default=Path("benchmark_report.json"))
    args = parser.parse_args()

    commands = [
        [sys.executable, "-m", "pytest", "-q", "tests/e2e"],
        [sys.executable, "tools/memoryx_production_selfcheck.py", "--root", "."],
    ]

    if not args.skip_benchmark and args.benchmark_report.exists():
        commands.append(
            [
                sys.executable,
                "tools/benchmark_gate.py",
                "--report",
                str(args.benchmark_report),
            ]
        )

    if not args.skip_docker:
        commands.append(["docker", "build", "-t", "memoryx:p8-gate", "."])

    for cmd in commands:
        code = run(cmd)
        if code != 0:
            return code

    print("P8 E2E gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
