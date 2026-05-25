# memoryx/feishu/__init__.py
"""P14 Feishu UX Adapter — 飞书产品界面层

P14.1 生产硬化: 去重、DLQ、retry/backoff、事件安全
P14.2 附件落盘: 真实下载、sha256 哈希、spool 管理
P14.3 体验极致: 状态机、防乱序、溢出处理、附件预处理、全链路追踪
"""
from .schemas import (
    AttachmentRef,
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
    VisibleState,
    ToolPhase,
    STATE_VIEW,
    get_visible_state,
)
from .state_machine import (
    can_transition,
    assert_transition,
    get_state_display,
    ALLOWED_TRANSITIONS,
)
from .update_coalescer import CardUpdateCoalescer, PendingCardUpdate
from .overflow import CardOverflowPolicy, OverflowResult
from .attachment_prepare import AttachmentPreparer, PreparedAttachment
from .trace import FeishuTraceStore
from .stream_sanitizer import StreamSanitizer
from .renderer import FeishuCardRenderer, STATE_META, VISIBLE_STATE_META
from .client import FeishuClient, FeishuAPIError
from .queue import FeishuSQLiteQueue
from .bot_service import FeishuHermesBotService, HermesRunner
from .dedupe import FeishuEventDedupe
from .event_security import (
    verify_challenge,
    verify_signature,
    decrypt_event,
    parse_event_request,
)
from .routes import create_feishu_router
from .hermes_runner import HermesRunner as RealHermesRunner, RunnerStage, StageReport

__all__ = [
    # Schemas
    "AttachmentRef",
    "FeishuRenderJob",
    "HermesRunState",
    "ToolCallRecord",
    "VisibleState",
    "ToolPhase",
    "STATE_VIEW",
    "get_visible_state",
    # State machine
    "can_transition",
    "assert_transition",
    "get_state_display",
    "ALLOWED_TRANSITIONS",
    # Update coalescer
    "CardUpdateCoalescer",
    "PendingCardUpdate",
    # Overflow
    "CardOverflowPolicy",
    "OverflowResult",
    # Attachment prepare
    "AttachmentPreparer",
    "PreparedAttachment",
    # Trace
    "FeishuTraceStore",
    # Stream sanitizer
    "StreamSanitizer",
    # Renderer
    "FeishuCardRenderer",
    "STATE_META",
    "VISIBLE_STATE_META",
    # Client
    "FeishuClient",
    "FeishuAPIError",
    # Queue
    "FeishuSQLiteQueue",
    # Bot service
    "FeishuHermesBotService",
    "HermesRunner",
    # Dedupe
    "FeishuEventDedupe",
    # Event security
    "verify_challenge",
    "verify_signature",
    "decrypt_event",
    "parse_event_request",
    # Routes
    "create_feishu_router",
    # Hermes runner
    "RealHermesRunner",
    "RunnerStage",
    "StageReport",
]
