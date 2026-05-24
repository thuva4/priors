from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from priors import config as config_mod
from priors.adapters.base import Adapter
from priors.digest import build_digest
from priors.schema import Entry

PREAMBLE = """\
## How to use the priors MCP server

Before editing code, call `priors_for_context` when you have a concrete target
file or snippet and the work touches correctness-sensitive areas such as
database migrations, transactions, async/concurrency, auth/security, config,
time/date handling, external APIs, or production incidents. Pass the file path
and the relevant code snippet. If it returns matches, treat those matched priors
as active constraints for the edit.

Use `search_priors` for broader topic lookup when there is no exact file/snippet
yet, or when the task is planning/review rather than editing a specific code
site.

When the user states a durable cross-project rule — phrases like "always",
"never", "don't ever", "we got burned by", "remember this for next time" — call
the `propose_entry` tool on the `priors` MCP server. The tool's own docstring
has the full guard rails; honor them. In particular:

- Only propose for ARCHITECTURAL FOOTGUNS and SILENT CORRECTNESS BUGS.
- Do NOT propose for variable renames, typos, style, or one-off logic bugs.
- The `body` MUST include a verbatim `> `-prefixed quote of the user's words.
- If unsure, do not call it.

The rules below are the currently active digest. Treat them as standing
guidance for this session.
"""


class CodexAdapter(Adapter):
    """Writes ~/.codex/AGENTS.md (global). Project AGENTS.md is owned by the
    generic `agents` adapter — don't duplicate it here.
    """

    name = "codex"

    def target_path(self, scope: Literal["global", "project"], cwd: Path) -> Path | None:
        if scope != "global":
            return None
        cfg_path = config_mod.get("adapters.codex.global_path")
        if cfg_path:
            return Path(os.path.expanduser(str(cfg_path)))
        return Path.home() / ".codex" / "AGENTS.md"

    def filter(self, entry: Entry, scope: str, stacks: set[str]) -> bool:
        return entry.scope == "global"

    def render(self, entries: list[Entry]) -> str:
        return PREAMBLE + "\n" + build_digest(entries)
