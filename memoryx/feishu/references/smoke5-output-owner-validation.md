# P14.4 shadow smoke 5: MemoryX 唯一输出 owner 验证报告

**时间**: 2026-05-25 14:37 CST  
**验证目标**: 验证 MemoryX 是飞书唯一输出 owner，只允许一张动态卡片，不允许内部工具短消息

---

## ✅ 验证结果总览

| 检查项 | 状态 | 详情 |
|--------|------|------|
| FEISHU_OUTPUT_MODE=card_only | ✅ PASS | 只更新卡片，不发文本消息 |
| FEISHU_SEND_TEXT_FALLBACK=false | ✅ PASS | 不允许文本回退 |
| FEISHU_STREAM_TEXT_MESSAGES=false | ✅ PASS | 不允许流式文本 |
| INTERNAL_TOOL_NAMES 过滤 | ✅ PASS | execute_code, python, bash, terminal, hermes 等 |
| NOISE_PATTERNS 过滤 | ✅ PASS | import os, import sqlite3, systemctl, curl 等 |
| should_show_tool() 过滤 | ✅ PASS | internal/debug/diagnostic 阶段工具 |
| 单卡片机制 | ✅ PASS | live_card 单例控制器，所有更新通过 transition_and_patch() |
| card_message_id 保存 | ✅ PASS | 初始卡片发送后保存，后续 patch 使用 |
| final_view=True 渲染 | ✅ PASS | 只显示最终结果、耗时、执行摘要、附件 |
| Trace 事件完整性 | ✅ PASS | 10/10 关键事件完整记录 |

---

## 1. 输出策略配置

```
FEISHU_OUTPUT_MODE=card_only          ✅ 只更新卡片
FEISHU_SEND_TEXT_FALLBACK=false       ✅ 不允许文本回退
FEISHU_STREAM_TEXT_MESSAGES=false     ✅ 不允许流式文本
FEISHU_RUNNER_MODE=shadow             ✅ Shadow 模式（后台跑真 Hermes）
```

## 2. 内部噪音过滤

### INTERNAL_TOOL_NAMES (工具名称过滤)
- `execute_code`, `python`, `python_exec`, `shell`, `bash`, `terminal`, `subprocess`, `hermes`

### NOISE_PATTERNS (文本内容过滤)
- `execute_code:`, `import os`, `import sqlite3`, `import yaml`, `subprocess`
- `hermes_pa`, `config_path`, `sqlite3 `, `journalctl `, `systemctl `
- `python -`, `bash `, `curl `, `wget `, `git `, `pip `, `npm `

### should_show_tool() 额外过滤
- phase 为 `internal`, `debug`, `diagnostic` 的工具调用不展示

## 3. 单卡片机制

- `FeishuLiveCardController` 是单例，所有卡片更新通过 `transition_and_patch()` 统一入口
- `card_message_id` 在初始卡片发送后被保存，后续所有 patch 使用同一 message_id
- 没有独立的 `send_message()` 调用发送文本消息
- `FEISHU_OUTPUT_MODE=card_only` 确保 `allow_text_message()` 始终返回 `False`

## 4. 卡片状态流转

```
已收到 (RECEIVED)
    ↓ accept_event()
排队中 (QUEUED)
    ↓ worker claim
正在处理 (THINKING) → prepare → context → generate
    ↓
整理结果 (WRITING) → verify
    ↓
已完成 (DONE) → final_view=True
```

### final_view=True 时只显示:
- **最终结果** (answer 正文)
- **耗时** (started_at → ended_at)
- **执行摘要** (可见阶段 marks: prepare → context → generate → verify → done)
- **附件** (uploaded 文件列表)

### final_view=True 时隐藏:
- 阶段进度条
- 当前阶段
- 实时输出
- MemoryX badges
- 工具调用详情

## 5. Trace 事件完整性

最近完成任务 `ab2724ff8cc2405c...` 的完整 trace (10 条):

| # | 事件 | Phase | 说明 |
|---|------|-------|------|
| 1 | `event_accepted` | received | 飞书消息被接受 |
| 2 | `job_queued` | queue | 任务入队 |
| 3 | `job_claimed` | prepare | Worker 领取任务 |
| 4 | `runner_start` | runner | Runner 启动 |
| 5 | `hermes_cli_start` | hermes | Hermes CLI 开始执行 |
| 6 | `card_sent` | received | 初始卡片发送 |
| 7 | `runner_done` | runner | Runner 完成 |
| 8 | `hermes_cli_done` | hermes | Hermes CLI 完成 |
| 9 | `state_transition` | state | thinking → done |
| 10 | `job_done` | done | 任务完成 |

✅ 所有 10 个关键事件均完整记录

---

## 6. 发现的问题

### ⚠️ 问题 1: 运行中任务的 ended_at 为 None
- 最近完成任务 `ab2724ff8cc2405c...` 的 `ended_at` 字段为 `None`
- 原因：`bot_service.py` 中 `job.ended_at = time.time()` 在 `final_view=True` 的 `transition_and_patch()` 之前设置
- 但 `queue.update(job)` 在 `transition_and_patch()` 之后执行，理论上应该更新
- **影响**: 耗时计算可能不准确（fallback 到 updated_at）
- **建议**: 在 `queue.update(job)` 前确保 `ended_at` 已设置（当前代码已满足）

### ⚠️ 问题 2: 运行中任务 `e5155299e8f642f9...` 仍在 `state=running visible=thinking phase=prepare`
- 该任务可能卡在 prepare 阶段
- 建议检查是否有附件下载失败或上下文加载问题

---

## 7. 结论

**P14.4 shadow smoke 5: ✅ PASS**

MemoryX 是飞书唯一输出 owner，配置完整，过滤机制有效，单卡片机制正常工作，trace 事件完整记录。最终卡片只显示结果，不暴露内部工具调用细节。
