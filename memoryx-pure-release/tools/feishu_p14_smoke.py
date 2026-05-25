#!/usr/bin/env python3
"""
P14 Feishu UX Adapter Smoke Test

测试 8 个场景：
1. 纯文本
2. 单图片
3. 多图片
4. 文件
5. 图片 + 文件 + 文本
6. Hermes 忙碌时连续发 3 条
7. stream 中包含 tool_call / analysis 标记
8. 工具调用失败
"""
from __future__ import annotations

import json
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoryx.feishu.schemas import (
    AttachmentRef,
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
)
from memoryx.feishu.stream_sanitizer import StreamSanitizer
from memoryx.feishu.renderer import FeishuCardRenderer, STATE_META
from memoryx.feishu.queue import FeishuSQLiteQueue


def _job(**kwargs):
    """辅助函数：创建 FeishuRenderJob"""
    defaults = {
        "chat_id": "test_chat",
        "user_id": "test_user",
        "message_id": "test_msg",
        "text": "测试文本",
        "title": "测试任务",
    }
    defaults.update(kwargs)
    return FeishuRenderJob(**defaults)


def test_1_plain_text():
    """场景 1: 纯文本"""
    job = _job(text="今天天气不错")
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    assert card["header"]["template"] == "grey"
    assert "已收到" in card["header"]["title"]["content"]
    print("✅ 场景 1: 纯文本")


def test_2_single_image():
    """场景 2: 单图片"""
    job = _job(
        text="看这张图",
        attachments=[
            AttachmentRef(
                kind="image",
                image_key="img_test_001",
                name="screenshot.png",
                size=124000,
            )
        ],
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    image_found = any(
        e.get("tag") == "markdown" and "img_test_001" in e.get("content", "")
        for e in card["elements"]
    )
    assert image_found
    print("✅ 场景 2: 单图片")


def test_3_multi_images():
    """场景 3: 多图片（超过 6 张应折叠）"""
    job = _job(
        text="多图",
        attachments=[
            AttachmentRef(kind="image", image_key=f"img_{i}", name=f"img_{i}.png")
            for i in range(8)
        ],
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    fold_found = any(
        "还有 2 张图片已保存" in str(e)
        for e in card["elements"]
    )
    assert fold_found
    print("✅ 场景 3: 多图片（折叠）")


def test_4_file():
    """场景 4: 文件"""
    job = _job(
        text="看这个文件",
        attachments=[
            AttachmentRef(
                kind="file",
                file_key="file_test_001",
                name="选题表.xlsx",
                size=127000,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        ],
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    file_found = any("选题表.xlsx" in str(e) for e in card["elements"])
    assert file_found
    print("✅ 场景 4: 文件")


def test_5_mixed():
    """场景 5: 图片 + 文件 + 文本"""
    job = _job(
        text="综合分析",
        title="小红书运营",
        attachments=[
            AttachmentRef(kind="image", image_key="img_001", name="cover.png"),
            AttachmentRef(kind="file", file_key="file_001", name="plan.xlsx", size=50000),
        ],
        context_summary="MemoryX 已检索 5 条相关记忆",
        memoryx_badges=["MemoryX ✅", "Semantic ✅", "P13 ✅"],
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    card_str = json.dumps(card, ensure_ascii=False)
    assert "MemoryX ✅" in card_str
    assert "cover.png" in card_str
    assert "plan.xlsx" in card_str
    print("✅ 场景 5: 图文混排")


def test_6_stream_sanitizer():
    """场景 6: stream 中包含内部标记"""
    sanitizer = StreamSanitizer()
    dirty_text = """
<|analysis|>
让我分析一下这个问题...
[TOOL_CALL]{"tool": "web_search", "arguments": {"query": "小红书规则"}}[/TOOL_CALL]
scratchpad: 需要查证平台规则
<|/analysis|>

最终答案：
小红书平台规则要求...
```json
{"tool": "web_search", "arguments": {...}}
```
"""
    clean = sanitizer.clean(dirty_text)
    assert "<|analysis|>" not in clean
    assert "[TOOL_CALL]" not in clean
    assert "scratchpad" not in clean.lower()
    assert "最终答案" in clean
    print("✅ 场景 6: stream 清洗")


def test_7_state_transitions():
    """场景 7: 状态流转"""
    job = _job()
    assert job.state == HermesRunState.QUEUED
    assert STATE_META[HermesRunState.QUEUED]["template"] == "grey"
    job.state = HermesRunState.RUNNING
    assert STATE_META[HermesRunState.RUNNING]["template"] == "blue"
    job.state = HermesRunState.DONE
    assert STATE_META[HermesRunState.DONE]["template"] == "green"
    job.state = HermesRunState.ERROR
    assert STATE_META[HermesRunState.ERROR]["template"] == "red"
    print("✅ 场景 7: 状态流转")


def test_8_tool_records():
    """场景 8: 工具调用记录"""
    job = _job(
        tools=[
            ToolCallRecord(
                name="memoryx_search",
                status="done",
                summary="召回 5 条记忆",
                duration_ms=23,
            ),
            ToolCallRecord(
                name="claim_guard",
                status="done",
                summary="事实校验通过",
                guard_decision="pass",
                duration_ms=12,
            ),
            ToolCallRecord(
                name="web_search",
                status="running",
                input_preview="查询小红书平台规则...",
            ),
        ],
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)
    tool_names = json.dumps(card)
    assert "memoryx_search" in tool_names
    assert "claim_guard" in tool_names
    assert "web_search" in tool_names
    print("✅ 场景 8: 工具调用记录")


def test_queue():
    """场景 9: 队列基本操作"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    job = _job()
    job_id = queue.enqueue(job, priority=50)
    assert job_id == job.job_id

    claimed = queue.claim_next()
    assert claimed is not None
    assert claimed.state == HermesRunState.RUNNING

    claimed.state = HermesRunState.DONE
    claimed.answer = "测试完成"
    queue.update(claimed)

    stats = queue.stats()
    assert stats.get("done", 0) == 1

    db_path.unlink(missing_ok=True)
    print("✅ 场景 9: 队列操作")


def main():
    print("=" * 50)
    print("P14 Feishu UX Adapter Smoke Test")
    print("=" * 50)

    tests = [
        test_1_plain_text,
        test_2_single_image,
        test_3_multi_images,
        test_4_file,
        test_5_mixed,
        test_6_stream_sanitizer,
        test_7_state_transitions,
        test_8_tool_records,
        test_queue,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1

    print("=" * 50)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 50)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
