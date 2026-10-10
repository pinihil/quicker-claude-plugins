#!/usr/bin/env python3
"""
Audit the display logic of a Quicker appraisal form - what an appraiser sees for each answer.

Usage:
    python3 audit_form.py form.json work/                 # -> work/audit.md, work/audit.json
    python3 audit_form.py form.json work/ --ops-out work/fix_ops.json   # + ready update_field ops
    python3 audit_form.py form.json work/ --section environmentFields  # one section only

Findings (Hebrew report, most serious first):
  לתיקון  - a detail shown for every answer of its question ("מפת אתרי עתיקות" also when "לא נבדק"),
            a condition that compares to an option that doesn't exist, a negated condition that shows
            details before anyone answered, a chain that stays open when its first question changes,
            a condition on a hidden or missing field.
  לבדיקה  - a generic detail right after a question, a value a selectOther may still hold.
  המלצות - a check with no "לא נבדק" answer, a question AI Fill may answer from silence, long text
            that would read better as rich text, a rich-text prompt that loses paragraphs.
The "מפת התנאים" section shows, for every question that opens something, what each answer shows.

Every finding is heuristic where it reads labels (which field is a detail of which question):
confirm before you plan. The suggested ops go through check_ops.py and the plan like any other.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formlib import label_of, load_form, options_of, section_keys, section_title, walk  # noqa: E402
from formlogic import (UNKNOWN, audit, is_gate, matrix, suggested_ops)  # noqa: E402

LEVELS = [("fix", "לתיקון"), ("check", "לבדיקה"), ("advice", "המלצות")]


def _cell(v):
    return "✓" if v is True else ("-" if v is False else "תלוי בשדות אחרים")


def gate_maps(form, findings, sections=None):
    infos = list(walk(form["schema"]))
    index = {i["path"]: i for i in infos}
    out = []
    for g in infos:
        if g["kind"] != "field" or not is_gate(g["node"]):
            continue
        if sections and g["section"] not in sections:
            continue
        m = matrix(g, infos, index)
        always = [label_of(index[f["path"]]["node"]) or f["path"] for f in findings
                  if f["kind"] == "ungated" and f.get("gate") == g["path"] and f["path"] in index]
        if m or always:
            out.append((g, m, index, always))
    return out


def _names(labels, cap=10):
    return ", ".join(labels[:cap]) + (f" ועוד {len(labels) - cap}" if len(labels) > cap else "")


def render_map(g, m, index, md, always=()):
    node = g["node"]
    answers = [True, False] if node.get("type") == "checkbox" else options_of(node)
    names = {True: "מסומן", False: "לא מסומן", None: "(לא נענה)"}
    lines = [f'#### "{label_of(node) or g["key"]}" (`{g["path"]}`) - {section_title(md, g["section"])}', "",
             "| תשובה | מוצגים |", "|---|---|"]
    for a in answers + [None]:
        shown = [label_of(index[p]["node"]) or p for p, row in m.items() if row.get(a) is True]
        maybe = [label_of(index[p]["node"]) or p for p, row in m.items() if row.get(a) is UNKNOWN]
        text = _names(shown) if shown else "-"
        if maybe:
            text += f" (ואולי, לפי שדות אחרים: {_names(maybe)})"
        lines.append(f"| {names.get(a, a) if not isinstance(a, str) else a} | {text} |")
    never = [label_of(index[p]["node"]) or p for p, row in m.items() if all(v is False for v in row.values())]
    if never:
        lines += ["", f"לא מוצגים באף תשובה: {', '.join(never)}"]
    if always:
        lines += ["", f"מוצגים בכל תשובה, בלי תנאי (נראים כמו פרטים של השאלה): {', '.join(always)}"]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    form = load_form(args[0])
    out_dir = args[1] if len(args) > 1 and not args[1].startswith("--") else "."
    os.makedirs(out_dir, exist_ok=True)
    sections = None
    if "--section" in args:
        sections = {args[i + 1] for i, a in enumerate(args) if a == "--section"}
        unknown = sections - set(section_keys(form["schema"]))
        if unknown:
            sys.exit(f"unknown section(s): {', '.join(sorted(unknown))}")
    findings = audit(form)
    if sections:
        index = {i["path"]: i for i in walk(form["schema"])}
        findings = [f for f in findings if index.get(f["path"], {}).get("section") in sections]
    md = form.get("metadata") or {}

    lines = [f"# בדיקת לוגיקת התצוגה - {form.get('title') or form.get('name') or ''}", ""]
    counts = {lvl: sum(1 for f in findings if f["level"] == lvl) for lvl, _ in LEVELS}
    lines.append(" | ".join(f"{he}: {counts[lvl]}" for lvl, he in LEVELS))
    lines.append("")
    for lvl, he in LEVELS:
        items = [f for f in findings if f["level"] == lvl]
        if not items:
            continue
        lines += [f"## {he}", ""]
        for f in items:
            lines.append(f"- `{f['path']}` - {f['message']}")
            if f.get("suggest"):
                lines.append(f"  - תנאי מוצע: `{f['suggest']}`")
        lines.append("")
    maps = gate_maps(form, findings, sections)
    if maps:
        lines += ["## מפת התנאים", "", "מה כל תשובה מציגה (שדות שהתנאי שלהם קורא את השאלה).", ""]
        for g, m, index, always in maps:
            lines += [render_map(g, m, index, md, always), ""]
    md_path = os.path.join(out_dir, "audit.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    with open(os.path.join(out_dir, "audit.json"), "w", encoding="utf-8") as fh:
        json.dump(findings, fh, ensure_ascii=False, indent=1)
    print(f"-> {md_path}  ({' | '.join(f'{lvl} {counts[lvl]}' for lvl, _ in LEVELS)})")
    if "--ops-out" in args:
        p = args[args.index("--ops-out") + 1]
        ops = suggested_ops(findings)
        spec = {"templateId": form.get("id"), "note": "תיקון תנאי תצוגה", "ops": ops}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
        print(f"-> {p}  ({len(ops)} update_field ops - check them with check_ops.py)")


if __name__ == "__main__":
    main()
