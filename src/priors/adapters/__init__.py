from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from priors import config as config_mod
from priors import stacks as stacks_mod
from priors import store
from priors.adapters.agents import AgentsAdapter
from priors.adapters.base import Adapter
from priors.adapters.claude_code import ClaudeCodeAdapter
from priors.adapters.codex import CodexAdapter

REGISTRY: dict[str, type[Adapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "agents": AgentsAdapter,
    "codex": CodexAdapter,
}


@dataclass
class SyncResult:
    adapter: str
    scope: str
    target: Path
    changed: bool
    rule_count: int


def enabled_adapters() -> list[Adapter]:
    cfg = config_mod.load()
    raw = cfg.get("adapters", {}).get("enabled", "")
    if isinstance(raw, str):
        names = [n.strip() for n in raw.split(",") if n.strip()]
    else:
        names = list(raw)
    if not names:
        names = list(REGISTRY.keys())
    out: list[Adapter] = []
    for n in names:
        cls = REGISTRY.get(n)
        if cls is None:
            continue
        out.append(cls())
    return out


def sync_all(cwd: Path, *, check_only: bool = False) -> list[SyncResult]:
    entries = store.load_all()
    detected = stacks_mod.detect_stacks(cwd)
    in_project = stacks_mod.find_project_root(cwd) is not None
    results: list[SyncResult] = []
    for adapter in enabled_adapters():
        for scope in ("global", "project"):
            if scope == "project" and not in_project:
                continue
            target = adapter.target_path(scope, cwd)
            if target is None:
                continue
            filtered = [e for e in entries if adapter.filter(e, scope, detected)]
            content = adapter.render(filtered)
            changed = adapter.would_change(target, content)
            if changed and not check_only:
                adapter.write(target, content)
            results.append(
                SyncResult(
                    adapter=adapter.name,
                    scope=scope,
                    target=target,
                    changed=changed,
                    rule_count=len(filtered),
                )
            )
    return results
