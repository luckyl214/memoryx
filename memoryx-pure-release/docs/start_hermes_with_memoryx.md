# Start Hermes with MemoryX Semantic Gate

使用以下命令启动 Hermes，P13 语义运行时完整性检查会在 Hermes 启动前自动运行：

```bash
${HOME}/bin/hermes-memoryx
```

## 检查内容

P13 gate 验证以下 8 条硬不变量：

| # | 检查项 | 说明 |
|---|--------|------|
| 1 | Canonical DB path | 唯一生产数据库路径 `${HOME}./data/memoryx.db` |
| 2 | WAL mode | 开启 Write-Ahead Logging |
| 3 | Required tables | 所有必需表存在（56 个） |
| 4 | DB fingerprint | 运行时 DB 唯一标识（runtime_identity 表） |
| 5 | Embedding coverage | 覆盖率 ≥ 95%（当前 100%） |
| 6 | Non-zero vectors | 无坏向量，维度一致（4096） |
| 7 | Maintenance freshness | maintenance 审计记录新鲜 |
| 8 | Systemd units | service + timer 均为 active |

## 启动流程

```
/hermes-memoryx
  │
  ├─→ P13 Semantic Integrity Gate
  │     ├─ ✅ 全部通过 → "MemoryX Semantic Retrieval Online ✅"
  │     │                    → 启动 Hermes
  │     │
  │     └─ ❌ 任一失败 → 输出失败详情
  │                        → 阻止 Hermes 启动
  │                        → 运行修复命令
  │
  └─→ Hermes Chat
        ├─ MemoryX 认知脊柱在线
        ├─ 语义检索在线
        └─ 进入学习模式
```

## 如果 Gate 失败

检查输出中的具体失败项，常见修复命令：

```bash
# 修复 embedding
cd ${HOME}/memoryx
MEMORYX_DB_PATH=data/memoryx.db .venv/bin/python tools/backfill_embeddings_OPENAI_COMPATIBLE.py --include-conversations

# 手动刷新 maintenance
sudo systemctl start memoryx-maintenance.service

# 重新验证
MEMORYX_DB_PATH=data/memoryx.db python tools/memoryx_semantic_integrity_gate.py --include-conversations --check-systemd
```

## 手动验证（不启动 Hermes）

```bash
cd ${HOME}/memoryx
MEMORYX_DB_PATH=data/memoryx.db python tools/memoryx_semantic_integrity_gate.py --include-conversations --check-systemd
```

## 维护

- **Embedding backfill**: 由 `memoryx-maintenance.timer` 每 30 分钟自动运行
- **手动触发**: `sudo systemctl start memoryx-maintenance.service`
- **查看日志**: `journalctl -u memoryx-maintenance.service -n 100 --no-pager`

## 长期方案（可选）

当前使用 wrapper script（推荐，简单确定）。后续如需更优雅集成，可创建 Python plugin：

```yaml
# ~/.hermes/plugins/memoryx_p13_gate/plugin.yaml
name: memoryx-p13-gate
version: 1.0.0
entry: plugin.py
```

```python
# plugin.py
def register(ctx):
    async def on_session_start(**kwargs):
        # 运行 P13 gate，失败则 block
        ...
    ctx.register_hook("on_session_start", on_session_start)
```

> **注意**: 不要将 P13 gate 放入 `pre_response` 或每次 tool loop，那会导致每轮都跑、可能触发 agent 自修复、进入工具调用循环。P13 是会话级准入检查，只应在启动时或 session start 跑一次。

## 版本标签

```
baseline/p13-semantic-runtime-integrity-green
```

---

**MemoryX Ready: Hermes Cognitive Spine Online**
**MemoryX Semantic Retrieval Online**
**P13 Semantic Runtime Integrity Gate Passed**
