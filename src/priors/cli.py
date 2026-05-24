from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date as date_cls
from pathlib import Path
from typing import Optional

import frontmatter
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from priors import adapters as adapters_mod
from priors import config as config_mod
from priors import drafts as drafts_mod
from priors import indexing
from priors import paths as paths_mod
from priors import retrieval
from priors import stacks as stacks_mod
from priors import store
from priors.schema import (
    SCOPES,
    SEVERITIES,
    SOURCES,
    Entry,
    SchemaError,
    derive_id,
    entry_from_frontmatter,
)
from priors.templates import editor_template

app = typer.Typer(
    no_args_is_help=True,
    help="Local memory for AI-coding lessons.",
)


def _complete_entry_id(incomplete: str) -> list[str]:
    try:
        return store.find_by_prefix(incomplete)
    except Exception:
        return []


def _complete_draft_id(incomplete: str) -> list[str]:
    try:
        return [e.id for e in drafts_mod.load_drafts() if e.id.startswith(incomplete)]
    except Exception:
        return []
console = Console()
err_console = Console(stderr=True)


@app.command()
def init(
    wire_claude: Optional[bool] = typer.Option(
        None, "--wire-claude/--no-wire-claude",
        help="Add 'priors' MCP server to ~/.claude.json. Default: prompt.",
    ),
    wire_codex: Optional[bool] = typer.Option(
        None, "--wire-codex/--no-wire-codex",
        help="Add 'priors' MCP server to ~/.codex/config.toml. Default: prompt.",
    ),
) -> None:
    """Create ~/.priors/ and a default config; optionally wire Claude Code / Codex."""
    paths_mod.ensure_dirs()
    created = config_mod.write_default_if_missing()
    home = paths_mod.priors_home()
    if created:
        console.print(f"Initialized priors at [bold]{home}[/bold]")
    else:
        console.print(f"Priors already initialized at [bold]{home}[/bold]")

    existing_enabled = _current_enabled_adapters()
    enabled_adapters: set[str] = set(existing_enabled)

    claude_json = Path.home() / ".claude.json"
    claude_dir = Path.home() / ".claude"
    if claude_json.exists() or claude_dir.exists():
        if wire_claude is None:
            wire_claude = typer.confirm("Detected Claude Code — wire up MCP server + CLAUDE.md adapter?", default=True)
        if wire_claude:
            enabled_adapters.add("claude-code")
            if claude_json.exists():
                changed = _wire_claude_code(claude_json)
                if changed:
                    console.print(f"Updated [bold]{claude_json}[/bold] — restart Claude Code or run /mcp reload.")
                else:
                    console.print(f"[dim]{claude_json} already references the priors MCP server.[/dim]")

    codex_dir = Path.home() / ".codex"
    if codex_dir.exists():
        codex_config = codex_dir / "config.toml"
        if wire_codex is None:
            wire_codex = typer.confirm("Detected Codex — wire up MCP server + adapter?", default=True)
        if wire_codex:
            enabled_adapters.add("codex")
            changed = _wire_codex(codex_config)
            if changed:
                console.print(f"Updated [bold]{codex_config}[/bold] — restart Codex.")
            else:
                console.print(f"[dim]{codex_config} already references the priors MCP server.[/dim]")

    # Only persist when host detection added something. Leaving the list empty
    # preserves the "fallback to all adapters" semantics for users who haven't
    # opted in / out of anything.
    if enabled_adapters and set(enabled_adapters) != set(existing_enabled):
        # AGENTS.md is per-repo with no host — bundle it alongside any host adapter.
        enabled_adapters.add("agents")
        new_enabled = ",".join(sorted(enabled_adapters))
        config_mod.set_("adapters.enabled", new_enabled)
        console.print(f"Enabled adapters: [bold]{new_enabled}[/bold]")


def _current_enabled_adapters() -> list[str]:
    raw = config_mod.get("adapters.enabled") or ""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [n.strip() for n in str(raw).split(",") if n.strip()]


