#!/usr/bin/env python3
"""
Print a compact, ID-addressed outline of a Word report so the model can decide where
variables, conditions and loops belong - without losing track of tables, text boxes,
headers/footers, highlights, comments and author instructions.

Usage:
    python3 docx_outline.py <file.docx> [--json outline.json] [--max 400]

Line format:
    P0042 T3:r2c1 [Heading 1|num|center|b] text ...
Markers inside text:
    ⇥ tab   ⏎ line break   [🖼 picture WxHpx alt="..."] picture (alt text = placeholder tag, engine 7+)
    [▭ text box] text box (its paragraphs are listed separately as "textbox")   [🖼] other drawing
    ⟦hl:yellow│...⟧  highlighted (often = "a value that changes per report")
    ⟦c5│...⟧        text covered by Word comment #5 (comment text listed at line end)
    [[ ... ]]        author instruction written directly in the document
    { ... }          an existing easy-template-x tag
    ∅                empty paragraph / empty table cell
"""
import json
import re
import sys
from collections import Counter

sys.path.insert(0, __import__("os").path.dirname(__file__))
from docxlib import Docx, collect, paragraph_atoms, NS, q, table_grid, cell_paragraphs, paragraph_drawings  # noqa: E402

DOC_TYPE_HINTS = [
    ("בנק / משכנתא", r"בנק|הלוואה|לווה|משכנתא|בטוחה לאשראי"),
    ("היטל השבחה", r"היטל השבחה|השבחה"),
    ("מס שבח / מקרקעין", r"מס שבח|מיסוי מקרקעין|מס רכישה"),
    ("ירושה / עיזבון", r"עיזבון|ירושה|יורשים"),
    ("גירושין / פירוק שיתוף", r"גירושין|פירוק שיתוף|איזון משאבים"),
    ("מס רכוש / נזק", r"מס רכוש|נזק|פיצוי"),
    ("ביטוח / שומת רכוש", r"חברת הביטוח|פוליסה|שומת רכוש|המבוטח"),   # not "ערך כינון" - bank reports carry it too
    ("שומה מכרעת / ועדת ערר", r"שומה מכרעת|שמאי מכריע|ועדת ערר"),
    ("פיצויי הפקעה / ירידת ערך (סעיף 197)", r"הפקעה|ירידת ערך|סעיף 197"),
    ("תמ\"א 38 / התחדשות עירונית", r"תמ\"א 38|התחדשות עירונית|פינוי בינוי"),
]


def fmt_text(atoms, comments_seen, drawings=None):
    out, cur_hl, cur_c = [], None, ()
    dq = list(drawings or [])
    for a in atoms:
        hl = a.hl
        cs = a.comments
        if hl != cur_hl:
            if cur_hl:
                out.append("⟧")
            if hl:
                out.append(f"⟦hl:{hl}│")
            cur_hl = hl
        if cs != cur_c:
            if cur_c:
                out.append("⟧")
            if cs:
                out.append(f"⟦c{','.join(cs)}│")
                comments_seen.update(cs)
            cur_c = cs
        t = a.text
        if a.kind == "tab":
            t = " ⇥ "
        elif a.kind == "br":
            t = " ⏎ "
        elif a.kind == "obj":
            t = "[🖼]"
            if dq:
                d = dq.pop(0)
                if d["kind"] == "picture":
                    alt = f' alt="{d["alt"][:60]}"' if d["alt"] else ""
                    t = f"[🖼 picture {d['width']}x{d['height']}px{alt}]"
                elif d["kind"] == "textbox":
                    t = "[▭ text box]"
        out.append(t)
    if cur_c:
        out.append("⟧")
    if cur_hl:
        out.append("⟧")
    return "".join(out)


def para_flags(p, style_names):
    flags = []
    ppr = p.find("w:pPr", NS)
    if ppr is not None:
        ps = ppr.find("w:pStyle", NS)
        if ps is not None:
            flags.append(style_names.get(ps.get(q("w:val")), ps.get(q("w:val"))))
        if ppr.find("w:numPr", NS) is not None:
            flags.append("num")
        jc = ppr.find("w:jc", NS)
        if jc is not None and jc.get(q("w:val")) in ("center", "both", "left", "right", "start", "end"):
            if jc.get(q("w:val")) == "center":
                flags.append("center")
    bold = [r for r in p.iter(q("w:r")) if r.find("w:rPr/w:b", NS) is not None and
            r.find("w:rPr/w:b", NS).get(q("w:val")) not in ("0", "false")]
    if bold and len(bold) == len(list(p.iter(q("w:r")))):
        flags.append("b")
    return flags


