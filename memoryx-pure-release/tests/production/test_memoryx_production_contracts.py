"""
Production contract wrapper around tools/memoryx_production_selfcheck.py.

This test is intentionally non-invasive and fast by default. It runs the static/schema/runtime
core checks, but it does not recursively run pytest from inside pytest.

Usage:
    pytest -q tests/production/test_memoryx_production_contracts.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_selfcheck_module(root: Path):
    script = root / "tools" / "memoryx_production_selfcheck.py"
    spec = importlib.util.spec_from_file_location("memoryx_production_selfcheck", script)
    assert spec and spec.loader, f"Cannot load {script}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memoryx_production_contracts(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    mod = _load_selfcheck_module(root)
    checker = mod.ProductionSelfCheck(
        root,
        run_pytest=False,
        run_bandit=False,
        run_ruff=False,
        run_pip_check=False,
        timeout=120,
        fail_on=mod.Severity.ERROR,
        report_json=tmp_path / "production_selfcheck_report.json",
        report_md=tmp_path / "production_selfcheck_report.md",
    )
    exit_code = checker.run()
    blockers = [f for f in checker.findings if f.level >= mod.Severity.ERROR]
    assert exit_code == 0, "\n".join(
        f"[{f.severity}] {f.check} {f.path}: {f.message} {f.detail}" for f in blockers[:20]
    )
