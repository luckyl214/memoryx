#!/usr/bin/env python3
"""验证 P14.3 所有模块导入"""
from memoryx.feishu import (
    # Schemas
    AttachmentRef, FeishuRenderJob, HermesRunState, ToolCallRecord,
    VisibleState, ToolPhase, STATE_VIEW, get_visible_state,
    # State machine
    can_transition, assert_transition, get_state_display, ALLOWED_TRANSITIONS,
    # Update coalescer
    CardUpdateCoalescer, PendingCardUpdate,
    # Overflow
    CardOverflowPolicy, OverflowResult,
    # Attachment prepare
    AttachmentPreparer, PreparedAttachment,
    # Trace
    FeishuTraceStore,
    # Stream sanitizer
    StreamSanitizer,
    # Renderer
    FeishuCardRenderer, STATE_META, VISIBLE_STATE_META,
    # Client
    FeishuClient, FeishuAPIError,
    # Queue
    FeishuSQLiteQueue,
    # Bot service
    FeishuHermesBotService, HermesRunner,
    # Dedupe
    FeishuEventDedupe,
    # Event security
    verify_challenge, verify_signature, decrypt_event, parse_event_request,
    # Routes
    create_feishu_router,
    # Hermes runner
    RealHermesRunner, RunnerStage, StageReport,
)

print("✅ OK: memoryx.feishu import works — all exports OK")

# 验证状态机
from memoryx.feishu.state_machine import ALLOWED_TRANSITIONS as sm_at
assert ALLOWED_TRANSITIONS is sm_at
assert can_transition(VisibleState.RECEIVED, VisibleState.QUEUED)  # type: ignore
assert not can_transition(VisibleState.DONE, VisibleState.THINKING)  # type: ignore
print("✅ State machine: transitions validated")

# 验证溢出策略
policy = CardOverflowPolicy(max_chars=100, max_bytes=500)
result = policy.split("x" * 200)
assert result.overflow
assert len(result.card_text) <= 100
print("✅ Overflow: split works")

# 验证 coalescer
coalescer = CardUpdateCoalescer(min_interval=0.1)
print("✅ Coalescer: created")

# 验证附件预处理器
preparer = AttachmentPreparer()
print("✅ AttachmentPreparer: created")

# 验证 trace store
import tempfile
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    trace = FeishuTraceStore(f.name)
    trace.record(job_id="test", phase="test", event_type="test")
    events = trace.get_events("test")
    assert len(events) == 1
print("✅ FeishuTraceStore: works")

# 验证 renderer
renderer = FeishuCardRenderer()
job = FeishuRenderJob(
    chat_id="test",
    user_id=None,
    message_id=None,
    text="test",
    visible_state=VisibleState.THINKING,
    revision=5,
    phase="generate",
)
card = renderer.render(job)
assert card["header"]["template"] == "blue"
# "rev 5" 在 Trace field（index 2）中
trace_content = card["elements"][0]["fields"][2]["text"]["content"]
assert "rev 5" in trace_content, f"Expected 'rev 5' in Trace field, got: {trace_content}"
print("✅ FeishuCardRenderer: renders with revision")

print("\n🎉 All P14.3 modules verified successfully!")
