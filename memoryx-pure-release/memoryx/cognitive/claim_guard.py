from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s+|\n+")
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff\-\.]+", re.UNICODE)
_NEGATIONS = {"not", "no", "never", "cannot", "can't", "不会", "不是", "不能", "不要", "没有", "无"}
_SPECULATIVE = {"maybe", "might", "could", "可能", "也许", "大概", "或许", "猜测"}
_CODEISH = re.compile(r"^\s*(def |class |import |from |SELECT |UPDATE |INSERT |DELETE |CREATE |ALTER |```)", re.I)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "") if len(t.strip()) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _negation_parity(text: str) -> int:
    tokens = _tokens(text)
    return sum(1 for n in _NEGATIONS if n in tokens or n in text.lower()) % 2


@dataclass(slots=True)
class Claim:
    claim_id: str
    text: str
    normalized: str
    claim_type: str = "fact"
    confidence_score: float = 0.5


@dataclass(slots=True)
class Evidence:
    memory_id: str | None
    text: str
    source: str = "memoryx"
    score: float = 0.0
    verdict: str = "unknown"


@dataclass(slots=True)
class VerifiedClaim:
    claim: Claim
    status: str
    confidence_score: float
    evidence: list[Evidence] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class ClaimVerificationReport:
    run_id: str
    session_id: str | None
    question: str
    answer_hash: str
    claims: list[VerifiedClaim]
    supported_count: int
    contradicted_count: int
    unsupported_count: int
    risk_score: float
    action: str
    created_at: str

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClaimExtractor:
    def extract(self, answer: str, *, question: str = "", max_claims: int = 16) -> list[Claim]:
        pieces = []
        for raw in _SENTENCE_SPLIT.split(answer or ""):
            text = raw.strip(" \t\r\n-•")
            if not text or len(text) < 8:
                continue
            if _CODEISH.search(text):
                continue
            if text.endswith(":") and len(text.split()) < 8:
                continue
            pieces.append(text)

        claims: list[Claim] = []
        for text in pieces[: max_claims * 2]:
            claim_type = self._classify(text)
            confidence = 0.45 if any(s in text.lower() for s in _SPECULATIVE) else 0.65
            normalized = " ".join(sorted(_tokens(text)))[:500]
            if not normalized:
                continue
            claims.append(Claim(uuid4().hex, text, normalized, claim_type, confidence))
            if len(claims) >= max_claims:
                break
        return claims

    def _classify(self, text: str) -> str:
        lower = text.lower()
        if any(x in lower for x in ["before", "after", "last year", "this year", "去年", "今年", "之前", "之后", "多久", "duration"]):
            return "temporal"
        if any(x in lower for x in ["run ", "execute", "delete", "deploy", "rm -rf", "drop table", "执行", "删除", "部署"]):
            return "action"
        if any(x in lower for x in ["prefer", "like", "dislike", "喜欢", "不喜欢", "偏好", "认为", "觉得"]):
            return "preference"
        if "`" in text or any(x in lower for x in ["api", "function", "class", "sql", "python"]):
            return "code"
        return "fact"


