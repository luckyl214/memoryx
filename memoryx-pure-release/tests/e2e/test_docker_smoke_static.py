from __future__ import annotations

from pathlib import Path


def test_dockerfile_uses_uvicorn_rest_entrypoint_and_healthcheck():
    root = Path(__file__).resolve().parents[2]
    dockerfile = root / "Dockerfile"
    assert dockerfile.exists()

    text = dockerfile.read_text(encoding="utf-8")
    assert "uvicorn" in text
    assert "memoryx.api.rest_app:app" in text
    assert "--port" in text and "8080" in text
    assert "HEALTHCHECK" in text or "/live" in text
