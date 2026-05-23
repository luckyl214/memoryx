# API 参考文档

## 概述

本文档提供 Mnemosyne-X 的完整 API 参考。

---

## MemoryRepository

核心记忆存储接口。

### 初始化

```python
from memoryx.storage import MemoryRepository

# 使用默认配置
repo = MemoryRepository()

# 自定义配置
repo = MemoryRepository(
    db_path="./data/memoryx.db",
    vector_store_path="/path/to/vectors.json",
    embedding_endpoint="https://api.openai.com/v1/embeddings",
    embedding_api_key="your_api_key"
)
```

### 存储记忆

```python
from memoryx.storage import MemoryRecord

# 创建记忆记录
record = MemoryRecord(
    memory_id="user_preference_001",
    content="用户偏好简洁回答，不喜欢冗长解释",
    memory_type="FACT",
    importance_score=0.8,
    confidence_score=0.9,
    scope="global",
    source_message_id="msg_12345",
    tags_json='["preference", "communication"]',
    entities_json='["user", "preference"]'
)

# 存储
memory_id = await repo.store_memory(record)
print(f"存储成功，ID: {memory_id}")
```

### 检索记忆

```python
# 简单检索
results = await repo.search(
    query="用户偏好",
    limit=5
)

for r in results:
    print(f"[{r.memory_type}] {r.content}")
```

### 按类型检索

```python
# 检索所有 PERSONA 类型记忆
persona_memories = await repo.list_memories(
    memory_type="PERSONA",
    limit=10
)

# 检索所有 EPISODIC 类型记忆
episodic_memories = await repo.list_memories(
    memory_type="EPISODIC",
    limit=10
)
```

### 更新记忆

```python
# 更新重要性分数
await repo.update_memory(
    memory_id="user_preference_001",
    importance_score=0.9
)

# 更新内容
await repo.update_memory(
    memory_id="user_preference_001",
    content="用户偏好简洁回答，喜欢分点说明"
)
```

### 删除记忆

```python
# 删除记忆
await repo.delete_memory("user_preference_001")

# 软删除（标记为已废弃）
await repo.delete_memory("user_preference_001", soft=True)
```

### 实体管理

```python
# 添加实体
entity_id = await repo.add_entity(
    entity_name="example_user",
    entity_type="user",
    aliases='["alias1", "alias2"]'
)

# 添加关系
await repo.add_relation(
    from_entity="entity_user",
    to_entity="entity_memoryx",
    relation_type="developer",
    confidence=0.9
)

# 查询实体相关记忆
related_memories = await repo.get_entity_memories("entity_user")
```

---

## HybridRetrievalEngine

混合检索引擎，支持 6 通道融合检索。

### 初始化

```python
from memoryx.retrieval import HybridRetrievalEngine

engine = HybridRetrievalEngine(repo)
```

### 混合检索

```python
results = await engine.search(
    query="user personal growth",
    limit=5,
    min_score=0.5,
    tag_filter=["growth", "personal"],
    tag_mode="any",  # "all" | "any"
    progressive=False,  # 是否逐层揭示
    explain_scores=True  # 返回可解释评分
)

for r in results:
    print(f"最终分数: {r.final_score}")
    if r.explain_scores:
        print(f"  语义: {r.semantic_score}")
        print(f"  关键词: {r.keyword_score}")
        print(f"  时序: {r.temporal_score}")
        print(f"  重要性: {r.importance_score}")
```

### 检索配置

```python
# 自定义权重
engine.set_weights(
    semantic=1.0,
    keyword=0.8,
    temporal=0.3,
    relation=0.2,
    importance=0.5,
    episodic=0.3
)

# 获取当前权重
weights = engine.get_weights()
```

---

## ConversationLogStore

对话日志存储。

### 初始化

```python
from memoryx.conversation_log import ConversationLogStore

log_store = ConversationLogStore(repo)
```

### 记录对话

```python
# 记录用户消息
await log_store.log(
    session_id="session_123",
    role="user",
    content="你好，我想了解一下记忆系统"
)

# 记录助手响应
await log_store.log(
    session_id="session_123",
    role="assistant",
    content="记忆系统是一个..."
)
```

