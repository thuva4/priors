from __future__ import annotations

from datetime import date as date_cls

from priors.schema import Entry

DIGEST_HEADER = "## Personal AI priors (auto-generated, do not edit)"


def build_digest(
    entries: list[Entry],
    *,
    max_rules: int = 100,
    max_bytes: int = 8192,
    today: date_cls | None = None,
) -> str:
    today = today or date_cls.today()
    curated = [e for e in entries if e.source in ("human", "ai-approved")]
    pinned = [e for e in curated if e.pin]
    rest = [e for e in curated if not e.pin]
    pinned.sort(key=lambda e: (e.date, e.id), reverse=True)
    rest.sort(key=lambda e: (e.date, e.id), reverse=True)

    ordered: list[Entry] = []
    seen: set[str] = set()
    for e in pinned + rest:
        if e.id in seen:
            continue
        seen.add(e.id)
        ordered.append(e)
        if len(ordered) >= max_rules:
            break

    lines = [DIGEST_HEADER, f"Last synced: {today.isoformat()}", ""]
    for e in ordered:
        lines.append(_format_bullet(e))
    out = "\n".join(lines).rstrip() + "\n"
    if len(out.encode("utf-8")) <= max_bytes:
        return out

    # Trim until under the byte cap.
    while ordered and len(out.encode("utf-8")) > max_bytes:
        ordered.pop()
        lines = [DIGEST_HEADER, f"Last synced: {today.isoformat()}", ""]
        for e in ordered:
            lines.append(_format_bullet(e))
        out = "\n".join(lines).rstrip() + "\n"
    return out


def _format_bullet(e: Entry) -> str:
    stack_label = ""
    if e.stacks:
        stack_label = f" ({', '.join(e.stacks)})"
    rule = e.rule.strip()
    if len(rule) > 200:
        rule = rule[:199].rstrip() + "…"
    trigger = e.trigger.strip()
    if len(trigger) > 120:
        trigger = trigger[:119].rstrip() + "…"
    return f"- **{trigger}**{stack_label}: {rule} [{e.date.isoformat()}]"