def _wire_claude_code(claude_json: Path) -> bool:
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    servers = data.setdefault("mcpServers", {})
    if "priors" in servers:
        return False
    servers["priors"] = {"command": "priors", "args": ["mcp"]}
    claude_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _wire_codex(codex_config: Path) -> bool:
    """Append [mcp_servers.priors] to ~/.codex/config.toml. Returns False if
    the entry already exists. Appends to preserve user comments/formatting."""
    block = '[mcp_servers.priors]\ncommand = "priors"\nargs = ["mcp"]\n'
    if not codex_config.exists():
        codex_config.parent.mkdir(parents=True, exist_ok=True)
        codex_config.write_text(block, encoding="utf-8")
        return True
    text = codex_config.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        data = {}
    if "priors" in (data.get("mcp_servers") or {}):
        return False
    sep = "" if text.endswith("\n") else "\n"
    codex_config.write_text(text + sep + "\n" + block, encoding="utf-8")
    return True


@app.command(name="add")
def add_cmd(
    message: Optional[str] = typer.Option(None, "-m", "--message", help="Body text; skips editor."),
    rule: Optional[str] = typer.Option(None, "--rule"),
    trigger: Optional[str] = typer.Option(None, "--trigger"),
    tag: list[str] = typer.Option([], "--tag", help="Repeatable."),
    model: list[str] = typer.Option([], "--model", help="Repeatable."),
    tool: list[str] = typer.Option([], "--tool", help="Repeatable."),
    severity: Optional[str] = typer.Option(None, "--severity"),
    scope: str = typer.Option("project", "--scope"),
    stacks: Optional[str] = typer.Option(None, "--stacks", help="Comma-separated."),
    pin: bool = typer.Option(False, "--pin"),
) -> None:
    """Add a new entry."""
    paths_mod.ensure_dirs()
    if severity and severity not in SEVERITIES:
        err_console.print(f"[red]severity must be one of {list(SEVERITIES)}[/red]")
        raise typer.Exit(3)
    if scope not in SCOPES:
        err_console.print(f"[red]scope must be one of {list(SCOPES)}[/red]")
        raise typer.Exit(3)

    stacks_list = [s.strip() for s in stacks.split(",")] if stacks else []
    stacks_list = [s for s in stacks_list if s]

    if message is not None:
        body = message
        if not trigger:
            err_console.print("[red]--trigger is required with -m[/red]")
            raise typer.Exit(3)
        if not rule:
            err_console.print("[red]--rule is required with -m[/red]")
            raise typer.Exit(3)
        today = date_cls.today()
        entry = Entry(
            id=derive_id(today, trigger),
            date=today,
            source="human",
            trigger=trigger,
            rule=rule,
            models=list(model),
            tools=list(tool),
            tags=list(tag),
            severity=severity,
            scope=scope,
            stacks=stacks_list,
            pin=pin,
            body=body,
        )
        path = store.write(entry, overwrite=False)
        indexing.index_entry(entry)
        console.print(str(path))
        return

    # Editor flow.
    if not sys.stdin.isatty():
        err_console.print("[red]non-interactive add requires -m / --message[/red]")
        raise typer.Exit(3)

    initial = editor_template(date_cls.today())
    edited = _open_editor(initial)
    if edited.strip() == initial.strip():
        err_console.print("[yellow]No changes; aborting.[/yellow]")
        raise typer.Exit(1)
    try:
        post = frontmatter.loads(edited)
        fm = dict(post.metadata)
        # Merge CLI flag overrides.
        if trigger:
            fm["trigger"] = trigger
        if rule:
            fm["rule"] = rule
        if tag:
            fm["tags"] = list(tag)
        if model:
            fm["models"] = list(model)
        if tool:
            fm["tools"] = list(tool)
        if severity:
            fm["severity"] = severity
        if scope != "project":
            fm["scope"] = scope
        if stacks_list:
            fm["stacks"] = stacks_list
        if pin:
            fm["pin"] = True
        # Always set source=human, ensure date present.
        fm.setdefault("source", "human")
        if not fm.get("date"):
            fm["date"] = date_cls.today().isoformat()
        # Derive id if missing.
        if not fm.get("id"):
            d = fm["date"]
            if isinstance(d, str):
                d = date_cls.fromisoformat(d)
            fm["id"] = derive_id(d, str(fm.get("trigger") or ""))
        entry = entry_from_frontmatter(fm, post.content)
    except (SchemaError, ValueError, KeyError) as exc:
        err_console.print(f"[red]invalid entry: {exc}[/red]")
        raise typer.Exit(3) from exc
    path = store.write(entry, overwrite=False)
    indexing.index_entry(entry)
    console.print(str(path))


