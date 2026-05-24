from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import frontmatter

from priors import adapters as adapters_mod
from priors import config as config_mod
from priors import paths as paths_mod
from priors import store
from priors.embeddings import DEFAULT_MODEL, embeddings_dir, sidecar_path
from priors.schema import SchemaError, entry_from_frontmatter

Status = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    status: Status
    message: str
    hint: str | None = None


def run_all(cwd: Path) -> list[Check]:
    out: list[Check] = []
    out.extend(_check_home())
    entries_result = _check_entries()
    out.extend(entries_result.checks)
    out.extend(_check_embeddings(entries_result.entry_ids))
    out.extend(_check_adapters(cwd))
    out.extend(_check_mcp())
    return out


@dataclass
class _EntriesResult:
    checks: list[Check]
    entry_ids: list[str]


def _check_home() -> list[Check]:
    home = paths_mod.priors_home()
    if not home.exists():
        return [Check("fail", f"{home} does not exist", "run `priors init`")]
    if not os.access(home, os.W_OK):
        return [Check("fail", f"{home} is not writable")]
    return [Check("ok", f"{home} exists and is writable")]


def _check_entries() -> _EntriesResult:
    d = paths_mod.entries_dir()
    if not d.exists():
        return _EntriesResult([Check("warn", "no entries directory yet")], [])
    paths = sorted(d.glob("*.md"))
    good_ids: list[str] = []
    corrupted: list[str] = []
    for p in paths:
        try:
            post = frontmatter.load(str(p))
            entry = entry_from_frontmatter(dict(post.metadata), post.content)
            good_ids.append(entry.id)
        except (SchemaError, ValueError, KeyError, OSError):
            corrupted.append(p.name)
    checks: list[Check] = []
    msg = f"{len(good_ids)} entries, {len(corrupted)} corrupted"
    if corrupted:
        checks.append(
            Check(
                "fail",
                msg,
                hint=f"inspect: {', '.join(corrupted[:3])}"
                + (" …" if len(corrupted) > 3 else ""),
            )
        )
    else:
        checks.append(Check("ok", msg))
    return _EntriesResult(checks, good_ids)


def _check_embeddings(entry_ids: list[str]) -> list[Check]:
    mode = config_mod.get("retrieval.mode") or "embeddings"
    if mode == "bm25":
        return [Check("ok", f"retrieval mode is {mode}; embeddings not required")]

    checks: list[Check] = []
    try:
        import importlib.util

        spec = importlib.util.find_spec("sentence_transformers")
        if spec is None:
            checks.append(
                Check(
                    "fail",
                    "sentence-transformers not installed",
                    "pip install priors[embeddings] or switch retrieval.mode=bm25",
                )
            )
            return checks
        checks.append(Check("ok", f"embeddings model configured ({DEFAULT_MODEL})"))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(Check("fail", f"embeddings probe failed: {exc}"))
        return checks

    if not entry_ids:
        return checks

    edir = embeddings_dir()
    missing: list[str] = []
    for eid in entry_ids:
        if not sidecar_path(eid).exists():
            missing.append(eid)
    if not edir.exists() and entry_ids:
        checks.append(
            Check(
                "warn",
                f"no embeddings index yet ({len(entry_ids)} entries)",
                hint="run `priors reindex`",
            )
        )
    elif missing:
        checks.append(
            Check(
                "warn",
                f"{len(missing)} entries missing sidecars",
                hint="run `priors reindex`",
            )
        )
    else:
        checks.append(Check("ok", f"embeddings index up to date ({len(entry_ids)} entries)"))
    return checks


def _check_adapters(cwd: Path) -> list[Check]:
    checks: list[Check] = []
    enabled = adapters_mod.enabled_adapters()
    names = [a.name for a in enabled]
    if not names:
        checks.append(Check("warn", "no adapters enabled"))
        return checks
    checks.append(Check("ok", f"adapters enabled: {', '.join(names)}"))

    try:
        results = adapters_mod.sync_all(cwd, check_only=True)
    except (OSError, ValueError) as exc:
        checks.append(Check("fail", f"adapter sync probe failed: {exc}"))
        return checks

    for r in results:
        target = r.target
        if target.exists():
            writable = os.access(target, os.W_OK)
        else:
            # Walk up to the nearest existing ancestor; adapter.write() will mkdir
            # the rest with parents=True.
            anc = target.parent
            while not anc.exists() and anc != anc.parent:
                anc = anc.parent
            writable = anc.exists() and os.access(anc, os.W_OK)
        if not writable:
            checks.append(
                Check(
                    "fail",
                    f"{r.adapter} ({r.scope}): target not writable — {target}",
                )
            )
            continue
        if r.changed:
            checks.append(
                Check(
                    "warn",
                    f"{r.adapter} ({r.scope}): target stale — {target}",
                    hint="run `priors sync`",
                )
            )
        else:
            checks.append(
                Check("ok", f"{r.adapter} ({r.scope}): up to date ({target})")
            )
    return checks


def _check_mcp() -> list[Check]:
    checks: list[Check] = []
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        checks.append(
            Check(
                "warn",
                f"{claude_json} not found; MCP server not wired",
                hint="run `priors init` inside a project with Claude Code",
            )
        )
    else:
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or {}
            if "priors" in servers:
                checks.append(Check("ok", f"MCP server registered in {claude_json}"))
            else:
                checks.append(
                    Check(
                        "warn",
                        f"MCP server not registered in {claude_json}",
                        hint="run `priors init --wire-claude`",
                    )
                )
        except (OSError, ValueError) as exc:
            checks.append(Check("fail", f"could not read {claude_json}: {exc}"))

    codex_dir = Path.home() / ".codex"
    codex_config = codex_dir / "config.toml"
    if codex_dir.exists():
        if not codex_config.exists():
            checks.append(
                Check(
                    "warn",
                    f"{codex_config} not found; Codex MCP server not wired",
                    hint="run `priors init --wire-codex`",
                )
            )
        else:
            try:
                data = tomllib.loads(codex_config.read_text(encoding="utf-8"))
                servers = data.get("mcp_servers") or {}
                if "priors" in servers:
                    checks.append(Check("ok", f"MCP server registered in {codex_config}"))
                else:
                    checks.append(
                        Check(
                            "warn",
                            f"MCP server not registered in {codex_config}",
                            hint="run `priors init --wire-codex`",
                        )
                    )
            except (OSError, tomllib.TOMLDecodeError) as exc:
                checks.append(Check("fail", f"could not read {codex_config}: {exc}"))

    log_path = paths_mod.mcp_log_path()
    if not log_path.exists():
        checks.append(Check("ok", "MCP log absent (server has not run)"))
        return checks
    try:
        recent_errors = _count_recent_errors(log_path, hours=24)
    except OSError as exc:
        checks.append(Check("fail", f"could not read {log_path}: {exc}"))
        return checks
    if recent_errors:
        checks.append(
            Check(
                "fail",
                f"{recent_errors} ERROR line(s) in {log_path} in last 24h",
                hint=f"tail {log_path}",
            )
        )
    else:
        checks.append(Check("ok", "MCP log has no errors in last 24h"))
    return checks


def _count_recent_errors(path: Path, *, hours: int) -> int:
    cutoff = datetime.now() - timedelta(hours=hours)
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "ERROR" not in line:
                continue
            ts = _parse_log_timestamp(line)
            if ts is None or ts >= cutoff:
                count += 1
    return count


def _parse_log_timestamp(line: str) -> datetime | None:
    # Accept ISO-8601-ish prefix; if absent, treat as recent (return None).
    head = line[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(head, fmt)
        except ValueError:
            continue
    return None
