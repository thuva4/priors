from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

from priors import drafts as drafts_mod
from priors import store
from priors.cli import app
from priors.paths import drafts_dir
from priors.schema import Entry

runner = CliRunner()


def _seed_draft(draft_id="2026-05-24-x", trigger="t", severity="silent-bug"):
    drafts_dir().mkdir(parents=True, exist_ok=True)
    e = Entry(
        id=draft_id,
        date=date(2026, 5, 24),
        source="ai-drafted",
        trigger=trigger,
        rule="r",
        tags=["x"],
        severity=severity,
        body="> user said something\nbody",
        proposed_by="claude",
        proposed_at="2026-05-24T14:00:00+00:00",
        proposed_in="/tmp",
    )
    import frontmatter
    post = frontmatter.Post(e.body, **e.to_frontmatter())
    (drafts_dir() / f"{draft_id}.md").write_bytes(frontmatter.dumps(post).encode("utf-8") + b"\n")
    return e


def test_drafts_list_empty():
    result = runner.invoke(app, ["drafts"])
    assert result.exit_code == 0
    assert "no pending drafts" in result.output


def test_drafts_list_shows_drafts():
    _seed_draft()
    result = runner.invoke(app, ["drafts"])
    assert result.exit_code == 0
    assert "2026-05-24-x" in result.output


def test_review_approve_moves_to_entries():
    _seed_draft()
    result = runner.invoke(app, ["review"], input="a\n")
    assert result.exit_code == 0, result.output
    entries = store.load_all()
    assert any(e.id == "2026-05-24-x" for e in entries)
    assert entries[0].source == "ai-approved"
    assert not (drafts_dir() / "2026-05-24-x.md").exists()


def test_review_reject_deletes():
    _seed_draft()
    result = runner.invoke(app, ["review"], input="r\n")
    assert result.exit_code == 0
    assert not (drafts_dir() / "2026-05-24-x.md").exists()
    assert store.load_all() == []


def test_review_skip_leaves_alone():
    _seed_draft()
    result = runner.invoke(app, ["review"], input="s\n")
    assert result.exit_code == 0
    assert (drafts_dir() / "2026-05-24-x.md").exists()


def test_review_quit_stops():
    _seed_draft(draft_id="a")
    _seed_draft(draft_id="b")
    result = runner.invoke(app, ["review"], input="q\n")
    assert result.exit_code == 0
    # Both drafts remain.
    assert {p.stem for p in drafts_dir().glob("*.md")} == {"a", "b"}


def test_drafts_rm_all():
    _seed_draft(draft_id="a")
    _seed_draft(draft_id="b")
    result = runner.invoke(app, ["drafts", "--rm"])
    assert result.exit_code == 0
    assert list(drafts_dir().glob("*.md")) == []
