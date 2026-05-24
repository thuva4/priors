from datetime import date

from typer.testing import CliRunner

from priors import store
from priors.cli import app
from priors.schema import Entry

runner = CliRunner()


def _write(**kw):
    base = dict(
        id="2026-05-24-seed",
        date=date(2026, 5, 24),
        source="human",
        trigger="t",
        rule="r",
        body="body",
    )
    base.update(kw)
    store.write(Entry(**base))


def test_init():
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    result2 = runner.invoke(app, ["init"])
    assert result2.exit_code == 0


def test_init_wires_codex_when_dir_exists(tmp_path, monkeypatch):
    import tomllib
    from pathlib import Path
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    result = runner.invoke(app, ["init", "--no-wire-claude", "--wire-codex"])
    assert result.exit_code == 0, result.output
    cfg = codex_dir / "config.toml"
    assert cfg.exists()
    data = tomllib.loads(cfg.read_text())
    assert data["mcp_servers"]["priors"] == {"command": "priors", "args": ["mcp"]}


def test_init_codex_preserves_existing_config(tmp_path):
    import tomllib
    from pathlib import Path
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    cfg = codex_dir / "config.toml"
    cfg.write_text(
        '# user comment\nmodel = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "--no-wire-claude", "--wire-codex"])
    assert result.exit_code == 0, result.output
    text = cfg.read_text()
    assert "# user comment" in text  # preserved
    data = tomllib.loads(text)
    assert "priors" in data["mcp_servers"]
    assert "other" in data["mcp_servers"]  # not clobbered


def test_init_codex_idempotent(tmp_path):
    from pathlib import Path
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    runner.invoke(app, ["init", "--no-wire-claude", "--wire-codex"])
    before = (codex_dir / "config.toml").read_text()
    runner.invoke(app, ["init", "--no-wire-claude", "--wire-codex"])
    after = (codex_dir / "config.toml").read_text()
    assert before == after


def test_uninstall_removes_mcp_registrations(tmp_path):
    import json
    import tomllib
    from pathlib import Path

    claude_json = Path.home() / ".claude.json"
    claude_json.parent.mkdir(parents=True, exist_ok=True)
    claude_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "priors": {"command": "priors", "args": ["mcp"]},
                    "other": {"command": "x"},
                }
            }
        ),
        encoding="utf-8",
    )

    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_config = codex_dir / "config.toml"
    codex_config.write_text(
        'model = "gpt-5"\n\n'
        '[mcp_servers.priors]\ncommand = "priors"\nargs = ["mcp"]\n\n'
        '[mcp_servers.priors.tools.search_priors]\napproval_mode = "approve"\n\n'
        '[mcp_servers.other]\ncommand = "x"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["uninstall", "--yes", "--no-cli", "--keep-data"])
    assert result.exit_code == 0, result.output

    claude_data = json.loads(claude_json.read_text())
    assert "priors" not in claude_data["mcpServers"]
    assert "other" in claude_data["mcpServers"]

    codex_data = tomllib.loads(codex_config.read_text())
    assert "priors" not in codex_data["mcp_servers"]
    assert "other" in codex_data["mcp_servers"]
    assert codex_data["model"] == "gpt-5"


def test_add_with_message():
    result = runner.invoke(
        app,
        ["add", "-m", "the body", "--trigger", "mock hid bug", "--rule", "use real db", "--tag", "test"],
    )
    assert result.exit_code == 0, result.output
    entries = store.list_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e.rule == "use real db"
    assert e.trigger == "mock hid bug"
    assert "test" in e.tags


def test_add_missing_required_flags():
    result = runner.invoke(app, ["add", "-m", "x"])
    assert result.exit_code == 3


def test_list_outputs():
    _write(id="2026-05-24-a")
    _write(id="2026-05-24-b")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "2026-05-24-a" in result.output
    assert "2026-05-24-b" in result.output


def test_show_prefix():
    _write(id="2026-05-24-uniqueone")
    result = runner.invoke(app, ["show", "2026-05-24-uniq"])
    assert result.exit_code == 0
    assert "2026-05-24-uniqueone" in result.output


def test_show_ambiguous():
    _write(id="2026-05-24-aaa")
    _write(id="2026-05-24-aab")
    result = runner.invoke(app, ["show", "2026-05-24-aa"])
    assert result.exit_code == 2


def test_show_missing():
    result = runner.invoke(app, ["show", "no-such"])
    assert result.exit_code == 1


def test_search():
    _write(id="2026-05-24-mig", body="something about database migration scripts")
    _write(id="2026-05-24-other", body="totally unrelated content")
    result = runner.invoke(app, ["search", "migration"])
    assert result.exit_code == 0
    assert "2026-05-24-mig" in result.output


def test_rm_yes():
    _write(id="2026-05-24-del")
    result = runner.invoke(app, ["rm", "2026-05-24-del", "--yes"])
    assert result.exit_code == 0
    assert store.find_by_prefix("2026-05-24-del") == []


def test_config_set_and_get():
    set_res = runner.invoke(app, ["config", "set", "retrieval.mode", "hybrid"])
    assert set_res.exit_code == 0
    get_res = runner.invoke(app, ["config", "get", "retrieval.mode"])
    assert get_res.exit_code == 0
    assert "hybrid" in get_res.output


def test_list_json():
    _write(id="2026-05-24-j")
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    assert "2026-05-24-j" in result.output
