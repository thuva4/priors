from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import Any

SOURCES = ("human", "ai-drafted", "ai-approved")
SEVERITIES = ("nit", "misleading", "silent-bug", "silent-prod-bug")
SCOPES = ("global", "project")
TRIGGER_PATTERN_TYPES = ("regex",)

REQUIRED_FIELDS = ("id", "date", "source", "trigger", "rule")


class SchemaError(ValueError):
    pass


@dataclass
class Entry:
    id: str
    date: date_cls
    source: str
    trigger: str
    rule: str
    models: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    severity: str | None = None
    scope: str = "project"
    stacks: list[str] = field(default_factory=list)
    pin: bool = False
    body: str = ""
    proposed_by: str | None = None
    proposed_at: str | None = None
    proposed_in: str | None = None
    trigger_pattern: dict[str, Any] | None = None

    def to_frontmatter(self) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "id": self.id,
            "date": self.date.isoformat(),
            "source": self.source,
            "trigger": self.trigger,
            "rule": self.rule,
        }
        if self.models:
            fm["models"] = list(self.models)
        if self.tools:
            fm["tools"] = list(self.tools)
        if self.tags:
            fm["tags"] = list(self.tags)
        if self.severity:
            fm["severity"] = self.severity
        if self.scope and self.scope != "project":
            fm["scope"] = self.scope
        if self.stacks:
            fm["stacks"] = list(self.stacks)
        if self.pin:
            fm["pin"] = True
        if self.proposed_by:
            fm["proposed_by"] = self.proposed_by
        if self.proposed_at:
            fm["proposed_at"] = self.proposed_at
        if self.proposed_in:
            fm["proposed_in"] = self.proposed_in
        if self.trigger_pattern:
            fm["trigger_pattern"] = dict(self.trigger_pattern)
        return fm


def validate_frontmatter(fm: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_FIELDS if not _present(fm.get(k))]
    if missing:
        raise SchemaError(f"missing required fields: {', '.join(missing)}")
    if fm["source"] not in SOURCES:
        raise SchemaError(
            f"source must be one of {SOURCES}, got {fm['source']!r}"
        )
    sev = fm.get("severity")
    if sev is not None and sev not in SEVERITIES:
        raise SchemaError(
            f"severity must be one of {SEVERITIES}, got {sev!r}"
        )
    scope = fm.get("scope", "project")
    if scope not in SCOPES:
        raise SchemaError(f"scope must be one of {SCOPES}, got {scope!r}")
    tp = fm.get("trigger_pattern")
    if tp is not None:
        _validate_trigger_pattern(tp)


def _validate_trigger_pattern(tp: Any) -> None:
    if not isinstance(tp, dict):
        raise SchemaError(f"trigger_pattern must be a mapping, got {type(tp).__name__}")
    ttype = tp.get("type")
    if ttype not in TRIGGER_PATTERN_TYPES:
        raise SchemaError(
            f"trigger_pattern.type must be one of {TRIGGER_PATTERN_TYPES}, got {ttype!r}"
        )
    pattern = tp.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise SchemaError("trigger_pattern.pattern must be a non-empty string")
    langs = tp.get("languages")
    if langs is not None:
        if not isinstance(langs, list) or not all(isinstance(x, str) for x in langs):
            raise SchemaError("trigger_pattern.languages must be a list of strings")


def entry_from_frontmatter(fm: dict[str, Any], body: str) -> Entry:
    validate_frontmatter(fm)
    d = fm["date"]
    if isinstance(d, str):
        d = date_cls.fromisoformat(d)
    return Entry(
        id=str(fm["id"]),
        date=d,
        source=str(fm["source"]),
        trigger=str(fm["trigger"]),
        rule=str(fm["rule"]),
        models=list(fm.get("models") or []),
        tools=list(fm.get("tools") or []),
        tags=list(fm.get("tags") or []),
        severity=fm.get("severity"),
        scope=fm.get("scope", "project"),
        stacks=list(fm.get("stacks") or []),
        pin=bool(fm.get("pin", False)),
        body=body or "",
        proposed_by=fm.get("proposed_by"),
        proposed_at=fm.get("proposed_at"),
        proposed_in=fm.get("proposed_in"),
        trigger_pattern=dict(fm["trigger_pattern"]) if fm.get("trigger_pattern") else None,
    )


def slugify(text: str, max_words: int = 6) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    words = [w for w in re.split(r"[\s-]+", text) if w]
    return "-".join(words[:max_words]) or "entry"


def derive_id(date: date_cls, trigger: str) -> str:
    return f"{date.isoformat()}-{slugify(trigger)}"


def _present(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    return True
