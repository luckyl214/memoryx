from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_benchmark_report_gate_parses_json(tmp_path: Path):
    report = tmp_path / "bench.json"
    report.write_text(
        json.dumps(
            {
                "suite": "memoryx",
                "retrieval_p95_ms": 25.0,
                "store_p95_ms": 10.0,
                "lesson_match_p95_ms": 2.0,
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "tools/benchmark_gate.py",
            "--report",
            str(report),
            "--retrieval-p95-ms",
            "50",
            "--store-p95-ms",
            "20",
            "--lesson-match-p95-ms",
            "5",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert proc.returncode == 0, proc.stdout
