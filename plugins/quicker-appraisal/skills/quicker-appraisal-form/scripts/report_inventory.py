#!/usr/bin/env python3
"""
List the data points of an office's own report format - the raw material for its form.

Usage:
    python3 docx_outline.py report.docx --json work/outline.json > work/outline.txt
    python3 report_inventory.py work/outline.json work/                # -> work/inventory.md + .json
    python3 report_inventory.py work/outline.json work/ --form work/form_index.json
                                        # + matches each data point against the form's fields

What it finds (heuristics - read inventory.md next to outline.txt and correct it):
    pair        "label: value" / "label <tab> value" inside a paragraph, several per line allowed
    slot        a label followed by nothing, "____", "...", "XXX" - a value the template fills in
    table-pair  a table row "label | value" (label = the short text cell)
    table-list  a table with a header row and 2+ similar rows - a repeating list (a group in the form);
                its columns are listed as the group's candidate fields
    table-matrix  a grid: items down the first column x places across the header (finish per room);
                each cell is "<row> - <column>", an empty cell is a slot
    markup      [[...]] instructions the author typed (the template skill's markup language)
    tag         {p.ad.x} tags already in the document (an existing Quicker template)
Each item carries the heading it sits under, so fields can be placed in the matching form section,
and a value kind guessed from the sample (date, money, area, percent, id, number, yes/no, text).

With --form, each item gets the closest existing form fields (label similarity 0..1):
    exists  >= 0.75   the form already has it - map it, don't add it
    maybe   0.45-0.75 look at the candidates before deciding
    new     < 0.45    no field like it - a candidate for a new field
"""
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formlib import camel_words, norm, similarity  # noqa: E402

SLOT = re.compile(r"^[\s_.…\-–xX]*$|^_{2,}|^\.{3,}|^…|^XXX")
DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
MONEY = re.compile(r"₪|ש\"ח|ש״ח|\bשקל|\d{1,3}(,\d{3})+")
AREA = re.compile(r"מ\"ר|מ״ר|\bמטר|\bדונם")
PERCENT = re.compile(r"%|אחוז")
IDNUM = re.compile(r"\b\d{9}\b")
NUMBER = re.compile(r"^\s*[\d.,/-]+\s*$")
YESNO = re.compile(r"^\s*(כן|לא|קיים|לא קיים|אין|יש)\s*$")
TAG = re.compile(r"\{[^{}]+\}")
MARKUP = re.compile(r"\[\[(.+?)\]\]")
HEADING_STYLE = re.compile(r"heading|כותרת|title", re.I)
MAX_LABEL = 40


def value_kind(sample):
    s = sample or ""
    if not s.strip() or SLOT.match(s.strip()):
        return "empty"
    if DATE.search(s):
        return "date"
    if AREA.search(s):
        return "area"
    if PERCENT.search(s):
        return "percent"
    if MONEY.search(s):
        return "money"
    if IDNUM.search(s):
        return "id"
    if YESNO.match(s):
        return "yes/no"
    if NUMBER.match(s):
        return "number"
    return "long text" if len(s) > 80 else "text"


def is_label(text):
    t = text.strip().rstrip(":").strip()
    return 1 < len(t) <= MAX_LABEL and re.search(r"[א-ת]", t) and not DATE.search(t) \
        and len(re.findall(r"\d", t)) <= 3


def heading_of(rec):
    t = rec["text"].strip()
    if not t or rec.get("table") or len(t) > 70:
        return None
    flags = rec.get("flags") or []
    if any(HEADING_STYLE.search(f or "") for f in flags):
        return t
    if "b" in flags and not t.endswith(".") and ":" not in t[:-1]:
        return t.rstrip(":")
    if "num" in flags and len(t) <= 50 and not t.endswith(".") and ":" not in t[:-1]:
        return t.rstrip(":")
    return None


def pairs_in_text(text):
    """[(label, value)] from one paragraph: 'a: 1 <tab> b: 2', 'label:<tab>value', 'label: ____'."""
    out = []
    segs = [s.strip() for s in text.split("\t")]
    i = 0
    while i < len(segs):
        seg = segs[i]
        if not seg:
            i += 1
            continue
        if seg.endswith(":") and is_label(seg):
            val = segs[i + 1] if i + 1 < len(segs) and not (segs[i + 1].endswith(":") and is_label(segs[i + 1])) else ""
            out.append((seg.rstrip(":").strip(), val))
            i += 2 if val else 1
            continue
        if ":" in seg:
            lab, _, val = seg.partition(":")
            if is_label(lab) and not lab.strip().startswith("http"):
                out.append((lab.strip(), val.strip()))
        i += 1
    return out


