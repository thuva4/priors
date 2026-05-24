from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from priors import doctor as doctor_mod
from priors import paths as paths_mod
from priors import store
from priors.cli import app
from priors.schema import Entry

runner = CliRunner()


def _write(**kw) -> Entry:
    base = dict(
        id="2026-05-24-a",
        date=date(2026, 5, 24),
        source="human",
        trigger="t",
        rule="r",
        body="body",
    )
    base.update(kw)
    e = Entry(**base)
    store.write(e)
    return e


def _statuses(checks):
    return [c.status for c in checks]


def test_clean_install_no_failures(tmp_path):
    checks = doctor_mod.run_all(tmp_path)
    assert "fail" not in _statuses(checks)


def test_corrupted_entry_is_failure(tmp_path):
    bad = paths_mod.entries_dir() / "2026-05-24-bad.md"
    bad.write_text("---\nid: x\n---\nno required fields\n", encoding="utf-8")
    checks = doctor_mod.run_all(tmp_path)
    fails = [c for c in checks if c.status == "fail"]
    assert any("corrupted" in c.message for c in fails)


def test_missing_sidecar_warns_in_embeddings_mode(tmp_path, monkeypatch):
    # Switch off the bm25 fixture default.
    (paths_mod.priors_home() / "config.toml").write_text(
        '[retrieval]\nmode = "embeddings"\n', encoding="utf-8"
    )
    _write(id="2026-05-24-e")
    # Pretend sentence-transformers is installed without importing it.
    import importlib.util as _u
    monkeypatch.setattr(_u, "find_spec", lambda name: object() if name == "sentence_transformers" else None)
    checks = doctor_mod.run_all(tmp_path)
    msgs = [c.message for c in checks]
    assert any("sidecars" in m or "embeddings index" in m for m in msgs)
    # No failures from this path.
    assert "fail" not in _statuses(checks)


def test_mcp_log_recent_errors_fails(tmp_path):
    log = paths_mod.mcp_log_path()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(f"{now} ERROR boom\n", encoding="utf-8")
    checks = doctor_mod.run_all(tmp_path)
    assert any(c.status == "fail" and "ERROR" in c.message for c in checks)


def test_mcp_log_old_errors_ignored(tmp_path):
    log = paths_mod.mcp_log_path()
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(f"{old} ERROR ancient\n", encoding="utf-8")
    checks = doctor_mod.run_all(tmp_path)
    assert "fail" not in _statuses(checks)


def test_mcp_codex_warn_when_unwired(tmp_path):
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    checks = doctor_mod.run_all(tmp_path)
    assert any(
        c.status == "warn" and "Codex MCP" in c.message for c in checks
    ) or any(
        c.status == "warn" and "not registered" in c.message and ".codex" in c.message
        for c in checks
    )


def test_mcp_codex_ok_when_wired(tmp_path):
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "config.toml").write_text(
        '[mcp_servers.priors]\ncommand = "priors"\nargs = ["mcp"]\n',
        encoding="utf-8",
    )
    checks = doctor_mod.run_all(tmp_path)
    assert any("registered" in c.message and ".codex" in c.message for c in checks)


def test_mcp_wired_when_claude_json_lists_priors(tmp_path):
    claude_json = Path.home() / ".claude.json"
    claude_json.parent.mkdir(parents=True, exist_ok=True)
    claude_json.write_text(
        '{"mcpServers": {"priors": {"command": "priors", "args": ["mcp"]}}}',
        encoding="utf-8",
    )
    checks = doctor_mod.run_all(tmp_path)
    assert any("registered" in c.message for c in checks)


def test_cli_exit_codes(tmp_path):
    ok = runner.invoke(app, ["doctor"])
    assert ok.exit_code == 0, ok.output

    bad = paths_mod.entries_dir() / "2026-05-24-bad.md"
    bad.write_text("---\nid: x\n---\n", encoding="utf-8")
    fail = runner.invoke(app, ["doctor"])
    assert fail.exit_code == 1, fail.output
