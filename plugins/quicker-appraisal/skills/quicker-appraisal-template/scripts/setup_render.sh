#!/usr/bin/env bash
# One-time setup of the render harness outside the skill folder.
# Usage: bash setup_render.sh [v3|v8] [target_dir]
#   v3 (default): Quicker production (master) - easy-template-x 3.2.1.
#   v8: Quicker branch feat/easy-template-x-v8 - easy-template-x 8; validates image placeholders and
#       [% %] tag options (plus Quicker's image plugin, when a local copy is present - see below).
# Prints the harness directory. Needs node + npm and network access to the npm registry; exits 1
# (with a message on stderr) when they are missing - the skill then falls back to lint-only checks.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 || { echo "node/npm not available" >&2; exit 1; }
ENGINE="${1:-v3}"
DEST="${2:-$HOME/.qtpl-render-$ENGINE}"
mkdir -p "$DEST"
if [ "$ENGINE" = "v3" ]; then cp "$HERE/package.v3.json" "$DEST/package.json"; else cp "$HERE/package.json" "$DEST/package.json"; fi
cp "$HERE/render_check.mjs" "$DEST/"
# Quicker image plugin: optional, not shipped in the public plugin (engine 7+ only). Drop a copy of
# Quicker's server image plugin here as quicker/word-image-plugin.cjs to test grids/frames (gitignored).
if [ -f "$HERE/quicker/word-image-plugin.cjs" ]; then cp "$HERE/quicker/word-image-plugin.cjs" "$DEST/"; else rm -f "$DEST/word-image-plugin.cjs"; fi
if [ ! -d "$DEST/node_modules/easy-template-x" ] || ! grep -q "\"version\": \"$( [ "$ENGINE" = "v3" ] && echo 3 || echo 8 )" "$DEST/node_modules/easy-template-x/package.json"; then
  (cd "$DEST" && npm install --silent --no-audit --no-fund >/dev/null 2>&1) || { echo "npm install failed in $DEST" >&2; exit 1; }
fi
echo "$DEST"
