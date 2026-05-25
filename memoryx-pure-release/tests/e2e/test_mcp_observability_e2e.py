from __future__ import annotations

import pytest

from memoryx.mcp.observed import instrument_mcp_server


class FakeMCPServer:
    async def call_memoryx_search(self, arguments):
        return {"results": [], "arguments": arguments}


@pytest.mark.asyncio
async def test_mcp_tool_observer_wraps_tool_method():
    server = instrument_mcp_server(FakeMCPServer(), tool_names=["memoryx_search"])

    result = await server.call_memoryx_search({"query": "alpha"})

    assert result["results"] == []
    assert result["arguments"]["query"] == "alpha"
