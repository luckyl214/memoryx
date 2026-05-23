"""P0-C: MCP server must generate real query vectors, not empty lists."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from memoryx.api import MemoryQueryAPI
from memoryx.mcp_server import MCPServer
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_mcp_server_accepts_embedding_manager(tmp_path: Path) -> None:
    """MCPServer.__init__ must accept optional embedding_manager."""
    repo = MemoryRepository(tmp_path / "mcp_emb.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)

    # Without embedding_manager
    server = MCPServer(api)
    assert server.embedding_manager is None

    # With embedding_manager
    fake_em = object()
    server_with = MCPServer(api, embedding_manager=fake_em)
    assert server_with.embedding_manager is fake_em

    await repo.close()


@pytest.mark.asyncio
async def test_query_vector_returns_real_vector_when_manager_available(tmp_path: Path) -> None:
    """_query_vector must generate a real vector when embedding_manager is configured."""
    repo = MemoryRepository(tmp_path / "mcp_vec.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)

    fake_embedding = [0.1, 0.2, 0.3]
    fake_manager = AsyncMock()
    fake_manager.embed_text = AsyncMock(return_value=fake_embedding)

    server = MCPServer(api, embedding_manager=fake_manager)
    vec = await server._query_vector("test query")
    assert vec == fake_embedding
    fake_manager.embed_text.assert_called_once_with("test query")

    await repo.close()


@pytest.mark.asyncio
async def test_query_vector_returns_empty_when_no_manager(tmp_path: Path) -> None:
    """_query_vector must return empty list (not crash) when no embedding_manager."""
    repo = MemoryRepository(tmp_path / "mcp_noem.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)

    server = MCPServer(api)  # no embedding_manager
    vec = await server._query_vector("test query")
    assert vec == [], "Should return empty list, not None or raise"

    await repo.close()


@pytest.mark.asyncio
async def test_mcp_search_uses_real_query_vector(tmp_path: Path) -> None:
    """memoryx_search must call _query_vector and pass the result to api.search."""
    repo = MemoryRepository(tmp_path / "mcp_search.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)

    fake_embedding = [0.1, 0.2, 0.3]
    fake_manager = AsyncMock()
    fake_manager.embed_text = AsyncMock(return_value=fake_embedding)

    server = MCPServer(api, embedding_manager=fake_manager)

    # Store a memory so search returns something
    await repo.store_memory(MemoryRecord(id="ms1", memory_type="FACT", content="test memory for MCP"))

    # Patch api.search to verify arguments
    with patch.object(api, "search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []
        await server.handle_call("memoryx_search", {"query": "test"})
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["query_vector"] == fake_embedding, (
            f"Expected real vector {fake_embedding}, got {call_kwargs['query_vector']}"
        )

    await repo.close()


@pytest.mark.asyncio
async def test_mcp_reflect_uses_real_query_vector(tmp_path: Path) -> None:
    """memoryx_reflect must call _query_vector and pass the result to api.reflect_synthesis."""
    repo = MemoryRepository(tmp_path / "mcp_refl.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)

    fake_embedding = [0.4, 0.5, 0.6]
    fake_manager = AsyncMock()
    fake_manager.embed_text = AsyncMock(return_value=fake_embedding)

    server = MCPServer(api, embedding_manager=fake_manager)

    with patch.object(api, "reflect_synthesis", new_callable=AsyncMock) as mock_reflect:
        mock_reflect.return_value = {"synthesis": "ok"}
        await server.handle_call("memoryx_reflect", {"query": "reflect me"})
        mock_reflect.assert_called_once()
        call_kwargs = mock_reflect.call_args.kwargs
        assert call_kwargs["query_vector"] == fake_embedding, (
            f"Expected real vector {fake_embedding}, got {call_kwargs['query_vector']}"
        )

    await repo.close()
