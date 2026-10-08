#!/usr/bin/env python3
"""
Compare the text of two rendered documents paragraph by paragraph (unified diff).
Typical uses:
  - engine upgrade regression: same template + data rendered on v3 and v8
  - condition check: data_full vs data_empty render of the same template
  - before/after a template change

Usage: python3 diff_renders.py <a.docx> <b.docx> [--context 1] [--normalize]

--normalize (use it for v3 vs v8): compare content only - no table numbers or cell coordinates, and no
empty or picture-only paragraphs. The v8 harness builds `| grid` tables that v3 doesn't, which shifts
every later table number and would otherwise show the whole document as changed.
"""
import difflib
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from docxlib import Docx, collect, para_text  # noqa: E402


def lines(path, normalize=False):
    doc = Docx(path)
    paras, _ = collect(doc)
    out = []
    for pi in paras:
        text = para_text(pi.el)
        if normalize:
            if not text.strip():
                continue
            loc = "cell " if pi.table else ("textbox " if pi.textbox else "")
        else:
            loc = f"{pi.table}:r{pi.row}c{pi.col} " if pi.table else ("textbox " if pi.textbox else "")
        out.append(f"{pi.part.split('/')[-1]} {loc}| {text}")
    return out


def main():
    args = sys.argv[1:]
    ctx = 1
    if "--context" in args:
        i = args.index("--context"); ctx = int(args[i + 1]); del args[i:i + 2]
    norm = "--normalize" in args
    if norm:
        args.remove("--normalize")
    a, b = args
    la, lb = lines(a, norm), lines(b, norm)
    diff = list(difflib.unified_diff(la, lb, fromfile=a, tofile=b, n=ctx, lineterm=""))
    if not diff:
        print("identical text")
        return
    print("\n".join(diff))
    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    print(f"\n{dels} paragraphs only in A, {adds} only in B")


if __name__ == "__main__":
    main()
