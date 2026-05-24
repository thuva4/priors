from __future__ import annotations

import json
import logging
import re
import secrets
import time
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter
import numpy as np

from priors import config as config_mod
from priors.paths import (
    draft_rate_path,
    drafts_dir,
    rejected_drafts_dir,
)
from priors.schema import (
    SEVERITIES,
    Entry,
    SchemaError,
    entry_from_frontmatter,
    slugify,
)
from priors import store

log = logging.getLogger(__name__)

ALLOWED_DRAFT_SEVERITIES = ("misleading", "silent-bug", "silent-prod-bug")
DEDUP_THRESHOLD = 0.85
RATE_LIMIT_PER_DAY = 3
RATE_LIMIT_WINDOW_SEC = 24 * 60 * 60


class DraftError(Exception):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        out = {"error": self.code, "message": self.message}
        out.update(self.extra)
        return out


def draft_path(draft_id: str) -> Path:
    return drafts_dir() / f"{draft_id}.md"


def load_drafts() -> list[Entry]:
    d = drafts_dir()
    if not d.exists():
        return []
    out: list[Entry] = []
    for p in sorted(d.glob("*.md")):
        if not p.is_file():
            continue
        try:
            post = frontmatter.load(str(p))
            out.append(entry_from_frontmatter(dict(post.metadata), post.content))
        except (SchemaError, ValueError, KeyError) as exc:
            log.warning("skipping draft %s: %s", p.name, exc)
    return out


def delete_draft(draft_id: str, *, keep_rejected: bool | None = None) -> None:
    path = draft_path(draft_id)
    if not path.exists():
        raise FileNotFoundError(draft_id)
    if keep_rejected is None:
        keep_rejected = bool(config_mod.get("review.keep_rejected"))
    if keep_rejected:
        rejected_drafts_dir().mkdir(parents=True, exist_ok=True)
        path.rename(rejected_drafts_dir() / path.name)
    else:
        path.unlink()


def approve_draft(draft_id: str) -> Entry:
    path = draft_path(draft_id)
    if not path.exists():
        raise FileNotFoundError(draft_id)
    post = frontmatter.load(str(path))
    fm = dict(post.metadata)
    fm["source"] = "ai-approved"
    new_entry = entry_from_frontmatter(fm, post.content)
    store.write(new_entry, overwrite=True)
    path.unlink()
    return new_entry


def propose(
    *,
    trigger: str,
    body: str,
    rule: str,
    tags: list[str],
    model: str,
    severity: str,
    proposed_in: str | None = None,
    session_count: int = 0,
    today: date_cls | None = None,
    embed_fn=None,
) -> dict[str, Any]:
    """Validate + persist a proposed draft. Returns a dict for the MCP response.

    Raises DraftError for every rejection path so callers can surface a clean error.
    """
    if severity not in ALLOWED_DRAFT_SEVERITIES:
        raise DraftError(
            "severity_too_low",
            f"severity must be one of {list(ALLOWED_DRAFT_SEVERITIES)}",
        )
    if not _has_quoted_correction(body):
        raise DraftError(
            "missing_quoted_correction",
            "body must include a verbatim '> '-quoted user correction",
        )
    if not tags:
        raise DraftError("missing_tags", "at least one tag is required")
    if not trigger.strip() or not rule.strip():
        raise DraftError("missing_fields", "trigger and rule are required")

    if session_count >= 1:
        raise DraftError(
            "session_limit",
            "only one draft per MCP session; the user is still reviewing your previous draft",
        )

    _check_global_rate_limit()

    similar = _find_similar(trigger, embed_fn=embed_fn)
    if similar is not None:
        sim_id, sim_score = similar
        raise DraftError(
            "similar_entry_exists",
            f"a similar entry already exists ({sim_id}, cosine={sim_score:.2f}); "
            "tell the user they already noted this",
            similar_entry_exists=sim_id,
        )

    today = today or date_cls.today()
    draft_id = f"{today.isoformat()}-{slugify(trigger)}-{secrets.token_hex(3)}"
    entry = Entry(
        id=draft_id,
        date=today,
        source="ai-drafted",
        trigger=trigger.strip(),
        rule=rule.strip(),
        tags=list(tags),
        severity=severity,
        body=body,
        proposed_by=model,
        proposed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        proposed_in=proposed_in,
    )
    drafts_dir().mkdir(parents=True, exist_ok=True)
    path = draft_path(draft_id)
    post = frontmatter.Post(entry.body, **entry.to_frontmatter())
    path.write_bytes(frontmatter.dumps(post).encode("utf-8") + b"\n")

    _record_rate_limit()

    return {
        "draft_id": draft_id,
        "preview_path": str(path),
        "message_to_user": (
            "I've drafted a priors entry. Run `priors review` to approve, edit, or reject it."
        ),
    }


def _has_quoted_correction(body: str) -> bool:
    return any(line.lstrip().startswith("> ") for line in body.splitlines())


def _check_global_rate_limit(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    timestamps = _load_rate_timestamps()
    recent = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SEC]
    if len(recent) >= RATE_LIMIT_PER_DAY:
        raise DraftError(
            "rate_limit_reached",
            "rate limit reached; user is reviewing existing drafts",
        )


def _record_rate_limit(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    timestamps = [t for t in _load_rate_timestamps() if now - t < RATE_LIMIT_WINDOW_SEC]
    timestamps.append(now)
    p = draft_rate_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"timestamps": timestamps}), encoding="utf-8")


def _load_rate_timestamps() -> list[float]:
    p = draft_rate_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [float(t) for t in data.get("timestamps", [])]
    except (OSError, ValueError):
        return []


def _find_similar(trigger: str, embed_fn=None) -> tuple[str, float] | None:
    """Return (id, score) of most similar existing entry/draft over the dedup threshold."""
    if embed_fn is None:
        embed_fn = _default_embed
    try:
        q = embed_fn([trigger])[0]
    except Exception as exc:  # pragma: no cover
        log.warning("dedup embedding failed: %s", exc)
        return None

    best: tuple[str, float] | None = None
    candidates: list[tuple[str, np.ndarray]] = []
    for e in store.load_all():
        candidates.append((e.id, embed_fn([e.trigger])[0]))
    for e in load_drafts():
        candidates.append((e.id, embed_fn([e.trigger])[0]))

    for eid, vec in candidates:
        sim = float(np.dot(q, vec))
        if sim >= DEDUP_THRESHOLD and (best is None or sim > best[1]):
            best = (eid, sim)
    return best


def _default_embed(texts: list[str]):
    from priors import embeddings as emb
    return emb.encode(texts)