class ClaimVerifier:
    def __init__(self, *, repository, retrieval_engine: Any | None = None, support_threshold: float = 0.34, contradiction_threshold: float = 0.42) -> None:
        self.repository = repository
        self.retrieval_engine = retrieval_engine
        self.extractor = ClaimExtractor()
        self.support_threshold = support_threshold
        self.contradiction_threshold = contradiction_threshold

    async def verify_answer(self, *, question: str, answer: str, session_id: str | None = None, store: bool = True, max_claims: int = 16) -> ClaimVerificationReport:
        claims = self.extractor.extract(answer, question=question, max_claims=max_claims)
        verified: list[VerifiedClaim] = []
        for claim in claims:
            evidence = await self._retrieve_evidence(claim, session_id=session_id)
            verified.append(self._judge(claim, evidence))

        supported = sum(1 for c in verified if c.status == "supported")
        contradicted = sum(1 for c in verified if c.status == "contradicted")
        unsupported = sum(1 for c in verified if c.status == "unsupported")
        denominator = max(1, len(verified))
        risk = min(1.0, (unsupported + 2.0 * contradicted) / (2.0 * denominator))
        action = "block" if contradicted > 0 or risk >= 0.65 else ("warn" if unsupported > 0 or risk >= 0.30 else "allow")
        report = ClaimVerificationReport(uuid4().hex, session_id, question, _sha256(answer), verified, supported, contradicted, unsupported, risk, action, _utcnow())
        if store:
            await self.persist_report(report)
        return report

    async def _retrieve_evidence(self, claim: Claim, *, session_id: str | None) -> list[Evidence]:
        if self.retrieval_engine is not None and hasattr(self.retrieval_engine, "retrieve"):
            try:
                results = await self.retrieval_engine.retrieve(
                    query=claim.text, query_vector=[], limit=5,
                    session_id=session_id, include_global=True, include_lessons=True, explain_scores=True
                )
                evidence = []
                for item in results:
                    memory_id = getattr(item, "memory_id", None) or getattr(item, "id", None)
                    text = getattr(item, "content", "") or ""
                    source = getattr(item, "memory_type", "memoryx") or "memoryx"
                    score = float(getattr(item, "final_score", 0.0) or 0.0)
                    evidence.append(Evidence(memory_id=memory_id, text=str(text), source=str(source), score=score))
                if evidence:
                    return evidence
            except Exception:
                pass

        try:
            rows = await self.repository.db.fetchall(
                """
                SELECT m.id AS memory_id, m.content AS content, m.memory_type AS memory_type
                FROM memories_fts f
                JOIN memories m ON m.rowid = f.rowid
                WHERE memories_fts MATCH ? AND m.active_state = 'active'
                LIMIT 5;
                """,
                (self._fts_query(claim.text),),
            )
        except Exception:
            rows = await self.repository.db.fetchall(
                """
                SELECT id AS memory_id, content, memory_type
                FROM memories
                WHERE active_state = 'active' AND content LIKE ?
                LIMIT 5;
                """,
                (f"%{claim.text[:80]}%",),
            )

        evidence = []
        claim_tokens = _tokens(claim.text)
        for row in rows:
            text = str(row["content"])
            get = row.get if hasattr(row, "get") else lambda k, d=None: row[k] if k in row.keys() else d
            evidence.append(Evidence(str(row["memory_id"]), text, str(get("memory_type", "memoryx")), _jaccard(claim_tokens, _tokens(text))))
        return evidence

    def _fts_query(self, text: str) -> str:
        toks = list(_tokens(text))[:8]
        return " OR ".join(toks) if toks else text[:80]

    def _judge(self, claim: Claim, evidence: list[Evidence]) -> VerifiedClaim:
        claim_tokens = _tokens(claim.text)
        if not evidence:
            return VerifiedClaim(claim, "unsupported", 0.35, [], "no evidence retrieved")

        judged: list[Evidence] = []
        best_score = 0.0
        best_verdict = "unknown"
        for ev in evidence:
            overlap = max(ev.score, _jaccard(claim_tokens, _tokens(ev.text)))
            neg_conflict = _negation_parity(claim.text) != _negation_parity(ev.text)
            verdict = "contradicts" if overlap >= self.contradiction_threshold and neg_conflict else ("supports" if overlap >= self.support_threshold else "unknown")
            judged.append(Evidence(ev.memory_id, ev.text, ev.source, overlap, verdict))
            if overlap > best_score:
                best_score, best_verdict = overlap, verdict

        if best_verdict == "contradicts":
            return VerifiedClaim(claim, "contradicted", min(0.95, 0.45 + best_score), judged, "retrieved evidence appears to contradict the claim")
        if best_verdict == "supports":
            return VerifiedClaim(claim, "supported", min(0.95, 0.45 + best_score), judged, "retrieved evidence supports the claim")
        return VerifiedClaim(claim, "unsupported", 0.35, judged, "retrieved evidence was insufficient")

    async def persist_report(self, report: ClaimVerificationReport) -> None:
        await self.repository.db.execute(
            """
            INSERT INTO claim_verification_runs(id, session_id, question, answer_hash, claim_count, supported_count, contradicted_count, unsupported_count, risk_score, action, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (report.run_id, report.session_id, report.question, report.answer_hash, report.claim_count, report.supported_count, report.contradicted_count, report.unsupported_count, report.risk_score, report.action, report.created_at, "{}"),
        )
        for vc in report.claims:
            await self.repository.db.execute(
                """
                INSERT INTO claims(id, run_id, session_id, claim_text, normalized_claim, claim_type, source, confidence_score, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, 'assistant', ?, ?, ?);
                """,
                (vc.claim.claim_id, report.run_id, report.session_id, vc.claim.text, vc.claim.normalized, vc.claim.claim_type, vc.confidence_score, vc.status, json.dumps({"reason": vc.reason}, ensure_ascii=False)),
            )
            for ev in vc.evidence:
                await self.repository.db.execute(
                    """
                    INSERT INTO claim_evidence(id, claim_id, memory_id, evidence_text, verdict, support_score, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (uuid4().hex, vc.claim.claim_id, ev.memory_id, ev.text, ev.verdict, ev.score, ev.source),
                )
            if vc.status in {"unsupported", "contradicted"}:
                severity = "high" if vc.status == "contradicted" else "medium"
                await self.repository.db.execute(
                    """
                    INSERT INTO hallucination_events(id, claim_id, session_id, severity, reason, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (uuid4().hex, vc.claim.claim_id, report.session_id, severity, vc.reason, json.dumps({"claim": vc.claim.text, "status": vc.status}, ensure_ascii=False)),
                )


def render_claim_guard_block(report: ClaimVerificationReport) -> str:
    if report.action == "allow":
        return ""
    lines = ["## MemoryX Claim Verification", f"Decision: {report.action.upper()}", f"Risk score: {report.risk_score:.2f}"]
    for vc in report.claims:
        if vc.status in {"unsupported", "contradicted"}:
            lines.append(f"- {vc.status.upper()}: {vc.claim.text}")
            lines.append(f"  Reason: {vc.reason}")
    lines.append("Instruction: do not present unsupported claims as facts; cite evidence or ask to verify.")
    return "\n".join(lines)
