from .cache_layer import EmbeddingCache
from .embedding_manager import EmbeddingManager, GenericEmbeddingClient
from .models import EmbeddingRequest, EmbeddingResult
from .queue_worker import EmbeddingQueueWorker
from .vector_store import VectorStore

__all__ = [
    "EmbeddingCache",
    "EmbeddingManager",
    "EmbeddingQueueWorker",
    "EmbeddingRequest",
    "EmbeddingResult",
    "GenericEmbeddingClient",
    "LanceDBVectorStore",
    "VectorStore",
]

# Lazy import for optional dependency
def __getattr__(name):
    if name == "LanceDBVectorStore":
        from .lancedb_vector_store import LanceDBVectorStore
        return LanceDBVectorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
