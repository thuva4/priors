from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from priors.paths import priors_home
from priors.schema import Entry

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

DEFAULT_MODEL = "all-MiniLM-L6-v2"

_model_cache: dict[str, "SentenceTransformer"] = {}


def embeddings_dir() -> Path:
    return priors_home() / "embeddings"


def sidecar_path(entry_id: str) -> Path:
    return embeddings_dir() / f"{entry_id}.npy"


def text_for(entry: Entry) -> str:
    body_prefix = entry.body[:500]
    return f"{entry.trigger}\n{entry.rule}\n{body_prefix}"


def get_model(name: str = DEFAULT_MODEL) -> "SentenceTransformer":
    if name not in _model_cache:
        from sentence_transformers import SentenceTransformer  # heavy import
        log.info("loading sentence-transformers model %s", name)
        _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


def encode(texts: list[str], model_name: str = DEFAULT_MODEL) -> np.ndarray:
    model = get_model(model_name)
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def embed_entry(entry: Entry, model_name: str = DEFAULT_MODEL) -> Path:
    embeddings_dir().mkdir(parents=True, exist_ok=True)
    vec = encode([text_for(entry)], model_name=model_name)[0]
    path = sidecar_path(entry.id)
    np.save(path, vec)
    return path


def delete_sidecar(entry_id: str) -> None:
    p = sidecar_path(entry_id)
    if p.exists():
        p.unlink()


def load_matrix(entry_ids: list[str]) -> tuple[list[str], np.ndarray]:
    """Load sidecar vectors for the given ids. Missing sidecars are skipped."""
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    for eid in entry_ids:
        p = sidecar_path(eid)
        if not p.exists():
            continue
        vecs.append(np.load(p))
        ids.append(eid)
    if not vecs:
        return [], np.zeros((0, 0), dtype=np.float32)
    return ids, np.vstack(vecs).astype(np.float32)
