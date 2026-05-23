# 使用示例

## 基础示例

### 1. 存储和检索记忆

```python
import asyncio
from memoryx.storage import MemoryRepository, MemoryRecord

async def example_basic():
    repo = MemoryRepository()
    
    # 存储记忆
    record = MemoryRecord(
        memory_id="user_pref_001",
        content="用户偏好简洁回答，不喜欢冗长解释",
        memory_type="FACT",
        importance_score=0.8
    )
    await repo.store_memory(record)
    
    # 检索记忆
    results = await repo.search("用户偏好", limit=3)
    for r in results:
        print(f"[{r.memory_type}] {r.content}")

asyncio.run(example_basic())
```

### 2. 混合检索

```python
from memoryx.retrieval import HybridRetrievalEngine

async def example_hybrid_search():
    repo = MemoryRepository()
    engine = HybridRetrievalEngine(repo)
    
    results = await engine.search(
        query="user personal growth",
        limit=5,
        min_score=0.5,
        explain_scores=True
    )
    
    for r in results:
        print(f"分数: {r.final_score:.3f}")
        print(f"  语义: {r.semantic_score:.3f}")
        print(f"  关键词: {r.keyword_score:.3f}")
        print(f"  内容: {r.content[:100]}...")
        print()

asyncio.run(example_hybrid_search())
```

### 3. 对话日志

```python
from memoryx.conversation_log import ConversationLogStore

async def example_conversation_log():
    repo = MemoryRepository()
    log_store = ConversationLogStore(repo)
    
    # 记录对话
    await log_store.log("session_001", "user", "你好")
    await log_store.log("session_001", "assistant", "你好！有什么可以帮你的吗？")
    await log_store.log("session_001", "user", "我想了解一下记忆系统")
    
    # 检索历史
    history = await log_store.session_history("session_001", limit=10)
    for log in history:
        print(f"[{log.role}] {log.content}")

asyncio.run(example_conversation_log())
```

---

## 高级示例

### 4. 实体关系

```python
async def example_entities():
    repo = MemoryRepository()
    
    # 添加实体
    user_id = await repo.add_entity(
        entity_name="example_user",
        entity_type="user",
        aliases='["alias1", "alias2"]'
    )
    
    # 添加记忆并关联实体
    record = MemoryRecord(
        memory_id="user_bio_001",
        content="Example user, 30 years old, from Example City",
        memory_type="PERSONA",
        entities_json=f'["{user_id}"]'
    )
    await repo.store_memory(record)
    
    # 查询实体相关记忆
    related = await repo.get_entity_memories(user_id)
    for r in related:
        print(f"[{r.memory_type}] {r.content}")

asyncio.run(example_entities())
```

### 5. Palace 导航

```python
from memoryx.palace import PalaceEngine

async def example_palace():
    repo = MemoryRepository()
    palace = PalaceEngine(repo)
    
    # 列出所有 Wing
    wings = await palace.list_wings()
    print("记忆类型:", wings)
    
    # 列出 PERSONA 下的 Room
    rooms = await palace.list_rooms("PERSONA")
    print("用户画像主题:", rooms)
    
    # 导航到具体记忆
    drawers = await palace.list_drawers("PERSONA", "用户画像")
    for drawer_id in drawers:
        memory = await palace.get_drawer_content("PERSONA", "用户画像", drawer_id)
        print(f"  {drawer_id}: {memory.content[:50]}...")

asyncio.run(example_palace())
```

### 6. 事件处理

```python
from memoryx.hooks import EventBus

async def example_events():
    event_bus = EventBus()
    
    # 定义处理器
    async def on_user_message(payload):
        print(f"收到用户消息: {payload['message']}")
    
    async def on_session_end(payload):
        print(f"会话结束: {payload['session_id']}")
    
    # 订阅事件
    event_bus.subscribe("on_user_message", on_user_message, priority=10)
    event_bus.subscribe("on_session_end", on_session_end, priority=30)
    
    # 模拟事件
    await event_bus.emit("on_user_message", {
        "session_id": "session_001",
        "message": "你好"
    })
    
    await event_bus.emit("on_session_end", {
        "session_id": "session_001",
        "duration": 300
    })

asyncio.run(example_events())
```

