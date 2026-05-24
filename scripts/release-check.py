#!/usr/bin/env python3
"""
release-check.py — 推送前安全检查

确保不会把非代码文件、敏感信息、个人路径等推送到 GitHub。
使用: python scripts/release-check.py
"""

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
errors = []
warnings = []
passes = 0


def check(ok: bool, msg: str, is_error: bool = False):
    global passes
    if ok:
        passes += 1
    elif is_error:
        errors.append(msg)
    else:
        warnings.append(msg)


def scan_file(path: Path):
    """扫描单个文件中的敏感信息。"""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return

    # API Keys / Tokens
    for pattern, label in [
        (r'sk-[a-zA-Z0-9]{20,}', "OpenAI-style API key"),
        (r'ghp_[a-zA-Z0-9]{36,}', "GitHub PAT"),
        (r'AIza[0-9A-Za-z\-_]{35}', "Google API key"),
        (r'AKIA[0-9A-Z]{16}', "AWS access key"),
    ]:
        matches = re.findall(pattern, content)
        for m in matches:
            check(False, f"[SECRET] {label} found in {rel(path)}", is_error=True)

    # Absolute local paths
    # 排除生成的报告文件、测试文件、网关脚本、文档示例、systemd 配置
    if path.suffix in (".py", ".md", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".env.example", ".service"):
        # 白名单：这些文件类型允许包含 /home/ 路径
        allowed_patterns = [
            "test_",          # 测试文件（test_*.py）
            "_test.",         # 测试文件（*_test.py）
            "_report.",       # 生成的报告文件
            "_gate.",         # 网关脚本（生产配置）
            "README.md",      # 文档示例
            "*.service",      # systemd 服务配置
            "start_hermes",   # 启动脚本文档
        ]
        if any(p in path.name for p in allowed_patterns):
            return
        for line in content.split("\n"):
            if "/home/" in line and "${HOME}/" not in line and path.name not in (".gitignore", "release-check.py"):
                check(False, f"[PATH] {rel(path)}: {line.strip()[:80]}", is_error=True)


def rel(p: Path) -> str:
    return str(p.relative_to(REPO))


# ── 检查 1: Git 状态 ──
print("=" * 50)
print("RELEASE CHECK — Mnemosyne-X")
print("=" * 50)

import subprocess
result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO)
modified = [line for line in result.stdout.strip().split("\n") if line.strip()]
check(len(modified) == 0, f"Git working tree is clean ({len(modified)} uncommitted files)", is_error=True)

# ── 检查 2: .gitignore 存在且完整 ──
gi = REPO / ".gitignore"
check(gi.exists(), ".gitignore exists", is_error=True)
if gi.exists():
    content = gi.read_text()
    for needed in ["*.db", "logs/", ".env", "__pycache__/", "*.log", "cache/", "dead_letters/", "queue/"]:
        check(needed in content, f".gitignore covers: {needed}", is_error=True)

# ── 检查 3: git add --dry-run 不产生文件 ──
result = subprocess.run(["git", "add", "--dry-run", "-A"], capture_output=True, text=True, cwd=REPO)
files_to_add = [line for line in result.stdout.strip().split("\n") if line.strip()]
check(len(files_to_add) == 0, f"git add -A would add {len(files_to_add)} files (should be 0)", is_error=True)

# ── 检查 4: 扫描源码中的敏感信息 ──
for ext in ("*.py", "*.md", "*.yaml", "*.yml", "*.toml", "*.ini", "*.sh", "*.cfg", "*.service", "Makefile", "Dockerfile"):
    for f in REPO.rglob(ext):
        if ".venv" in str(f) or "__pycache__" in str(f) or ".git" in str(f):
            continue
        scan_file(f)

# ── 报告 ──
print()

# 安全扫描的 errors 数量（不包括前面的检查错误）
security_errors = len([e for e in errors if e.startswith("[SECRET]") or e.startswith("[PATH]")])
check(security_errors == 0, f"Security scan: {security_errors} errors, {len(warnings)} warnings", is_error=True)

print(f"\n✓ {passes} checks passed")
if warnings:
    print(f"⚠  {len(warnings)} warnings:")
    for w in warnings:
        print(f"   ⚠  {w}")
if errors:
    print(f"✗  {len(errors)} ERRORS (must fix before push):")
    for e in errors:
        print(f"   ✗  {e}")
    sys.exit(1)
else:
    print("✅ READY TO PUSH")
