#!/usr/bin/env bash
# Build an uploadable plugin zip (Customize > Plugins > Add > Upload plugin, or an organization's
# "Upload a plugin") from what git tracks - ignored files such as the internal image plugin never get in.
# Usage: bash tools/build_zip.sh [plugin-name]      -> dist/<plugin>-<version>.zip
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-quicker-appraisal}"
PDIR="plugins/$NAME"
VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/$PDIR/.claude-plugin/plugin.json'))['version'])")"
OUT="$ROOT/dist/$NAME-$VERSION.zip"
mkdir -p "$ROOT/dist"; rm -f "$OUT"
cd "$ROOT/$PDIR"
git ls-files --cached --others --exclude-standard -z . | xargs -0 zip -q -X "$OUT"
echo "$OUT"
