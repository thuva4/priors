from datetime import date

from priors import retrieval, store
from priors.schema import Entry


def _w(**kw):
    base = dict(
        id="x",
        date=date(2026, 5, 1),
        source="human",
        trigger="t",
        rule="r",
        body="body",
    )
    base.update(kw)
    store.write(Entry(**base))


def test_bm25_finds_relevant():
    _w(id="a", trigger="postgres migration broke prod", rule="use real db")
    _w(id="b", trigger="forEach with async", rule="use for...of")
    res = retrieval.search("postgres migration", k=5, mode="bm25")
    assert res
    assert res[0].entry.id == "a"


def test_tag_filter_and():
    _w(id="a", tags=["x", "y"], body="alpha alpha")
    _w(id="b", tags=["x"], body="alpha alpha")
    res = retrieval.search("alpha", filters=retrieval.Filters(tags=["x", "y"]), mode="bm25")
    ids = {r.entry.id for r in res}
    assert ids == {"a"}


def test_stack_filter_keeps_no_stack_entries():
    _w(id="generic", stacks=[], body="alpha")
    _w(id="py", stacks=["python"], body="alpha")
    _w(id="go", stacks=["go"], body="alpha")
    res = retrieval.search("alpha", filters=retrieval.Filters(stacks={"python"}), mode="bm25")
    ids = {r.entry.id for r in res}
    assert ids == {"generic", "py"}


def test_scope_filter():
    _w(id="g", scope="global", body="alpha")
    _w(id="p", scope="project", body="alpha")
    res = retrieval.search("alpha", filters=retrieval.Filters(scope="global"), mode="bm25")
    assert {r.entry.id for r in res} == {"g"}


def test_hybrid_fuses():
    _w(id="a", trigger="migration broke prod", body="alpha")
    _w(id="b", trigger="forEach async", body="alpha")
    res = retrieval.search("migration", k=2, mode="hybrid")
    assert res[0].entry.id == "a"
