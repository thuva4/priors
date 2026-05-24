from __future__ import annotations

import logging
import re
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

import frontmatter

from priors.paths import entries_dir
from priors.schema import Entry, SchemaError, entry_from_frontmatter

log = logging.getLogger(__name__)


def entry_path(entry_id: str) -> Path:
    return entries_dir() / f"{entry_id}.md"


def write(entry: Entry, *, overwrite: bool = False) -> Path:
    path = entry_path(entry.id)
    if path.exists() and not overwrite:
        raise FileExistsError(f"entry already exists: {entry.id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(entry.body, **entry.to_frontmatter())
    path.write_bytes(frontmatter.dumps(post).encode("utf-8") + b"\n")
    return path


def read_file(path: Path) -> Entry:
    post = frontmatter.load(str(path))
    return entry_from_frontmatter(dict(post.metadata), post.content)


def get(entry_id: str) -> Entry:
    path = entry_path(entry_id)
    if not path.exists():
        raise FileNotFoundError(entry_id)
    return read_file(path)


def find_by_prefix(prefix: str) -> list[str]:
    d = entries_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob(f"{prefix}*.md"))


def delete(entry_id: str) -> None:
    path = entry_path(entry_id)
    if not path.exists():
        raise FileNotFoundError(entry_id)
    path.unlink()


def load_all() -> list[Entry]:
    d = entries_dir()
    if not d.exists():
        return []
    entries: list[Entry] = []
    for path in sorted(d.glob("*.md")):
        try:
            entries.append(read_file(path))
        except (SchemaError, ValueError, KeyError) as exc:
            log.warning("skipping %s: %s", path.name, exc)
    return entries


def list_entries(
    *,
    tags: list[str] | None = None,
    model: str | None = None,
    source: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[Entry]:
    entries = load_all()
    if tags:
        tagset = set(tags)
        entries = [e for e in entries if tagset.issubset(set(e.tags))]
    if model:
        entries = [e for e in entries if model in e.models]
    if source:
        entries = [e for e in entries if e.source == source]
    if since:
        cutoff = _parse_since(since)
        entries = [e for e in entries if e.date >= cutoff]
    entries.sort(key=lambda e: (e.date, e.id), reverse=True)
    if limit is not None:
        entries = entries[:limit]
    return entries


def _parse_since(s: str) -> date_cls:
    m = re.fullmatch(r"(\d+)([dwmy])", s.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
        return (datetime.now().date() - timedelta(days=days))
    return date_cls.fromisoformat(s)
