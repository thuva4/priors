from __future__ import annotations

from datetime import date

import pytest

from priors import triggers
from priors.schema import Entry, SchemaError, entry_from_frontmatter, validate_frontmatter


def _entry(**kw):
    base = dict(
        id="x",
        date=date(2026, 5, 1),
        source="human",
        trigger="t",
        rule="r",
        body="",
    )
    base.update(kw)
    return Entry(**base)


def test_detect_language():
    assert triggers.detect_language("foo/bar.py") == "python"
    assert triggers.detect_language("a.tsx") == "typescript"
    assert triggers.detect_language("Main.java") == "java"
    assert triggers.detect_language(None) is None
    assert triggers.detect_language("README") is None
    assert triggers.detect_language("foo.unknown") is None


def test_match_regex_hits():
    e = _entry(trigger_pattern={"type": "regex", "pattern": r"\btime\.time\(\)"})
    m = triggers.match(e, "foo.py", "elapsed = time.time() - start")
    assert m is not None
    assert m.matched_text == "time.time()"


def test_match_language_gate():
    e = _entry(trigger_pattern={
        "type": "regex",
        "pattern": r"\btime\.time\(\)",
        "languages": ["python"],
    })
    assert triggers.match(e, "foo.py", "time.time()") is not None
    assert triggers.match(e, "foo.js", "time.time()") is None
    assert triggers.match(e, None, "time.time()") is None


def test_match_no_pattern_returns_none():
    e = _entry()
    assert triggers.match(e, "foo.py", "anything") is None


def test_invalid_pattern_skipped(caplog):
    e = _entry(trigger_pattern={"type": "regex", "pattern": "[unclosed"})
    with caplog.at_level("WARNING"):
        assert triggers.match(e, "foo.py", "anything") is None


def test_find_matches_filters():
    a = _entry(id="a", trigger_pattern={"type": "regex", "pattern": r"forEach"})
    b = _entry(id="b", trigger_pattern={"type": "regex", "pattern": r"asyncio\.gather"})
    c = _entry(id="c")  # no pattern
    out = triggers.find_matches([a, b, c], "x.ts", "items.forEach(...)")
    assert [m.entry.id for m in out] == ["a"]


def test_schema_accepts_trigger_pattern():
    fm = {
        "id": "x",
        "date": "2026-05-01",
        "source": "human",
        "trigger": "t",
        "rule": "r",
        "trigger_pattern": {
            "type": "regex",
            "pattern": r"\btime\.time\(\)",
            "languages": ["python"],
        },
    }
    validate_frontmatter(fm)
    e = entry_from_frontmatter(fm, "")
    assert e.trigger_pattern["pattern"] == r"\btime\.time\(\)"
    assert e.to_frontmatter()["trigger_pattern"]["languages"] == ["python"]


@pytest.mark.parametrize("tp", [
    {"type": "ast", "pattern": "foo"},
    {"type": "regex"},
    {"type": "regex", "pattern": ""},
    {"type": "regex", "pattern": "x", "languages": "python"},
    "not-a-dict",
])
def test_schema_rejects_bad_trigger_pattern(tp):
    fm = {
        "id": "x",
        "date": "2026-05-01",
        "source": "human",
        "trigger": "t",
        "rule": "r",
        "trigger_pattern": tp,
    }
    with pytest.raises(SchemaError):
        validate_frontmatter(fm)