### 7. 批量操作

```python
async def example_batch():
    repo = MemoryRepository()
    
    # 批量存储
    records = [
        MemoryRecord(
            memory_id=f"fact_{i}",
            content=f"事实 {i}",
            memory_type="FACT",
            importance_score=0.5
        )
        for i in range(10)
    ]
    
    await repo.store_batch(records)
    
    # 批量检索
    results = await repo.search("事实", limit=20)
    print(f"找到 {len(results)} 条记忆")

asyncio.run(example_batch())
```

---

## Hermes 集成示例

### 8. 上下文注入

```python
# hooks/pre_response.sh
#!/bin/bash
MEMORYX_SKILL_DIR="$HOME/.hermes/skills/memoryx"
USER_MESSAGE="${HERMES_LAST_QUERY:-$(cat)}"
SESSION_ID="${HERMES_SESSION_ID:-hermes}"

CONTEXT=$(python3 "$MEMORYX_SKILL_DIR/context_injection.py" \
    --session "$SESSION_ID" \
    --limit 5 \
    <<< "$USER_MESSAGE")

if [ -n "$CONTEXT" ]; then
    echo "$CONTEXT"
fi
```

### 9. 自动存储

```python
# hooks/post_response.sh
#!/bin/bash
MEMORYX_SKILL_DIR="$HOME/.hermes/skills/memoryx"
QUERY="${HERMES_LAST_QUERY:-}"
RESPONSE="${HERMES_LAST_RESPONSE:-}"
SESSION_ID="${HERMES_SESSION_ID:-hermes}"

python3 "$MEMORYX_SKILL_DIR/auto_store_hook.py" \
    --session "$SESSION_ID" \
    --query "$QUERY" \
    --response "$RESPONSE"
```

### 10. CLI 工具

```bash
# 搜索记忆
cd ~/.hermes/skills/memoryx
python3 memoryx_cli.py search -q "用户偏好" -l 5

# 存储记忆
python3 memoryx_cli.py store -c "用户喜欢简洁回答" -t FACT

# 查看状态
python3 memoryx_cli.py status

# 列出所有记忆
python3 memoryx_cli.py list -l 10
```

---

## 完整工作流示例

```python
import asyncio
from memoryx.storage import MemoryRepository, MemoryRecord
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.conversation_log import ConversationLogStore

async def full_workflow():
    # 1. 初始化
    repo = MemoryRepository()
    engine = HybridRetrievalEngine(repo)
    log_store = ConversationLogStore(repo)
    
    session_id = "session_demo_001"
    
    # 2. 用户消息到达
    user_message = "I want to know about the user's personal growth"
    await log_store.log(session_id, "user", user_message)
    
    # 3. 检索相关记忆
    print("=== 检索相关记忆 ===")
    results = await engine.search(user_message, limit=5)
    for r in results:
        print(f"[{r.memory_type}] {r.content[:80]}...")
    
    # 4. 生成响应（模拟）
    assistant_response = "According to memory, the user conducted 7 consecutive days of strength awareness practice in April 2026..."
    await log_store.log(session_id, "assistant", assistant_response)
    
    # 5. 存储新记忆（从对话中提取）
    new_record = MemoryRecord(
        memory_id="episodic_001",
        content="The user conducted 7 consecutive days of strength awareness practice from April 11-17, 2026",
        memory_type="EPISODIC",
        importance_score=0.7
    )
    await repo.store_memory(new_record)
    print("\n=== 存储新记忆 ===")
    print(f"已存储: {new_record.content}")
    
    # 6. 会话结束
    print("\n=== 会话结束 ===")
    history = await log_store.session_history(session_id)
    print(f"会话共 {len(history)} 条记录")

asyncio.run(full_workflow())
```
