#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryX benchmark threshold gate.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--retrieval-p95-ms", type=float, default=100.0)
    parser.add_argument("--store-p95-ms", type=float, default=50.0)
    parser.add_argument("--lesson-match-p95-ms", type=float, default=10.0)
    args = parser.parse_args()

    data = json.loads(args.report.read_text(encoding="utf-8"))
    failures: list[str] = []

    checks = [
        ("retrieval_p95_ms", args.retrieval_p95_ms),
        ("store_p95_ms", args.store_p95_ms),
        ("lesson_match_p95_ms", args.lesson_match_p95_ms),
    ]
    for key, threshold in checks:
        value = float(data.get(key, 0.0))
        if value > threshold:
            failures.append(f"{key}={value:.3f} > {threshold:.3f}")

    if failures:
        print("Benchmark gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Benchmark gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
