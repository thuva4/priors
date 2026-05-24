from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from typer.testing import CliRunner

from priors import effectiveness as eff
from priors import store
from priors.cli import app
from priors.paths import effectiveness_log_path
from priors.schema import Entry

runner = CliRunner()


def _entry(eid: str, d: date) -> Entry:
    return Entry(id=eid, date=d, source="human", trigger="t", rule="r", body="")


def test_record_fire_appends_jsonl():
    eff.record_fire(["a", "b"], tool="search_priors", query="hello")
    eff.record_fire(["a"], tool="priors_for_context")
    events = eff.load_events()
    assert len(events) == 2
    assert events[0]["type"] == "fire"
    assert events[0]["entry_ids"] == ["a", "b"]
    assert events[0]["tool"] == "search_priors"


def test_record_fire_skips_empty():
    eff.record_fire([], tool="search_priors", query="x")
    assert not effectiveness_log_path().exists() or not eff.load_events()


def test_record_near_miss():
    eff.record_near_miss("existing-1", draft_trigger="similar trigger", model="claude", score=0.91)
    events = eff.load_events()
    assert events[0]["type"] == "near_miss"
    assert events[0]["existing_id"] == "existing-1"


def test_aggregate_window_and_cold(priors_home):
    today = date(2026, 5, 24)
    entries = [
        _entry("fresh-hot", today - timedelta(days=10)),
        _entry("fresh-cold", today - timedelta(days=10)),       # young, not cold yet
        _entry("old-cold", today - timedelta(days=120)),        # cold candidate
        _entry("old-hot", today - timedelta(days=120)),         # fired, not cold
    ]
    # Write events directly to the log to control timestamps.
    in_window = (datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
                 - timedelta(days=5)).isoformat(timespec="seconds")
    out_of_window = (datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
                     - timedelta(days=90)).isoformat(timespec="seconds")
    log = effectiveness_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        for ts, ids in (
            (in_window, ["fresh-hot", "fresh-hot", "old-hot"]),
            (out_of_window, ["fresh-cold"]),  # outside window — doesn't count for fires…
        ):
            f.write(json.dumps({"type": "fire", "ts": ts, "tool": "t", "query": "", "entry_ids": ids}) + "\n")
        f.write(json.dumps({
            "type": "near_miss", "ts": in_window,
            "existing_id": "fresh-hot", "draft_trigger": "x", "model": "m", "score": 0.9,
        }) + "\n")

    s = eff.aggregate(eff.load_events(), entries, window_days=30, cold_min_age_days=60, today=today)
    fires = dict(s.fires)
    assert fires["fresh-hot"] == 2
    assert fires["old-hot"] == 1
    assert "fresh-cold" not in fires  # out-of-window
    cold_ids = {eid for eid, _ in s.cold}
    # …but the out-of-window fire still counts as "ever fired", so fresh-cold isn't cold,
    # AND it's not old enough anyway. old-cold is the only cold candidate.
    assert cold_ids == {"old-cold"}
    assert dict(s.near_misses) == {"fresh-hot": 1}


def test_mcp_search_logs_fire(tmp_path):
    from priors.mcp_server import build_server
    store.write(Entry(
        id="hit", date=date(2026, 5, 1), source="human",
        trigger="postgres migration broke prod", rule="real db", body=""
    ))
    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["search_priors"].fn
    fn(query="postgres", limit=3, all_stacks=True)
    events = eff.load_events()
    assert any(ev["type"] == "fire" and "hit" in ev["entry_ids"] for ev in events)


def test_mcp_propose_similar_logs_near_miss(tmp_path, monkeypatch):
    from priors import drafts as drafts_mod
    from priors.mcp_server import build_server
    import numpy as np

    # Existing entry whose trigger we'll be "similar to".
    store.write(Entry(
        id="existing", date=date(2026, 5, 1), source="human",
        trigger="never X in transactions", rule="don't", body=""
    ))
    # Force every embedding to the same vector → cosine 1.0 → near-miss.
    monkeypatch.setattr(
        drafts_mod, "_default_embed",
        lambda texts: np.vstack([np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32) for _ in texts]),
    )
    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["propose_entry"].fn
    out = fn(
        trigger="never X inside transactions",
        body="> the user said never X\nrationale",
        rule="never X",
        tags=["x"],
        model="claude",
        severity="silent-bug",
    )
    assert out.get("error") == "similar_entry_exists"
    events = eff.load_events()
    near = [ev for ev in events if ev["type"] == "near_miss"]
    assert near and near[0]["existing_id"] == "existing"


def test_stats_cli_no_flag_summary():
    store.write(Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", body=""))
    store.write(Entry(id="b", date=date(2026, 5, 2), source="ai-approved", trigger="t", rule="r", body=""))
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0, result.output
    assert "Curated entries: 2" in result.output
    assert "human: 1" in result.output
    assert "ai-approved: 1" in result.output


def test_stats_cli_effectiveness_flag():
    store.write(Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", body=""))
    eff.record_fire(["a"], tool="search_priors", query="q")
    result = runner.invoke(app, ["stats", "--effectiveness"])
    assert result.exit_code == 0, result.output
    assert "Top firing entries" in result.output
    assert "a" in result.output
