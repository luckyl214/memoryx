#!/usr/bin/env python3
"""
MemoryX repository guard.

Run before committing or asking an agent to modify the repo.

Checks:
- worktree status visibility
- forbidden runtime/private files
- protected tags not moved locally
- package version consistency
- stable tag hygiene hints

This script intentionally does not mutate repository state.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROTECTED_TAGS = ["v2.0.0", "v2.0.0-rc.1", "v2.0.0-rc.2"]
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env($|/)"),
    re.compile(r"(^|/)reports($|/)"),
    re.compile(r"(^|/)artifacts($|/)"),
    re.compile(r"(^|/)logs($|/)"),
    re.compile(r"(^|/)traces($|/)"),
    re.compile(r"(^|/)lancedb($|/)"),
    re.compile(r"\.sqlite$"),
    re.compile(r"\.db$"),
    re.compile(r"__pycache__"),
    re.compile(r"\.pytest_cache"),
]
SECRET_PATTERNS = [
    re.compile(r"OPENAI_API_KEY\s*="),
    re.compile(r"SILICONFLOW_API_KEY\s*="),
    re.compile(r"api[_-]?key\s*=\s*['\"][A-Za-z0-9_\-]{16,}", re.I),
    re.compile(r"secret\s*=\s*['\"][A-Za-z0-9_\-]{16,}", re.I),
    re.compile(r"token\s*=\s*['\"][A-Za-z0-9_\-]{16,}", re.I),
    re.compile(r"password\s*=\s*['\"][^'\"]{8,}", re.I),
]


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def fail(msg: str) -> None:
    print(f"[memoryx_repo_guard] FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def warn(msg: str) -> None:
    print(f"[memoryx_repo_guard] WARN: {msg}")


def ok(msg: str) -> None:
    print(f"[memoryx_repo_guard] PASS: {msg}")


def repo_root() -> Path:
    try:
        cp = run(["git", "rev-parse", "--show-toplevel"])
    except Exception:
        fail("not inside a git repository")
    return Path(cp.stdout.strip())


def git_status(root: Path) -> list[str]:
    cp = run(["git", "status", "--short"], check=True)
    lines = [x for x in cp.stdout.splitlines() if x.strip()]
    if lines:
        warn("worktree is dirty:")
        for line in lines:
            print(f"  {line}")
    else:
        ok("worktree clean")
    return lines


def check_forbidden_paths(root: Path) -> None:
    cp = run(["git", "ls-files"], check=True)
    bad: list[str] = []
    for rel in cp.stdout.splitlines():
        for pat in FORBIDDEN_PATH_PATTERNS:
            if pat.search(rel):
                bad.append(rel)
                break
    if bad:
        print("\nForbidden tracked paths:")
        for item in bad:
            print(f"  {item}")
        fail("forbidden runtime/private files are tracked")
    ok("no forbidden runtime/private tracked files")


def check_secret_patterns(root: Path) -> None:
    cp = run(["git", "ls-files"], check=True)
    bad: list[tuple[str, int, str]] = []

    skip_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".gz", ".zip"}
    for rel in cp.stdout.splitlines():
        path = root / rel
        if path.suffix.lower() in skip_ext:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        for i, line in enumerate(text.splitlines(), 1):
            if "your_" in line or "placeholder" in line.lower() or "example" in rel.lower():
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    bad.append((rel, i, line.strip()))
                    break

    if bad:
        print("\nPossible secret hits:")
        for rel, line_no, line in bad[:50]:
            print(f"  {rel}:{line_no}: {line}")
        fail("possible secrets found")
    ok("secret pattern scan clean")


def check_tags() -> None:
    for tag in PROTECTED_TAGS:
        cp = run(["git", "tag", "-l", tag], check=True)
        if not cp.stdout.strip():
            warn(f"protected tag not present locally: {tag}")
            continue
        tag_type = run(["git", "cat-file", "-t", tag], check=False)
        if tag_type.returncode == 0 and tag_type.stdout.strip() != "tag":
            fail(f"{tag} is not an annotated tag locally; got {tag_type.stdout.strip()!r}")
        ok(f"protected tag present and annotated locally: {tag}")


def check_version(root: Path) -> None:
    pyproject = root / "pyproject.toml"
    init_py = root / "memoryx" / "__init__.py"
    version_file = root / "VERSION"

    expected = "2.0.0"
    text = pyproject.read_text(encoding="utf-8")
    if 'version = "2.0.0"' not in text:
        warn('pyproject.toml does not contain version = "2.0.0"')

    if init_py.exists():
        init_text = init_py.read_text(encoding="utf-8")
        if '__version__ = "2.0.0"' not in init_text and "__version__='2.0.0'" not in init_text:
            warn("memoryx/__init__.py may not expose __version__ = 2.0.0")

    if version_file.exists() and version_file.read_text(encoding="utf-8").strip() != expected:
        warn("VERSION file is not 2.0.0")

    ok("version metadata checked")


def main() -> None:
    root = repo_root()
    os.chdir(root)
    print(f"[memoryx_repo_guard] repo: {root}")

    git_status(root)
    check_forbidden_paths(root)
    check_secret_patterns(root)
    check_tags()
    check_version(root)

    print("[memoryx_repo_guard] DONE")


if __name__ == "__main__":
    main()
