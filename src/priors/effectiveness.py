from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from priors.paths import effectiveness_log_path
from priors.schema import Entry

log = logging.getLogger(__name__)


FIRE = "fire"
NEAR_MISS = "near_miss"
PROPOSE_REJECTED = "propose_rejected"
DRAFT_WRITTEN = "draft_written"
DRAFT_APPROVED = "draft_approved"
DRAFT_REJECTED = "draft_rejected"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(event: dict[str, Any]) -> None:
    path = effectiveness_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Never let telemetry break a real request.
        log.warning("effectiveness log write failed: %s", exc)


def record_fire(entry_ids: Iterable[str], tool: str, query: str | None = None) -> None:
    ids = [eid for eid in entry_ids if eid]
    if not ids:
        return
    _append({
        "type": FIRE,
        "ts": _now_iso(),
        "tool": tool,
        "query": (query or "")[:200],
        "entry_ids": ids,
    })


def record_near_miss(
    existing_id: str,
    *,
    draft_trigger: str,
    model: str | None = None,
    score: float | None = None,
) -> None:
    if not existing_id:
        return
    _append({
        "type": NEAR_MISS,
        "ts": _now_iso(),
        "existing_id": existing_id,
        "draft_trigger": draft_trigger[:200],
        "model": model,
        "score": score,
    })


def record_propose_rejected(reason: str, *, model: str | None = None) -> None:
    _append({"type": PROPOSE_REJECTED, "ts": _now_iso(), "reason": reason, "model": model})


def record_draft_written(draft_id: str, *, model: str | None = None) -> None:
    _append({"type": DRAFT_WRITTEN, "ts": _now_iso(), "draft_id": draft_id, "model": model})


def record_draft_approved(draft_id: str) -> None:
    _append({"type": DRAFT_APPROVED, "ts": _now_iso(), "draft_id": draft_id})


def record_draft_rejected(draft_id: str) -> None:
    _append({"type": DRAFT_REJECTED, "ts": _now_iso(), "draft_id": draft_id})


@dataclass
class DraftStats:
    proposed: int
    written: int
    rejected_by_guard: int
    rejected_by_reason: list[tuple[str, int]]
    approved: int
    reviewed_rejected: int
    pending: int
    acceptance_rate: float | None  # approved / (approved + reviewed_rejected)
    write_rate: float | None       # written / proposed
    window_days: int


def aggregate_drafts(
    events: list[dict[str, Any]],
    *,
    pending: int = 0,
    window_days: int = 30,
    today: date_cls | None = None,
) -> DraftStats:
    today = today or date_cls.today()
    cutoff = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=window_days)

    written = 0
    rejected_guard = 0
    approved = 0
    reviewed_rejected = 0
    reasons: Counter[str] = Counter()

    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None or ts < cutoff:
            continue
        t = ev.get("type")
        if t == DRAFT_WRITTEN:
            written += 1
        elif t == PROPOSE_REJECTED:
            rejected_guard += 1
            reasons[str(ev.get("reason") or "unknown")] += 1
        elif t == DRAFT_APPROVED:
            approved += 1
        elif t == DRAFT_REJECTED:
            reviewed_rejected += 1

    proposed = written + rejected_guard
    reviewed = approved + reviewed_rejected
    return DraftStats(
        proposed=proposed,
        written=written,
        rejected_by_guard=rejected_guard,
        rejected_by_reason=reasons.most_common(),
        approved=approved,
        reviewed_rejected=reviewed_rejected,
        pending=pending,
        acceptance_rate=(approved / reviewed) if reviewed else None,
        write_rate=(written / proposed) if proposed else None,
        window_days=window_days,
    )


def load_events(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or effectiveness_log_path()
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@dataclass
class Stats:
    fires: list[tuple[str, int]]      # (entry_id, count), desc
    cold: list[tuple[str, int]]        # (entry_id, age_days)
    near_misses: list[tuple[str, int]] # (existing_id, count), desc
    window_days: int
    cold_min_age_days: int


def aggregate(
    events: list[dict[str, Any]],
    entries: list[Entry],
    *,
    window_days: int = 30,
    cold_min_age_days: int = 60,
    today: date_cls | None = None,
) -> Stats:
    today = today or date_cls.today()
    cutoff = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=window_days)

    fire_counts: Counter[str] = Counter()
    near_miss_counts: Counter[str] = Counter()
    fired_ever: set[str] = set()

    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        in_window = ts is not None and ts >= cutoff
        if ev.get("type") == FIRE:
            for eid in ev.get("entry_ids", []):
                fired_ever.add(eid)
                if in_window:
                    fire_counts[eid] += 1
        elif ev.get("type") == NEAR_MISS:
            existing = ev.get("existing_id")
            if existing and in_window:
                near_miss_counts[existing] += 1

    cold: list[tuple[str, int]] = []
    for e in entries:
        if e.id in fired_ever:
            continue
        age = (today - e.date).days
        if age >= cold_min_age_days:
            cold.append((e.id, age))
    cold.sort(key=lambda t: -t[1])

    return Stats(
        fires=fire_counts.most_common(),
        cold=cold,
        near_misses=near_miss_counts.most_common(),
        window_days=window_days,
        cold_min_age_days=cold_min_age_days,
    )
