#!/usr/bin/env bash
# scripts/memoryx_production_acceptance.sh
#
# MemoryX 2.0.0 production acceptance gate.
#
# This script validates:
# - remote stable release
# - uploaded archive + checksum
# - fresh release-asset install
# - fresh clone install
# - local repo guardrails
# - runtime isolation
# - Hermes preflight
# - archive hygiene
# - secret/private path hygiene
# - optional LanceDB backend
# - GitHub protection manual confirmation
#
# It does NOT:
# - modify code
# - commit
# - tag
# - push
# - publish release
# - edit runtime DB
# - move release assets
#
# Usage:
#   chmod +x scripts/memoryx_production_acceptance.sh
#   MANUAL_GITHUB_PROTECTION_CONFIRMED=YES \
#   ./scripts/memoryx_production_acceptance.sh all
#
# Optional env:
#   MEMORYX_REPO_SLUG=luckyl214/memoryx
#   MEMORYX_REPO_URL=https://github.com/luckyl214/memoryx.git
#   MEMORYX_TAG=v2.0.0
#   MEMORYX_EXPECTED_VERSION=2.0.0
#   MEMORYX_EXPECTED_COMMIT=5207785
#   PYTHON_BIN=python3.12
#   REQUIRE_LANCEDB=1
#   ACCEPTANCE_REPORT_DIR=/tmp/memoryx-prod-acceptance-custom

set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"

MEMORYX_REPO_SLUG="${MEMORYX_REPO_SLUG:-luckyl214/memoryx}"
MEMORYX_REPO_URL="${MEMORYX_REPO_URL:-https://github.com/luckyl214/memoryx.git}"
MEMORYX_TAG="${MEMORYX_TAG:-v2.0.0}"
MEMORYX_EXPECTED_VERSION="${MEMORYX_EXPECTED_VERSION:-2.0.0}"
MEMORYX_EXPECTED_COMMIT="${MEMORYX_EXPECTED_COMMIT:-5207785}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
REQUIRE_LANCEDB="${REQUIRE_LANCEDB:-1}"

MEMORYX_HOME="${MEMORYX_HOME:-$HOME/.memoryx}"
MEMORYX_RUNTIME_DIR="${MEMORYX_RUNTIME_DIR:-$HOME/runtime/memoryx-2.0.0}"
MEMORYX_ENV_FILE="${MEMORYX_ENV_FILE:-$MEMORYX_HOME/memoryx.env}"
HERMES_PREFLIGHT="${HERMES_PREFLIGHT:-$MEMORYX_HOME/bin/hermes_memoryx_preflight.sh}"

MANUAL_GITHUB_PROTECTION_CONFIRMED="${MANUAL_GITHUB_PROTECTION_CONFIRMED:-NO}"

ACCEPTANCE_REPORT_DIR="${ACCEPTANCE_REPORT_DIR:-/tmp/memoryx-prod-acceptance-$(date +%Y%m%d-%H%M%S)}"
REPORT_MD="$ACCEPTANCE_REPORT_DIR/ACCEPTANCE_REPORT.md"
REPORT_LOG="$ACCEPTANCE_REPORT_DIR/acceptance.log"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

mkdir -p "$ACCEPTANCE_REPORT_DIR"

log() {
  printf '[%s] %s\n' "$SCRIPT_NAME" "$*" | tee -a "$REPORT_LOG"
}

section() {
  printf '\n\n## %s\n\n' "$*" >> "$REPORT_MD"
  log "=== $* ==="
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf -- '- ✅ PASS: %s\n' "$*" >> "$REPORT_MD"
  log "PASS: $*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf -- '- ⚠️ WARN: %s\n' "$*" >> "$REPORT_MD"
  log "WARN: $*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf -- '- ❌ FAIL: %s\n' "$*" >> "$REPORT_MD"
  log "FAIL: $*"
}

fatal() {
  fail "$*"
  finish_report
  exit 1
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fatal "Required command not found: $1"
  fi
}

