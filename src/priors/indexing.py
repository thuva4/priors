from __future__ import annotations

import logging

from priors import config as config_mod
from priors.schema import Entry

log = logging.getLogger(__name__)


def index_entry(entry: Entry) -> None:
    """Embed an entry's text if embeddings retrieval is enabled. Silent no-op otherwise."""
    mode = config_mod.get("retrieval.mode") or "embeddings"
    if mode == "bm25":
        return
    try:
        from priors import embeddings as emb
        emb.embed_entry(entry)
    except Exception as exc:  # pragma: no cover - resilience path
        log.warning("embedding failed for %s: %s", entry.id, exc)


def remove_index(entry_id: str) -> None:
    try:
        from priors import embeddings as emb
        emb.delete_sidecar(entry_id)
    except Exception as exc:  # pragma: no cover
        log.warning("removing embedding for %s failed: %s", entry_id, exc)
