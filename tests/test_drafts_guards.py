from __future__ import annotations

import json
from datetime import date

import numpy as np
import pytest

from priors import drafts as drafts_mod
from priors import store
from priors.paths import draft_rate_path, drafts_dir
from priors.schema import Entry


def _fake_embed_orthogonal(texts):
    """Returns an orthonormal-ish vector keyed by hash. Identical text → identical vec."""
    out = []
    for t in texts:
        rng = np.random.default_rng(abs(hash(t)) % (2**32))
        v = rng.normal(size=8).astype(np.float32)
        v /= np.linalg.norm(v) or 1.0
        out.append(v)
    return np.vstack(out)


def _fake_embed_constant(texts):
    return np.vstack([np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)] * len(texts))


def _propose(**overrides):
    args = dict(
        trigger="never call async inside forEach",
        body="> never use forEach with async\nbody text",
        rule="use for...of",
        tags=["javascript"],
        model="claude-opus-4-7",
        severity="silent-bug",
        embed_fn=_fake_embed_orthogonal,
    )
    args.update(overrides)
    return drafts_mod.propose(**args)


def test_happy_path_writes_draft():
    res = _propose()
    assert "draft_id" in res
    assert (drafts_dir() / f"{res['draft_id']}.md").exists()


def test_severity_too_low():
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose(severity="nit")
    assert exc.value.code == "severity_too_low"
    assert not any(drafts_dir().glob("*.md"))


def test_missing_quoted_correction():
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose(body="no quoted line here\njust text")
    assert exc.value.code == "missing_quoted_correction"


def test_missing_tags():
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose(tags=[])
    assert exc.value.code == "missing_tags"


def test_session_limit():
    _propose()
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose(session_count=1, trigger="something totally different here please")
    assert exc.value.code == "session_limit"


def test_dedup_against_existing_entry():
    store.write(
        Entry(
            id="2026-05-01-existing",
            date=date(2026, 5, 1),
            source="human",
            trigger="never call async inside forEach",
            rule="x",
        )
    )
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose()
    assert exc.value.code == "similar_entry_exists"
    assert exc.value.extra["similar_entry_exists"] == "2026-05-01-existing"


def test_rate_limit_across_sessions():
    for i in range(3):
        _propose(trigger=f"unique trigger number {i} alpha beta gamma")
    # 4th attempt: simulate a brand-new session (session_count=0), still blocked by global rate.
    with pytest.raises(drafts_mod.DraftError) as exc:
        _propose(trigger="something completely unseen delta epsilon zeta")
    assert exc.value.code == "rate_limit_reached"


def test_rate_limit_persistence():
    _propose()
    data = json.loads(draft_rate_path().read_text())
    assert len(data["timestamps"]) == 1
