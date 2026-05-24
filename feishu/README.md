# P14 Feishu UX Adapter

飞书产品界面层：Hermes 异步处理的可视化卡片系统。

## 核心原则

```text
先入队，后处理；
先显示状态，再输出答案；
工具调用可解释；
附件永不丢；
stream 永不泄漏内部标记；
卡片始终结构化。
```

## 架构

```
feishu/
├── schemas.py              # Job、Attachment、ToolCall、状态枚举
├── stream_sanitizer.py     # 清理 stream 内部标记，防泄漏
├── renderer.py             # 飞书卡片渲染器（三状态 + 工具 + 图文）
├── client.py               # 飞书 OpenAPI：发消息、更新卡片、上传附件
├── queue.py                # SQLite 持久队列，忙碌不丢附件
├── bot_service.py          # 飞书事件 → 队列 → Hermes → 卡片更新
└── tests/
```

## 状态流转

```
queued   排队中  grey  →  卡片立即出现，附件已入队
running  处理中  blue  →  节流更新卡片，展示工具调用和 stream
done     已完成  green →  最终结构化正文，MemoryX 保存状态
error    失败    red   →  错误信息，附件仍保存在队列中
```

## 使用

### Smoke 测试

```bash
cd /home/lucky/memoryx
python3 tools/feishu_p14_smoke.py
```

### 集成到 Hermes

```python
from feishu import FeishuClient, FeishuSQLiteQueue, FeishuCardRenderer, FeishuHermesBotService

client = FeishuClient(app_id="...", app_secret="...")
queue = FeishuSQLiteQueue("/home/lucky/memoryx/data/feishu_queue.db")
renderer = FeishuCardRenderer()
service = FeishuHermesBotService(client=client, queue=queue, renderer=renderer)

# 接受飞书事件
job = FeishuRenderJob(chat_id=..., text=..., attachments=[...])
await service.accept_event(job)

# Worker 处理
await service.run_worker_once(hermes_runner)
```

## 测试场景

| # | 场景 | 验收标准 |
|---|------|----------|
| 1 | 纯文本 | 灰色卡片，排队中 |
| 2 | 单图片 | 图片可预览 |
| 3 | 多图片 | 超过 6 张自动折叠 |
| 4 | 文件 | 文件名 + 大小显示 |
| 5 | 图文混排 | 图片 + 文件 + MemoryX 徽章 |
| 6 | stream 清洗 | 无内部标记泄漏 |
| 7 | 状态流转 | queued→running→done→error |
| 8 | 工具调用 | 工具名、状态、耗时、guard 可见 |
| 9 | 队列操作 | 入队、领取、更新、统计 |

## 与 P13 的关系

- **P13**: 启动准入检查（Hermes 启动前验证 MemoryX 健康）
- **P14**: 飞书产品界面层（Hermes 运行时的可视化）

两者独立，P14 不依赖 P13 的状态检查，但可以在卡片中展示 P13 状态徽章。

## 长期优化

- [ ] Python plugin 集成（`on_session_start` hook）
- [ ] 附件自动上传到飞书（image_key / file_key）
- [ ] 卡片更新节流策略优化
- [ ] 错误重试机制
- [ ] 多语言支持
