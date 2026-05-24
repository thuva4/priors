from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from priors.digest import build_digest
from priors.schema import Entry

BEGIN_MARK = "<!-- BEGIN priors -->"
END_MARK = "<!-- END priors -->"


class Adapter(ABC):
    name: str = "adapter"

    @abstractmethod
    def target_path(self, scope: Literal["global", "project"], cwd: Path) -> Path | None: ...

    @abstractmethod
    def filter(self, entry: Entry, scope: str, stacks: set[str]) -> bool: ...

    def render(self, entries: list[Entry]) -> str:
        return build_digest(entries)

    def would_change(self, target: Path, content: str) -> bool:
        new_doc = _apply_markers(target, content)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        return new_doc != existing

    def write(self, target: Path, content: str) -> bool:
        new_doc = _apply_markers(target, content)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if new_doc == existing:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_doc, encoding="utf-8")
        return True


def _apply_markers(target: Path, content: str) -> str:
    block = f"{BEGIN_MARK}\n{content.rstrip()}\n{END_MARK}\n"
    if not target.exists():
        return block
    existing = target.read_text(encoding="utf-8")
    if BEGIN_MARK in existing and END_MARK in existing:
        before, _, rest = existing.partition(BEGIN_MARK)
        _, _, after = rest.partition(END_MARK)
        # `after` keeps any trailing content after the END marker.
        return f"{before}{block.rstrip()}\n{after.lstrip()}" if after.strip() else f"{before}{block}"
    # Append, separated by a blank line.
    sep = "" if existing.endswith("\n") else "\n"
    return f"{existing}{sep}\n{block}"
