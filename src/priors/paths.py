from __future__ import annotations

import os
from pathlib import Path


def priors_home() -> Path:
    env = os.environ.get("PRIORS_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".priors"


def entries_dir() -> Path:
    return priors_home() / "entries"


def drafts_dir() -> Path:
    return priors_home() / "drafts"


def rejected_drafts_dir() -> Path:
    return drafts_dir() / "rejected"


def draft_rate_path() -> Path:
    return priors_home() / ".draft_rate"


def mcp_log_path() -> Path:
    return priors_home() / "mcp.log"


def effectiveness_log_path() -> Path:
    return priors_home() / "effectiveness.jsonl"


def config_path() -> Path:
    return priors_home() / "config.toml"


def ensure_dirs() -> None:
    entries_dir().mkdir(parents=True, exist_ok=True)
    drafts_dir().mkdir(parents=True, exist_ok=True)
