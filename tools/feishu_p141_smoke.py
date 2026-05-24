#!/usr/bin/env python3
"""
P14.1 Feishu Production Hardening Smoke Test

测试 12 个生产边界场景：
1. 事件去重
2. DLQ 自动移入
3. max_attempts 限制
4. 队列双写 attachments
5. 附件状态跟踪
6. DLQ 统计
7. 状态流转
8. 队列操作
9. 空文本提取
10. 富文本提取
11. 附件提取
12. 卡片渲染完整流程
"""
from __future__ import annotations

import json
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from feishu.schemas import (
    AttachmentRef,
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
)
from feishu.queue import FeishuSQLiteQueue
from feishu.dedupe import FeishuEventDedupe
from feishu.renderer import FeishuCardRenderer
from feishu.routes import _extract_text, _extract_attachments


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


def test_1_event_dedupe():
    """场景 1: 事件去重"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    dedupe = FeishuEventDedupe(db_path)

    # 第一次：新事件
    result1 = dedupe.seen_or_mark(event_id="evt_001", message_id="msg_001")
    assert result1 is False, f"新事件应返回 False, got {result1}"

    # 第二次：重复事件
    result2 = dedupe.seen_or_mark(event_id="evt_001", message_id="msg_001")
    assert result2 is True, f"重复事件应返回 True, got {result2}"

    db_path.unlink(missing_ok=True)
    print("✅ 场景 1: 事件去重")


def test_2_dlq_auto():
    """场景 2: DLQ 自动移入"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    job = _job()
    queue.enqueue(job)

    # 模拟 3 次失败
    for i in range(3):
        claimed = queue.claim_next(max_attempts=3)
        assert claimed is not None, f"第 {i+1} 次应能领取"
        claimed.state = HermesRunState.ERROR
        queue.update(claimed)

    # 再调用一次 claim_next 触发 DLQ 移动
    claimed = queue.claim_next(max_attempts=3)
    assert claimed is None, f"超过 max_attempts 应返回 None, got {claimed}"

    # 检查 DLQ
    dlq_stats = queue.dlq_stats()
    assert dlq_stats.get("max_attempts_exceeded", 0) == 1, f"DLQ 应有 1 条, got {dlq_stats}"

    db_path.unlink(missing_ok=True)
    print("✅ 场景 2: DLQ 自动移入")


def test_3_max_attempts():
    """场景 3: max_attempts 限制"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    job = _job()
    queue.enqueue(job)

    # 领取 3 次（max_attempts=3）- 每次失败后重新领取
    for i in range(3):
        claimed = queue.claim_next(max_attempts=3)
        assert claimed is not None, f"第 {i+1} 次应能领取"
        claimed.state = HermesRunState.ERROR
        queue.update(claimed)

    # 第 4 次：应返回 None（attempts=3 不小于 max_attempts=3）
    claimed = queue.claim_next(max_attempts=3)
    assert claimed is None, f"第 4 次应返回 None, got {claimed}"

    db_path.unlink(missing_ok=True)
    print("✅ 场景 3: max_attempts 限制")


def test_4_queue_attachments():
    """场景 4: 队列双写 attachments"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    job = _job(
        attachments=[
            AttachmentRef(kind="image", image_key="img_001", name="cover.png"),
            AttachmentRef(kind="file", file_key="file_001", name="plan.xlsx", size=50000),
        ],
    )
    queue.enqueue(job)

    # 检查 attachments 表
    atts = queue.get_attachments_for_job(job.job_id)
    assert len(atts) == 2, f"应有 2 个附件, got {len(atts)}"
    assert atts[0]["kind"] == "image"
    assert atts[1]["kind"] == "file"
    assert atts[1]["size"] == 50000

    db_path.unlink(missing_ok=True)
    print("✅ 场景 4: 队列双写 attachments")


