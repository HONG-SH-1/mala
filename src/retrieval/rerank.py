"""Lightweight rerank: semantic hits + keyword overlap (Phase 3 demo quality)."""

from __future__ import annotations

import re

from src.retrieval.chroma_store import SearchHit

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


def query_tokens(query: str) -> set[str]:
    q = query.lower()
    tokens = {t for t in _TOKEN_RE.findall(q) if len(t) > 1}
    if re.search(r"phase\s*2", q):
        tokens.update({"phase", "2", "phase-2", "phase2"})
    if re.search(r"phase\s*3", q):
        tokens.update({"phase", "3", "phase-3", "phase3"})
    return tokens


def _phase_source_boost(query: str, source: str) -> int:
    q = query.lower()
    s = source.lower()
    boost = 0
    if re.search(r"phase\s*2", q) and "phase-2" in s:
        boost += 8
    if re.search(r"phase\s*3", q) and "phase-3" in s:
        boost += 8
    return boost


def rerank_hits(query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    if not hits or top_k <= 0:
        return []
    tokens = query_tokens(query)

    def score(hit: SearchHit) -> tuple[int, float]:
        heading = hit.heading.lower()
        body = f"{hit.source} {hit.text}".lower()
        kw = _phase_source_boost(query, hit.source)
        for t in tokens:
            if t in heading:
                kw += 3
            elif t in body:
                kw += 1
        dist = hit.distance if hit.distance is not None else 1.0
        return (kw, -dist)

    ordered = sorted(hits, key=score, reverse=True)
    return ordered[:top_k]
