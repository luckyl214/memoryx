from __future__ import annotations

import pytest
from memoryx import auto_upgrade


def test_check_update_returns_structure():
    """check_update 返回正确结构。"""
    import asyncio
    result = asyncio.run(auto_upgrade.check_update(timeout=5.0))

    assert "current_version" in result
    assert "latest_version" in result
    assert "up_to_date" in result
    assert "release_url" in result
    assert result["current_version"] == "1.1.0-rc1"
    # 允许网络失败——仓库刚创建，可能没有正式 release
    # 但函数本身不应该抛异常
    assert "error" in result
