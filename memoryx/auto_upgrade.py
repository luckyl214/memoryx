"""
自动升级检查 — 从 GitHub 检查最新版本。

用法:
    from memoryx import auto_upgrade
    result = await auto_upgrade.check_update()
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

GITHUB_REPO = "lucky99/memoryx"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/tags"


async def check_update(*, timeout: float = 10.0) -> dict[str, Any]:
    """检查 GitHub 上是否有新版本。

    Returns:
        {
            "current_version": "1.1.0",
            "latest_version": "1.2.0",
            "up_to_date": False,
            "release_url": "https://github.com/...",
            "release_notes": "...",
            "error": None
        }
    """
    from . import __version__ as current

    result: dict[str, Any] = {
        "current_version": current,
        "latest_version": current,
        "up_to_date": True,
        "release_url": f"https://github.com/{GITHUB_REPO}/releases",
        "release_notes": "",
        "error": None,
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(GITHUB_API) as resp:
                if resp.status == 200:
                    tags = await resp.json()
                    if tags and isinstance(tags, list):
                        latest = tags[0].get("name", "").lstrip("v")
                        result["latest_version"] = latest
                        result["release_url"] = f"https://github.com/{GITHUB_REPO}/releases/tag/{tags[0].get('name', 'v' + current)}"
                        result["release_notes"] = tags[0].get("commit", {}).get("message", "")[:500] if isinstance(tags[0], dict) else ""
                        try:
                            cv = tuple(int(x) for x in current.split("."))
                            lv = tuple(int(x) for x in latest.split("."))
                            result["up_to_date"] = cv >= lv
                        except (ValueError, AttributeError):
                            result["up_to_date"] = current == latest
                    else:
                        result["up_to_date"] = True
                elif resp.status == 302:
                    # 无 release (空仓库) — 正常
                    result["up_to_date"] = True
                else:
                    result["error"] = f"GitHub API returned {resp.status}"
    except aiohttp.ClientError as e:
        result["error"] = f"Network error: {e}"
    except Exception as e:
        result["error"] = str(e)

    return result
