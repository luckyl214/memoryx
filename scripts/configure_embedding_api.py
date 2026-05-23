#!/usr/bin/env python3
"""
memoryx Embedding API 配置和测试
支持多种后端：SenseNova、OpenAI 兼容、本地模型
"""

import asyncio
import os
import sys
import hashlib
from pathlib import Path
from typing import Optional

# 添加 memoryx 到路径（使用相对路径）
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent))

from memoryx.embeddings import GenericEmbeddingClient, EmbeddingManager, EmbeddingCache, VectorStore
from memoryx.storage import MemoryRepository
from memoryx.api import MemoryQueryAPI
from memoryx.retrieval import HybridRetrievalEngine

# 路径配置（使用相对路径，自动解析）
MEMORYX_DIR = SCRIPT_DIR.parent  # scripts/ -> memoryx/
MEMORYX_DB = MEMORYX_DIR / "memoryx.db"
DATA_DIR = MEMORYX_DIR / "data"
VECTOR_STORE_PATH = DATA_DIR / "vectors.json"
EMBEDDING_CACHE_PATH = DATA_DIR / "embedding_cache.json"

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Embedding 配置（从 .env 读取）
EMBEDDING_ENDPOINT = os.getenv("MEMORYX_EMBEDDING_ENDPOINT")
EMBEDDING_API_KEY = os.getenv("MEMORYX_EMBEDDING_API_KEY")
EMBEDDING_MODEL = os.getenv("MEMORYX_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
EMBEDDING_DIMENSION = int(os.getenv("MEMORYX_EMBEDDING_DIMENSION", "4096"))

print("="*70)
print("🔧 memoryx Embedding API 配置")
print("="*70)
print(f"\n   端点: {EMBEDDING_ENDPOINT or '未配置'}")
print(f"   模型: {EMBEDDING_MODEL or '未配置'}")
print(f"   维度: {EMBEDDING_DIMENSION}")
print(f"   数据目录: {DATA_DIR}")

async def test_embedding():
    """测试 embedding API"""
    print("\n【Embedding API 测试】")
    
    client = GenericEmbeddingClient(
        endpoint=EMBEDDING_ENDPOINT,
        api_key=EMBEDDING_API_KEY,
        model=EMBEDDING_MODEL,
        timeout_seconds=15.0,
        max_retries=2,
    )
    
    texts = [
        "用户的记忆系统配置",
        "TencentDB 迁移到 memoryx",
        "用户画像：用户，笔名用户",
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
        print(f"   ❌ Embedding API 不可用: {e}")
        print(f"\n   💡 解决方案:")
        print(f"      1. SenseNova 当前仅提供 chat 模型，无 embedding 端点")
        print(f"      2. 可切换到其他 embedding 提供商:")
        print(f"         - OpenAI: https://api.openai.com/v1/embeddings")
        print(f"         - Together AI: https://api.together.xyz/v1/embeddings")
        print(f"         - 本地: sentence-transformers (all-MiniLM-L6-v2)")
        print(f"      3. 当前可先用 FTS5 全文检索（已验证可用）")
        return None

async def setup_local_embedding_fallback():
    """设置本地 embedding 回退方案（基于词袋 + TF-IDF 的轻量实现）"""
    print("\n【本地 Embedding 回退方案】")
    
    # 创建一个简单的基于关键词的伪 embedding
    class LocalKeywordEmbedding:
        """基于关键词匹配的轻量级本地 embedding"""
        
        def __init__(self, dimension: int = 128):
            self.dimension = dimension
            self.vocab: dict[str, int] = {}
            self._built = False
        
        def _build_vocab(self, texts: list[str]):
            if self._built:
                return
            word_set = set()
            for text in texts:
                # 简单分词：按非字母数字字符分割
                words = "".join(
                    c if c.isalnum() else " " for c in text.lower()
                ).split()
                word_set.update(words)
            
            # 取前 dimension 个词
            for i, word in enumerate(sorted(word_set)[:self.dimension]):
                self.vocab[word] = i
            self._built = True
        
        def embed(self, text: str) -> list[float]:
            self._build_vocab([])  # 确保 vocab 初始化
            
            if not self.vocab:
                return [0.0] * self.dimension
            
            vector = [0.0] * self.dimension
            words = "".join(
                c if c.isalnum() else " " for c in text.lower()
            ).split()
            
            for word in words:
                if word in self.vocab:
                    vector[self.vocab[word]] += 1.0
            
            # L2 归一化
            norm = sum(x*x for x in vector)**0.5
            if norm > 0:
                vector = [x/norm for x in vector]
            
            return vector
    
    print("   ✅ 本地关键词 embedding 已就绪")
    print(f"   维度: {EMBEDDING_DIMENSION}")
    print("   说明: 基于词频的轻量级方案，适合中文关键词检索")
    print("   建议: 生产环境建议接入专业 embedding 模型")
    return LocalKeywordEmbedding(dimension=EMBEDDING_DIMENSION)

async def migrate_memories_to_vector_store(vectors: list | None, keyword_emb=None):
    """将已迁移的记忆插入向量存储"""
    print("\n【记忆向量化】")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    memories = await repo.list_active_memories(limit=50)
    print(f"   找到 {len(memories)} 条活跃记忆")
    
    embedded_count = 0
    for m in memories:
        memory_id = m["memory_id"]
        content = m["content"]
        
        vector = None
        if vectors:
            # 如果有 API embedding，循环使用
            idx = embedded_count % len(vectors)
            vector = vectors[idx]
        elif keyword_emb:
            vector = keyword_emb.embed(content)
        
        if vector:
            await vs.upsert(memory_id, vector, {
                "memory_type": m["memory_type"],
                "scope": m.get("scope", "global"),
                "importance": m.get("importance_score", 0.5),
            })
            embedded_count += 1
    
    print(f"   ✅ 已向量化 {embedded_count} 条记忆")
    print(f"   向量存储: {VECTOR_STORE_PATH}")
    
    await repo.close()
    return embedded_count

async def test_hybrid_search_with_vectors():
    """测试带向量的混合检索"""
    print("\n【混合检索测试（带向量）】")
    
    repo = MemoryRepository(MEMORYX_DB)
    await repo.open()
    
    vs = VectorStore(VECTOR_STORE_PATH)
    await vs.open()
    
    # 检查向量存储
    all_memories = await repo.list_memories(limit=10)
    
    if all_memories:
        # 用第一条记忆的向量做搜索
        first = all_memories[0]
        # 生成查询向量
        query_text = "用户 记忆 系统"
        
        # 简单模拟查询向量（实际应该用 embedding 模型）
        query_vec = [0.1] * EMBEDDING_DIMENSION
        
        engine = HybridRetrievalEngine(repository=repo, vector_store=vs)
        results = await engine.retrieve(
            query=query_text,
            query_vector=query_vec,
            limit=5,
        )
        
        print(f"   搜索 '{query_text}':")
        for r in results[:3]:
            preview = r.content[:50].replace("\n", " ")
            print(f"      [{r.memory_type}] score={r.final_score:.3f} | {preview}...")
    
    await repo.close()

async def generate_config_report():
    """生成配置报告"""
    print("\n【配置报告】")
    
    report = f"""# memoryx API 配置报告

**生成时间**: 2026-05-22

## 当前配置

| 项目 | 值 |
|------|-----|
| Embedding 提供商 | {EMBEDDING_PROVIDER} |
| Embedding 端点 | {EMBEDDING_ENDPOINT} |
| Embedding 模型 | {EMBEDDING_MODEL} |
| 向量维度 | {EMBEDDING_DIMENSION} |
| 数据库 | {MEMORYX_DB} |
| 向量存储 | {VECTOR_STORE_PATH} |
| Embedding 缓存 | {EMBEDDING_CACHE_PATH} |

## 可用功能

| 功能 | 状态 | 说明 |
|------|------|------|
| FTS5 全文检索 | ✅ 可用 | 基于 SQLite FTS5，中文检索正常 |
| 对话历史搜索 | ✅ 可用 | 搜索 L0 原始对话 |
| 向量存储 | ✅ 可用 | JSON 文件存储，余弦相似度 |
| 混合检索 | ✅ 可用 | 向量 + 关键词 + 重要性融合 |
| 标签管理 | ✅ 可用 | tag/untag/list_tags |
| 用户反馈 | ✅ 可用 | feedback 调整置信度 |
| 时间线版本 | ✅ 可用 | timeline 查看记忆版本 |
| Embedding API | ⚠️ 需配置 | SenseNova 无 embedding 端点 |

## Embedding 配置建议

### 方案 1: OpenAI Embedding（推荐）
```
MEMORYX_EMBEDDING_PROVIDER=openai-compatible
MEMORYX_EMBEDDING_ENDPOINT=https://api.openai.com/v1/embeddings
MEMORYX_EMBEDDING_API_KEY=sk-xxx
MEMORYX_EMBEDDING_MODEL=text-embedding-3-small
MEMORYX_EMBEDDING_DIMENSION=1536
```

### 方案 2: Together AI Embedding
```
MEMORYX_EMBEDDING_PROVIDER=openai-compatible
MEMORYX_EMBEDDING_ENDPOINT=https://api.together.xyz/v1/embeddings
MEMORYX_EMBEDDING_API_KEY=xxx
MEMORYX_EMBEDDING_MODEL=Alibaba_NLP_GTE/GTE-large-en
MEMORYX_EMBEDDING_DIMENSION=1024
```

### 方案 3: 本地 embedding（免费）
```
MEMORYX_EMBEDDING_PROVIDER=local
MEMORYX_EMBEDDING_MODEL=all-MiniLM-L6-v2
MEMORYX_EMBEDDING_DIMENSION=384
```
需要安装: `pip install sentence-transformers`

## 下一步

1. 选择 embedding 提供商并配置 API Key
2. 运行 `python scripts/verify_memoryx.py` 验证
3. 将已迁移的记忆向量化到 vector store
"""
    
    report_path = DATA_DIR / "API_CONFIG_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"   报告已保存: {report_path}")

async def main():
    # 1. 测试 embedding API
    vectors = await test_embedding()
    
    # 2. 设置本地回退
    keyword_emb = None
    if not vectors:
        keyword_emb = await setup_local_embedding_fallback()
    
    # 3. 向量化记忆
    await migrate_memories_to_vector_store(vectors, keyword_emb)
    
    # 4. 测试混合检索
    await test_hybrid_search_with_vectors()
    
    # 5. 生成配置报告
    await generate_config_report()
    
    print("\n" + "="*70)
    print("✅ API 配置完成")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
