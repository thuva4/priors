from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from priors import config as config_mod
from priors import stacks as stacks_mod
from priors.adapters.base import Adapter
from priors.schema import Entry


class ClaudeCodeAdapter(Adapter):
    name = "claude-code"

    def target_path(self, scope: Literal["global", "project"], cwd: Path) -> Path | None:
        if scope == "global":
            cfg_path = config_mod.get("adapters.claude-code.global_path")
            if cfg_path:
                return Path(os.path.expanduser(str(cfg_path)))
            return Path.home() / ".claude" / "CLAUDE.md"
        root = stacks_mod.find_project_root(cwd)
        if root is None:
            return None
        return root / "CLAUDE.md"

    def filter(self, entry: Entry, scope: str, stacks: set[str]) -> bool:
        if scope == "global":
            return entry.scope == "global"
        if entry.scope == "global":
            return True
        if not entry.stacks:
            return True
        return bool(set(entry.stacks) & stacks)
