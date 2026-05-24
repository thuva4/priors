from datetime import date
from pathlib import Path

from priors import adapters as adapters_mod
from priors import store
from priors.adapters.base import BEGIN_MARK, END_MARK
from priors.adapters.claude_code import ClaudeCodeAdapter
from priors.adapters.agents import AgentsAdapter
from priors.schema import Entry


def _w(**kw):
    base = dict(
        id="x",
        date=date(2026, 5, 1),
        source="human",
        trigger="t",
        rule="r",
        body="",
    )
    base.update(kw)
    store.write(Entry(**base))


def _python_project(tmp_path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    return tmp_path


def test_claude_global_only_takes_global_entries():
    a = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="global")
    b = Entry(id="b", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="project")
    adapter = ClaudeCodeAdapter()
    assert adapter.filter(a, "global", set())
    assert not adapter.filter(b, "global", set())


def test_claude_project_filter_intersects_stacks():
    a = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="project", stacks=["python"])
    b = Entry(id="b", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="project", stacks=["go"])
    c = Entry(id="c", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="project", stacks=[])
    adapter = ClaudeCodeAdapter()
    assert adapter.filter(a, "project", {"python"})
    assert not adapter.filter(b, "project", {"python"})
    assert adapter.filter(c, "project", {"python"})  # no-stack entries always pass


def test_sync_writes_only_matching_stacks(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])
    _w(id="go", trigger="go rule", rule="go rule", scope="project", stacks=["go"])
    _w(id="glob", trigger="global rule", rule="global rule", scope="global")

    adapters_mod.sync_all(root)
    target = root / "CLAUDE.md"
    content = target.read_text()
    assert "py rule" in content
    assert "go rule" not in content
    assert "global rule" in content


def test_marker_roundtrip_preserves_other_content(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    target = root / "CLAUDE.md"
    target.write_text("# My project\n\nHand-written intro.\n")
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])

    adapters_mod.sync_all(root)
    content = target.read_text()
    assert "# My project" in content
    assert "Hand-written intro." in content
    assert BEGIN_MARK in content and END_MARK in content
    assert "py rule" in content


def test_sync_idempotent(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])

    first = adapters_mod.sync_all(root)
    second = adapters_mod.sync_all(root)
    assert any(r.changed for r in first)
    assert all(not r.changed for r in second)


def test_check_only_does_not_write(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])

    results = adapters_mod.sync_all(root, check_only=True)
    assert any(r.changed for r in results)
    assert not (root / "CLAUDE.md").exists()


def test_agents_writes_only_in_project(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])

    adapters_mod.sync_all(root)
    assert (root / "AGENTS.md").exists()


def test_agents_no_global_target():
    assert AgentsAdapter().target_path("global", Path("/tmp")) is None


def test_codex_writes_only_global(tmp_path, monkeypatch):
    from priors.adapters.codex import CodexAdapter
    fakehome = tmp_path / "fakehome"
    monkeypatch.setenv("HOME", str(fakehome))
    adapter = CodexAdapter()
    assert adapter.target_path("project", tmp_path) is None
    assert adapter.target_path("global", tmp_path) == fakehome / ".codex" / "AGENTS.md"


def test_codex_filter_global_only():
    from priors.adapters.codex import CodexAdapter
    a = Entry(id="a", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="global")
    b = Entry(id="b", date=date(2026, 5, 1), source="human", trigger="t", rule="r", scope="project")
    adapter = CodexAdapter()
    assert adapter.filter(a, "global", set())
    assert not adapter.filter(b, "global", set())


def test_codex_global_path_override(tmp_path, monkeypatch):
    from priors import paths as paths_mod
    from priors.adapters.codex import CodexAdapter
    custom = tmp_path / "custom" / "codex.md"
    paths_mod.config_path().write_text(
        f'[adapters.codex]\nglobal_path = "{custom}"\n', encoding="utf-8"
    )
    assert CodexAdapter().target_path("global", tmp_path) == custom


def test_codex_sync_writes_global_agents_md(tmp_path, monkeypatch):
    root = _python_project(tmp_path)
    fakehome = tmp_path / "fakehome"
    monkeypatch.setenv("HOME", str(fakehome))
    _w(id="glob", trigger="global rule", rule="global rule", scope="global")
    _w(id="py", trigger="py rule", rule="py rule", scope="project", stacks=["python"])

    adapters_mod.sync_all(root)
    codex_global = fakehome / ".codex" / "AGENTS.md"
    assert codex_global.exists()
    content = codex_global.read_text()
    assert "global rule" in content
    assert "py rule" not in content  # global file excludes project-scoped entries


def test_codex_render_includes_preamble():
    from priors.adapters.codex import CodexAdapter, PREAMBLE
    out = CodexAdapter().render([])
    assert PREAMBLE.strip() in out
    assert "priors_for_context" in out
    assert "search_priors" in out
    assert "propose_entry" in out
    assert "priors" in out
