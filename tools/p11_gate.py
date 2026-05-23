#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main() -> int:
    commands = [
        [sys.executable, "-m", "pytest", "-q", "tests/p11"],
        [sys.executable, "tools/memoryx_production_selfcheck.py", "--root", "."],
    ]
    for cmd in commands:
        code = run(cmd)
        if code != 0:
            return code
    print("P11 cognitive guard gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
