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
├── client.py               # 飞书 OpenAPI 客户端（带 retry/backoff）
├── queue.py                # SQLite 持久队列（DLQ + max_attempts + 附件双写）
├── dedupe.py               # 事件去重（防飞书重试重复卡片）
├── event_security.py       # 验证 Token + 签名校验 + AES 解密
├── routes.py               # FastAPI 事件入口
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
cd ${HOME}/memoryx
python3 tools/feishu_p14_smoke.py      # P14 模块级测试（9 场景）
python3 tools/feishu_p141_smoke.py     # P14.1 生产硬化测试（12 场景）
```

### 集成到 Hermes

```python
from feishu import FeishuClient, FeishuSQLiteQueue, FeishuCardRenderer, FeishuHermesBotService, FeishuEventDedupe, create_feishu_router

client = FeishuClient(app_id="...", app_secret="...")
queue = FeishuSQLiteQueue("${HOME}/memoryx/data/feishu_queue.db")
renderer = FeishuCardRenderer()
service = FeishuHermesBotService(client=client, queue=queue, renderer=renderer)
dedupe = FeishuEventDedupe("${HOME}/memoryx/data/feishu_queue.db")

# FastAPI 路由
app = FastAPI()
app.include_router(create_feishu_router(bot_service=service, queue_db_path="${HOME}/memoryx/data/feishu_queue.db"))
```

## 测试场景

### P14（模块级）

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

### P14.1（生产硬化）

| # | 场景 | 验收标准 |
|---|------|----------|
| 1 | 事件去重 | 重复 event_id 不生成新卡片 |
| 2 | DLQ 自动移入 | 超过 max_attempts 移入 dead_letter |
| 3 | max_attempts 限制 | 第 4 次领取返回 None |
| 4 | 队列双写 attachments | attachments 表可查询 |
| 5 | 附件状态跟踪 | pending/done/failed 可更新 |
| 6 | DLQ 统计 | dead_letter 表可统计 |
| 7 | 状态流转 | 四种状态正确渲染 |
| 8 | 队列操作 | 入队、领取、更新、统计 |
| 9 | 空文本提取 | 空 JSON/空字符串返回 "" |
| 10 | 富文本提取 | items 格式正确拼接 |
| 11 | 附件提取 | 图片/文件正确解析 |
| 12 | 卡片渲染完整流程 | 三状态 + 工具 + 正文 |

## 与 P13/P12.1 的关系

- **P13**: 启动准入检查（Hermes 启动前验证 MemoryX 健康）
- **P12.1**: Hermes Cognitive Spine / LLM Safety / MemoryX Guard
- **P14**: 飞书产品界面层（Hermes 运行时的可视化）

三者独立，P14 的卡片中可以展示 P13/P12.1 状态徽章。

## 长期优化

- [ ] 附件真实下载落盘（image_key → local_path）
- [ ] Hermes runner 真接入（stream + tool call + guard）
- [ ] 长答案溢出转文件 / 飞书文档
- [ ] Python plugin 集成（`on_session_start` hook）
- [ ] 卡片更新节流策略优化
- [ ] 错误重试机制
- [ ] 多语言支持
