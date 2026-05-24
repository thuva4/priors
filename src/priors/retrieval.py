from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import Literal

import numpy as np

from priors import config as config_mod
from priors import embeddings as emb
from priors import store
from priors.schema import Entry

Mode = Literal["embeddings", "bm25", "hybrid"]


@dataclass
class Filters:
    tags: list[str] = field(default_factory=list)
    stacks: set[str] = field(default_factory=set)
    scope: str | None = None
    source: str | None = None
    since: str | None = None


@dataclass
class ScoredEntry:
    entry: Entry
    score: float


def search(
    query: str,
    k: int = 5,
    filters: Filters | None = None,
    mode: Mode | None = None,
) -> list[ScoredEntry]:
    if not query.strip():
        return []
    if mode is None:
        cfg_mode = config_mod.get("retrieval.mode") or "embeddings"
        mode = cfg_mode if cfg_mode in ("embeddings", "bm25", "hybrid") else "embeddings"

    entries = _filtered_entries(filters)
    if not entries:
        return []

    if mode == "embeddings":
        scored = _embeddings_score(query, entries)
    elif mode == "bm25":
        scored = _bm25_score(query, entries)
    else:
        scored = _hybrid_score(query, entries)

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:k]


def _filtered_entries(f: Filters | None) -> list[Entry]:
    entries = store.load_all()
    if f is None:
        return entries
    if f.tags:
        tagset = set(f.tags)
        entries = [e for e in entries if tagset.issubset(set(e.tags))]
    if f.stacks:
        entries = [
            e for e in entries
            if not e.stacks or set(e.stacks) & f.stacks
        ]
    if f.scope:
        entries = [e for e in entries if e.scope == f.scope]
    if f.source:
        entries = [e for e in entries if e.source == f.source]
    if f.since:
        cutoff = store._parse_since(f.since)
        entries = [e for e in entries if e.date >= cutoff]
    return entries


def _embeddings_score(query: str, entries: list[Entry]) -> list[ScoredEntry]:
    ids = [e.id for e in entries]
    have_ids, matrix = emb.load_matrix(ids)
    if not have_ids:
        return _bm25_score(query, entries)
    qvec = emb.encode([query])[0]
    sims = matrix @ qvec
    by_id = {eid: float(sims[i]) for i, eid in enumerate(have_ids)}
    out: list[ScoredEntry] = []
    missing: list[Entry] = []
    for e in entries:
        if e.id in by_id:
            out.append(ScoredEntry(e, by_id[e.id]))
        else:
            missing.append(e)
    if missing:
        # If some entries lack sidecars, fall back to BM25 for them and rescale.
        fallback = _bm25_score(query, missing)
        # BM25 scores are unbounded; squash to [0, 0.5) so embeddings dominate.
        for se in fallback:
            se.score = min(0.49, se.score / 10.0)
            out.append(se)
    return out


def _bm25_score(query: str, entries: list[Entry]) -> list[ScoredEntry]:
    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(_doc_text(e)) for e in entries]
    if not any(corpus):
        return [ScoredEntry(e, 0.0) for e in entries]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    return [ScoredEntry(e, float(s)) for e, s in zip(entries, scores)]


def _hybrid_score(query: str, entries: list[Entry]) -> list[ScoredEntry]:
    # Reciprocal Rank Fusion.
    emb_ranked = sorted(_embeddings_score(query, entries), key=lambda s: s.score, reverse=True)
    bm_ranked = sorted(_bm25_score(query, entries), key=lambda s: s.score, reverse=True)
    k = 60.0
    fused: dict[str, float] = {}
    for rank, se in enumerate(emb_ranked):
        fused[se.entry.id] = fused.get(se.entry.id, 0.0) + 1.0 / (k + rank)
    for rank, se in enumerate(bm_ranked):
        fused[se.entry.id] = fused.get(se.entry.id, 0.0) + 1.0 / (k + rank)
    by_id = {e.id: e for e in entries}
    return [ScoredEntry(by_id[eid], score) for eid, score in fused.items()]


def _doc_text(e: Entry) -> str:
    return f"{e.trigger} {e.rule} {e.body} {' '.join(e.tags)} {' '.join(e.stacks)}"


def _tokenize(text: str) -> list[str]:
    return [t for t in (
        ''.join(c.lower() if c.isalnum() else ' ' for c in text).split()
    ) if t]
