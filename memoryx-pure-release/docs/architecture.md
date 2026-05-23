# 架构设计文档

## 概述

Mnemosyne-X 是一个**事件驱动的认知记忆操作系统**，采用模块化设计，支持高并发、低延迟的记忆存储和检索。

## 核心设计原则

1. **无 ORM**：直接使用 SQLite + FTS5，避免重量级框架
2. **异步优先**：所有 IO 操作均为 async
3. **事件驱动**：基于 EventBus 的松耦合架构
4. **自修复**：崩溃后可自动恢复
5. **资源感知**：适配 2C4G 等低配环境

## 模块架构

### 1. 存储层 (storage/)

```
storage/
├── sqlite.py           # SQLite 主接口
├── sqlite_async.py     # 异步封装
├── repository.py       # MemoryRepository 主类
├── backup.py           # 备份/恢复
└── migrations/         # 数据库迁移
    ├── 001_initial.sql
    └── 002_indexes.sql
```

**关键特性**：
- 22 张表，支持多层记忆
- FTS5 全文检索
- WAL 模式（高并发）
- 自动备份（每小时）

### 2. 检索层 (retrieval/)

```
retrieval/
├── engine.py           # 混合检索引擎
├── models.py           # 检索结果模型
└── scorer.py           # 评分算法
```

**6 通道混合检索**：

| 通道 | 算法 | 权重 |
|------|------|------|
| 语义向量 | Cosine Similarity | 1.0 |
| 关键词 | BM25/FTS5 | 1.0 |
| 时序 | Exponential Decay | 0.45 |
| 实体关系 | Graph Traversal | 0.35 |
| 重要性 | Linear | 0.6 |
| 情节 | Context Window | 0.4 |

**融合公式**：

```
final_score = α·semantic + β·keyword + γ·temporal + δ·relation + ε·importance + ζ·episodic
```

### 3. 事件层 (hooks/)

```
hooks/
├── dispatcher.py       # 事件分发
├── subscriber_manager.py  # 订阅管理
├── queue_manager.py    # 队列管理
├── retry_manager.py    # 重试逻辑
├── dead_letter_queue.py  # 死信队列
└── health_monitor.py   # 健康监控
```

**事件类型**：

| 事件 | 触发时机 | 优先级 |
|------|----------|--------|
| on_user_message | 用户消息到达 | HIGH |
| on_assistant_response | 助手响应前 | NORMAL |
| on_tool_call | 工具调用前 | HIGH |
| on_tool_result | 工具返回后 | NORMAL |
| on_session_end | 会话结束 | LOW |

### 4. 提取层 (extraction/)

```
extraction/
├── engine.py           # 提取引擎
├── client.py           # LLM 客户端
└── models.py           # 提取结果模型
```

**提取流程**：

```
用户消息 → LLM 分析 → 提取记忆 → 分类 → 存储
                    ↓
              实体识别 → 关系提取 → 图存储
```

### 5. 注入层 (injection/)

```
injection/
├── engine.py           # 注入引擎
├── models.py           # 注入配置
└── context_assembly.py # 上下文组装
```

**注入策略**：

1. **检索相关记忆**：混合检索 top-K
2. **去重**：基于 checksum
3. **排序**：按 final_score
4. **裁剪**：按 token 预算
5. **格式化**：生成系统提示

### 6. Palace 引擎 (palace/)

```
palace/
├── engine.py           # Palace 引擎
├── models.py           # 层次模型
└── navigator.py        # 导航器
```

**层次结构**：

```
Memory Palace
├── Wing (记忆类型)
│   ├── PERSONA
│   ├── EPISODIC
│   ├── FACT
│   └── OBSERVATION
│   └── Room (主题)
│       └── Drawer (具体记忆)
```

### 7. 自修复引擎 (self_healing/)

```
self_healing/
├── engine.py           # 自修复引擎
├── conflict_resolver.py  # 冲突解决
└── validator.py        # 验证器
```

**修复策略**：

1. **数据一致性检查**：checksum 验证
2. **冲突检测**：相似记忆去重
3. **自动修复**：合并/标记/删除
4. **日志记录**：所有修复操作

### 8. 资源治理 (governance/)

```
governance/
├── engine.py           # 资源治理引擎
└── resource_monitor.py # 资源监控
```

**限制**：

| 资源 | 限制 | 策略 |
|------|------|------|
| 内存 | 2GB | LRU 淘汰 |
| 磁盘 | 10GB | 自动归档 |
| API 调用 | 100/min | 限流 |
| 并发 | 10 | 队列 |

### 9. 系统协调 (orchestrator/)

```
memoryx/
├── orchestrator.py     # 主协调器
├── module_registry.py  # 模块注册
└── health_check.py     # 健康检查
```

**启动顺序**：

```
1. EventBus (事件中枢)
2. MemoryStore (存储层)
3. EmbeddingCache (向量缓存)
4. Retriever (检索层)
5. Extractor (提取层)
6. Injector (注入层)
7. PalaceEngine (层次存储)
8. SelfHealing (自修复)
9. Governance (资源治理)
```

## 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                      Hermes Agent                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    EventBus (事件总线)                        │
│  on_user_message → on_assistant_response → on_session_end   │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Extractor   │    │  Retriever   │    │  Injector    │
│  (提取记忆)   │    │  (检索记忆)   │    │  (注入上下文) │
└──────────────┘    └──────────────┘    └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Memory Store                              │
│  SQLite + FTS5 + WAL + LanceDB (向量)                        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ PalaceEngine │    │SelfHealing   │    │ Governance   │
│ (层次导航)    │    │ (自修复)      │    │ (资源治理)    │
└──────────────┘    └──────────────┘    └──────────────┘
```

## 性能优化

### 1. 数据库优化

- **WAL 模式**：支持并发读写
- **FTS5 索引**：全文检索 < 10ms
- **分页查询**：避免全表扫描
- **连接池**：复用数据库连接

### 2. 向量优化

- **本地缓存**：EmbeddingCache (LRU)
- **批量嵌入**：减少 API 调用
- **异步队列**：Worker 池处理

### 3. 检索优化

- **增量检索**：progressive=True
- **标签过滤**：提前剪枝
- **评分缓存**：避免重复计算

### 4. 内存优化

- **懒加载**：按需加载记忆
- **LRU 淘汰**：自动清理热点
- **压缩存储**：SymbolicIndex

## 扩展性

### 添加新存储后端

```python
# 实现 StorageBackend 接口
class MyBackend(StorageBackend):
    async def store(self, record: MemoryRecord) -> str: ...
    async def retrieve(self, memory_id: str) -> MemoryRecord: ...
    async def search(self, query: str) -> List[MemoryRecord]: ...
```

### 添加新检索通道

```python
# 实现 Scorer 接口
class MyScorer(Scorer):
    async def score(self, record: MemoryRecord, query: str) -> float: ...
```

### 添加新事件处理器

```python
# 订阅事件
event_bus.subscribe(
    event_type="on_user_message",
    handler=my_handler,
    priority=10
)
```
