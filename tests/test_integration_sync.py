"""Integration: capture -> sync -> edit -> sync, end-to-end."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from priors import store
from priors.cli import app

runner = CliRunner()


def test_capture_sync_edit_sync(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

    runner.invoke(app, ["init"])
    add = runner.invoke(
        app,
        [
            "add",
            "-m",
            "body",
            "--trigger",
            "the python rule",
            "--rule",
            "always foo the bar",
            "--scope",
            "project",
            "--stacks",
            "python",
        ],
    )
    assert add.exit_code == 0, add.output

    sync = runner.invoke(app, ["sync", "--path", str(project)])
    assert sync.exit_code == 0, sync.output
    claude_md = project / "CLAUDE.md"
    assert claude_md.exists()
    assert "always foo the bar" in claude_md.read_text()

    # Edit by overwriting via store layer (avoids interactive editor).
    [entry] = store.load_all()
    entry.rule = "always baz the qux"
    store.write(entry, overwrite=True)

    sync2 = runner.invoke(app, ["sync", "--path", str(project)])
    assert sync2.exit_code == 0
    assert "always baz the qux" in claude_md.read_text()
    assert "always foo the bar" not in claude_md.read_text()
