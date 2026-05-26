from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from memoryx.search.rate_limiter import AdaptiveConcurrencyLimiter


LLMSummarizer = Callable[[str, str], Awaitable[str]]


@dataclass(slots=True)
class SessionCandidate:
    session_id: str
    summary: str
    content_hash: str
    score: float
    started_at: str | None = None
    ended_at: str | None = None


@dataclass(slots=True)
class SessionSearchResult:
    session_id: str
    answer: str
    score: float
    source: str
    degraded: bool = False
    error: str = ""


class SessionSearchEngine:
    """高效 session 搜索：先索引、再精排、少调用、可降级、可观测。"""

    def __init__(
        self,
        *,
        db_path: str | Path,
        llm_summarize: LLMSummarizer | None = None,
        limiter: AdaptiveConcurrencyLimiter | None = None,
        max_sessions: int = 10,
        max_llm_sessions: int = 5,
        per_session_timeout: float = 18.0,
        total_timeout: float = 30.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.llm_summarize = llm_summarize
        self.limiter = limiter or AdaptiveConcurrencyLimiter(initial=6, min_limit=2, max_limit=8)
        self.max_sessions = max_sessions
        self.max_llm_sessions = max_llm_sessions
        self.per_session_timeout = per_session_timeout
        self.total_timeout = total_timeout

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    async def search(self, query: str) -> dict[str, Any]:
        started = time.perf_counter()
        query_hash = self._query_hash(query)
        candidates = self._candidate_search(query, limit=self.max_sessions)

        cache_hits = 0
        fallback_count = 0
        rate_limit_count = 0
        timeout_count = 0

        if not candidates:
            result = {
                "query": query,
                "results": [],
                "degraded": False,
                "reason": "no_candidates",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "stats": {
                    "candidate_count": 0,
                    "llm_sessions": 0,
                    "cache_hits": 0,
                    "fallback_count": 0,
                    "rate_limit_count": 0,
                    "timeout_count": 0,
                },
            }
            self._record_event(query_hash, result["stats"], result["duration_ms"])
            return result

        top_for_llm = candidates[: self.max_llm_sessions]
        rest = candidates[self.max_llm_sessions :]

        llm_results: list[SessionSearchResult] = []

        if self.llm_summarize is not None:
            try:
                llm_results = await asyncio.wait_for(
                    self._summarize_candidates(query, top_for_llm),
                    timeout=self.total_timeout,
                )
            except asyncio.TimeoutError:
                await self.limiter.on_timeout()
                timeout_count = len(top_for_llm)
                llm_results = [self._fallback_result(c, reason="total_timeout") for c in top_for_llm]
            except Exception as exc:
                if self._is_rate_limit(exc):
                    await self.limiter.on_rate_limit()
                    rate_limit_count = len(top_for_llm)
                llm_results = [self._fallback_result(c, reason=f"provider_error:{exc}") for c in top_for_llm]
        else:
            llm_results = [self._fallback_result(c, reason="llm_disabled") for c in top_for_llm]

        rest_results = [self._fallback_result(c, reason="not_in_llm_top_k") for c in rest]

        results = sorted(
            [*llm_results, *rest_results],
            key=lambda x: x.score,
            reverse=True,
        )

        # Count stats
        cache_hits = sum(1 for r in results if r.source == "cache")
        fallback_count = sum(1 for r in results if r.degraded)

        duration_ms = int((time.perf_counter() - started) * 1000)

        stats = {
            "candidate_count": len(candidates),
            "llm_sessions": len(top_for_llm),
            "cache_hits": cache_hits,
            "fallback_count": fallback_count,
            "rate_limit_count": rate_limit_count,
            "timeout_count": timeout_count,
        }

        result = {
            "query": query,
            "results": [r.__dict__ for r in results],
            "degraded": any(r.degraded for r in results),
            "limiter": await self.limiter.snapshot(),
            "duration_ms": duration_ms,
            "stats": stats,
        }

        self._record_event(query_hash, stats, duration_ms)
        return result

    def _candidate_search(self, query: str, *, limit: int) -> list[SessionCandidate]:
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT idx.session_id, idx.summary, idx.content_hash,
                           idx.started_at, idx.ended_at,
                           bm25(session_search_fts) AS rank
                    FROM session_search_fts
                    JOIN session_search_index idx
                      ON idx.session_id = session_search_fts.session_id
                    WHERE session_search_fts MATCH ?
                      AND idx.active_state='active'
                    ORDER BY rank
                    LIMIT ?;
                    """,
                    (self._fts_query(query), int(limit)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT session_id, summary, content_hash, started_at, ended_at
                    FROM session_search_index
                    WHERE active_state='active'
                      AND (summary LIKE ? OR title LIKE ? OR keywords_json LIKE ?)
                    ORDER BY updated_at DESC
                    LIMIT ?;
                    """,
                    (f"%{query}%", f"%{query}%", f"%{query}%", int(limit)),
                ).fetchall()

        candidates: list[SessionCandidate] = []
        for i, row in enumerate(rows):
            rank = float(row["rank"]) if "rank" in row.keys() else float(i + 1)
            score = 1.0 / (1.0 + abs(rank))
            candidates.append(
                SessionCandidate(
                    session_id=row["session_id"],
                    summary=row["summary"],
                    content_hash=row["content_hash"],
                    score=score,
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                )
            )

        return candidates

    async def _summarize_candidates(
        self, query: str, candidates: list[SessionCandidate],
    ) -> list[SessionSearchResult]:
        sem = await self.limiter.limit()

        async def one(candidate: SessionCandidate) -> SessionSearchResult:
            cached = self._cache_get(query, candidate)
            if cached:
                return SessionSearchResult(
                    session_id=candidate.session_id,
                    answer=cached,
                    score=candidate.score,
                    source="cache",
                    degraded=False,
                )

            async with sem:
                try:
                    answer = await asyncio.wait_for(
                        self.llm_summarize(query, candidate.summary),  # type: ignore[misc]
                        timeout=self.per_session_timeout,
                    )
                    self._cache_put(query, candidate, answer)
                    await self.limiter.on_success()
                    return SessionSearchResult(
                        session_id=candidate.session_id,
                        answer=answer,
                        score=candidate.score,
                        source="llm",
                        degraded=False,
                    )
                except asyncio.TimeoutError:
                    await self.limiter.on_timeout()
                    return self._fallback_result(candidate, reason="timeout")
                except Exception as exc:
                    if self._is_rate_limit(exc):
                        await self.limiter.on_rate_limit()
                        return self._fallback_result(candidate, reason="rate_limit")
                    return self._fallback_result(candidate, reason=f"error:{exc}")

        return await asyncio.gather(*(one(c) for c in candidates))

    def _fallback_result(self, candidate: SessionCandidate, *, reason: str) -> SessionSearchResult:
        return SessionSearchResult(
            session_id=candidate.session_id,
            answer=candidate.summary,
            score=candidate.score * 0.92,
            source=f"index_summary:{reason}",
            degraded=True,
            error=reason,
        )

    def _cache_get(self, query: str, candidate: SessionCandidate) -> str | None:
        query_hash = self._query_hash(query)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT answer FROM session_search_cache
                WHERE query_hash=? AND session_id=? AND content_hash=?
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                LIMIT 1;
                """,
                (query_hash, candidate.session_id, candidate.content_hash),
            ).fetchone()
            return str(row["answer"]) if row else None

    def _cache_put(self, query: str, candidate: SessionCandidate, answer: str) -> None:
        query_hash = self._query_hash(query)
        cache_id = hashlib.sha256(
            f"{query_hash}:{candidate.session_id}:{candidate.content_hash}".encode()
        ).hexdigest()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_search_cache(
                    id, query_hash, session_id, content_hash, answer, score, model, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'auxiliary', datetime('now', '+72 hours'));
                """,
                (cache_id, query_hash, candidate.session_id, candidate.content_hash, answer, candidate.score),
            )

    def _query_hash(self, query: str) -> str:
        return hashlib.sha256((" ".join(query.lower().split())).encode()).hexdigest()

    def _fts_query(self, query: str) -> str:
        terms = [x for x in query.replace('"', " ").split() if x.strip()]
        if not terms:
            return query
        return " OR ".join(terms[:12])

    def _is_rate_limit(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "too many requests" in text

    def _record_event(self, query_hash: str, stats: dict, duration_ms: int) -> None:
        """Record search event to session_search_events table for P17 monitoring."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO session_search_events(
                        id, query_hash, candidate_count, llm_sessions, cache_hits,
                        fallback_count, rate_limit_count, timeout_count, duration_ms,
                        created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?);
                    """,
                    (
                        hashlib.sha256(f"{query_hash}:{time.time()}".encode()).hexdigest(),
                        query_hash,
                        stats["candidate_count"],
                        stats["llm_sessions"],
                        stats["cache_hits"],
                        stats["fallback_count"],
                        stats["rate_limit_count"],
                        stats["timeout_count"],
                        duration_ms,
                        json.dumps({}),
                    ),
                )
        except Exception:
            pass  # Don't let event recording fail the search