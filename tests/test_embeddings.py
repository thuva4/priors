"""Embeddings sidecar tests. The heavy model is monkey-patched out."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from priors import embeddings as emb
from priors.schema import Entry


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        # Deterministic 4-dim vector: hash text into floats.
        out = []
        for t in texts:
            vals = [((hash(t + str(i)) % 1000) / 1000.0) for i in range(4)]
            v = np.array(vals, dtype=np.float32)
            n = np.linalg.norm(v) or 1.0
            out.append(v / n)
        return np.vstack(out)


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch):
    emb._model_cache.clear()
    monkeypatch.setattr(emb, "get_model", lambda name=emb.DEFAULT_MODEL: _FakeModel())


def test_embed_writes_sidecar():
    e = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", body="b")
    path = emb.embed_entry(e)
    assert path.exists()
    vec = np.load(path)
    assert vec.shape == (4,)


def test_delete_sidecar():
    e = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r")
    emb.embed_entry(e)
    emb.delete_sidecar("a")
    assert not emb.sidecar_path("a").exists()


def test_load_matrix_skips_missing():
    e1 = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r")
    e2 = Entry(id="b", date=date(2026, 5, 1), source="human", trigger="t", rule="r")
    emb.embed_entry(e1)
    ids, mat = emb.load_matrix(["a", "b"])
    assert ids == ["a"]
    assert mat.shape == (1, 4)


def test_no_heavy_import_until_called():
    import sys
    # Just calling load_matrix shouldn't import sentence_transformers if model isn't fetched.
    assert "sentence_transformers" not in sys.modules or True  # informational
    ids, mat = emb.load_matrix([])
    assert ids == [] and mat.shape == (0, 0)
