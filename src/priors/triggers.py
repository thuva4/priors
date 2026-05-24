from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath

from priors.schema import Entry

log = logging.getLogger(__name__)

LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".tf": "terraform",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
}


def detect_language(file_path: str | None) -> str | None:
    if not file_path:
        return None
    return LANGUAGE_BY_EXT.get(PurePath(file_path).suffix.lower())


@dataclass(frozen=True)
class Match:
    entry: Entry
    pattern: str
    span: tuple[int, int]
    matched_text: str


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        log.warning("skipping invalid trigger_pattern %r: %s", pattern, exc)
        return None


def match(entry: Entry, file_path: str | None, snippet: str) -> Match | None:
    tp = entry.trigger_pattern
    if not tp:
        return None
    langs = tp.get("languages")
    if langs:
        lang = detect_language(file_path)
        if lang is None or lang not in langs:
            return None
    pattern = tp.get("pattern")
    if not pattern:
        return None
    compiled = _compile(pattern)
    if compiled is None:
        return None
    m = compiled.search(snippet)
    if not m:
        return None
    return Match(entry=entry, pattern=pattern, span=m.span(), matched_text=m.group(0))


def find_matches(
    entries: list[Entry],
    file_path: str | None,
    snippet: str,
) -> list[Match]:
    out: list[Match] = []
    for e in entries:
        m = match(e, file_path, snippet)
        if m is not None:
            out.append(m)
    return out