def build(outline):
    paras = outline["paragraphs"]
    items, headings = [], []
    heading = "(ראש המסמך)"
    tables = OrderedDict()
    for rec in paras:
        if rec.get("table"):
            tables.setdefault(rec["table"], []).append(rec)
            continue
        h = heading_of(rec)
        if h:
            heading = h
            headings.append({"id": rec["id"], "text": h})
            continue
        text = rec["text"]
        for m in MARKUP.finditer(text):
            items.append({"where": rec["id"], "section": heading, "source": "markup", "label": m.group(1).strip(), "sample": ""})
        for m in TAG.finditer(text):
            items.append({"where": rec["id"], "section": heading, "source": "tag", "label": m.group(0), "sample": ""})
        clean = MARKUP.sub("", TAG.sub("", text))
        for lab, val in pairs_in_text(clean):
            items.append({"where": rec["id"], "section": heading, "source": "slot" if value_kind(val) == "empty" else "pair",
                          "label": lab, "sample": val[:120]})
    for tid, recs in tables.items():
        items.extend(table_items(tid, recs, heading_for_table(paras, recs[0]["id"], headings)))
    for it in items:
        it["kind"] = value_kind(it.get("sample"))
    return {"file": outline.get("file"), "headings": headings, "items": items}


def heading_for_table(paras, first_id, headings):
    ids = [p["id"] for p in paras]
    pos = ids.index(first_id)
    best = "(ראש המסמך)"
    for h in headings:
        if ids.index(h["id"]) < pos:
            best = h["text"]
    return best


def table_items(tid, recs, section):
    grid = defaultdict(dict)
    for r in recs:
        cell = grid[r.get("row") or 0].get(r.get("col") or 0, "")
        grid[r.get("row") or 0][r.get("col") or 0] = " ".join((cell + " " + r["text"]).split())
    keys = sorted(grid)
    rows = [grid[k] for k in keys]
    if not rows:
        return []
    cols = sorted({c for r in rows for c in r})
    out = []
    first = rows[0]
    header = [(c, first.get(c, "")) for c in cols]
    body = rows[1:]
    header_like = len(cols) >= 2 and sum(1 for _, h in header if h and is_label(h)) >= max(2, len(cols) - 1)
    if header_like and len(body) >= 1 and all(set(r) == set(cols) for r in body):
        out.append({"where": f"{tid}", "section": section, "source": "table-list",
                    "label": " / ".join(h for _, h in header if h), "sample": f"{len(body)} שורות",
                    "columns": [{"label": h, "sample": body[0].get(c, "")[:80], "kind": value_kind(body[0].get(c, ""))}
                                for c, h in header if h]})
        return out
    first_col = cols[0] if cols else 0
    head_labels = [h for c, h in sorted(first.items()) if c != first_col and h and is_label(h)]
    body_labels = [r.get(first_col, "") for r in body if r.get(first_col, "") and is_label(r.get(first_col, ""))]
    if len(cols) >= 3 and len(head_labels) >= 2 and len(body_labels) >= 2:
        # a matrix: items down the first column x places / rooms across the header
        out = []
        last = ""
        for ri, r in zip(keys[1:], body):
            rlab = (r.get(first_col, "") or "").strip()
            rlab = rlab if rlab else (f"{last} (המשך)" if last else "")
            if r.get(first_col, "").strip():
                last = r.get(first_col, "").strip()
            filled = [c for c in cols if c != first_col and (r.get(c) or "").strip()]
            if len(filled) <= 1 and len(cols) > 3:     # a merged row: one value for the whole line
                val = r.get(filled[0], "") if filled else ""
                if rlab or val:
                    out.append({"where": f"{tid}:r{ri}", "section": section, "source": "table-pair",
                                "label": rlab or val, "sample": val[:120] if rlab else ""})
                continue
            for c in cols:
                if c == first_col or not (first.get(c) or "").strip():
                    continue
                out.append({"where": f"{tid}:r{ri}c{c}", "section": section, "source": "table-matrix",
                            "label": f"{rlab} - {first[c].strip()}" if rlab else first[c].strip(),
                            "sample": (r.get(c) or "")[:120]})
        return out
    for ri, row in zip(keys, rows):
        ckeys = sorted(row)
        cells = [row.get(c, "") for c in ckeys]
        i = 0
        while i < len(cells):
            lab = cells[i]
            inline = pairs_in_text(lab or "") if ":" in (lab or "")[:-1] else []
            if inline:                                   # "שם: יוסי" inside the cell itself
                for lab2, val in inline:
                    out.append({"where": f"{tid}:r{ri}c{ckeys[i]}", "section": section, "source": "pair", "label": lab2, "sample": val[:120]})
                i += 1
                continue
            if lab and is_label(lab) and i + 1 < len(cells) and not (cells[i + 1] and is_label(cells[i + 1]) and value_kind(cells[i + 1]) == "text" and len(cells[i + 1]) < 15):
                out.append({"where": f"{tid}:r{ri}c{ckeys[i]}", "section": section, "source": "table-pair",
                            "label": lab.rstrip(":").strip(), "sample": cells[i + 1][:120]})
                i += 2
                continue
            for lab2, val in pairs_in_text(lab or ""):
                out.append({"where": f"{tid}:r{ri}c{ckeys[i]}", "section": section, "source": "pair", "label": lab2, "sample": val[:120]})
            i += 1
    return out


