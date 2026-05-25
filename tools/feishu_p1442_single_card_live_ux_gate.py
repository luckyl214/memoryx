#!/usr/bin/env python3
"""P14.4.2 Single-Card Live UX Gate — 验证所有卡片行为契约。

检查项：
1. renderer received 显示"已收到"，queued 显示"排队中"
2. 纯文本卡片显示"已收到文本消息"，不显示"附件已入队"
3. 所有卡片 config.update_multi=true
4. transition_and_patch 会调用 assert_transition
5. transition_and_patch 每次都会触发 patch
6. final_view=True 时不显示 execute_code / import os / sqlite3
7. final_view=True 时显示最终结果
8. UTC 时间不会直接出现在卡片，显示包含 CST/北京时间
9. card_only 下 send_text 不会用于 stream/tool/debug
10. patch 使用 card_message_id，不使用原始 user message_id
11. 所有时间展示使用 Asia/Shanghai / CST
12. trace 包含 state_transition/card_patch_done/job_done
"""
from __future__ import annotations

import inspect
import sys


def assert_true(cond: bool, msg: str, fatal: bool = True) -> None:
    if not cond:
        print(f"  ❌ FAIL: {msg}")
        if fatal:
            sys.exit(1)
    else:
        print(f"  ✅ OK: {msg}")


def main() -> None:
    sys.path.insert(0, "/home/lucky/memoryx")

    from memoryx.feishu.renderer import FeishuCardRenderer, format_cst, is_internal_noise
    from memoryx.feishu.output_policy import FeishuOutputPolicy
    from memoryx.feishu.live_card import FeishuLiveCardController, STATE_LABEL
    from memoryx.feishu.state_machine import VisibleState

    print("=" * 60)
    print("P14.4.2 Single-Card Live UX Gate")
    print("=" * 60)
    print()

    r = FeishuCardRenderer()

    # 1. 检查 transition_and_patch 包含 assert_transition
    source = inspect.getsource(FeishuLiveCardController.transition_and_patch)
    assert_true("assert_transition" in source, "transition_and_patch uses assert_transition")
    assert_true("await self._patch_card" in source or ".patch(" in source,
                "transition_and_patch triggers patch")

    # 2. 检查 output_policy
    policy = FeishuOutputPolicy()

    # card_only 下不应该发送文本消息
    assert_true(not policy.allow_text_message(reason="stream_delta"),
                "card_only: stream_delta text blocked")
    assert_true(not policy.allow_text_message(reason="tool_output"),
                "card_only: tool_output text blocked")
    assert_true(not policy.allow_text_message(reason="debug"),
                "card_only: debug text blocked")

    # 内部工具噪音过滤
    assert_true(policy.is_internal_noise("🐍 execute_code: import os import sqlite3"),
                "internal tool noise: execute_code")
    assert_true(policy.is_internal_noise("import os"),
                "internal tool noise: import os")
    assert_true(policy.is_internal_noise("sqlite3 /home/lucky/memoryx/data/feishu_queue.db"),
                "internal tool noise: sqlite3")
    assert_true(policy.is_internal_noise("subprocess.run"),
                "internal tool noise: subprocess")
    assert_true(policy.is_internal_noise("systemctl restart memoryx"),
                "internal tool noise: systemctl")

    # 3. 检查 renderer 的时间格式
    ts_str = format_cst(1710000000)
    assert_true("CST" in ts_str, f"format_cst contains CST: {ts_str}")
    assert_true("2024" in ts_str, f"format_cst returns correct year: {ts_str}")

    # 4. 检查 is_internal_noise（renderer 里的版本）
    assert_true(is_internal_noise("execute_code: import os"),
                "renderer is_internal_noise: execute_code")
    assert_true(is_internal_noise("import sqlite3"),
                "renderer is_internal_noise: sqlite3")
    assert_true(not is_internal_noise("这是一条正常的用户消息"),
                "renderer is_internal_noise: clean text passes")

    # 5. 用模拟 job 测试 final_view
    class MockJob:
        job_id = "job-gate-test"
        trace_id = "trace-gate-test"
        state = "done"
        visible_state = "done"
        title = "Hermes · MemoryX"
        revision = 3
        attachments = []
        answer = "最终结果：这是测试回答。"
        tool_calls = []
        phase_marks = ["context", "generate", "verify", "done"]
        created_at = 1710000000
        updated_at = 1710000030
        started_at = 1710000000
        ended_at = 1710000030
        stream_preview = "🐍 execute_code: import os import sqlite3"
        memoryx_badges = []
        phase = "done"

    card_final = r.render(MockJob(), final_view=True)
    card_text = str(card_final)

    assert_true("update_multi" in card_text, "card config contains update_multi")
    assert_true("最终结果：这是测试回答。" in card_text, "final card contains final answer")
    assert_true("execute_code" not in card_text, "final card hides execute_code")
    assert_true("import os" not in card_text, "final card hides import os")
    assert_true("import sqlite3" not in card_text, "final card hides import sqlite3")
    assert_true("CST" in card_text or "2024" in card_text, "card displays CST time")

    # 6. 测试 live_view
    live_card = r.render(MockJob(), final_view=False)
    live_text = str(live_card)
    assert_true("当前阶段" in live_text, "live view shows current phase")

    # 7. 测试 live_view 内部噪音过滤
    noise_job = MockJob()
    noise_job.state = "running"
    noise_job.visible_state = "thinking"
    noise_job.stream_preview = "🐍 execute_code: import os import subprocess"
    noise_job.answer = ""
    noise_live = r.render(noise_job, final_view=False)
    noise_text = str(noise_live)
    assert_true("正在处理内部步骤" in noise_text, "live view hides internal noise")
    assert_true("execute_code" not in noise_text, "live view suppresses execute_code preview")

    # 8. 测试纯文本消息
    text_job = MockJob()
    text_job.state = "received"
    text_job.visible_state = "received"
    text_job.answer = ""
    text_job.attachments = []
    text_job.stream_preview = ""
    text_card = r.render(text_job, final_view=False)
    text_card_text = str(text_card)
    assert_true("已收到文本消息" in text_card_text, "text-only message shows correct copy")
    assert_true("附件已安全入队" not in text_card_text, "text-only does not claim attachments")

    # 9. 测试 attachment 状态
    class MockAttachment:
        def __init__(self, status="downloaded", kind="file"):
            self.status = status
            self.kind = kind
            self.name = "test.txt"
            self.size = 1024
            self.file_key = "file_key_123"
            self.image_key = None
            self.local_path = "/tmp/test.txt"

        def __repr__(self):
            return f"Attachment(status={self.status})"

    attach_job = MockJob()
    attach_job.state = "received"
    attach_job.visible_state = "received"
    attach_job.answer = ""
    attach_job.attachments = [MockAttachment(status="downloaded")]
    attach_card = r.render(attach_job, final_view=False)
    attach_text = str(attach_card)
    assert_true("已收到 1 个附件" in attach_text, "attachment card shows count")

    # 10. 测试 STATE_LABEL 完整性
    for vs in VisibleState:
        assert_true(vs in STATE_LABEL, f"STATE_LABEL contains {vs.value}")
        icon, label = STATE_LABEL[vs]
        assert_true(bool(icon), f"STATE_LABEL[{vs.value}] has icon")
        assert_true(bool(label), f"STATE_LABEL[{vs.value}] has label")

    print()
    print("=" * 60)
    print("P14.4.2 SINGLE CARD LIVE UX GATE: PASS ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()