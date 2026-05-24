from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Any, Literal

from priors import drafts as drafts_mod
from priors import effectiveness
from priors import retrieval
from priors import stacks as stacks_mod
from priors import triggers as triggers_mod
from priors.paths import mcp_log_path
from priors.schema import Entry

log = logging.getLogger("priors.mcp")


def _setup_logging() -> None:
    log_path = mcp_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _entry_to_dict(e: Entry) -> dict[str, Any]:
    return {
        "id": e.id,
        "date": e.date.isoformat(),
        "trigger": e.trigger,
        "rule": e.rule,
        "tags": e.tags,
        "stacks": e.stacks,
        "severity": e.severity,
        "scope": e.scope,
        "body": e.body,
    }


def build_server(cwd: Path | None = None):
    """Construct a FastMCP server with the three priors tools registered."""
    from mcp.server.fastmcp import FastMCP

    cwd = cwd or Path.cwd()
    detected_stacks = set(stacks_mod.detect_stacks(cwd))
    session_state: dict[str, int] = {"drafts_in_session": 0}

    server = FastMCP("priors")

    @server.tool()
    def search_priors(
        query: str,
        tags: list[str] | None = None,
        limit: int = 5,
        all_stacks: bool = False,
    ) -> list[dict]:
        """Search the user's personal AI-mistake priors for entries relevant to a query.

        Use this before performing tasks in domains where the user may have noted past
        mistakes — concurrency, transactions, dates, auth, migrations, security. Returns
        ranked entries with id, trigger, rule, body, tags, date, severity.
        Filtered to the current project's detected technology stacks by default; set
        all_stacks=true to search across all priors.
        """
        filters = retrieval.Filters(
            tags=tags or [],
            stacks=set() if all_stacks else detected_stacks,
        )
        results = retrieval.search(query, k=limit, filters=filters, mode="hybrid")
        effectiveness.record_fire(
            [r.entry.id for r in results], tool="search_priors", query=query
        )
        return [{"score": r.score, **_entry_to_dict(r.entry)} for r in results]

    @server.tool()
    def recent_entries(limit: int = 10, tag: str | None = None) -> list[dict]:
        """List the most recent priors entries. Useful at session start to load
        general context, or when the user references something they just added.
        Stack-filtered to the current project by default.
        """
        from priors import store
        entries = store.list_entries(tags=[tag] if tag else None, limit=None)
        filtered: list[Entry] = []
        for e in entries:
            if e.scope == "global" or not e.stacks or (set(e.stacks) & detected_stacks):
                filtered.append(e)
            if len(filtered) >= limit:
                break
        return [_entry_to_dict(e) for e in filtered]

    @server.tool()
    def priors_for_context(
        file_path: str | None = None,
        snippet: str = "",
        limit: int = 10,
        all_stacks: bool = False,
    ) -> list[dict]:
        """Return priors whose trigger_pattern matches the given code context.

        Call this before suggesting an edit so contextually-relevant rules surface
        without dumping the full digest into the conversation. Provide the target
        file_path (for language gating) and a snippet of the code under consideration
        (the change site, or the file body). Entries without a trigger_pattern are
        ignored — for general lookup, use search_priors instead.

        Filtered to the current project's detected stacks by default.
        """
        from priors import store
        entries = store.load_all()
        if not all_stacks and detected_stacks:
            entries = [
                e for e in entries
                if e.scope == "global" or not e.stacks or (set(e.stacks) & detected_stacks)
            ]
        matches = triggers_mod.find_matches(entries, file_path, snippet or "")
        matches = matches[:limit]
        effectiveness.record_fire(
            [m.entry.id for m in matches],
            tool="priors_for_context",
            query=file_path or "",
        )
        out: list[dict] = []
        for m in matches:
            d = _entry_to_dict(m.entry)
            d["matched_pattern"] = m.pattern
            d["matched_text"] = m.matched_text
            out.append(d)
        return out

    @server.tool()
    def propose_entry(
        trigger: str,
        body: str,
        rule: str,
        tags: list[str],
        model: str,
        severity: Literal["misleading", "silent-bug", "silent-prod-bug"],
    ) -> dict:
        """Propose a priors entry. For ARCHITECTURAL FOOTGUNS and SILENT CORRECTNESS
        BUGS only — patterns the user will hit again across projects and sessions.

        DO NOT CALL THIS TOOL FOR:
        - Variable renames, typos, formatting, or style corrections
        - One-off logic bugs specific to the current code
        - Misunderstanding the user's intent
        - Anything you would describe as "I made a mistake" rather than "this is a
          class of mistake"
        - Things already covered by linters, type checkers, or existing priors entries
          (use search_priors first to check)

        ONLY CALL THIS TOOL WHEN:
        - The user's correction includes language like "always...", "never...",
          "don't ever...", "we got burned by...", "remember this for next time", or
          "add this to your rules"; OR
        - The user describes a SILENT failure mode (data corruption, race condition,
          lock contention, security boundary, etc.) that the surface code does not
          reveal.

        The 'body' MUST include a verbatim quote of the user's correction, prefixed
        with '> '. Do not paraphrase — the user's exact words are the evidence that
        this entry is justified.

        If you are unsure whether to call this tool: DO NOT call it. The cost of a
        missed entry is zero. The cost of a noisy entry is the user abandoning the
        priors.

        Severity must be 'misleading' or higher. Drafts at lower severity are
        rejected server-side.
        """
        try:
            result = drafts_mod.propose(
                trigger=trigger,
                body=body,
                rule=rule,
                tags=tags,
                model=model,
                severity=severity,
                proposed_in=str(cwd),
                session_count=session_state["drafts_in_session"],
            )
        except drafts_mod.DraftError as exc:
            log.info("propose rejected: %s", exc.code)
            if exc.code == "similar_entry_exists":
                existing = exc.extra.get("similar_entry_exists")
                if existing:
                    effectiveness.record_near_miss(
                        existing,
                        draft_trigger=trigger,
                        model=model,
                    )
            return exc.to_dict()
        session_state["drafts_in_session"] += 1
        log.info("propose accepted: %s", result["draft_id"])
        return result

    return server


def run_stdio(cwd: Path | None = None) -> None:
    _setup_logging()
    server = build_server(cwd=cwd)
    log.info("starting MCP stdio server in %s", cwd or os.getcwd())
    server.run("stdio")