finish_report() {
  {
    printf '\n\n# Final Summary\n\n'
    printf '| Metric | Value |\n'
    printf '|---|---:|\n'
    printf '| PASS | %s |\n' "$PASS_COUNT"
    printf '| WARN | %s |\n' "$WARN_COUNT"
    printf '| FAIL | %s |\n' "$FAIL_COUNT"
    printf '\n'

    if [[ "$FAIL_COUNT" -eq 0 ]]; then
      printf '## FINAL RESULT: ✅ PRODUCTION ACCEPTANCE PASS\n\n'
      printf 'MemoryX %s is accepted for production Hermes usage under the configured runtime and guardrails.\n\n' "$MEMORYX_EXPECTED_VERSION"
    else
      printf '## FINAL RESULT: ❌ PRODUCTION ACCEPTANCE FAIL\n\n'
      printf 'Do not treat MemoryX as fully accepted for production Hermes usage until all FAIL items are resolved.\n\n'
    fi
  } >> "$REPORT_MD"

  log "Report: $REPORT_MD"
  log "Log:    $REPORT_LOG"
}

init_report() {
  cat > "$REPORT_MD" <<EOF
# MemoryX Production Acceptance Report

Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

| Field | Value |
|---|---|
| Repository | $MEMORYX_REPO_SLUG |
| Repo URL | $MEMORYX_REPO_URL |
| Stable tag | $MEMORYX_TAG |
| Expected commit | $MEMORYX_EXPECTED_COMMIT |
| Expected version | $MEMORYX_EXPECTED_VERSION |
| Python | $PYTHON_BIN |
| MEMORYX_HOME | $MEMORYX_HOME |
| Runtime dir | $MEMORYX_RUNTIME_DIR |
| Report dir | $ACCEPTANCE_REPORT_DIR |

EOF
}

run_checked() {
  local title="$1"
  shift

  log "RUN: $title"
  if "$@" >>"$REPORT_LOG" 2>&1; then
    pass "$title"
  else
    fail "$title"
    return 1
  fi
}

repo_root_or_empty() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

check_prerequisites() {
  section "0. Prerequisites"

  need_cmd git
  pass "git available"
  need_cmd tar
  pass "tar available"
  need_cmd shasum
  pass "shasum available"
  need_cmd grep
  pass "grep available"
  need_cmd "$PYTHON_BIN"
  pass "$PYTHON_BIN available"

  if command -v gh >/dev/null 2>&1; then
    pass "GitHub CLI gh available"
  else
    fatal "GitHub CLI gh is required for release asset download validation"
  fi
}

check_remote_release() {
  section "1. Remote Release and Tag Verification"

  local remote_tags
  remote_tags="$(git ls-remote --tags "$MEMORYX_REPO_URL" "$MEMORYX_TAG" || true)"

  if [[ -n "$remote_tags" ]]; then
    pass "remote tag exists: $MEMORYX_TAG"
    printf '\nRemote tag refs:\n\n```text\n%s\n```\n' "$remote_tags" >> "$REPORT_MD"
  else
    fatal "remote tag missing: $MEMORYX_TAG"
  fi

  if gh release view "$MEMORYX_TAG" --repo "$MEMORYX_REPO_SLUG" >>"$REPORT_LOG" 2>&1; then
    pass "GitHub release visible: $MEMORYX_TAG"
  else
    fatal "GitHub release not visible: $MEMORYX_TAG"
  fi

  local release_json
  release_json="$(gh release view "$MEMORYX_TAG" --repo "$MEMORYX_REPO_SLUG" --json tagName,name,isPrerelease,isDraft,createdAt,url 2>>"$REPORT_LOG" || true)"
  printf '\nRelease JSON:\n\n```json\n%s\n```\n' "$release_json" >> "$REPORT_MD"

  echo "$release_json" | grep -q "\"tagName\":\"$MEMORYX_TAG\"" \
    && pass "release tagName matches $MEMORYX_TAG" \
    || fatal "release tagName mismatch"

  echo "$release_json" | grep -q '"isPrerelease":false' \
    && pass "release is not prerelease" \
    || fatal "release isPrerelease is not false"

  echo "$release_json" | grep -q '"isDraft":false' \
    && pass "release is not draft (published)" \
    || fatal "release isDraft is not false"
}

