#!/usr/bin/env bash
# Install the priors CLI globally and register it as an MCP server in ~/.claude.json.
# Safe to run while Claude Code is open — after it finishes, run `/mcp reload`
# inside your Claude session (or restart Claude) to pick up the new server.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_JSON="$HOME/.claude.json"

echo "→ installing priors CLI globally from $REPO_DIR"
if command -v uv >/dev/null 2>&1; then
  uv tool install --force --editable "$REPO_DIR"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force --editable "$REPO_DIR"
else
  echo "✗ neither uv nor pipx found. Install uv and re-run this script." >&2
  exit 1
fi

PRIORS_BIN="$(command -v priors || true)"
if [[ -z "$PRIORS_BIN" ]]; then
  echo "✗ 'priors' is not on PATH after install. Add the install bindir to PATH and re-run." >&2
  exit 1
fi
echo "✓ priors installed at $PRIORS_BIN"

echo "→ ensuring ~/.priors exists"
"$PRIORS_BIN" init --no-wire-claude >/dev/null

echo "→ merging MCP server entry into $CLAUDE_JSON"
python3 - "$CLAUDE_JSON" "$PRIORS_BIN" <<'PY'
import json, sys, pathlib, shutil
from datetime import datetime

claude_json = pathlib.Path(sys.argv[1])
priors_bin = sys.argv[2]

if claude_json.exists():
    backup = claude_json.with_suffix(claude_json.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(claude_json, backup)
    print(f"  backed up existing config to {backup}")
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ✗ existing {claude_json} is not valid JSON: {exc}")
        sys.exit(1)
else:
    data = {}

servers = data.setdefault("mcpServers", {})
existing = servers.get("priors")
desired = {"command": priors_bin, "args": ["mcp"]}

if existing == desired:
    print("  already registered — nothing to change.")
    sys.exit(0)

if existing is not None:
    print(f"  updating existing 'priors' entry (was: {existing})")
else:
    print("  adding new 'priors' entry")

servers["priors"] = desired
claude_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"  wrote {claude_json}")
PY

cat <<MSG

✓ Done.

Claude is still using its cached MCP config. To pick up the priors server in
your open session:
  1. In your Claude Code prompt, run:  /mcp
  2. If it doesn't list 'priors', either:
       - run /mcp reload, OR
       - restart Claude Code

Then ask Claude something like "what are my prior rules about migrations?"
to confirm it calls search_priors.

Tail the server log if anything looks off:
  tail -f ~/.priors/mcp.log
MSG
