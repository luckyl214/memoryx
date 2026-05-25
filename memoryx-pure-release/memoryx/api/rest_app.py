"""Backward-compatible REST module.

New code should use memoryx.api.app_factory.create_app(). The module-level app is
kept for Uvicorn/Docker compatibility:
    uvicorn memoryx.api.rest_app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from memoryx.api.app_factory import MemoryXAppState, create_app

app = create_app(auto_open=True)


def configure(repository, query_api, self_editor=None, consolidation=None):
    """Test/runtime compatibility hook.

    For production prefer create_app(repository=..., query_api=...).
    """
    app.state.memoryx = MemoryXAppState(
        repository=repository,
        query_api=query_api,
        self_editor=self_editor,
        consolidation=consolidation,
        owns_repository=False,
        owns_query_api=False,
    )