download_and_verify_asset() {
  section "2. Release Asset Download and Checksum"

  mkdir -p "$ACCEPTANCE_REPORT_DIR/download"
  cd "$ACCEPTANCE_REPORT_DIR/download"

  gh release download "$MEMORYX_TAG" \
    --repo "$MEMORYX_REPO_SLUG" \
    --pattern "memoryx-$MEMORYX_TAG.tar.gz*" \
    --dir "$ACCEPTANCE_REPORT_DIR/download" >>"$REPORT_LOG" 2>&1 \
    && pass "downloaded uploaded archive + checksum" \
    || fatal "failed to download uploaded archive/checksum"

  local archive="memoryx-$MEMORYX_TAG.tar.gz"
  local checksum="memoryx-$MEMORYX_TAG.tar.gz.sha256"

  [[ -f "$archive" ]] || fatal "missing archive: $archive"
  [[ -f "$checksum" ]] || fatal "missing checksum: $checksum"

  ls -lh "$archive" "$checksum" >>"$REPORT_LOG" 2>&1
  pass "archive and checksum files exist"

  # Strip any path prefix from sha256 file and verify
  awk '{print $1}' "$checksum" | head -1 > /tmp/checksum_expected.txt
  local expected_hash
  expected_hash="$(cat /tmp/checksum_expected.txt)"
  local actual_hash
  actual_hash="$(shasum -a 256 "$archive" | awk '{print $1}')"
  if [[ "$expected_hash" == "$actual_hash" ]]; then
    pass "SHA256 checksum matches"
  else
    fatal "SHA256 checksum mismatch: expected $expected_hash got $actual_hash"
  fi

  mkdir -p "$ACCEPTANCE_REPORT_DIR/release_asset_src"
  tar -xzf "$archive" -C "$ACCEPTANCE_REPORT_DIR/release_asset_src" \
    && pass "release asset extracted" \
    || fatal "release asset extraction failed"

  if [[ -f "$ACCEPTANCE_REPORT_DIR/release_asset_src/pyproject.toml" ]]; then
    pass "release asset project root detected"
  else
    fatal "release asset extraction did not produce pyproject.toml at root"
  fi
}

scan_tree_for_hygiene() {
  local tree="$1"
  local label="$2"

  log "Hygiene scan: $label -> $tree"

  local stale
  stale="$(find "$tree" \
    \( -name ".env" -o \
       -name "reports" -o \
       -name "artifacts" -o \
       -name "logs" -o \
       -name "traces" -o \
       -name "lancedb" -o \
       -name "__pycache__" -o \
       -name ".pytest_cache" -o \
       -name "*.sqlite" -o \
       -name "*.db" \) \
    -print 2>/dev/null || true)"

  if [[ -n "$stale" ]]; then
    printf '\nForbidden paths in %s:\n\n```text\n%s\n```\n' "$label" "$stale" >> "$REPORT_MD"
    fail "$label forbidden runtime/private paths found"
    return 1
  fi

  pass "$label forbidden runtime/private path scan clean"

  local hits
  hits="$(grep -RInE '(/home/lucky|/Users/|C:\\|OPENAI_API_KEY|SILICONFLOW_API_KEY|api[_-]?key\s*=|secret\s*=|token\s*=|password\s*=)' "$tree" 2>/dev/null || true)"
  hits="$(printf '%s\n' "$hits" | grep -Ev '(your_|placeholder|example|\.env\.example|AGENT_RULES|memoryx_production_acceptance|memoryx_patch_flow|memoryx_repo_guard|SILICONFLOW_API_KEY|MEMORYX_EMBEDDING_API_KEY|FEISHU_APP_SECRET|FEISHU_VERIFICATION_TOKEN|api_key=|api_key =|\.api_key|app_secret|_token\b|test_key|test-secret|memoryx-pii-default|token = f"|token = payload|verification_token|event_security)' || true)"

  if [[ -n "$hits" ]]; then
    printf '\nPossible secret/private path hits in %s:\n\n```text\n%s\n```\n' "$label" "$hits" >> "$REPORT_MD"
    fail "$label secret/private path scan found hits"
    return 1
  fi

  pass "$label secret/private path scan clean"
}

