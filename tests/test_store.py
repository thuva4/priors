from datetime import date, timedelta

import pytest

from priors import store
from priors.paths import entries_dir
from priors.schema import Entry


def _entry(**kw):
    base = dict(
        id="2026-05-24-test",
        date=date(2026, 5, 24),
        source="human",
        trigger="t",
        rule="r",
        body="body",
    )
    base.update(kw)
    return Entry(**base)


def test_write_and_get():
    e = _entry()
    path = store.write(e)
    assert path.exists()
    got = store.get(e.id)
    assert got.id == e.id
    assert got.rule == "r"
    assert got.body.strip() == "body"


def test_write_refuses_overwrite():
    e = _entry()
    store.write(e)
    with pytest.raises(FileExistsError):
        store.write(e)
    store.write(e, overwrite=True)  # ok


def test_list_filters_by_tag():
    store.write(_entry(id="2026-05-24-a", tags=["x"]))
    store.write(_entry(id="2026-05-24-b", tags=["y"]))
    store.write(_entry(id="2026-05-24-c", tags=["x", "y"]))
    out = store.list_entries(tags=["x"])
    assert {e.id for e in out} == {"2026-05-24-a", "2026-05-24-c"}
    both = store.list_entries(tags=["x", "y"])
    assert {e.id for e in both} == {"2026-05-24-c"}


def test_list_filters_by_since():
    today = date.today()
    store.write(_entry(id="recent", date=today))
    store.write(_entry(id="oldish", date=today - timedelta(days=400)))
    out = store.list_entries(since="30d")
    assert [e.id for e in out] == ["recent"]


def test_list_sort_and_limit():
    store.write(_entry(id="2026-05-01-a", date=date(2026, 5, 1)))
    store.write(_entry(id="2026-05-10-b", date=date(2026, 5, 10)))
    store.write(_entry(id="2026-05-05-c", date=date(2026, 5, 5)))
    out = store.list_entries(limit=2)
    assert [e.id for e in out] == ["2026-05-10-b", "2026-05-05-c"]


def test_prefix_lookup():
    store.write(_entry(id="2026-05-24-aaa"))
    store.write(_entry(id="2026-05-24-aab"))
    assert store.find_by_prefix("2026-05-24-aa") == ["2026-05-24-aaa", "2026-05-24-aab"]
    assert store.find_by_prefix("2026-05-24-aaa") == ["2026-05-24-aaa"]


def test_delete():
    e = _entry()
    store.write(e)
    store.delete(e.id)
    with pytest.raises(FileNotFoundError):
        store.get(e.id)


def test_corrupted_file_is_skipped(caplog):
    bad = entries_dir() / "bad.md"
    bad.write_text("---\nid: x\ndate: 2026-05-24\nsource: bogus\ntrigger: t\nrule: r\n---\nbody\n")
    good = _entry(id="2026-05-24-good")
    store.write(good)
    out = store.list_entries()
    assert [e.id for e in out] == ["2026-05-24-good"]


def test_filter_by_source_and_model():
    store.write(_entry(id="a", models=["claude"], source="human"))
    store.write(_entry(id="b", models=["gpt"], source="human"))
    assert [e.id for e in store.list_entries(model="claude")] == ["a"]
    assert [e.id for e in store.list_entries(source="human")] == sorted(["a", "b"], reverse=True)


def test_since_iso_date():
    store.write(_entry(id="old", date=date(2025, 1, 1)))
    store.write(_entry(id="new", date=date(2026, 5, 1)))
    out = store.list_entries(since="2026-01-01")
    assert [e.id for e in out] == ["new"]
