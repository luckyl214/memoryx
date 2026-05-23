"""P2: PII filter tests."""

from __future__ import annotations

import pytest

from memoryx.pii_filter import PIIFilter


@pytest.fixture
def pii() -> PIIFilter:
    return PIIFilter(secret="test-secret")


def test_detect_email(pii: PIIFilter):
    result = pii.detect("Contact me at test@example.com for details")
    assert result.has_pii
    assert result.detected_count == 1
    assert result.spans[0].type == "email"
    assert "test@example.com" not in result.anonymized_text


def test_detect_phone_cn(pii: PIIFilter):
    result = pii.detect("Call 13812345678 for support")
    assert result.has_pii
    assert result.spans[0].type == "phone_cn"
    assert "13812345678" not in result.anonymized_text


def test_detect_cn_id(pii: PIIFilter):
    result = pii.detect("ID: 110101199001011234")
    assert result.has_pii
    assert result.spans[0].type == "cn_id"


def test_detect_ipv4(pii: PIIFilter):
    result = pii.detect("Server at 192.168.1.100 is down")
    assert result.has_pii
    assert result.spans[0].type == "ipv4"


def test_detect_api_key(pii: PIIFilter):
    result = pii.detect("api_key=sk-abcdefghijklmnopqrstuv")
    assert result.has_pii
    assert result.spans[0].type == "api_key"


def test_detect_bearer(pii: PIIFilter):
    result = pii.detect("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc")
    assert result.has_pii
    assert result.spans[0].type == "bearer"


def test_no_pii_on_clean_text(pii: PIIFilter):
    result = pii.detect("This is a normal sentence without any PII.")
    assert not result.has_pii
    assert result.detected_count == 0
    assert result.anonymized_text == result.original_text


def test_multiple_pii(pii: PIIFilter):
    result = pii.detect("Email a@b.com, phone 13900001111, IP 10.0.0.1")
    assert result.detected_count == 3


def test_hmac_deterministic(pii: PIIFilter):
    """Same input → same anonymized output."""
    text = "Email me at test@example.com"
    r1 = pii.filter(text)
    r2 = pii.filter(text)
    assert r1 == r2


def test_hmac_different_for_different_inputs(pii: PIIFilter):
    r1 = pii.anonymize("a@b.com")
    r2 = pii.anonymize("c@d.com")
    assert r1 != r2


def test_filter_convenience(pii: PIIFilter):
    result = pii.filter("Email: hello@world.com")
    assert "hello@world.com" not in result
    assert result.startswith("Email: <")
