from __future__ import annotations

from memoryx.observability.metrics import record_llm_safety_event, record_rest_request


def test_metric_helpers_use_canonical_labels():
    record_rest_request(route="/live", method="GET", status_code=200)
    record_llm_safety_event(surface="tool_call", decision="allow", severity="low")
