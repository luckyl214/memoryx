from __future__ import annotations

import pytest
from memoryx.cognitive.claim_guard import ClaimVerifier


class FakeDB:
    def __init__(self):
        self.inserted = []
        self.rows = [{"memory_id": "m1", "content": "MemoryX uses SQLite WAL and FTS5 for storage and retrieval.", "memory_type": "FACT"}]

    async def fetchall(self, sql, params=()):
        if "memories_fts" in sql or "FROM memories" in sql:
            return self.rows
        return []

    async def execute(self, sql, params=()):
        self.inserted.append((sql, params))


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


@pytest.mark.asyncio
async def test_claim_verifier_marks_supported_and_persists():
    repo = FakeRepo()
    verifier = ClaimVerifier(repository=repo)
    report = await verifier.verify_answer(question="What does MemoryX use?", answer="MemoryX uses SQLite WAL and FTS5 for storage and retrieval.", session_id="s1", store=True)
    assert report.claim_count == 1
    assert report.supported_count == 1
    assert report.action == "allow"
    assert repo.db.inserted


@pytest.mark.asyncio
async def test_claim_verifier_warns_on_unsupported_claim():
    repo = FakeRepo()
    repo.db.rows = []
    verifier = ClaimVerifier(repository=repo)
    report = await verifier.verify_answer(question="What is the current CEO?", answer="The CEO is Jane Example and the company has 900 employees.", session_id="s1", store=False)
    assert report.unsupported_count >= 1
    assert report.action in {"warn", "block"}