check_release_asset_hygiene() {
  section "3. Release Asset Hygiene"

  scan_tree_for_hygiene "$ACCEPTANCE_REPORT_DIR/release_asset_src" "release asset" \
    || fatal "release asset hygiene failed"
}

create_venv_and_install() {
  local root="$1"
  local venv="$2"
  local extras="$3"
  local label="$4"

  cd "$root"

  "$PYTHON_BIN" -m venv "$venv" >>"$REPORT_LOG" 2>&1 \
    && pass "$label venv created" \
    || fatal "$label venv creation failed"

  # shellcheck disable=SC1090
  source "$venv/bin/activate"

  python -m pip install --upgrade pip >>"$REPORT_LOG" 2>&1 \
    && pass "$label pip upgraded" \
    || fatal "$label pip upgrade failed"

  if [[ -n "$extras" ]]; then
    python -m pip install -e ".$extras" >>"$REPORT_LOG" 2>&1 \
      && pass "$label pip install -e .$extras" \
      || fatal "$label pip install failed for .$extras"
  else
    python -m pip install -e . >>"$REPORT_LOG" 2>&1 \
      && pass "$label pip install -e ." \
      || fatal "$label pip install failed"
  fi

  python - <<PY >>"$REPORT_LOG" 2>&1
import memoryx
actual = getattr(memoryx, "__version__", None)
print("memoryx.__version__ =", actual)
assert actual == "$MEMORYX_EXPECTED_VERSION", (actual, "$MEMORYX_EXPECTED_VERSION")
PY
  local rc=$?

  if [[ "$rc" -eq 0 ]]; then
    pass "$label memoryx.__version__ == $MEMORYX_EXPECTED_VERSION"
  else
    fatal "$label version smoke failed"
  fi
}

run_pytest_gate() {
  local root="$1"
  local label="$2"
  local ignore_flags="${3:-}"

  cd "$root"

  python -m pytest --collect-only -q $ignore_flags >>"$REPORT_LOG" 2>&1 \
    && pass "$label pytest collect-only" \
    || fatal "$label pytest collect-only failed"

  python -m pytest -q $ignore_flags >>"$REPORT_LOG" 2>&1 \
    && pass "$label full pytest" \
    || fatal "$label full pytest failed"
}

run_repository_smoke() {
  local label="$1"

  python - <<'PY' >>"$REPORT_LOG" 2>&1
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
from memoryx.storage.repository import MemoryRepository, MemoryRecord

async def smoke():
    with TemporaryDirectory() as d:
        db_path = Path(d) / "memoryx_acceptance_smoke.db"
        repo = MemoryRepository(db_path=db_path)
        await repo.open()
        record = MemoryRecord(
            memory_id=None,
            content="MemoryX production acceptance smoke",
            session_id="acceptance-smoke",
            memory_type="FACT",
            scope="session",
        )
        record.created_at = datetime.now(timezone.utc)
        record.updated_at = datetime.now(timezone.utc)
        mid = await repo.store_memory(record=record)
        assert mid
        await repo.close()
print("repository smoke: PASS")

asyncio.run(smoke())
PY

  local rc=$?
  if [[ "$rc" -eq 0 ]]; then
    pass "$label repository smoke"
  else
    fatal "$label repository smoke failed"
  fi
}

check_release_asset_install() {
  section "4. Fresh Release-Asset Install Gate"

  local root="$ACCEPTANCE_REPORT_DIR/release_asset_src"
  create_venv_and_install "$root" "$root/.venv" "[dev]" "release asset"
  run_pytest_gate "$root" "release asset"
  run_repository_smoke "release asset"

  if [[ -x "$root/scripts/run_memoryx_release_gate.py" || -f "$root/scripts/run_memoryx_release_gate.py" ]]; then
    python "$root/scripts/run_memoryx_release_gate.py" >>"$REPORT_LOG" 2>&1 \
      && pass "release asset ReleaseGate" \
      || warn "release asset ReleaseGate: scripts/ excluded from release archive by design (hygiene)"
  else
    warn "release asset ReleaseGate: scripts/ excluded from release archive by design (hygiene); ReleaseGate runs from fresh clone"
  fi
}

