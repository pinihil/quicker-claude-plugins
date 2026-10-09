#!/usr/bin/env python3
"""
Check a form against what the appraisal type requires (law, standards, bank/authority practice),
and - when given the office's report inventory - against what the office's own report shows.

Usage:
    python3 gap_check.py --list                                   # appraisal types in the checklist
    python3 gap_check.py work/form_index.json --type mortgage [--type collateral19 ...]
                         [--inventory work/inventory.json] [--md work/gaps.md] [--no-base]

The checklist is assets/checklists.json ("base" = every report, added unless --no-base). For each item:
    ✓  the form has a field that looks like it (paths shown - confirm they mean the same thing)
    ✗  nothing like it in the form
    ~  partly: only hidden fields, only something close (a plan instead of a sketch), a free-text box
       where the item needs a table or an amount, a multi-part item with parts missing ("missing:
       purpose, rent"), or only a field with default text (the wording decides - read it)
and, with --inventory, whether the office's report shows it ("בדוח": the outline id of the evidence).

How to read the result: an item the office's report shows but the form lacks is a strong candidate
for a new field. An item the standard requires that neither the report nor the form has is a finding
to raise with the user (not to add silently): offices often hold it as fixed text in the template, in
an attached file, or outside Quicker. Matching is by words, so both ✓ and ✗ can be wrong - check.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formlib import camel_words, norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKLISTS = os.path.join(HERE, "..", "assets", "checklists.json")
LEVEL_HE = {"required": "חובה", "conditional": "כשרלוונטי", "recommended": "מומלץ"}


def load_checklists():
    with open(CHECKLISTS, encoding="utf-8") as f:
        return json.load(f)


def contains(hay, pat):
    """Long patterns anywhere; "abc*" = a word starting with abc; a short pattern (<= 4 letters) only
    as a whole word - each may follow one Hebrew prefix letter (ה ו ב ל מ ש כ)."""
    if pat.endswith("*"):
        return re.search(rf"(?:^|\s)[והבלמשכ]?{re.escape(pat[:-1])}", hay) is not None
    if len(pat) > 4 or " " in pat:
        return pat in hay
    return re.search(rf"(?:^|\s)[והבלמשכ]?{re.escape(pat)}(?:\s|$)", hay) is not None


def _matches(patterns, idx, want_type):
    pats = [norm(p) + ("*" if p.endswith("*") else "") for p in patterns if norm(p)]
    found = []
    for path, e in idx["nodes"].items():
        hay = norm(e.get("label") or "")
        key = e.get("key") or ""
        cw = camel_words(key)
        ok = any(p and contains(hay, p) for p in pats) or any(r == key or (r.isascii() and r.lower() in (key.lower(), cw)) for r in patterns)
        if not ok:
            cols = e.get("linkedTo") or []
            sp = (e.get("systemPath") or "").replace("p.", "")
            ok = any(r in cols or r == sp for r in patterns)
        if ok:
            if want_type == "image" and e.get("type") != "image":
                continue
            found.append({"path": path, "label": e.get("label"), "hidden": bool(e.get("hidden")),
                          "kind": e.get("kind"), "type": e.get("type")})
    return found


def _missing_parts(item, visible, idx):
    """Parts of a multi-part item ("term, purpose, rent") that none of the found nodes - or their children -
    show."""
    parts = item.get("parts") or {}
    if not parts:
        return []
    roots = [h["path"] for h in visible]
    hay = []
    for path, e in idx["nodes"].items():
        if any(path == r or path.startswith(r + ".") for r in roots):
            hay.append(norm(e.get("label") or "") + " " + camel_words(e.get("key") or ""))
    text = " | ".join(hay)
    return [name for name, pats in parts.items()
            if not any(contains(text, norm(pt) + ("*" if pt.endswith("*") else "")) for pt in pats)]


def hits_in_form(item, idx):
    """(status, found, why): ✓ found; ~ only hidden / only a near match / a free-text box where a table or
    an amount is expected / some parts of a multi-part item missing / only a field with default text;
    ✗ nothing."""
    want = (item.get("suggest") or {}).get("type")
    full = _matches(item.get("match") or [], idx, want)
    visible = [h for h in full if not h["hidden"]]
    if visible:
        if want == "group" and all(h["kind"] != "group" and "." not in h["path"] for h in visible):
            return "~", visible, "only a free-text field, not a table"
        if want in ("currency", "number", "date") and all(h.get("type") in ("textarea", "richtext") for h in visible):
            return "~", visible, "only inside a free-text field"
        missing = _missing_parts(item, visible, idx)
        if missing:
            return "~", visible, "missing: " + ", ".join(missing)
        if all((idx["nodes"].get(h["path"]) or {}).get("hasDefault") for h in visible):
            return "~", visible, "only in a field with default text - check the wording"
        return "✓", visible, ""
    if full:
        return "~", full, "only hidden fields"
    near = [h for h in _matches(item.get("partial") or [], idx, None) if not h["hidden"]]
    if near:
        return "~", near, "something close, not the same"
    return "✗", [], ""


def hits_in_report(item, inv):
    pats = [norm(p) + ("*" if p.endswith("*") else "") for p in item.get("match") or [] if norm(p) and not p.isascii()]
    out = []
    for it in inv.get("items", []):
        text = norm(" ".join([it.get("label") or "", it.get("sample") or ""] + [c.get("label", "") for c in it.get("columns") or []]))
        if any(contains(text, p) for p in pats):
            out.append(it.get("where"))
    for h in inv.get("headings", []):
        if any(contains(norm(h.get("text")), p) for p in pats):
            out.append(h.get("id"))
    return out


def run(idx, types, inv=None):
    cl = load_checklists()["types"]
    results = []
    for t in types:
        if t not in cl:
            sys.exit(f"unknown type {t}. Known: {', '.join(cl)}")
        spec = cl[t]
        rows = []
        for item in spec["items"]:
            status, fh, why = hits_in_form(item, idx)
            row = {"type": t, "id": item["id"], "label": item["label"], "level": item["level"], "basis": item.get("basis", []),
                   "status": status, "form": fh[:3], "why": why, "suggest": item.get("suggest"), "note": item.get("note")}
            if inv is not None:
                row["report"] = hits_in_report(item, inv)[:3]
            rows.append(row)
        results.append({"type": t, "title": spec["title"], "when": spec.get("when"), "valuationDate": spec.get("valuationDate"),
                        "notes": spec.get("notes", []), "rows": rows})
    return results


def render(results, form_title, with_report):
    out = [f"# בדיקת שלמות: {form_title}", ""]
    for r in results:
        out += [f"## {r['title']}", ""]
        if r.get("valuationDate"):
            out.append(f"- מועד קובע: {r['valuationDate']}")
        for n in r["notes"]:
            out.append(f"- {n}")
        out.append("")
        head = "| | פריט | רמה | מקור | בטופס |" + (" בדוח |" if with_report else "") + " הצעה אם חסר |"
        out += [head, "|" + "---|" * (head.count("|") - 1)]
        order = {"✗": 0, "~": 1, "✓": 2}
        for row in sorted(r["rows"], key=lambda x: (order[x["status"]], ["required", "conditional", "recommended"].index(x["level"]))):
            form = ", ".join(f"`{h['path']}`" + (" (מוסתר)" if h["hidden"] else "") for h in row["form"]) or "-"
            if row.get("why"):
                form += f" ({row['why']})"
            sug = row["suggest"] or {}
            s = f"`{sug.get('name')}` ({sug.get('type')})" if row["status"] != "✓" and sug else ""
            if row.get("note") and row["status"] != "✓":
                s += f" - {row['note']}"
            cells = [row["status"], row["label"], LEVEL_HE[row["level"]], ", ".join(row["basis"]), form]
            if with_report:
                cells.append(", ".join(row.get("report") or []) or "-")
            cells.append(s)
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
        miss = [x for x in r["rows"] if x["status"] == "✗"]
        part = [x for x in r["rows"] if x["status"] == "~"]
        out += ["", f"חלקי: {len(part)}. חסרים: {sum(1 for x in miss if x['level'] == 'required')} חובה, "
                     f"{sum(1 for x in miss if x['level'] == 'conditional')} כשרלוונטי, "
                     f"{sum(1 for x in miss if x['level'] == 'recommended')} מומלץ.", ""]
    return "\n".join(out) + "\n"


def main():
    args = sys.argv[1:]
    if "--list" in args:
        for k, v in load_checklists()["types"].items():
            print(f"{k:16} {v['title']}  -  {v.get('when', '')}")
        return
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    idx = json.load(open(args[0], encoding="utf-8"))
    types = [args[i + 1] for i, a in enumerate(args) if a == "--type"]
    if "--no-base" not in args:
        types = ["base"] + [t for t in types if t != "base"]
    inv = None
    if "--inventory" in args:
        inv = json.load(open(args[args.index("--inventory") + 1], encoding="utf-8"))
    results = run(idx, types, inv)
    md = render(results, idx["form"].get("title"), inv is not None)
    if "--md" in args:
        p = args[args.index("--md") + 1]
        open(p, "w", encoding="utf-8").write(md)
        print(f"-> {p}")
    if "--json" in args:
        p = args[args.index("--json") + 1]
        json.dump(results, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in results:
        miss = [x for x in r["rows"] if x["status"] == "✗"]
        part = [x for x in r["rows"] if x["status"] == "~"]
        print(f"{r['type']:16} {len(r['rows'])} items: {len(r['rows']) - len(miss) - len(part)} found, {len(part)} partly, {len(miss)} missing "
              f"({sum(1 for x in miss if x['level'] == 'required')} required)")
    if "--md" not in args:
        print(md)


if __name__ == "__main__":
    main()
