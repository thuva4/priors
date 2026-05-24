from datetime import date

from priors.digest import build_digest
from priors.schema import Entry


def _e(**kw):
    base = dict(
        id="x",
        date=date(2026, 5, 1),
        source="human",
        trigger="t",
        rule="r",
    )
    base.update(kw)
    return Entry(**base)


def test_orders_pinned_first():
    a = _e(id="a", trigger="alpha", date=date(2026, 5, 1), pin=False)
    b = _e(id="b", trigger="beta", date=date(2025, 1, 1), pin=True)
    out = build_digest([a, b], today=date(2026, 5, 24))
    assert out.index("beta") < out.index("alpha")


def test_recent_first_within_group():
    a = _e(id="a", trigger="alpha", date=date(2026, 5, 1))
    b = _e(id="b", trigger="beta", date=date(2026, 5, 10))
    out = build_digest([a, b], today=date(2026, 5, 24))
    assert out.index("beta") < out.index("alpha")


def test_filters_to_curated():
    drafted = _e(id="d", source="ai-drafted", trigger="drafted")
    human = _e(id="h", source="human", trigger="kept")
    out = build_digest([drafted, human], today=date(2026, 5, 24))
    assert "kept" in out
    assert "drafted" not in out


def test_truncates_long_rule():
    e = _e(rule="x" * 500)
    out = build_digest([e], today=date(2026, 5, 24))
    assert "…" in out


def test_max_rules():
    entries = [_e(id=f"e{i}", date=date(2026, 5, i + 1)) for i in range(20)]
    out = build_digest(entries, max_rules=5, today=date(2026, 5, 24))
    assert out.count("\n- ") == 5


def test_max_bytes_trims():
    entries = [_e(id=f"e{i}", trigger=f"trigger {i}" * 5, rule=f"rule {i}" * 5) for i in range(50)]
    out = build_digest(entries, max_bytes=400, today=date(2026, 5, 24))
    assert len(out.encode("utf-8")) <= 400