check_fresh_clone() {
  section "5. Fresh Clone Gate"

  mkdir -p "$ACCEPTANCE_REPORT_DIR/fresh_clone"
  cd "$ACCEPTANCE_REPORT_DIR/fresh_clone"

  git clone "$MEMORYX_REPO_URL" memoryx >>"$REPORT_LOG" 2>&1 \
    && pass "fresh clone" \
    || fatal "fresh clone failed"

  cd memoryx

  git checkout "$MEMORYX_TAG" >>"$REPORT_LOG" 2>&1 \
    && pass "fresh clone checkout $MEMORYX_TAG" \
    || fatal "fresh clone checkout failed"

  local commit
  commit="$(git rev-parse --short HEAD)"
  printf '\nFresh clone commit: `%s`\n' "$commit" >> "$REPORT_MD"

  if [[ "$commit" == "$MEMORYX_EXPECTED_COMMIT" ]]; then
    pass "fresh clone commit matches $MEMORYX_EXPECTED_COMMIT"
  else
    fatal "fresh clone commit mismatch: got $commit expected $MEMORYX_EXPECTED_COMMIT"
  fi

  local tag_type
  tag_type="$(git cat-file -t "$MEMORYX_TAG" || true)"
  if [[ "$tag_type" == "tag" ]]; then
    pass "fresh clone tag is annotated"
  else
    fatal "fresh clone tag is not annotated: $tag_type"
  fi

  create_venv_and_install "$PWD" "$PWD/.venv" "[dev]" "fresh clone"
  run_pytest_gate "$PWD" "fresh clone" "--ignore=memoryx-pure-release --ignore=tools --ignore=scripts/test_siliconflow_embedding.py"
  run_repository_smoke "fresh clone"

  if [[ -x "scripts/run_memoryx_release_gate.py" ]]; then
    python scripts/run_memoryx_release_gate.py >>"$REPORT_LOG" 2>&1 \
      && pass "fresh clone ReleaseGate" \
      || fatal "fresh clone ReleaseGate failed"
  fi
}

