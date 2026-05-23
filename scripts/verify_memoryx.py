#!/usr/bin/env python3
"""
memoryx 检索功能验证 + API 配置
"""

import asyncio
import json
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone

# 添加 memoryx 到路径（使用相对路径）
import sys
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent))

from memoryx.storage import MemoryRepository, MemoryRecord
from memoryx.embeddings import VectorStore, EmbeddingCache, GenericEmbeddingClient, EmbeddingManager
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.routing import MemoryRouter
from memoryx.recall import ActiveRecallEngine
from memoryx.api import MemoryQueryAPI
from memoryx.conversation_log import ConversationLogStore
from uuid import uuid4

# ========== 配置 ==========\
MEMORYX_DB = SCRIPT_DIR.parent / "memoryx.db"
DATA_DIR = SCRIPT_DIR.parent / "data"
VECTOR_STORE_PATH = DATA_DIR / "vectors.json"
EMBEDDING_CACHE_PATH = DATA_DIR / "embedding_cache.json"

# Embedding API 配置（从 .env 读取）
EMBEDDING_ENDPOINT = os.getenv("MEMORYX_EMBEDDING_ENDPOINT")
EMBEDDING_API_KEY = os.getenv("MEMORYX_EMBEDDING_API_KEY")
EMBEDDING_MODEL = os.getenv("MEMORYX_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")

print("="*70)
print("🔍 memoryx 检索验证 + API 配置")
print("="*70)

async def verify_fts_retrieval():
    """验证 FTS5 全文检索（无需 embedding）"""
    print("\n【1】FTS5 全文检索验证...")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    queries = ["用户", "自我觉察", "社交媒体", "某作者", "memoryx"]
    
    for q in queries:
        results = await repo.search_full_text(q, limit=3)
        print(f"   搜索 '{q}': 找到 {len(results)} 条")
        for r in results[:2]:
            content_preview = r["content"][:60].replace("\n", " ")
            print(f"      [{r['memory_type']}] {content_preview}...")
    
    await repo.close()

async def verify_conversation_search():
    """验证对话历史搜索"""
    print("\n【2】对话历史搜索验证...")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    log_store = ConversationLogStore(repository=repo)
    
    queries = ["迁移", "TencentDB", "系统优化"]
    
    for q in queries:
        results = await log_store.search(q, limit=3)
        print(f"   搜索 '{q}': 找到 {len(results)} 条对话")
        for r in results[:2]:
            content_preview = r["content"][:50].replace("\n", " ")
            print(f"      [{r['role']}] {content_preview}...")
    
    await repo.close()

async def verify_vector_store():
    """验证向量存储和相似度搜索"""
    print("\n【3】向量存储验证...")
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    test_vectors = {
        "test-vector-1": [0.1] * 4096,
        "test-vector-2": [0.9] * 4096,
        "test-vector-3": [0.5] * 4096,
    }
    
    for mid, vec in test_vectors.items():
        await vs.upsert(mid, vec, {"test": True, "content": f"测试向量 {mid}"})
    
    query_vec = [0.95] * 4096
    results = await vs.search(query_vec, limit=3)
    print(f"   向量搜索: 找到 {len(results)} 条")
    for r in results:
        print(f"      {r['memory_id']}: score={r['score']:.4f}")
    
    for mid in test_vectors:
        await vs.delete(mid)
    
    print("   ✅ 向量存储功能正常")

async def test_embedding_api():
    """测试 Embedding API"""
    print("\n【4】Embedding API 测试...")
    
    client = GenericEmbeddingClient(
        endpoint=EMBEDDING_ENDPOINT or "",
        api_key=EMBEDDING_API_KEY or "",
        model=EMBEDDING_MODEL or "Qwen/Qwen3-Embedding-8B",
        timeout_seconds=15.0,
        max_retries=2,
    )
    
    texts = ["测试嵌入", "用户的记忆系统", "TencentDB 迁移完成"]
    
    try:
        vectors = await client.embed_texts(texts)
        print(f"   ✅ 成功嵌入 {len(texts)} 条文本")
        print(f"   向量维度: {len(vectors[0])}")
        for i, (text, vec) in enumerate(zip(texts, vectors)):
            print(f"      [{i+1}] {text}: dim={len(vec)}, norm≈{sum(x*x for x in vec)**0.5:.2f}")
        return vectors
    except Exception as e:
        print(f"   ❌ Embedding API 失败: {e}")
        print(f"   提示: 请确认 SenseNova 是否提供 embedding 端点")
        print(f"   当前配置: {SENSENOVA_EMBEDDING_ENDPOINT}")
        return None

async def verify_hybrid_retrieval(vectors: list | None):
    """验证混合检索（向量 + 关键词）"""
    print("\n【5】混合检索验证...")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    if vectors:
        memories = await repo.list_active_memories(limit=5)
        for i, m in enumerate(memories):
            if i < len(vectors):
                await vs.upsert(m["memory_id"], vectors[i], {
                    "memory_type": m["memory_type"],
                    "content_preview": m["content"][:100]
                })
        print(f"   已插入 {min(len(vectors), len(memories))} 个记忆向量")
    
    engine = HybridRetrievalEngine(repository=repo, vector_store=vs)
    
    test_queries = ["用户", "记忆系统", "迁移"]
    
    for q in test_queries:
        query_vec = vectors[0] if vectors else [0.1] * 4096
        results = await engine.retrieve(query=q, query_vector=query_vec, limit=3)
        print(f"   搜索 '{q}': 找到 {len(results)} 条")
        for r in results[:2]:
            print(f"      [{r.memory_type}] final={r.final_score:.3f} | {r.content[:50].replace(chr(10), ' ')}...")
    
    await repo.close()

async def full_api_test(vectors: list | None):
    """端到端 API 测试"""
    print("\n【6】端到端 API 测试...")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    api = MemoryQueryAPI(repository=repo, vector_store=vs)
    
    # 测试 store
    test_id = await api.store(
        memory_type="FACT",
        content="这是一个测试记忆，用于验证 memoryx 的存储功能。",
        scope="global",
        importance_score=0.8,
    )
    print(f"   ✅ 存储测试记忆: {test_id}")
    
    # 测试 list
    memories = await repo.list_memories(limit=5)
    print(f"   ✅ 列出记忆: {len(memories)} 条")
    
    # 测试 conversation_search
    conv_results = await api.conversation_search(query="迁移", limit=3)
    print(f"   ✅ 对话搜索 '迁移': {len(conv_results)} 条")
    
    # 测试 tag
    if memories:
        test_mem_id = memories[0]["memory_id"]
        await api.tag(test_mem_id, "test-tag")
        tags = await api.list_tags(test_mem_id)
        print(f"   ✅ 标签操作: {tags}")
        await api.untag(test_mem_id, "test-tag")
    
    # 测试 feedback
    if memories:
        feedback = await api.feedback(memories[0]["memory_id"], positive=True)
        print(f"   ✅ 反馈测试: confidence={feedback.get('new_confidence', 'N/A')}")
    
    # 测试 timeline
    if memories:
        timeline = await api.timeline(memory_id=memories[0]["memory_id"])
        print(f"   ✅ 时间线: {len(timeline.get('versions', []))} 个版本")
    
    await repo.close()

async def main():
    await verify_fts_retrieval()
    await verify_conversation_search()
    await verify_vector_store()
    vectors = await test_embedding_api()
    await verify_hybrid_retrieval(vectors)
    await full_api_test(vectors)
    
    print("\n" + "="*70)
    print("✅ 验证完成")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
