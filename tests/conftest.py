from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def priors_home(tmp_path, monkeypatch):
    home = tmp_path / "priors"
    monkeypatch.setenv("PRIORS_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    home.mkdir(parents=True, exist_ok=True)
    (home / "entries").mkdir(parents=True, exist_ok=True)
    (home / "drafts").mkdir(parents=True, exist_ok=True)
    # Default to bm25 mode so tests don't hit the heavy embeddings model.
    (home / "config.toml").write_text(
        '[retrieval]\nmode = "bm25"\n', encoding="utf-8"
    )
    yield home
