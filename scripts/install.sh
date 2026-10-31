#!/usr/bin/env bash
# Manual install of token-routing into one project (no plugin system).
# Usage: scripts/install.sh /path/to/your/project
# It copies skills, agents and scripts into <project>/.claude/.
# It never touches your routing table, lessons or history (they are created on first use).
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/plugins/token-routing"
DEST="${1:-}"
if [ -z "$DEST" ] || [ ! -d "$DEST" ]; then
  echo "Usage: $0 /path/to/your/project" >&2
  exit 1
fi
DEST="$(cd "$DEST" && pwd)/.claude"

mkdir -p "$DEST/skills" "$DEST/agents" "$DEST/routing"
for s in "$SRC"/skills/*/; do
  name="$(basename "$s")"
  rm -rf "$DEST/skills/$name"
  cp -R "$s" "$DEST/skills/$name"
done
cp "$SRC"/agents/*.md "$DEST/agents/"
cp "$SRC"/routing/*.py "$DEST/routing/"
rm -rf "$DEST/routing/defaults" "$DEST/routing/templates"
cp -R "$SRC/routing/defaults" "$SRC/routing/templates" "$DEST/routing/"

echo "Installed into $DEST"
echo "Next: paste $SRC/CLAUDE.routing.md into your project's CLAUDE.md, restart Claude Code, run /orchestrate <request>."