def main():
    args = sys.argv[1:]
    js = None
    if "--json" in args:
        i = args.index("--json"); js = args[i + 1]; del args[i:i + 2]
    limit = None
    if "--max" in args:
        i = args.index("--max"); limit = int(args[i + 1]); del args[i:i + 2]
    path = args[0]
    doc = Docx(path)
    paras, tables = collect(doc)
    styles = doc.style_names()
    comments = doc.comments()

    lines, records = [], []
    stats = Counter()
    full_text = []
    last_part, last_table, empty_run = None, None, []

    def flush_empty():
        if not empty_run:
            return
        if len(empty_run) >= 3:
            lines.append(f"{empty_run[0]}..{empty_run[-1]}  ∅×{len(empty_run)}")
        else:
            for e in empty_run:
                lines.append(f"{e}  ∅")
        empty_run.clear()

    for pi in paras:
        if pi.part != last_part:
            flush_empty()
            lines.append(f"\n=============== {pi.part} ===============")
            last_part = pi.part
        if pi.table != last_table:
            flush_empty()
            if pi.table:
                grid = table_grid(tables[pi.table]["el"])
                ncols = max(len(r) for r in grid) if grid else 0
                lines.append(f"── table {pi.table} ({len(grid)} rows × {ncols} cols) ──")
            elif last_table:
                lines.append("── end table ──")
            last_table = pi.table
        atoms = paragraph_atoms(pi.el)
        seen = set()
        text = fmt_text(atoms, seen, paragraph_drawings(pi.el))
        raw = "".join(a.text for a in atoms)
        full_text.append(raw)
        loc = ""
        if pi.table:
            loc = f"{pi.table}:r{pi.row}c{pi.col}"
        if pi.textbox:
            loc = (loc + " " if loc else "") + "textbox"
        flags = para_flags(pi.el, styles)
        stats["tags"] += len(re.findall(r"\{[^{}]+\}", raw))
        stats["markup"] += len(re.findall(r"\[\[.+?\]\]", raw))
        stats["highlight"] += 1 if "⟦hl:" in text else 0
        stats["comments"] += len(seen)
        stats["textbox"] += 1 if pi.textbox else 0
        rec = {"id": pi.id, "part": pi.part, "table": pi.table, "row": pi.row, "col": pi.col,
               "textbox": pi.textbox, "flags": flags, "text": raw}
        records.append(rec)
        if not raw.strip() and not pi.table and not pi.textbox:
            empty_run.append(pi.id)
            continue
        flush_empty()
        ctext = " ".join(f"💬#{c} «{comments.get(c, {}).get('text', '')}»" for c in sorted(seen))
        fl = f"[{'|'.join(flags)}] " if flags else ""
        body = text if raw.strip() else "∅"
        lines.append(f"{pi.id} {loc + ' ' if loc else ''}{fl}{body}{('   ' + ctext) if ctext else ''}")
    flush_empty()

    alltext = "\n".join(full_text)
    counts = [(name, len(re.findall(rx, alltext))) for name, rx in DOC_TYPE_HINTS]
    hints = [f"{name} ({n})" for name, n in sorted(counts, key=lambda x: -x[1]) if n]
    header = [
        f"# outline: {path}",
        f"paragraphs: {len(paras)} | tables: {len(tables)} | text-box paragraphs: {stats['textbox']} | "
        f"existing tags: {stats['tags']} | [[markup]]: {stats['markup']} | highlighted paras: {stats['highlight']} | "
        f"commented spans: {stats['comments']}",
        f"report-type hints (matches, strongest first): {', '.join(hints) if hints else '-'}",
    ]
    out = header + lines
    if limit:
        out = out[:limit] + [f"... (truncated at {limit} lines; rerun without --max)"]
    print("\n".join(out))
    if js:
        json.dump({"file": path, "paragraphs": records,
                   "tables": {k: {"part": v["part"]} for k, v in tables.items()},
                   "comments": comments}, open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