### 检索对话历史

```python
# 获取会话历史
history = await log_store.session_history(
    session_id="session_123",
    limit=20
)

for log in history:
    print(f"[{log.role}] {log.content}")
```

### 搜索对话

```python
# 搜索包含关键词的对话
logs = await log_store.search(
    query="记忆系统",
    session_id="session_123",
    limit=10
)
```

---

## EmbeddingManager

向量嵌入管理。

### 初始化

```python
from memoryx.embeddings import EmbeddingManager

manager = EmbeddingManager(
    endpoint="https://api.openai.com/v1/embeddings",
    api_key="your_api_key",
    model="text-embedding-3-small"
)
```

### 嵌入文本

```python
# 单个文本
vector = await manager.embed_text("用户偏好简洁回答")
print(f"向量维度: {len(vector)}")

# 批量嵌入
vectors = await manager.embed_texts([
    "用户偏好简洁回答",
    "用户喜欢分点说明",
    "用户讨厌冗长解释"
])
```

### 缓存管理

```python
# 获取缓存命中率
stats = manager.get_cache_stats()
print(f"缓存命中率: {stats.hit_rate:.2%}")

# 清空缓存
manager.clear_cache()
```

---

## EventBus

事件总线。

### 订阅事件

```python
from memoryx.hooks import EventBus

event_bus = EventBus()

# 订阅用户消息事件
event_bus.subscribe(
    event_type="on_user_message",
    handler=my_handler,
    priority=10,
    session_id="session_123"
)

# 订阅多个事件
event_bus.subscribe_multi([
    ("on_user_message", handler1, 10),
    ("on_assistant_response", handler2, 20),
    ("on_session_end", handler3, 30)
])
```

### 发布事件

```python
# 发布事件
await event_bus.emit(
    event_type="on_user_message",
    payload={
        "session_id": "session_123",
        "message": "你好",
        "timestamp": "2026-05-22T22:00:00Z"
    }
)
```

### 取消订阅

```python
# 取消订阅
event_bus.unsubscribe(handler=my_handler)
```

---

## PalaceEngine

可导航层次存储。

### 初始化

```python
from memoryx.palace import PalaceEngine

palace = PalaceEngine(repo)
```

### 导航

```python
# 列出所有 Wing（记忆类型）
wings = await palace.list_wings()
print(wings)  # ['PERSONA', 'EPISODIC', 'FACT', 'OBSERVATION']

# 列出 Room（主题）
rooms = await palace.list_rooms(wing="PERSONA")
print(rooms)  # ['用户画像', '偏好', '特征']

# 列出 Drawer（具体记忆）
drawers = await palace.list_drawers(wing="PERSONA", room="用户画像")
print(drawers)  # ['m_001', 'm_002', 'm_003']

# 获取记忆详情
memory = await palace.get_drawer_content(wing="PERSONA", room="用户画像", drawer="m_001")
print(memory.content)
```

---

## 完整示例

```python
import asyncio
from memoryx.storage import MemoryRepository, MemoryRecord
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.conversation_log import ConversationLogStore
from memoryx.hooks import EventBus

async def main():
    # 1. 初始化
    repo = MemoryRepository()
    engine = HybridRetrievalEngine(repo)
    log_store = ConversationLogStore(repo)
    event_bus = EventBus()
    
    # 2. 存储记忆
    record = MemoryRecord(
        memory_id="user_001",
        content="用户偏好简洁回答",
        memory_type="FACT",
        importance_score=0.8
    )
    await repo.store_memory(record)
    
    # 3. 记录对话
    await log_store.log("session_001", "user", "你好")
    await log_store.log("session_001", "assistant", "你好！有什么可以帮你的吗？")
    
    # 4. 检索记忆
    results = await engine.search("用户偏好", limit=3)
    for r in results:
        print(f"[{r.memory_type}] {r.content}")
    
    # 5. 事件处理
    async def on_message(payload):
        print(f"收到消息: {payload['message']}")
    
    event_bus.subscribe("on_user_message", on_message, priority=10)
    await event_bus.emit("on_user_message", {"message": "测试消息"})

asyncio.run(main())
```