def test_5_attachment_status():
    """场景 5: 附件状态跟踪"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    job = _job(
        attachments=[AttachmentRef(kind="image", image_key="img_001", name="cover.png")],
    )
    queue.enqueue(job)

    atts = queue.get_attachments_for_job(job.job_id)
    att_id = atts[0]["id"]

    # 更新下载状态
    queue.mark_attachment_status(att_id, download_status="done")

    atts = queue.get_attachments_for_job(job.job_id)
    assert atts[0]["download_status"] == "done"

    # 模拟失败
    queue.mark_attachment_status(att_id, download_status="failed", error_msg="file too large")
    atts = queue.get_attachments_for_job(job.job_id)
    assert atts[0]["download_status"] == "failed"
    assert "too large" in atts[0]["error_msg"]

    db_path.unlink(missing_ok=True)
    print("✅ 场景 5: 附件状态跟踪")


def test_6_dlq_stats():
    """场景 6: DLQ 统计"""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    queue = FeishuSQLiteQueue(db_path)

    # 创建 2 个 job 并让它们失败
    for i in range(2):
        job = _job()
        queue.enqueue(job)
        for _ in range(3):
            claimed = queue.claim_next(max_attempts=3)
            if claimed:
                claimed.state = HermesRunState.ERROR
                queue.update(claimed)

    # 再调用一次 claim_next 触发 DLQ 移动（DLQ 移动在 claim_next 开始时执行）
    queue.claim_next(max_attempts=3)

    dlq_stats = queue.dlq_stats()
    assert dlq_stats.get("max_attempts_exceeded", 0) == 2, f"DLQ 应有 2 条, got {dlq_stats}"

    db_path.unlink(missing_ok=True)
    print("✅ 场景 6: DLQ 统计")


def test_7_state_transitions():
    """场景 7: 状态流转"""
    job = _job()
    assert job.state == HermesRunState.QUEUED

    job.state = HermesRunState.RUNNING
    assert job.state == HermesRunState.RUNNING

    job.state = HermesRunState.DONE
    assert job.state == HermesRunState.DONE

    job.state = HermesRunState.ERROR
    assert job.state == HermesRunState.ERROR

    print("✅ 场景 7: 状态流转")


def test_8_queue_ops():
    """场景 8: 队列基本操作"""
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
    print("✅ 场景 8: 队列操作")


def test_9_extract_empty():
    """场景 9: 空文本提取"""
    msg = {"content": "{}"}
    text = _extract_text(msg)
    assert text == "", f"空 JSON 应返回空字符串, got '{text}'"

    msg = {"content": ""}
    text = _extract_text(msg)
    assert text == "", f"空字符串应返回空字符串, got '{text}'"

    msg = {}
    text = _extract_text(msg)
    assert text == "", f"空对象应返回空字符串, got '{text}'"

    print("✅ 场景 9: 空文本提取")


def test_10_extract_rich_text():
    """场景 10: 富文本提取"""
    # 纯文本 content
    msg = {"content": json.dumps({"text": "你好"})}
    text = _extract_text(msg)
    assert text == "你好", f"应返回 '你好', got '{text}'"

    # 富文本 items
    msg = {
        "content": json.dumps({
            "items": [
                {"tag": "text", "text": "Hello "},
                {"tag": "text", "text": "World"},
            ]
        })
    }
    text = _extract_text(msg)
    assert text == "Hello World", f"应返回 'Hello World', got '{text}'"

    print("✅ 场景 10: 富文本提取")


def test_11_extract_attachments():
    """场景 11: 附件提取"""
    # 图片
    msg = {
        "content": json.dumps({
            "items": [
                {"tag": "img", "image_key": "img_001", "alt": "screenshot"},
            ]
        })
    }
    atts = _extract_attachments(msg)
    assert len(atts) == 1, f"应有 1 个附件, got {len(atts)}"
    assert atts[0].kind == "image"
    assert atts[0].image_key == "img_001"

    # 文件
    msg = {
        "content": json.dumps({
            "items": [
                {"tag": "file", "file_key": "file_001", "name": "report.xlsx", "size": 12345},
            ]
        })
    }
    atts = _extract_attachments(msg)
    assert len(atts) == 1, f"应有 1 个附件, got {len(atts)}"
    assert atts[0].kind == "file"
    assert atts[0].file_key == "file_001"
    assert atts[0].size == 12345

    print("✅ 场景 11: 附件提取")


def test_12_full_render():
    """场景 12: 卡片渲染完整流程"""
    job = _job(
        state=HermesRunState.RUNNING,
        title="小红书运营",
        text="帮我写一个小红书文案",
        context_summary="MemoryX 已检索 5 条相关记忆",
        memoryx_badges=["MemoryX ✅", "Semantic ✅", "P13 ✅"],
        attachments=[
            AttachmentRef(kind="image", image_key="img_001", name="cover.png"),
        ],
        tools=[
            ToolCallRecord(
                name="memoryx_search",
                status="done",
                summary="召回 5 条记忆",
                duration_ms=23,
            ),
        ],
        answer="一、结论\n二、原因\n三、下一步",
    )
    renderer = FeishuCardRenderer()
    card = renderer.render(job)

    # 验证卡片结构
    assert card["header"]["template"] == "blue", f"应返回 blue, got {card['header']['template']}"
    assert "处理中" in card["header"]["title"]["content"], f"应包含 '处理中'"
    card_str = json.dumps(card, ensure_ascii=False)
    assert "MemoryX ✅" in card_str
    assert "memoryx_search" in card_str
    assert "一、结论" in card_str

    print("✅ 场景 12: 卡片渲染完整流程")


def main():
    print("=" * 50)
    print("P14.1 Feishu Production Hardening Smoke Test")
    print("=" * 50)

    tests = [
        test_1_event_dedupe,
        test_2_dlq_auto,
        test_3_max_attempts,
        test_4_queue_attachments,
        test_5_attachment_status,
        test_6_dlq_stats,
        test_7_state_transitions,
        test_8_queue_ops,
        test_9_extract_empty,
        test_10_extract_rich_text,
        test_11_extract_attachments,
        test_12_full_render,
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
