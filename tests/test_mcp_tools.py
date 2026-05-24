from __future__ import annotations

from datetime import date
from pathlib import Path

from priors import store
from priors.mcp_server import build_server
from priors.schema import Entry


def _w(**kw):
    base = dict(
        id="x", date=date(2026, 5, 1), source="human", trigger="t", rule="r", body="body"
    )
    base.update(kw)
    store.write(Entry(**base))


def test_tools_registered(tmp_path):
    server = build_server(cwd=tmp_path)
    # FastMCP exposes registered tools via list_tools (async). Inspect via internal API.
    tool_names = list(server._tool_manager._tools.keys())
    assert {
        "search_priors",
        "recent_entries",
        "propose_entry",
        "priors_for_context",
    }.issubset(set(tool_names))


def test_priors_for_context_returns_matches(tmp_path):
    _w(
        id="monotonic",
        trigger="time.time for elapsed",
        rule="use monotonic",
        stacks=["python"],
    )
    # second entry won't match
    _w(id="other", trigger="other", rule="r")
    # write the trigger_pattern by reloading + rewriting
    from priors import store
    e = store.get("monotonic")
    e.trigger_pattern = {
        "type": "regex",
        "pattern": r"\btime\.time\(\)",
        "languages": ["python"],
    }
    store.write(e, overwrite=True)

    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["priors_for_context"].fn
    out = fn(file_path="foo.py", snippet="elapsed = time.time() - start", all_stacks=True)
    assert [r["id"] for r in out] == ["monotonic"]
    assert out[0]["matched_text"] == "time.time()"


def test_search_tool_callable(tmp_path):
    _w(id="hit", trigger="postgres migration broke prod", rule="real db")
    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["search_priors"].fn
    out = fn(query="postgres", limit=3, all_stacks=True)
    assert out
    assert out[0]["id"] == "hit"


def test_recent_tool_stack_filter(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    _w(id="py", stacks=["python"])
    _w(id="go", stacks=["go"])
    _w(id="global", scope="global")
    server = build_server(cwd=project)
    fn = server._tool_manager._tools["recent_entries"].fn
    out = fn(limit=10)
    ids = {r["id"] for r in out}
    assert "py" in ids
    assert "global" in ids
    assert "go" not in ids


def test_propose_entry_via_tool(tmp_path, monkeypatch):
    from priors import drafts as drafts_mod
    import numpy as np
    monkeypatch.setattr(drafts_mod, "_default_embed", lambda texts: np.vstack(
        [np.array([float(abs(hash(t)) % 1000) / 1000.0] * 4, dtype=np.float32) for t in texts]
    ))
    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["propose_entry"].fn
    out = fn(
        trigger="never X",
        body="> user said: never X\nbecause Y",
        rule="don't do X",
        tags=["x"],
        model="claude",
        severity="silent-bug",
    )
    assert "draft_id" in out, out


def test_propose_entry_rejection_returns_error(tmp_path):
    server = build_server(cwd=tmp_path)
    fn = server._tool_manager._tools["propose_entry"].fn
    out = fn(
        trigger="t",
        body="no quoted line",
        rule="r",
        tags=["x"],
        model="claude",
        severity="silent-bug",
    )
    assert out["error"] == "missing_quoted_correction"
