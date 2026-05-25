# MemoryX Release Tracks

## Track A: v1.1.0 Stable First Release

`v1.1.0-rc1` is the frozen release-candidate line for the first stable open-source release.

**Scope:**
- P0 schema recovery
- Cognitive production gate (FATAL=0, ERROR=0)
- Open-source hardening (Docker, REST, /live /ready)
- Observability + E2E gate (Prometheus, trace-id, 6 E2E tests)
- Performance/data model hardening (benchmarks, SQLite retry, vector deprecation)
- Release engineering (wheel, sdist, SBOM, checksums)

**Released:** [v1.1.0-rc1 on GitHub](https://github.com/YOUR_GITHUB_USERNAME/memoryx/releases/tag/v1.1.0-rc1)

**During RC soak, ONLY allowed:**
- Installation fixes
- Documentation fixes
- Security fixes
- Release asset / checksum / SBOM fixes
- Blocking bug fixes

**NOT allowed:**
- New features
- Schema expansion
- P11 / P12 / P12.1 merges
- Hermes behavior changes
- Benchmark threshold relaxation

**Target:** `v1.1.0`

---

## Track B: v1.2.0 Hermes Cognitive Spine

The P11/P12/P12.1 line is reserved for `v1.2.0-rc1`.

**Included baselines:**
- `baseline/p11-cognitive-guard-narrative-green`
- `baseline/p12-1-lifespan-hermes-llm-safety-green`
- `baseline/hermes-smoke-p12-1-green`

**Capabilities:**
- Claim verification against MemoryX evidence
- LESSON policy enforcement (warn/block/require_dry_run)
- Narrative reflection (task/opinion/lesson/claim synthesis)
- FastAPI lifespan / app factory
- LLM firewall (prompt injection, tool safety, output guard)
- Hermes bridge / provider

**Verified Hermes smoke:**
| Hook | Return | Status |
|------|--------|--------|
| `on_user_message` | `context_block` | ✅ |
| `on_tool_call` | `require_dry_run` | ✅ |
| `on_assistant_response` | `warn` | ✅ |
| `on_session_end` | narrative reflection | ✅ |

**Target:** `v1.2.0-rc1`

---

## Full Tag Chain

```
baseline/p0-cognitive-recovered
baseline/cognitive-production-gate-green
baseline/open-source-hardening-green
baseline/p8-observability-e2e-green
baseline/p9-performance-data-hardening-green
baseline/p11-cognitive-guard-narrative-green
baseline/p12-1-lifespan-hermes-llm-safety-green
baseline/hermes-smoke-p12-1-green
```