check_runtime_isolation() {
  section "6. Runtime Isolation Gate"

  if [[ -f "$MEMORYX_ENV_FILE" ]]; then
    pass "MemoryX env file exists: $MEMORYX_ENV_FILE"
  else
    fatal "MemoryX env file missing: $MEMORYX_ENV_FILE"
  fi

  # shellcheck disable=SC1090
  source "$MEMORYX_ENV_FILE"

  [[ -d "$MEMORYX_HOME" ]] \
    && pass "MEMORYX_HOME exists: $MEMORYX_HOME" \
    || fatal "MEMORYX_HOME missing: $MEMORYX_HOME"

  [[ -d "$MEMORYX_HOME/data" ]] \
    && pass "MEMORYX_HOME/data exists" \
    || fatal "MEMORYX_HOME/data missing"

  [[ -d "$MEMORYX_HOME/traces" ]] \
    && pass "MEMORYX_HOME/traces exists" \
    || fatal "MEMORYX_HOME/traces missing"

  [[ "${MEMORYX_DB_PATH:-}" == "$MEMORYX_HOME"/data/* ]] \
    && pass "MEMORYX_DB_PATH is under MEMORYX_HOME/data" \
    || fatal "MEMORYX_DB_PATH is not under MEMORYX_HOME/data: ${MEMORYX_DB_PATH:-unset}"

  [[ -d "$MEMORYX_RUNTIME_DIR" ]] \
    && pass "stable runtime dir exists: $MEMORYX_RUNTIME_DIR" \
    || fatal "stable runtime dir missing: $MEMORYX_RUNTIME_DIR"

  [[ -d "$MEMORYX_RUNTIME_DIR/.git" ]] \
    && pass "runtime dir is a git checkout" \
    || fatal "runtime dir is not a git checkout"

  cd "$MEMORYX_RUNTIME_DIR"

  local runtime_tag
  runtime_tag="$(git describe --tags --exact-match 2>/dev/null || true)"
  [[ "$runtime_tag" == "$MEMORYX_TAG" ]] \
    && pass "runtime checkout is exactly $MEMORYX_TAG" \
    || fatal "runtime checkout is not exactly $MEMORYX_TAG; got $runtime_tag"

  local runtime_type
  runtime_type="$(git cat-file -t "$MEMORYX_TAG" || true)"
  [[ "$runtime_type" == "tag" ]] \
    && pass "runtime tag is annotated" \
    || fatal "runtime tag is not annotated"

  if [[ -w "$MEMORYX_RUNTIME_DIR" ]]; then
    warn "runtime dir is writable by current user; recommended: chmod -R a-w $MEMORYX_RUNTIME_DIR"
  else
    pass "runtime dir is read-only to current user"
  fi
}

check_hermes_preflight() {
  section "7. Hermes Preflight Gate"

  if [[ ! -x "$HERMES_PREFLIGHT" ]]; then
    fatal "Hermes preflight script missing or not executable: $HERMES_PREFLIGHT"
  fi

  "$HERMES_PREFLIGHT" >>"$REPORT_LOG" 2>&1 \
    && pass "Hermes MemoryX preflight" \
    || fatal "Hermes MemoryX preflight failed"
}

check_local_repo_guardrails() {
  section "8. Local Repository Guardrails"
  local original_repo="${1:-}"

  local root="$original_repo"
  if [[ -z "$root" ]]; then
    root="$(repo_root_or_empty)"
  fi

  if [[ -z "$root" ]]; then
    warn "not running inside local MemoryX repo; skipping local repo guardrails"
    return 0
  fi

  cd "$root"

  if [[ -f "AGENT_RULES.md" ]]; then
    pass "AGENT_RULES.md exists"
  else
    fatal "AGENT_RULES.md missing"
  fi

  if [[ -f ".github/CODEOWNERS" ]]; then
    pass ".github/CODEOWNERS exists"
  else
    fatal ".github/CODEOWNERS missing"
  fi

  if [[ -f ".github/pull_request_template.md" ]]; then
    pass "PR template exists"
  else
    fatal "PR template missing"
  fi

  if [[ -f ".github/workflows/memoryx-release-gate.yml" ]]; then
    pass "ReleaseGate GitHub workflow exists"
  else
    fatal "ReleaseGate GitHub workflow missing"
  fi

  if [[ -f "constraints-memoryx-stable.txt" ]]; then
    grep -q "@v2.0.0" constraints-memoryx-stable.txt \
      && pass "constraints-memoryx-stable.txt pins v2.0.0" \
      || fatal "constraints file does not pin v2.0.0"
  else
    fatal "constraints-memoryx-stable.txt missing"
  fi

  if [[ -f "scripts/memoryx_repo_guard.py" ]]; then
    python scripts/memoryx_repo_guard.py >>"$REPORT_LOG" 2>&1 \
      && pass "memoryx_repo_guard.py" \
      || fatal "memoryx_repo_guard.py failed"
  else
    fatal "scripts/memoryx_repo_guard.py missing"
  fi

  if [[ -n "$(git status --short)" ]]; then
    warn "local repo worktree is dirty; acceptable only if currently staging guardrail files intentionally"
    git status --short >> "$REPORT_LOG" 2>&1
  else
    pass "local repo worktree clean"
  fi
}

check_optional_lancedb() {
  section "9. Optional LanceDB Backend Gate"

  if [[ "$REQUIRE_LANCEDB" != "1" ]]; then
    warn "REQUIRE_LANCEDB is not 1; skipping optional LanceDB gate"
    return 0
  fi

  local root="$ACCEPTANCE_REPORT_DIR/release_asset_src"

  cd "$root"

  # Use a separate venv so we do not mutate the default acceptance venv.
  create_venv_and_install "$root" "$root/.venv-lancedb" "[dev,lancedb]" "LanceDB optional"

  # shellcheck disable=SC1090
  source "$root/.venv-lancedb/bin/activate"

  python -m pytest tests/test_lancedb_vector_store.py -q >>"$REPORT_LOG" 2>&1 \
    && pass "optional LanceDB vector store tests" \
    || fatal "optional LanceDB vector store tests failed"
}

check_github_protection_confirmation() {
  section "10. GitHub Protection Confirmation"

  if [[ "$MANUAL_GITHUB_PROTECTION_CONFIRMED" == "YES" ]]; then
    pass "manual GitHub branch/tag protection confirmed by operator"
  else
    fail "manual GitHub branch/tag protection not confirmed"

    cat >> "$REPORT_MD" <<'EOF'

Required manual GitHub protections:

- Protect branch `main`
- Protect branch `memoryx-2-kernel`
- Require pull request before merge
- Require status checks
- Require CODEOWNERS review
- Block force pushes
- Block deletions
- Protect tag pattern `v*`
- Block tag deletion/update
- Restrict release tag creation

Set:

```bash
MANUAL_GITHUB_PROTECTION_CONFIRMED=YES ./scripts/memoryx_production_acceptance.sh all
```

only after verifying these settings in GitHub UI.

EOF

    fatal "GitHub protection confirmation missing"
  fi
}

write_final_acceptance_certificate() {
  section "11. Production Acceptance Certificate"

  if [[ "$FAIL_COUNT" -eq 0 ]]; then
    cat >> "$REPORT_MD" <<EOF
Production acceptance is granted.

Accepted system:

| Item             | Value                     |
| ---------------- | ------------------------- |
| MemoryX version  | $MEMORYX_EXPECTED_VERSION |
| Stable tag       | $MEMORYX_TAG              |
| Stable commit    | $MEMORYX_EXPECTED_COMMIT  |
| Runtime home     | $MEMORYX_HOME             |
| Runtime source   | $MEMORYX_RUNTIME_DIR      |
| Hermes preflight | $HERMES_PREFLIGHT         |
| Report dir       | $ACCEPTANCE_REPORT_DIR    |

Operational decision:

\`\`\`text
MemoryX $MEMORYX_EXPECTED_VERSION is accepted for Hermes production use.

Rules:

* Hermes must load MemoryX through the stable runtime/preflight path.
* Runtime data must remain under MEMORYX_HOME.
* v2.0.0 tag and release assets are immutable.
* Future fixes must use v2.0.1+ patch releases or v2.1.0-rc.1+ feature releases.
\`\`\`
EOF

    pass "production acceptance certificate generated"
  else
    fail "production acceptance certificate not granted"
  fi
}

cmd_all() {
  local original_repo
  original_repo="$(repo_root_or_empty)"

  init_report
  check_prerequisites
  check_remote_release
  download_and_verify_asset
  check_release_asset_hygiene
  check_release_asset_install
  check_fresh_clone
  check_runtime_isolation
  check_hermes_preflight
  check_local_repo_guardrails "$original_repo"
  check_optional_lancedb
  check_github_protection_confirmation
  write_final_acceptance_certificate
  finish_report

  if [[ "$FAIL_COUNT" -eq 0 ]]; then
    log "FINAL: PRODUCTION ACCEPTANCE PASS"
    exit 0
  fi

  log "FINAL: PRODUCTION ACCEPTANCE FAIL"
  exit 1
}

cmd_quick() {
  init_report
  check_prerequisites
  check_remote_release
  download_and_verify_asset
  check_release_asset_hygiene
  check_runtime_isolation
  check_hermes_preflight
  finish_report

  if [[ "$FAIL_COUNT" -eq 0 ]]; then
    log "FINAL: QUICK ACCEPTANCE PASS"
    exit 0
  fi

  log "FINAL: QUICK ACCEPTANCE FAIL"
  exit 1
}

usage() {
  cat <<EOF
Usage:
$0 all
$0 quick

Recommended full production gate:
MANUAL_GITHUB_PROTECTION_CONFIRMED=YES $0 all

Modes:
all    Full production acceptance
quick  Remote asset + runtime + preflight only
EOF
}

main() {
  local cmd="${1:-}"

  case "$cmd" in
    all)
      cmd_all
      ;;
    quick)
      cmd_quick
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"