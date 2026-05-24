# priors

`priors` is local memory for AI-coding: a small CLI and MCP server for capturing
the lessons you do not want an AI assistant to make you relearn.

It is meant for durable rules, architectural footguns, and silent correctness
bugs. It is not a scratchpad for every typo or preference. The payoff is that
your best lessons can be searched, synced into agent context, and reused across
future coding sessions.

## What it does

- Stores priors entries as local Markdown files under `~/.priors/entries/`.
- Searches entries with embeddings, BM25, or hybrid retrieval.
- Writes compact digests into agent instruction files such as `AGENTS.md` and
  `CLAUDE.md`.
- Exposes an MCP server so Codex, Claude Code, and other clients can search the
  priors or propose guarded draft entries.
- Keeps AI-proposed entries in review until you approve them.
- Runs a `doctor` command to catch stale adapters, missing indexes, broken
  entries, and MCP registration problems.

Everything is local by default. Override the priors directory with
`PRIORS_HOME`.

## Install

```bash
uv tool install -e .
```

`pipx install -e .` also works, but this project uses `uv` during development.

## Quick Start

```bash
priors init
priors add -m "Stripe webhook signature verification needs raw body" \
  --rule "Read req.rawBody before any JSON parser runs; express.json() consumes the stream and Stripe.webhooks.constructEvent will throw 'No signatures found matching the expected signature'." \
  --trigger "stripe webhook returning 400 after adding body-parser middleware" \
  --tag stripe \
  --tag webhooks \
  --severity silent-prod-bug \
  --stacks node,express
priors search "stripe"
priors sync
```

Useful commands:

```bash
priors list --tag testing --since 30d
priors show 2026-05-24-mock-db
priors edit 2026-05-24-mock-db
priors context "database migrations"
priors drafts
priors review
priors doctor
priors reindex
```

## High Quality Entries

A good entry is a rule you would want an AI agent to obey six months from now in
a different repo.

Good entries usually have:

- A concrete trigger: what happened, in a phrase.
- A durable rule: short, imperative, and reusable.
- A hidden failure mode: why the mistake matters.
- A spotting guide: how to recognize it next time.
- Honest severity: reserve the priors for mistakes with real consequences.

Example — a real one, not a generic best-practice:

```markdown
---
source: human
trigger: "kafka consumer in staging stealing offsets from prod"
rule: "Every Kafka consumer group ID must include ${ENV} — never hard-code 'orders-consumer'. Staging and prod sharing a group caused 40min of dropped order events on 2025-09-14."
tags: ["kafka", "config", "incident"]
severity: silent-prod-bug
scope: project
stacks: ["java", "spring"]
trigger_pattern:
  type: regex
  pattern: 'group(\.|-)id["\s:=]+["''][^"''$]+["'']'
  languages: [java, yaml]
---

## What happened

A new staging deploy used the same `group.id` ("orders-consumer") as prod
because the value was hard-coded in `application.yml` instead of templated
from `${ENV}`. Staging consumers joined the prod consumer group and committed
offsets for messages they never processed downstream. Prod stopped seeing
those events.

## Why it's wrong

Kafka uses `group.id` as the sole identity for offset commits. Two environments
with the same group ID are, from the broker's perspective, the same consumer —
whichever one commits an offset first "wins," and the other never sees those
records. There is no warning, no error log, no metric that fires; the only
signal is missing downstream work.

## How to spot it

Grep for `group.id` and `group-id` in `application.yml`, `application.properties`,
and any KafkaConsumer construction. The value must reference `${ENV}`,
`${spring.profiles.active}`, or a similar env-scoped variable. A bare string
literal is the bug.
```

The trigger lines, severity, and provenance (incident date) are what make this
worth keeping. A generic "use environment variables in config" rule is not.

Skip entries that are only typos, formatting preferences, one-off local details,
or things a linter/type checker already catches reliably.

## Severity

- `nit`: low-value notes. Usually not worth keeping.
- `misleading`: advice or implementation direction that sends future work the
  wrong way.
- `silent-bug`: code can look correct while producing wrong behavior.
- `silent-prod-bug`: likely production incident, data loss, security issue, race,
  migration failure, or similarly expensive failure.

AI-proposed drafts are intentionally limited to `misleading`, `silent-bug`, and
`silent-prod-bug`.

## Scope and Stacks

Use `scope: global` for rules that should apply everywhere. Use
`scope: project` for rules tied to a specific codebase or stack.

Use `stacks` to keep project digests relevant:

```bash
priors add -m "events table: never add NOT NULL without backfill plan" \
  --rule "Adding a NOT NULL column to events (~200M rows) requires a three-step migration: add nullable, backfill in batches of 50k via the ingest worker, then ALTER to NOT NULL. The 2025-11 single-statement migration locked the table for 38 minutes." \
  --trigger "events table ALTER timing out" \
  --tag postgres \
  --tag migrations \
  --severity silent-prod-bug \
  --scope project \
  --stacks python,postgres
```

When `priors sync` writes project instructions, stack-matched entries are
included and unrelated entries are left out.

## MCP Integration

`priors init` can wire the MCP server into supported local clients.

The server exposes:

- `search_priors`: retrieve relevant rules before work in risky areas.
- `recent_entries`: load recent guidance for the current stack.
- `priors_for_context`: surface only the entries whose `trigger_pattern` matches
  the current file or snippet — avoids dumping the whole digest when a targeted
  hit will do.
- `propose_entry`: draft a new entry only when the user states a durable rule or
  describes a silent correctness bug.

AI drafts are written under the priors draft directory and must be reviewed:

```bash
priors drafts
priors review
```

## Development

```bash
uv run pytest
```

If your environment cannot write to the default uv cache, use a local cache:

```bash
UV_CACHE_DIR=/private/tmp/priors-uv-cache uv run pytest
```
