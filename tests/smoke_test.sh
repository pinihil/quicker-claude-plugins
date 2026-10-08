#!/usr/bin/env bash
# End-to-end smoke test of the skill's scripts on a fictional form and template:
# build_catalog -> apply_plan regression -> validate.py (lint, 5 datasets x v3/v8, engine diff).
# Usage: bash tests/smoke_test.sh            (from the repo root; needs python3 + python-docx + Pillow, node + npm)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S="$ROOT/plugins/quicker-appraisal/skills/quicker-appraisal-template/scripts"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

python3 "$S/build_catalog.py" "$ROOT/tests/fixtures/form.json" "$W/cat" >/dev/null
python3 "$ROOT/tests/make_fixture_docx.py" "$W/template.docx"
python3 "$ROOT/tests/test_apply.py" "$W/cat/catalog.json"
# lint + sample data + renders on v3 and v8 + v3/v8 diff, in one step (exit 0 = clean)
python3 "$S/validate.py" "$W/template.docx" "$W/cat/catalog.json" "$W/val"
