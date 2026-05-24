from __future__ import annotations

from pathlib import Path
from typing import Literal

from priors import stacks as stacks_mod
from priors.adapters.base import Adapter
from priors.schema import Entry


class AgentsAdapter(Adapter):
    name = "agents"

    def target_path(self, scope: Literal["global", "project"], cwd: Path) -> Path | None:
        if scope == "global":
            return None
        root = stacks_mod.find_project_root(cwd)
        if root is None:
            return None
        return root / "AGENTS.md"

    def filter(self, entry: Entry, scope: str, stacks: set[str]) -> bool:
        if entry.scope == "global":
            return True
        if not entry.stacks:
            return True
        return bool(set(entry.stacks) & stacks)
