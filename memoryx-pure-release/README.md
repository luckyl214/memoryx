# Mnemosyne-X — 认知记忆操作系统

> **让 Agent 拥有真正的生产级认知记忆：不仅记住，还能理解、反思和自我优化。**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-179%20passed-brightgreen)](https://github.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

---

## 📖 目录

- [简介](#简介)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [Hermes Agent 集成](#hermes-agent-集成)
- [架构设计](#架构设计)
- [API 参考](#api-参考)
- [开发指南](#开发指南)
- [常见问题](#常见问题)
- [许可证](#许可证)

---

## 简介

Mnemosyne-X（记忆女神 X）是一个**生产级的认知记忆操作系统**，专为 AI Agent 设计。它不仅仅是存储和检索记忆，而是提供：

- **多层级记忆存储**：工作记忆 → 短期事件 → 长期知识 → 归档
- **混合检索引擎**：向量 + 关键词 + 时序 + 实体关系 + 重要性
- **事件驱动架构**：基于 EventBus 的异步钩子系统
- **自修复能力**：崩溃恢复、数据一致性验证
- **资源治理**：适配 2C4G 等低配环境

---

## 核心特性

### 🏛️ 五层记忆层级

| 层级 | 分类标准 | 用途 |
|------|---------|------|
| **Working** | 当前会话 | 实时推理态 |
| **Short-term Episodic** | EPISODIC 类型 | 近期事件 |
| **Long-term Semantic** | importance ≥ 0.85 OR access_count ≥ 3 | 持久知识 |
| **Consolidated Knowledge** | 中等重要性默认 | 稳定知识 |
| **Archive** | decay ≥ 0.9 AND access_count = 0 | 冷存储 |

### 🎯 Palace 可导航存储

受 MemPalace 启发的层次化导航系统。记忆不仅可搜索，还可像建筑一样步进浏览：

```
Wing (记忆类型) → Room (主题) → Drawer (具体记忆)
```

### 🔍 6 通道混合检索

| 通道 | 权重 | 用途 |
|------|------|------|
| 语义向量 | 1.0 | 理解含义 |
| 关键词 BM25/FTS5 | 1.0 | 精确匹配 |
| 时序衰减 | 0.45 | 新鲜度 |
| 实体关系 | 0.35 | 关联推理 |
| 重要性 | 0.6 | 优先级 |
| 情节 | 0.4 | 上下文 |

### 📡 事件驱动钩子系统

```
5 事件类型:
  - on_user_message
  - on_assistant_response
  - on_tool_call
  - on_tool_result
  - on_session_end

5 优先级: CRITICAL=0 → HIGH=10 → NORMAL=20 → LOW=30 → BACKGROUND=40

功能:
  - DLQ (死信队列)
  - 队列持久化
  - 崩溃恢复
  - 健康指标
  - 追踪 ID
```

---

## 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/lucky99/memoryx.git
cd memoryx

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置（至少需要 Embedding API）
# .env:
#   MEMORYX_EMBEDDING_ENDPOINT=https://api.openai.com/v1/embeddings
#   MEMORYX_EMBEDDING_API_KEY=your_api_key_here
#   MEMORYX_EMBEDDING_MODEL=text-embedding-3-small
```

### 3. 初始化数据库

```bash
# 创建数据库
python3 scripts/init_db.py

# 验证
python3 scripts/verify_memoryx.py
```

### 4. 基本使用

```python
from memoryx.storage import MemoryRepository
from memoryx.retrieval import HybridRetrievalEngine

# 存储记忆
repo = MemoryRepository()
await repo.store_memory(
    memory_id="user_preference_001",
    content="用户偏好简洁回答",
    memory_type="FACT",
    importance_score=0.8
)

# 检索记忆
engine = HybridRetrievalEngine(repo)
results = await engine.search(
    query="用户偏好",
    limit=5,
    min_score=0.5
)

for r in results:
    print(f"[{r.memory_type}] {r.content} (score: {r.final_score})")
```

---

## Hermes Agent 集成

### 方案 A：使用 hooks（推荐）

```bash
# 1. 复制 hooks
cp hooks/pre_response.sh ~/.hermes/hooks/
cp hooks/post_response.sh ~/.hermes/hooks/
chmod +x ~/.hermes/hooks/*.sh

# 2. 复制技能
cp -r skills/memoryx ~/.hermes/skills/

# 3. 添加到 PINNED_SKILLS
# 编辑 ~/.hermes/skills/PINNED_SKILLS.json，添加 "memoryx"

# 4. 重启 Gateway
hermes gateway restart
```

### 方案 B：直接集成

```python
# 在 Hermes 插件中使用
from memoryx.hermes_adapter import MemoryXHermesAdapter

adapter = MemoryXHermesAdapter()

# 对话前：注入相关记忆
context = await adapter.get_context(user_query, session_id)

# 对话后：存储重要信息
await adapter.store_from_response(query, response)
```

### 自动存储触发关键词

| 类别 | 关键词 |
|------|--------|
| 个人信息 | 我叫、我的名字、我是、我来自、我的生日 |
| 偏好习惯 | 我喜欢、我不喜欢、我偏好、我每天、我每周 |
| 观点态度 | 我认为、我觉得、我相信、我支持、我反对 |
| 重要事件 | 我完成了、我学会了、我参加了、我获得了 |

---

## 架构设计

```
                    Hermes Agent (消息管道 / 工具调用)
                              │
                    ┌─────────▼─────────┐
                    │   EventBus + DLQ  │  事件驱动中枢
                    │   优先级队列/追踪   │
                    └─────────┬─────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
    Extractor           Retriever            Injector
   (L1 记忆提取)      (6 通道混合检索)      (上下文注入)
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────────┐
                    │    Memory Store      │  SQLite + FTS5 + WAL
                    │    (22 表，多层)     │  LanceDB 向量
                    └─────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   PalaceEngine        SelfHealing          ResourceGovernance
   (可导航层次存储)     (自修复/崩溃恢复)      (2C4G 资源治理)
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────────┐
                    │  ModuleRegistry +    │  全局模块编排
                    │  SystemOrchestrator  │  (健康检查/依赖管理)
                    └─────────────────────┘
```

---

## API 参考

### MemoryRepository

```python
# 存储记忆
await repo.store_memory(record: MemoryRecord) -> str

# 检索记忆
await repo.search(query: str, limit: int = 10) -> List[MemoryRecord]

# 按类型检索
await repo.list_memories(memory_type: str, limit: int = 10) -> List[MemoryRecord]

# 更新记忆
await repo.update_memory(memory_id: str, **kwargs)

# 删除记忆
await repo.delete_memory(memory_id: str)
```

### HybridRetrievalEngine

```python
engine = HybridRetrievalEngine(repo)

# 混合检索
results = await engine.search(
    query="用户偏好简洁回答",
    limit=5,
    min_score=0.5,
    tag_filter=["preference"],
    progressive=False  # 是否逐层揭示
)

# 获取可解释评分
for r in results:
    print(f"语义: {r.semantic_score}, 关键词: {r.keyword_score}, 最终: {r.final_score}")
```

### ConversationLogStore

```python
log_store = ConversationLogStore(repo)

# 记录对话
await log_store.log(session_id, role, content)

# 检索对话历史
logs = await log_store.session_history(session_id, limit=20)

# 搜索对话
logs = await log_store.search("user birthday", limit=10)
```

---

## 开发指南

### 添加新模块

```
module/
├── __init__.py    # 导出
├── engine.py      # 主实现
├── models.py      # 数据模型
└── tests/         # 测试
    └── test_module.py
```

### 运行测试

```bash
# 全部测试
pytest -q

# 定向测试
pytest -q tests/test_storage.py

# 带覆盖率
pytest --cov=memoryx --cov-report=html
```

### 代码风格

- Python 3.11+ type hints 必须
- async/await 优先
- 无 ORM，无重量级框架
- 所有 API 调用必须 retry + timeout + backoff
- 所有 IO 必须 async

---

## 常见问题

### Q: 为什么需要记忆系统？

A: 现代 AI Agent 需要在多次对话中保持上下文一致性。记忆系统让 Agent：
- 记住用户偏好和历史
- 跨会话保持连续性
- 自我反思和优化

### Q: 支持哪些数据库？

A: 当前支持 SQLite（生产推荐）。计划支持：
- PostgreSQL（大规模）
- LanceDB（向量优化）
- Redis（缓存层）

### Q: 如何迁移现有记忆？

A: 使用 `migrate.py` 脚本：

```bash
python3 scripts/migrate.py --from tencentdb --to memoryx
```

支持迁移：TencentDB, Mem0, Letta, Zep, Cognee 等。

### Q: 性能如何？

A: 基准测试（2C4G VPS）：
- 检索延迟：< 50ms（1000 条记忆）
- 存储吞吐：> 100 ops/s
- 内存占用：< 200MB

---

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。

---

## 贡献

欢迎贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 联系

- GitHub Issues: https://github.com/lucky99/memoryx/issues
- 文档: https://github.com/lucky99/memoryx/tree/main/docs
