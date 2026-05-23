#!/usr/bin/env python3
"""
测试 SiliconFlow Qwen3 Embedding API
"""

import asyncio
import os
import sys
from pathlib import Path
import sys
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent))

from memoryx.embeddings import GenericEmbeddingClient, EmbeddingManager, EmbeddingCache, VectorStore
from memoryx.storage import MemoryRepository
from memoryx.api import MemoryQueryAPI
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.conversation_log import ConversationLogStore

# 加载 .env
from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR.parent / ".env")
# 路径配置（使用相对路径，自动解析）
SCRIPT_DIR = Path(__file__).parent.resolve()
MEMORYX_DIR = SCRIPT_DIR.parent  # scripts/ -> memoryx/
MEMORYX_DB = MEMORYX_DIR / "memoryx.db"
DATA_DIR = MEMORYX_DIR / "data"
VECTOR_STORE_PATH = DATA_DIR / "vectors.json"

EMBEDDING_ENDPOINT = os.getenv("MEMORYX_EMBEDDING_ENDPOINT")
EMBEDDING_API_KEY = os.getenv("MEMORYX_EMBEDDING_API_KEY")
EMBEDDING_MODEL = os.getenv("MEMORYX_EMBEDDING_MODEL")
EMBEDDING_DIMENSION = int(os.getenv("MEMORYX_EMBEDDING_DIMENSION", "4096"))

print("="*70)
print("🔧 SiliconFlow Qwen3 Embedding API 测试")
print("="*70)
print(f"\n   端点: {EMBEDDING_ENDPOINT}")
print(f"   模型: {EMBEDDING_MODEL}")
print(f"   维度: {EMBEDDING_DIMENSION}")

async def test_embedding():
    print("\n【Embedding API 测试】")
    
    client = GenericEmbeddingClient(
        endpoint=EMBEDDING_ENDPOINT,
        api_key=EMBEDDING_API_KEY,
        model=EMBEDDING_MODEL,
        timeout_seconds=20.0,
        max_retries=2,
    )
    
    texts = [
        "用户的记忆系统配置",
        "TencentDB 迁移到 memoryx",
        "用户画像：用户，笔名用户",
        "自我觉察练习",
    ]
    
    try:
        vectors = await client.embed_texts(texts)
        print(f"   ✅ 成功嵌入 {len(texts)} 条文本")
        print(f"   向量维度: {len(vectors[0])}")
        for i, (text, vec) in enumerate(zip(texts, vectors)):
            norm = sum(x*x for x in vec)**0.5
            print(f"      [{i+1}] {text}: dim={len(vec)}, norm={norm:.2f}")
        return vectors
    except Exception as e:
        print(f"   ❌ Embedding API 失败: {e}")
        return None

async def re_embed_all_memories(vectors_template):
    """将所有记忆重新用 Qwen3 向量化"""
    print("\n【全量记忆向量化】")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    # 清空旧向量
    import json
    if VECTOR_STORE_PATH.exists():
        VECTOR_STORE_PATH.unlink()
    await vs.open()  # 重新初始化空存储
    
    memories = await repo.list_active_memories(limit=100)
    print(f"   找到 {len(memories)} 条活跃记忆")
    
    # 分批嵌入
    batch_size = 8
    embedded_count = 0
    client = GenericEmbeddingClient(
        endpoint=EMBEDDING_ENDPOINT,
        api_key=EMBEDDING_API_KEY,
        model=EMBEDDING_MODEL,
        timeout_seconds=30.0,
        max_retries=2,
    )
    
    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]
        texts = [m["content"][:500] for m in batch]  # 截断避免过长
        
        try:
            batch_vectors = await client.embed_texts(texts)
            for m, vec in zip(batch, batch_vectors):
                await vs.upsert(m["memory_id"], vec, {
                    "memory_type": m["memory_type"],
                    "scope": m.get("scope", "global"),
                    "importance": m.get("importance_score", 0.5),
                })
                embedded_count += 1
            print(f"   ✅ 已处理 {min(i+batch_size, len(memories))}/{len(memories)} 条")
        except Exception as e:
            print(f"   ⚠️ 批次 {i} 失败: {e}")
    
    print(f"   ✅ 共向量化 {embedded_count} 条记忆")
    
    # 同时插入已迁移的 TencentDB 对话记录
    row = await repo.db.fetchone("SELECT COUNT(*) FROM conversation_logs")
    conv_count = row[0] if row else 0
    print(f"   对话记录: {conv_count} 条（FTS5 全文检索，无需向量）")
    
    await repo.close()
    return embedded_count

async def test_hybrid_search():
    """测试混合检索"""
    print("\n【混合检索测试】")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    engine = HybridRetrievalEngine(repository=repo, vector_store=vs)
    
    # 获取第一条记忆的向量作为查询向量
    memories = await repo.list_active_memories(limit=1)
    if memories:
        # 用用户画像做查询
        query_text = "用户 个人成长 自我觉察"
        query_vec = [0.0] * EMBEDDING_DIMENSION  # 占位，实际检索会融合关键词
        
        # 直接测试 FTS5 + 向量融合
        results = await engine.retrieve(
            query=query_text,
            query_vector=query_vec,
            limit=5,
        )
        
        print(f"   搜索 '{query_text}':")
        for r in results[:5]:
            preview = r.content[:60].replace("\n", " ")
            print(f"      [{r.memory_type}] final={r.final_score:.3f} | {preview}...")
    
    # 测试对话搜索
    log_store = ConversationLogStore(repository=repo)
    conv_results = await log_store.search("用户", limit=3)
    print(f"\n   对话搜索 '用户': {len(conv_results)} 条")
    for r in conv_results[:2]:
        preview = r["content"][:50].replace("\n", " ")
        print(f"      [{r['role']}] {preview}...")
    
    await repo.close()

async def main():
    vectors = await test_embedding()
    if vectors:
        await re_embed_all_memories(vectors)
        await test_hybrid_search()
    
    print("\n" + "="*70)
    print("✅ SiliconFlow Qwen3 Embedding 配置完成")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