@app.command(name="list")
def list_cmd(
    tag: list[str] = typer.Option([], "--tag"),
    model: Optional[str] = typer.Option(None, "--model"),
    source: Optional[str] = typer.Option(None, "--source"),
    since: Optional[str] = typer.Option(None, "--since"),
    limit: int = typer.Option(20, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List entries (most recent first)."""
    if source and source not in SOURCES:
        err_console.print(f"[red]source must be one of {list(SOURCES)}[/red]")
        raise typer.Exit(3)
    entries = store.list_entries(
        tags=list(tag) or None,
        model=model,
        source=source,
        since=since,
        limit=limit,
    )
    if as_json:
        console.print_json(data=[_entry_to_dict(e) for e in entries])
        return
    if not entries:
        console.print("[dim]no entries[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("date")
    table.add_column("severity")
    table.add_column("tags")
    for e in entries:
        table.add_row(e.id, e.date.isoformat(), e.severity or "", ",".join(e.tags))
    console.print(table)


@app.command()
def show(id_or_prefix: str = typer.Argument(..., autocompletion=_complete_entry_id)) -> None:
    """Print a single entry as rendered markdown."""
    matches = store.find_by_prefix(id_or_prefix)
    if not matches:
        err_console.print(f"[red]no entry matching {id_or_prefix!r}[/red]")
        raise typer.Exit(1)
    if len(matches) > 1 and id_or_prefix not in matches:
        err_console.print(f"[yellow]multiple matches:[/yellow]")
        for m in matches:
            err_console.print(f"  {m}")
        raise typer.Exit(2)
    chosen = id_or_prefix if id_or_prefix in matches else matches[0]
    entry = store.get(chosen)
    console.print(f"[bold]{entry.id}[/bold] ({entry.date.isoformat()}, {entry.source})")
    console.print(f"[dim]trigger:[/dim] {entry.trigger}")
    console.print(f"[dim]rule:[/dim] {entry.rule}")
    if entry.tags:
        console.print(f"[dim]tags:[/dim] {', '.join(entry.tags)}")
    if entry.severity:
        console.print(f"[dim]severity:[/dim] {entry.severity}")
    if entry.body.strip():
        console.print()
        console.print(Markdown(entry.body))


@app.command()
def edit(id_or_prefix: str = typer.Argument(..., autocompletion=_complete_entry_id)) -> None:
    """Open an entry in $EDITOR."""
    matches = store.find_by_prefix(id_or_prefix)
    if not matches:
        err_console.print(f"[red]no entry matching {id_or_prefix!r}[/red]")
        raise typer.Exit(1)
    if len(matches) > 1 and id_or_prefix not in matches:
        for m in matches:
            err_console.print(f"  {m}")
        raise typer.Exit(2)
    chosen = id_or_prefix if id_or_prefix in matches else matches[0]
    path = store.entry_path(chosen)
    _edit_path(path)
    try:
        indexing.index_entry(store.get(chosen))
    except FileNotFoundError:
        pass


@app.command()
def rm(
    id_or_prefix: str = typer.Argument(..., autocompletion=_complete_entry_id),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete an entry."""
    matches = store.find_by_prefix(id_or_prefix)
    if not matches:
        err_console.print(f"[red]no entry matching {id_or_prefix!r}[/red]")
        raise typer.Exit(1)
    if len(matches) > 1 and id_or_prefix not in matches:
        for m in matches:
            err_console.print(f"  {m}")
        raise typer.Exit(2)
    chosen = id_or_prefix if id_or_prefix in matches else matches[0]
    if not yes:
        if not sys.stdin.isatty():
            err_console.print("[red]refusing to delete without --yes in non-interactive mode[/red]")
            raise typer.Exit(3)
        confirm = typer.confirm(f"Delete {chosen}?")
        if not confirm:
            raise typer.Exit(1)
    store.delete(chosen)
    indexing.remove_index(chosen)
    console.print(f"deleted {chosen}")


@app.command()
def search(
    query: str = typer.Argument(...),
    k: int = typer.Option(10, "-k", "--limit"),
    tag: list[str] = typer.Option([], "--tag"),
    source: Optional[str] = typer.Option(None, "--source"),
    since: Optional[str] = typer.Option(None, "--since"),
    mode: Optional[str] = typer.Option(None, "--mode", help="embeddings | bm25 | hybrid"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Semantic search over entries (BM25 fallback)."""
    if source and source not in SOURCES:
        err_console.print(f"[red]source must be one of {list(SOURCES)}[/red]")
        raise typer.Exit(3)
    filters = retrieval.Filters(
        tags=list(tag),
        source=source,
        since=since,
    )
    results = retrieval.search(query, k=k, filters=filters, mode=mode)  # type: ignore[arg-type]
    if as_json:
        console.print_json(
            data=[{"score": r.score, **_entry_to_dict(r.entry)} for r in results]
        )
        return
    if not results:
        console.print("[dim]no matches[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("score")
    table.add_column("id")
    table.add_column("date")
    table.add_column("rule")
    for r in results:
        table.add_row(f"{r.score:.3f}", r.entry.id, r.entry.date.isoformat(), r.entry.rule)
    console.print(table)


@app.command()
def context(
    topic: str = typer.Argument(...),
    limit: int = typer.Option(5, "--limit"),
    stacks_override: Optional[str] = typer.Option(None, "--stacks", help="Comma-separated stacks to filter by."),
) -> None:
    """Print relevant entries for a topic to stdout (for piping into context)."""
    if stacks_override:
        stack_set = {s.strip() for s in stacks_override.split(",") if s.strip()}
    else:
        stack_set = set(stacks_mod.detect_stacks(Path.cwd()))
    filters = retrieval.Filters(stacks=stack_set)
    results = retrieval.search(topic, k=limit, filters=filters)
    for r in results:
        console.print(f"# {r.entry.id} ({r.entry.date.isoformat()})")
        console.print(f"trigger: {r.entry.trigger}")
        console.print(f"rule: {r.entry.rule}")
        if r.entry.body.strip():
            console.print(r.entry.body.rstrip())
        console.print()


@app.command()
def reindex() -> None:
    """Rebuild embeddings sidecars for every entry."""
    mode = config_mod.get("retrieval.mode") or "embeddings"
    if mode == "bm25":
        console.print("[yellow]retrieval.mode is bm25; nothing to reindex[/yellow]")
        return
    entries = store.load_all()
    if not entries:
        console.print("[dim]no entries[/dim]")
        return
    from priors import embeddings as emb
    for e in entries:
        emb.embed_entry(e)
    console.print(f"reindexed {len(entries)} entries")


@app.command()
def sync(
    adapter: Optional[str] = typer.Argument(None, help="Limit to one adapter (claude-code | agents)."),
    scope: Optional[str] = typer.Option(None, "--scope", help="global | project"),
    check: bool = typer.Option(False, "--check", help="Exit 1 if any target is stale; write nothing."),
    path: Optional[Path] = typer.Option(None, "--path", help="Working dir for stack detection."),
) -> None:
    """Run enabled adapters and write CLAUDE.md / AGENTS.md."""
    cwd = path or Path.cwd()
    results = adapters_mod.sync_all(cwd, check_only=check)
    if adapter:
        results = [r for r in results if r.adapter == adapter]
    if scope:
        results = [r for r in results if r.scope == scope]
    any_changed = False
    for r in results:
        if r.changed:
            any_changed = True
            verb = "would write" if check else "wrote"
            console.print(f"✓ {r.adapter} ({r.scope}): {verb} {r.rule_count} rules to {r.target}")
        else:
            console.print(f"  {r.adapter} ({r.scope}): up to date ({r.target})")
    if check and any_changed:
        raise typer.Exit(1)


@app.command()
def recent(n: int = typer.Argument(10)) -> None:
    """Show the n most recent entries."""
    list_cmd(tag=[], model=None, source=None, since=None, limit=n, as_json=False)


@app.command()
def stats(
    effectiveness_flag: bool = typer.Option(
        False, "--effectiveness", help="Show which entries actually fire."
    ),
    window: int = typer.Option(30, "--window", help="Window in days for fire/near-miss counts."),
    cold_age: int = typer.Option(60, "--cold-age", help="Minimum age (days) for cold-entry candidates."),
) -> None:
    """Summarize the priors set. --effectiveness reports which entries actually fire."""
    from priors import effectiveness as eff
    entries = store.load_all()
    if not effectiveness_flag:
        console.print(f"Curated entries: {len(entries)}")
        by_source: dict[str, int] = {}
        for e in entries:
            by_source[e.source] = by_source.get(e.source, 0) + 1
        for src, n in sorted(by_source.items()):
            console.print(f"  {src}: {n}")
        return

    events = eff.load_events()
    s = eff.aggregate(entries=entries, events=events, window_days=window, cold_min_age_days=cold_age)
    by_id = {e.id: e for e in entries}

    console.print(f"[bold]Top firing entries (last {s.window_days}d):[/bold]")
    if not s.fires:
        console.print("  [dim](none — no recorded fires in window)[/dim]")
    for eid, count in s.fires[:10]:
        e = by_id.get(eid)
        label = f"{eid}" if e is None else f"{eid}  [dim]{e.rule[:60]}[/dim]"
        console.print(f"  {count:>4}  {label}")

    console.print(f"\n[bold]Cold entries (0 fires, age ≥ {s.cold_min_age_days}d):[/bold]")
    if not s.cold:
        console.print("  [dim](none)[/dim]")
    for eid, age in s.cold[:10]:
        console.print(f"  {age:>4}d  {eid}  [dim]candidate for removal[/dim]")

    console.print(f"\n[bold]Near-misses (last {s.window_days}d):[/bold]")
    if not s.near_misses:
        console.print("  [dim](none — no AI drafts blocked by similar-entry guard)[/dim]")
    for eid, count in s.near_misses[:10]:
        hint = "rule wording may be weak" if count >= 3 else "model nearly re-proposed this"
        console.print(f"  {count:>4}  {eid}  [dim]{hint}[/dim]")


@app.command()
def doctor(
    path: Optional[Path] = typer.Option(None, "--path", help="Working dir for adapter checks."),
) -> None:
    """Diagnose common priors breakage. Exits 1 if any check fails."""
    from priors import doctor as doctor_mod
    cwd = path or Path.cwd()
    checks = doctor_mod.run_all(cwd)
    icons = {"ok": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]", "fail": "[red]✗[/red]"}
    any_fail = False
    for c in checks:
        if c.status == "fail":
            any_fail = True
        console.print(f"{icons[c.status]} {c.message}")
        if c.hint:
            console.print(f"  [dim]→ {c.hint}[/dim]")
    if any_fail:
        raise typer.Exit(1)


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not prompt before uninstalling."),
    keep_data: bool = typer.Option(True, "--keep-data/--remove-data", help="Keep or remove ~/.priors."),
    remove_cli: bool = typer.Option(True, "--cli/--no-cli", help="Remove the uv tool install if present."),
    remove_mcp: bool = typer.Option(True, "--mcp/--no-mcp", help="Remove Claude/Codex MCP registrations."),
) -> None:
    """Remove priors MCP registrations and optionally the CLI install/data."""
    if not yes and sys.stdin.isatty():
        if not typer.confirm("Uninstall priors integrations from this machine?", default=False):
            raise typer.Exit(1)
    elif not yes and not sys.stdin.isatty():
        err_console.print("[red]non-interactive uninstall requires --yes[/red]")
        raise typer.Exit(3)

    changed: list[str] = []
    skipped: list[str] = []

    if remove_mcp:
        if _remove_claude_mcp():
            changed.append("removed Claude MCP registration")
        else:
            skipped.append("Claude MCP registration not present")
        if _remove_codex_mcp():
            changed.append("removed Codex MCP registration")
        else:
            skipped.append("Codex MCP registration not present")

    if not keep_data:
        home = paths_mod.priors_home()
        if home.exists():
            shutil.rmtree(home)
            changed.append(f"removed {home}")
        else:
            skipped.append(f"{home} not present")

    if remove_cli:
        uv = shutil.which("uv")
        if uv:
            result = subprocess.run([uv, "tool", "uninstall", "priors"], text=True, capture_output=True)
            if result.returncode == 0:
                changed.append("removed uv tool install")
            else:
                skipped.append((result.stderr or result.stdout or "uv tool install not present").strip())
        else:
            skipped.append("uv not found; CLI install not removed")

    for item in changed:
        console.print(f"[green]✓[/green] {item}")
    for item in skipped:
        console.print(f"[dim]- {item}[/dim]")


@app.command()
def mcp(
    path: Optional[Path] = typer.Option(None, "--path", help="Working dir for stack detection."),
) -> None:
    """Run the stdio MCP server (long-running)."""
    from priors import mcp_server
    mcp_server.run_stdio(cwd=path or Path.cwd())


@app.command()
def drafts(
    age: Optional[str] = typer.Option(None, "--age", help="e.g. 30d — only show drafts older than this."),
    rm: bool = typer.Option(False, "--rm", help="Delete the listed drafts."),
    reject_all_nits: bool = typer.Option(False, "--reject-all-nits", help="Delete drafts below severity floor."),
    stats: bool = typer.Option(False, "--stats", help="Print acceptance/rejection rate over the recent window."),
    window: int = typer.Option(30, "--window", help="Window in days for --stats."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List or prune pending AI drafts."""
    items = drafts_mod.load_drafts()
    if stats:
        from priors import effectiveness as eff
        s = eff.aggregate_drafts(eff.load_events(), pending=len(items), window_days=window)
        if as_json:
            console.print_json(data={
                "window_days": s.window_days,
                "proposed": s.proposed,
                "written": s.written,
                "rejected_by_guard": s.rejected_by_guard,
                "rejected_by_reason": dict(s.rejected_by_reason),
                "approved": s.approved,
                "reviewed_rejected": s.reviewed_rejected,
                "pending": s.pending,
                "acceptance_rate": s.acceptance_rate,
                "write_rate": s.write_rate,
            })
            return
        console.print(f"[bold]Draft stats (last {s.window_days}d)[/bold]")
        console.print(f"  propose_entry calls: {s.proposed}  "
                      f"(written: {s.written}, blocked by guard: {s.rejected_by_guard})")
        if s.write_rate is not None:
            console.print(f"  write rate (post-guard): {s.write_rate * 100:.0f}%")
        if s.rejected_by_reason:
            console.print("  rejections by reason:")
            for reason, count in s.rejected_by_reason:
                console.print(f"    {count:>4}  {reason}")
        console.print(f"  reviewed: {s.approved + s.reviewed_rejected}  "
                      f"(approved: {s.approved}, rejected: {s.reviewed_rejected})")
        if s.acceptance_rate is not None:
            pct = s.acceptance_rate * 100
            hint = ""
            if pct < 50:
                hint = "  [dim]→ model is drafting too liberally; tighten guards[/dim]"
            elif pct > 90:
                hint = "  [dim]→ model may not be drafting enough[/dim]"
            console.print(f"  acceptance rate: {pct:.0f}%{hint}")
        console.print(f"  pending: {s.pending}")
        return
    if age:
        cutoff = store._parse_since(age)
        items = [e for e in items if e.date <= cutoff]
    if reject_all_nits:
        floor = set(drafts_mod.ALLOWED_DRAFT_SEVERITIES)
        targets = [e for e in items if e.severity not in floor]
        for e in targets:
            drafts_mod.delete_draft(e.id)
        console.print(f"rejected {len(targets)} drafts below severity floor")
        return
    if rm:
        for e in items:
            drafts_mod.delete_draft(e.id)
        console.print(f"deleted {len(items)} drafts")
        return
    if as_json:
        console.print_json(data=[_entry_to_dict(e) for e in items])
        return
    if not items:
        console.print("[dim]no pending drafts[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("proposed_at")
    table.add_column("by")
    table.add_column("severity")
    table.add_column("trigger")
    for e in items:
        table.add_row(e.id, e.proposed_at or "", e.proposed_by or "", e.severity or "", e.trigger)
    console.print(table)


@app.command()
def review(
    yes_all: bool = typer.Option(False, "--yes-all", help="Approve every pending draft without prompting."),
) -> None:
    """Interactive draft triage."""
    items = drafts_mod.load_drafts()
    if not items:
        console.print("[dim]no pending drafts[/dim]")
        return
    console.print(f"{len(items)} draft(s) pending.")

    for i, entry in enumerate(items, start=1):
        console.print()
        console.print(f"[bold]Draft {i}/{len(items)}[/bold] — "
                      f"{entry.proposed_by or '?'} in {entry.proposed_in or '?'}, "
                      f"{entry.proposed_at or entry.date.isoformat()}")
        _render_draft(entry)
        if yes_all:
            drafts_mod.approve_draft(entry.id)
            console.print(f"[green]approved[/green] {entry.id}")
            continue
        while True:
            choice = typer.prompt("[a]pprove [e]dit [r]eject [s]kip [q]uit", default="s").strip().lower()
            if choice in ("a", "approve"):
                drafts_mod.approve_draft(entry.id)
                console.print(f"[green]approved[/green] {entry.id}")
                break
            if choice in ("r", "reject"):
                drafts_mod.delete_draft(entry.id)
                console.print(f"[yellow]rejected[/yellow] {entry.id}")
                break
            if choice in ("s", "skip"):
                break
            if choice in ("q", "quit"):
                return
            if choice in ("e", "edit"):
                _edit_path(drafts_mod.draft_path(entry.id))
                # Reload and re-render, then loop again.
                try:
                    entry = next(d for d in drafts_mod.load_drafts() if d.id == entry.id)
                except StopIteration:
                    console.print("[yellow]draft no longer present after edit[/yellow]")
                    break
                _render_draft(entry)


def _render_draft(entry: Entry) -> None:
    console.print(f"  trigger:  {entry.trigger}")
    console.print(f"  rule:     {entry.rule}")
    console.print(f"  tags:     {entry.tags}")
    console.print(f"  scope:    {entry.scope}")
    console.print(f"  stacks:   {entry.stacks}")
    console.print(f"  severity: {entry.severity}")
    if entry.body.strip():
        console.print()
        console.print(entry.body.rstrip())


config_app = typer.Typer(help="Read/write config values.")
app.add_typer(config_app, name="config")


@config_app.command("get")
def config_get(key: str) -> None:
    val = config_mod.get(key)
    if val is None:
        raise typer.Exit(1)
    if isinstance(val, (dict, list)):
        console.print(json.dumps(val))
    else:
        console.print(str(val))


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    config_mod.set_(key, value)


def _remove_claude_mcp() -> bool:
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return False
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or "priors" not in servers:
        return False
    del servers["priors"]
    claude_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _remove_codex_mcp() -> bool:
    codex_config = Path.home() / ".codex" / "config.toml"
    if not codex_config.exists():
        return False
    text = codex_config.read_text(encoding="utf-8")
    new_text = _remove_toml_table_tree(text, "mcp_servers.priors")
    if new_text == text:
        return False
    codex_config.write_text(new_text, encoding="utf-8")
    return True


def _remove_toml_table_tree(text: str, table: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skip = False
    prefix = f"{table}."
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped.strip("[]").strip()
            skip = name == table or name.startswith(prefix)
        if not skip:
            out.append(line)
    return "".join(out)


def _entry_to_dict(e: Entry) -> dict:
    return {
        "id": e.id,
        "date": e.date.isoformat(),
        "source": e.source,
        "trigger": e.trigger,
        "rule": e.rule,
        "models": e.models,
        "tools": e.tools,
        "tags": e.tags,
        "severity": e.severity,
        "scope": e.scope,
        "stacks": e.stacks,
        "pin": e.pin,
        "body": e.body,
    }


def _open_editor(initial: str) -> str:
    editor = os.environ.get("EDITOR") or config_mod.get("editor.command") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tf:
        tf.write(initial)
        tmp_path = Path(tf.name)
    try:
        subprocess.run([editor, str(tmp_path)], check=True)
        return tmp_path.read_text(encoding="utf-8")
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _edit_path(path: Path) -> None:
    editor = os.environ.get("EDITOR") or config_mod.get("editor.command") or "vi"
    subprocess.run([editor, str(path)], check=True)
