# Vector Backend Migration

## Status

`memory_embeddings.vector_json` is **deprecated** as of MemoryX 1.1.0.

Production vector search must use **LanceDB** backend. The SQLite `vector_json` column exists
for backward compatibility only and will be removed in a future major release.

## Migration

```bash
# Dry run
python tools/migrate_sqlite_to_lancedb.py --dry-run

# Apply migration
python tools/migrate_sqlite_to_lancedb.py --apply
```

## LanceDB Configuration

```python
from memoryx.embeddings.lancedb_vector_store import LanceDBVectorStore, LanceDBSearchConfig

config = LanceDBSearchConfig(
    limit=50,
    nprobes=20,        # higher = better recall, slower
    refine_factor=1,
    metric="cosine",
)

store = LanceDBVectorStore(path="./data/lancedb", dimension=1536, config=config)
```

## Why LanceDB

- Native vector index (IVF_PQ) for sub-10ms top-K at 100K+ scale
- Zero-copy reads via Apache Arrow
- Incremental indexing, no full rebuild needed
- SQLite `vector_json` stores vectors as text — unusable for any real-time search beyond ~100 items