def match(inv, idx):
    nodes = idx["nodes"]
    for it in inv["items"]:
        if it["source"] in ("tag",):
            path = re.sub(r"^\{[#/^!]?\s*|\s*[|}].*$", "", it["label"]).replace("p.ad.", "")
            it["verdict"] = "exists" if path in nodes else "check"
            it["candidates"] = [{"path": path, "label": nodes[path]["label"], "score": 1.0}] if path in nodes else []
            continue
        cands = []
        for p, e in nodes.items():
            s = max(similarity(it["label"], e["label"]), similarity(it["label"], camel_words(e["key"])))
            if e["parent"]:
                s = round(s * 0.92, 3)          # same words deep inside a group are weaker evidence
            if s >= 0.34:
                cands.append({"path": p, "label": e["label"], "score": s, "type": e.get("type", "group")})
        cands.sort(key=lambda c: (-c["score"], c["path"].count(".")))
        it["candidates"] = cands[:3]
        best = cands[0]["score"] if cands else 0
        it["verdict"] = "exists" if best >= 0.75 else ("maybe" if best >= 0.45 else "new")
        generic = len(norm(it["label"]).split()) <= 1
        if it["verdict"] == "exists" and generic and sum(1 for c in cands if c["score"] >= 0.75) > 1:
            it["verdict"] = "maybe"             # "תאריך", "שם": the heading decides which field
        for col in it.get("columns") or []:
            cc = sorted(({"path": p, "label": e["label"], "score": similarity(col["label"], e["label"])}
                         for p, e in nodes.items() if e["kind"] == "field"), key=lambda c: -c["score"])[:2]
            col["candidates"] = [c for c in cc if c["score"] >= 0.45]
    return inv


def render(inv, with_match):
    lines = [f"# Report inventory: {os.path.basename(inv.get('file') or '')}", "",
             f"{len(inv['items'])} data points under {len(inv['headings'])} headings. Heuristic - check against outline.txt.", ""]
    by_sec = OrderedDict()
    for it in inv["items"]:
        by_sec.setdefault(it["section"], []).append(it)
    for sec, its in by_sec.items():
        lines.append(f"## {sec}")
        for it in its:
            s = f"- [{it['where']}] {it['source']}: **{it['label']}**"
            if it.get("sample"):
                s += f" = «{it['sample']}»"
            s += f" ({it['kind']})"
            if with_match:
                s += f" -> **{it['verdict']}**"
                if it.get("candidates"):
                    s += " " + "; ".join(f"`{c['path']}` {c['label']} ({c['score']:.2f})" for c in it["candidates"])
            lines.append(s)
            for col in it.get("columns") or []:
                c = f"    - column **{col['label']}** «{col['sample']}» ({col['kind']})"
                if with_match and col.get("candidates"):
                    c += " -> " + "; ".join(f"`{x['path']}` ({x['score']:.2f})" for x in col["candidates"])
                lines.append(c)
        lines.append("")
    if with_match:
        n = defaultdict(int)
        for it in inv["items"]:
            n[it["verdict"]] += 1
        lines.insert(3, f"Against the form: {n['exists']} exist, {n['maybe']} maybe, {n['new']} new, {n['check']} tags to check.")
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    outline = json.load(open(args[0], encoding="utf-8"))
    inv = build(outline)
    with_match = "--form" in args
    if with_match:
        idx = json.load(open(args[args.index("--form") + 1], encoding="utf-8"))
        inv = match(inv, idx)
    os.makedirs(args[1], exist_ok=True)
    json.dump(inv, open(os.path.join(args[1], "inventory.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(args[1], "inventory.md"), "w", encoding="utf-8").write(render(inv, with_match))
    print(f"{len(inv['items'])} data points -> {args[1]}/inventory.md")


if __name__ == "__main__":
    main()
