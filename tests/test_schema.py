from datetime import date

import pytest

from priors.schema import (
    Entry,
    SchemaError,
    derive_id,
    entry_from_frontmatter,
    slugify,
    validate_frontmatter,
)


def _base_fm():
    return {
        "id": "2026-05-24-x",
        "date": "2026-05-24",
        "source": "human",
        "trigger": "t",
        "rule": "r",
    }


def test_required_fields_pass():
    validate_frontmatter(_base_fm())


@pytest.mark.parametrize("field", ["id", "date", "source", "trigger", "rule"])
def test_required_field_missing(field):
    fm = _base_fm()
    del fm[field]
    with pytest.raises(SchemaError):
        validate_frontmatter(fm)


def test_source_enum():
    fm = _base_fm()
    fm["source"] = "bogus"
    with pytest.raises(SchemaError):
        validate_frontmatter(fm)


def test_severity_enum_optional():
    fm = _base_fm()
    fm["severity"] = "nit"
    validate_frontmatter(fm)
    fm["severity"] = "bad"
    with pytest.raises(SchemaError):
        validate_frontmatter(fm)


def test_scope_enum():
    fm = _base_fm()
    fm["scope"] = "global"
    validate_frontmatter(fm)
    fm["scope"] = "elsewhere"
    with pytest.raises(SchemaError):
        validate_frontmatter(fm)


def test_entry_from_frontmatter_defaults():
    e = entry_from_frontmatter(_base_fm(), "body")
    assert e.id == "2026-05-24-x"
    assert e.date == date(2026, 5, 24)
    assert e.scope == "project"
    assert e.pin is False
    assert e.body == "body"


def test_entry_round_trip():
    e = Entry(
        id="2026-05-24-x",
        date=date(2026, 5, 24),
        source="human",
        trigger="t",
        rule="r",
        tags=["a", "b"],
        severity="nit",
        pin=True,
    )
    fm = e.to_frontmatter()
    e2 = entry_from_frontmatter(fm, "")
    assert e2.tags == ["a", "b"]
    assert e2.severity == "nit"
    assert e2.pin is True


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("a b c d e f g h", max_words=3) == "a-b-c"
    assert slugify("") == "entry"


def test_derive_id():
    assert derive_id(date(2026, 5, 24), "Fix the migration bug") == "2026-05-24-fix-the-migration-bug"
