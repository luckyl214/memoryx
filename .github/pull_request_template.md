## MemoryX Change Gate

### Batch

- [ ] hotfix
- [ ] patch
- [ ] docs-only
- [ ] hygiene-only
- [ ] feature / minor
- [ ] other:

### Problem

Describe the exact failure or need.

### Root cause

Describe the verified root cause. Do not guess.

### Scope

Allowed files:

-

Forbidden files:

-

### Change summary

-

### Tests

Paste exact results:

```text
python -m pytest --collect-only -q
python -m pytest -q
python scripts/run_memoryx_release_gate.py
```

### Archive hygiene

Required if packaging/release/docs/runtime paths changed.

```text
archive hygiene:
secret scan:
private path scan:
```

### Risk

*

### Rollback

*

### Release impact

* [ ] no release needed
* [ ] patch v2.0.x candidate
* [ ] minor v2.1.0-rc.1 candidate
