#!/usr/bin/env python3
"""
Apply a mapping plan (JSON) to a Word report and write the tagged template.
Formatting is preserved: every inserted tag lives in its own run that clones the formatting
of the text it replaced (or of the text right before the insertion point).

Usage:
    python3 apply_plan.py <input.docx> <plan.json> <output.docx> [--report mapping_report.md] [--catalog catalog.json]

IDs (P0042, T3, H1-002 ...) always refer to docx_outline.py output for <input.docx>. Text ops on the same
paragraph run in plan order, and each `find` matches the paragraph's CURRENT text (after earlier ops).

--catalog (recommended): lets block placement tell loops from conditions. A loop must get its own
tag line when no paragraph sits before it (prepending would glue the items together); a condition can
open at the start of its first paragraph instead (one empty line less). Without the catalog every pure
path ({#p.ad.x}) is treated as a possible loop. Per op override: "loop": true / false.

Plan format:
{
  "form": {"id": "...", "title": "..."},          # which Quicker form the variables came from
  "summary": "...", "decisions": ["..."],          # Hebrew - go into the mapping report as written
  "unmatched": [{"where": "P0040", "text": "קרמיקה", "note": "אין שדה לסוג ריצוף במטבח"}],
  "v8_only": ["..."],                              # features that work only after the v8 deployment
  "block_style": "anchor",                         # default; "own" = block tags on their own lines
  "ops": [
    {"op": "replace", "p": "P0012", "find": "6938", "with": "{p.gush}", "nth": 1, "note": "גוש"},
    {"op": "replace", "p": "P0012", "find": "[[גוש]]", "with": "{p.gush}", "all": true},
    {"op": "insert",  "p": "P0020", "after": "גוש:", "text": " {p.gush}"},       # or "before": "...", or "at": "start"|"end"
    {"op": "set_text","p": "P0101", "text": "{p.ad.kitchen}"},                    # empty cell / whole paragraph
    {"op": "delete",  "p": "P0030", "find": "XXX"},
    {"op": "wrap_inline", "p": "P0040", "from_find": "מס' כניסה", "to_find": "3", "open": "{#p.ad.entryNumber}", "close": "{/p.ad.entryNumber}"},
    {"op": "wrap_block",  "from": "P0050", "to": "P0058", "open": "{#p.ad.extanded == 'שומה מורחבת'}", "close": "{/p.ad.extanded == 'שומה מורחבת'}"},
    {"op": "wrap_block",  "from": "P0070", "to": "P0070", "open": "{#p.ad.lobby}", "close": "{/p.ad.lobby}", "loop": false},
    {"op": "wrap_rows",   "table": "T3", "from_row": 2, "to_row": 2, "open": "{#p.ad.permits}", "close": "{/p.ad.permits}"},
    {"op": "insert_paragraph", "after": "P0060", "id": "N1", "text": "לא נמצאו חריגות בנייה"},   # "id" lets later ops (wrap_block, replace...) target the new paragraph
    {"op": "delete_paragraph", "p": "P0061"},
    {"op": "delete_rows", "table": "T2", "rows": [3, 4]},                         # sample rows 2..N of a list - keep one row and loop it
    {"op": "set_alt", "p": "P0112", "nth": 1, "alt": "{p.ad.planImage | maxSize:240:160}"},      # picture placeholder (v8 branch)
    {"op": "delete_drawings", "p": "P0111"},                                       # remove sample photo frames
    # replace / insert / set_text accept "format": {"bold": false} to override bold/italic/underline of the new tag run
    {"op": "strip_markup", "markup": true, "highlight_on_tags": true, "comments": true}
  ]
}
Every op may carry "note" (Hebrew explanation for the mapping report).
"""
import copy
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from docxlib import (Docx, collect, paragraph_atoms, para_text, replace_span, find_span,  # noqa: E402
                     new_run_like, run_from_paragraph_mark, NS, q, P, R, T, TBL, PPR, RPR,
                     table_grid, cell_paragraphs, strip_highlight, nearest, set_preserve,
                     has_direct_numbering, apply_format, paragraph_drawings, placeholder_png)

SKIPPABLE = {q("w:bookmarkStart"), q("w:bookmarkEnd"), q("w:proofErr"), q("w:commentRangeStart"),
             q("w:commentRangeEnd"), q("w:permStart"), q("w:permEnd")}


class PlanError(Exception):
    pass


def last_run(p):
    runs = [r for r in p.iter(R) if nearest(r, P) is p]
    return runs[-1] if runs else None


def first_run(p):
    runs = [r for r in p.iter(R) if nearest(r, P) is p]
    return runs[0] if runs else None


def _texty(p, last=True):
    """The last (or first) run of p that holds visible text - empty runs often carry stray highlight."""
    runs = [r for r in p.iter(R) if nearest(r, P) is p]
    for r in (reversed(runs) if last else runs):
        if "".join(t.text or "" for t in r.findall("w:t", NS)).strip():
            return r
    return None


def append_text_run(p, text):
    """Append text as its own run at the end of paragraph p (formatting of the last run with text)."""
    lr = last_run(p)
    model = _texty(p)
    model = model if model is not None else lr
    r = new_run_like(model, text) if model is not None else run_from_paragraph_mark(p, text)
    strip_highlight(r)
    if lr is not None and lr.getparent() is p:
        lr.addnext(r)
    else:
        p.append(r)
    return r


def prepend_text_run(p, text):
    fr = first_run(p)
    model = _texty(p, last=False)
    model = model if model is not None else fr
    r = new_run_like(model, text) if model is not None else run_from_paragraph_mark(p, text)
    strip_highlight(r)
    ppr = p.find("w:pPr", NS)
    if fr is not None and fr.getparent() is p:
        fr.addprevious(r)
    elif ppr is not None:
        ppr.addnext(r)
    else:
        p.insert(0, r)
    return r


def new_paragraph_like(ref_p, text):
    np_ = etree_el(P)
    ppr = ref_p.find("w:pPr", NS) if ref_p is not None and ref_p.tag == P else None
    if ppr is not None:
        ppr2 = copy.deepcopy(ppr)
        for tag in ("w:numPr", "w:sectPr", "w:pageBreakBefore"):
            for e in ppr2.findall(tag, NS):
                ppr2.remove(e)
        np_.append(ppr2)
    src = first_run(ref_p) if ref_p is not None and ref_p.tag == P else None
    np_.append(new_run_like(src, text) if src is not None else run_from_paragraph_mark(np_, text))
    return np_


def tag_paragraph(near, text):
    """A plain paragraph holding only block tags (removed entirely at render time). Keeps the RTL flag
    of a nearby paragraph so the template stays readable in Word; never numbered, never styled."""
    from lxml import etree
    np_ = etree.Element(P)
    src = near if near is not None and near.tag == P else None
    if src is None and near is not None:
        ps = [x for x in near.iter(P)]
        src = ps[0] if ps else None
    if src is not None and src.find("w:pPr/w:bidi", NS) is not None:
        ppr = etree.SubElement(np_, PPR)
        etree.SubElement(ppr, q("w:bidi"))
    np_.append(run_from_paragraph_mark(np_, text))
    return np_


def etree_el(tag):
    from lxml import etree
    return etree.Element(tag)


def prev_meaningful(el):
    s = el.getprevious()
    while s is not None and s.tag in SKIPPABLE:
        s = s.getprevious()
    return s


class Applier:
    def __init__(self, doc, catalog=None):
        self.doc = doc
        self.loop_paths, self.loop_names = None, None
        if catalog:
            self.loop_paths = {g["path"] for g in catalog.get("groups", [])} | {"customers"}
            self.loop_names = {g["name"] for g in catalog.get("groups", [])}
            for f in catalog.get("fields", []):           # image fields can be looped ({#p.ad.photos}{image}...)
                if f.get("kind") in ("image", "images"):
                    self.loop_paths.add(f["path"])
                    self.loop_names.add(f["name"])
        self.rowless = []
        self.paras, self.tables = collect(doc)
        self.by_id = {pi.id: pi for pi in self.paras}
        self.log, self.errors, self.dirty = [], [], set()
        self._neutral_rids = {}

    # ---------- helpers ----------
    def para(self, pid):
        if pid not in self.by_id:
            raise PlanError(f"unknown paragraph id {pid}")
        return self.by_id[pid]

    def block(self, bid):
        if bid in self.by_id:
            return self.by_id[bid].el, self.by_id[bid]
        if bid in self.tables:
            return self.tables[bid]["el"], None
        raise PlanError(f"unknown block id {bid}")

    def on_both(self, pi, fn):
        """Run a text op on the paragraph and on its legacy text-box twin (if any)."""
        before = para_text(pi.el)
        twin_ok = pi.twin is not None and para_text(pi.twin) == before
        res = fn(pi.el)
        if twin_ok:
            try:
                fn(pi.twin)
            except Exception:
                pass
        self.dirty.add(pi.part)
        return before, para_text(pi.el), res

    # ---------- text ops ----------
    def op_replace(self, op):
        pi = self.para(op["p"])
        find, new = op["find"], op["with"]
        unhl = op.get("unhighlight", True)

        def fn(p):
            count = 0
            if op.get("all"):
                while True:
                    sp = find_span(p, find, 1)
                    if not sp:
                        break
                    t_el = replace_span(p, sp[0], sp[1], new, unhighlight=unhl)
                    apply_format(t_el.getparent(), op.get("format"))
                    count += 1
                    if find in new:
                        break
            else:
                sp = find_span(p, find, op.get("nth", 1))
                if sp:
                    t_el = replace_span(p, sp[0], sp[1], new, unhighlight=unhl)
                    apply_format(t_el.getparent(), op.get("format"))
                    count = 1
            if not count:
                raise PlanError(f"text not found in {op['p']}: {find!r}")
            return count
        return self.on_both(pi, fn)

    def op_delete(self, op):
        op = dict(op, **{"with": ""})
        return self.op_replace(op)

    def op_insert(self, op):
        pi = self.para(op["p"])
        text = op["text"]

        def fn(p):
            full = para_text(p)
            if "after" in op:
                sp = find_span(p, op["after"], op.get("nth", 1))
                if not sp:
                    raise PlanError(f"anchor not found in {op['p']}: {op['after']!r}")
                pos = sp[1]
            elif "before" in op:
                sp = find_span(p, op["before"], op.get("nth", 1))
                if not sp:
                    raise PlanError(f"anchor not found in {op['p']}: {op['before']!r}")
                pos = sp[0]
            elif op.get("at") == "start":
                pos = 0
            else:
                pos = len(full)
            t_el = replace_span(p, pos, pos, text)
            apply_format(t_el.getparent(), op.get("format"))
        return self.on_both(pi, fn)

    def op_set_text(self, op):
        pi = self.para(op["p"])

        def fn(p):
            atoms = paragraph_atoms(p)
            n = atoms[-1].end if atoms else 0
            t_el = replace_span(p, 0, n, op["text"], unhighlight=True)
            apply_format(t_el.getparent(), op.get("format"))
        return self.on_both(pi, fn)

    def op_wrap_inline(self, op):
        pi = self.para(op["p"])
        if pi.numbered:
            self.warn(f"wrap_inline in numbered paragraph {op['p']}: on engine v3 a block opened in a "
                      "numbered list paragraph removes/repeats the WHOLE paragraph. Prefer a ternary value tag.")
        if pi.table:
            self.warn(f"wrap_inline in table cell {pi.table} r{pi.row}c{pi.col} ({op['p']}): on engine v3 "
                      "a block inside a table hides/repeats the WHOLE ROW. Prefer a ternary value tag or wrap_rows.")

        def fn(p):
            full = para_text(p)
            s, e = 0, len(full)
            if op.get("from_find"):
                sp = find_span(p, op["from_find"], op.get("from_nth", 1))
                if not sp:
                    raise PlanError(f"from_find not found in {op['p']}: {op['from_find']!r}")
                s = sp[0]
            if op.get("to_find"):
                sp = find_span(p, op["to_find"], op.get("to_nth", 1))
                if not sp or sp[1] < s:
                    raise PlanError(f"to_find not found after from_find in {op['p']}: {op['to_find']!r}")
                e = sp[1]
            replace_span(p, e, e, op["close"])
            replace_span(p, s, s, op["open"])
        return self.on_both(pi, fn)

    # ---------- structural ops (collected, applied together for correct nesting) ----------
    def plan_wrap_block(self, op, boundaries, order):
        first, fpi = self.block(op["from"])
        last, lpi = self.block(op["to"])
        self._add_block_boundaries(first, last, op, boundaries, order)
        if fpi is not None and lpi is not None and fpi.twin is not None and lpi.twin is not None:
            try:  # keep the legacy (VML) copy of a text box in sync
                self._add_block_boundaries(fpi.twin, lpi.twin, op, boundaries, order)
            except PlanError:
                pass
        part = (fpi or lpi).part if (fpi or lpi) else self.tables.get(op["from"], {}).get("part", "word/document.xml")
        self.dirty.add(part)

    @staticmethod
    def _boundary(boundaries, container, left, right):
        key = (id(container), id(left) if left is not None else "start")
        b = boundaries.setdefault(key, {"container": container, "left": left, "right": right, "items": []})
        if b["right"] is None:
            b["right"] = right
        return b

    def _add_block_boundaries(self, first, last, op, boundaries, order):
        """Every block tag sits at a boundary between two sibling elements. All tags that meet at one
        boundary are written together (closers inner->outer, then openers outer->inner), so nesting is
        always right however blocks touch."""
        if first.getparent() is not last.getparent():
            raise PlanError(f"wrap_block {op['from']}..{op['to']}: both ends must be in the same container "
                            "(same table cell / body / text box)")
        container = first.getparent()
        left_open = prev_meaningful(first)
        self._boundary(boundaries, container, left_open, first)["items"].append(("open", order, op["open"], op))
        nxt = last.getnext()
        while nxt is not None and nxt.tag in SKIPPABLE:
            nxt = nxt.getnext()
        self._boundary(boundaries, container, last, nxt)["items"].append(("close", order, op["close"], op))

    def is_loop_expr(self, tag):
        """Could {#expr} be a loop? Pure paths only; `.length` and comparisons are conditions."""
        e = tag.strip().strip("{}").lstrip("#").strip()
        if not re.fullmatch(r"[\w.\[\]$\u0590-\u05FF-]+", e) or e.endswith(".length"):
            return False
        if self.loop_paths is None:
            return True                                    # unknown: assume loop (the safe choice)
        if e in self.loop_paths:
            return True
        last = re.sub(r"\[\d+\]", "", e).split(".")[-1]
        return last in self.loop_names

    def materialize_boundaries(self, boundaries, style):
        """anchor (default): append the tags to the END of the paragraph on the left of the boundary -
        verified clean (no empty line when the condition is true or false) on engines v3 and v8.
        Fallbacks when there is no plain paragraph on the left (block at the start of a cell / text box,
        right after a table, after a numbered paragraph when the boundary opens a block):
          - only openers and a plain paragraph on the right -> at the START of that paragraph
            (clean when true; one empty paragraph when false);
          - otherwise a tag-only paragraph (one empty paragraph remains).
        own: always a tag-only paragraph (the opener/closer "on its own line")."""
        notes = []
        for b in boundaries.values():
            items = b["items"]
            closes = [it for it in items if it[0] == "close"]
            opens = [it for it in items if it[0] == "open"]
            seq = "".join(t for _, _, t, _ in sorted(closes, key=lambda x: -x[1])) + \
                "".join(t for _, _, t, _ in sorted(opens, key=lambda x: x[1]))
            X, Y = b["left"], b["right"]
            # never anchor on a paragraph that holds an html/grid tag - block HTML replaces the whole paragraph
            solo = re.compile(r"\|\s*(html|grid)\b")
            x_ok = X is not None and X.tag == P and not (has_direct_numbering(X) and opens) \
                and not solo.search(para_text(X))
            y_ok = Y is not None and Y.tag == P and not has_direct_numbering(Y) and not solo.search(para_text(Y))
            if style == "anchor" and x_ok:
                append_text_run(X, seq)
                continue
            loopish = any(op.get("loop", self.is_loop_expr(t)) for _, _, t, op in opens)
            if style == "anchor" and not closes and y_ok and not loopish:
                prepend_text_run(Y, seq)
                for _, _, t, op in opens:
                    notes.append(f"{op['from']}..{op['to']}: הפותח {t} בתחילת הפסקה הראשונה (אין לפניה פסקה מתאימה) - "
                                 "כשהתנאי שקרי תישאר שורה ריקה אחת")
                continue
            tp = tag_paragraph(X if X is not None else Y, seq)
            if X is not None:
                X.addnext(tp)
            elif Y is not None:
                Y.addprevious(tp)
            else:
                b["container"].append(tp)
            if style == "anchor":
                for kind, _, t, op in items:
                    why = "לולאה" if kind == "open" and op.get("loop", self.is_loop_expr(t)) else \
                        "אחרי טבלה / פסקה ממוספרת / בקצה תא או תיבת טקסט"
                    notes.append(f"{op['from']}..{op['to']}: {t} בשורה משלו ({why}) - עלולה להישאר שורה ריקה אחת. "
                                 "אם יש פסקה ריקה אחרי הטבלה, כלול אותה בבלוק כדי שהתג ייעגן בה")
        return notes

    @staticmethod
    def _grid_col(cell):
        """Grid column index of a cell (gridSpan aware)."""
        col = 0
        for c in cell.getparent():
            if c.tag != q("w:tc"):
                continue
            if c is cell:
                return col
            span = c.find("w:tcPr/w:gridSpan", NS)
            col += int(span.get(q("w:val"))) if span is not None else 1
        return col

    def op_wrap_rows(self, op):
        tbl = self.tables.get(op["table"])
        if not tbl:
            raise PlanError(f"unknown table {op['table']}")
        grid = table_grid(tbl["el"])
        r1, r2 = op["from_row"], op.get("to_row", op["from_row"])
        if not (1 <= r1 <= r2 <= len(grid)):
            raise PlanError(f"rows {r1}-{r2} out of range for {op['table']} ({len(grid)} rows)")
        if r2 - r1 >= 2 and not op.get("allow_v8_only"):
            raise PlanError(f"{op['table']} rows {r1}-{r2}: a block over 3+ rows breaks on engine v3 (production) - the "
                            "middle rows are kept/duplicated. Wrap each row (or pairs of rows) separately, or wrap the "
                            "whole table with wrap_block.")
        first_cell, last_cell = grid[r1 - 1][0], grid[r2 - 1][-1]
        if self._grid_col(first_cell) == self._grid_col(last_cell):
            raise PlanError(f"{op['table']} rows {r1}-{r2}: the opening and closing cells sit in the same grid column "
                            "(single-column or merged row) - the engine would repeat the COLUMN. Use a row with 2+ cells, "
                            "loop paragraphs inside the cell, or (v8 only) a [% loopOver: 'row' %] option.")
        if r1 == 1 and r2 == len(grid):
            self.rowless.append(op["table"])          # warned later unless a wrap_block covers the table
        fp = cell_paragraphs(first_cell)[0]
        lp = cell_paragraphs(last_cell)[-1]
        prepend_text_run(fp, op["open"])
        append_text_run(lp, op["close"])
        self.dirty.add(tbl["part"])
        return f"open→{op['table']} r{r1}c1, close→{op['table']} r{r2}c{len(grid[r2 - 1])}"

    def op_delete_drawings(self, op):
        """Remove pictures / text boxes from a paragraph (e.g. sample photo frames replaced by one
        flow/grid image tag). "nth" (1-based) removes one drawing, otherwise all of them."""
        pi = self.para(op["p"])
        removed = 0
        for el in [pi.el] + ([pi.twin] if pi.twin is not None else []):
            objs = [a for a in paragraph_atoms(el) if a.kind == "obj"]
            if op.get("nth"):
                objs = objs[op["nth"] - 1:op["nth"]]
            for a in objs:
                run = a.el.getparent()
                run.remove(a.el)
                if not [c for c in run if c.tag != RPR]:
                    run.getparent().remove(run)
                removed += 1
        if not removed:
            raise PlanError(f"no drawing found in {op['p']}")
        self.dirty.add(pi.part)
        return f"removed {removed} drawing(s) from {op['p']}"

    def op_set_alt(self, op):
        """Put an image tag in the alt text of an existing picture (image placeholder, engine 7+):
        the picture is swapped for the data image and keeps its frame, position and wrapping."""
        pi = self.para(op["p"])
        pics = [d for d in paragraph_drawings(pi.el) if d["kind"] == "picture"]
        n = op.get("nth", 1)
        if not (1 <= n <= len(pics)):
            raise PlanError(f"{op['p']} has {len(pics)} picture(s); nth={n}")
        d = pics[n - 1]
        before = d["alt"]
        d["docPr"].set("descr", op["alt"])          # the engine reads wp:docPr/@descr only
        if d["cNvPr"] is not None and d["cNvPr"].get("descr") is not None:
            del d["cNvPr"].attrib["descr"]           # don't leave the sample's alt text behind
        extra = ""
        if op.get("neutral", True):
            # Swap the sample photo (often a real client's property) for a neutral grey placeholder.
            # The engine keeps the placeholder's own picture when the data image is missing, so a
            # sample photo would otherwise leak into real reports.
            blip = next(d["docPr"].getparent().iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"), None)
            if blip is not None:
                key = (pi.part, d["width"], d["height"])
                rid = self._neutral_rids.get(key)
                if rid is None:
                    rid = self.doc.add_part_image(pi.part, placeholder_png(d["width"], d["height"]),
                                                  f"qtpl_placeholder_{d['width']}x{d['height']}.png")
                    self._neutral_rids[key] = rid
                blip.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", rid)
                extra = " (sample picture replaced by a neutral placeholder)"
        self.dirty.add(pi.part)
        return f"{op['p']} picture {n}: alt {before!r} -> {op['alt']!r}{extra}"

    def op_delete_rows(self, op):
        """Delete sample rows, e.g. the 2nd..Nth item rows of a filled report before looping the 1st."""
        tbl = self.tables.get(op["table"])
        if not tbl:
            raise PlanError(f"unknown table {op['table']}")
        grid_rows = [x for x in tbl["el"] if x.tag == q("w:tr")]
        rows = sorted(set(op["rows"]), reverse=True)
        if any(r < 1 or r > len(grid_rows) for r in rows):
            raise PlanError(f"rows {op['rows']} out of range for {op['table']} ({len(grid_rows)} rows)")
        if len(rows) >= len(grid_rows):
            raise PlanError(f"refusing to delete every row of {op['table']}")
        for r in rows:
            tbl["el"].remove(grid_rows[r - 1])
        self.dirty.add(tbl["part"])
        return f"deleted rows {sorted(rows)} of {op['table']}"

    def op_insert_paragraph(self, op):
        ref_id = op.get("after") or op.get("before")
        el, pi = self.block(ref_id)
        like = self.block(op["like"])[0] if op.get("like") else (el if el.tag == P else None)
        np_ = new_paragraph_like(like, op["text"])
        if op.get("after"):
            el.addnext(np_)
        else:
            el.addprevious(np_)
        part = pi.part if pi else self.tables[ref_id]["part"]
        self.dirty.add(part)
        if op.get("id"):
            from docxlib import ParaInfo
            ni = ParaInfo(op["id"], part, np_)
            ni.container = np_.getparent()
            if pi is not None:
                ni.table, ni.row, ni.col, ni.textbox = pi.table, pi.row, pi.col, pi.textbox
            self.by_id[op["id"]] = ni
        return op["text"]

    def op_delete_paragraph(self, op):
        pi = self.para(op["p"])
        before = para_text(pi.el)
        if pi.el.find(".//w:sectPr", NS) is not None:
            raise PlanError(f"{op['p']} carries a section break - not deleting")
        pi.el.getparent().remove(pi.el)
        if pi.twin is not None:
            pi.twin.getparent().remove(pi.twin)
        self.dirty.add(pi.part)
        return before

    def op_strip_markup(self, op):
        removed = []
        self.stripped = {"comments": 0, "highlights": 0}
        for pi in self.paras:
            p = pi.el
            if p.getparent() is None:
                continue
            if op.get("markup", True):
                while True:
                    txt = para_text(p)
                    m = re.search(r"\[\[.*?\]\]", txt)
                    if not m:
                        break
                    removed.append((pi.id, m.group(0)))
                    replace_span(p, m.start(), m.end(), "")
                    if pi.twin is not None:
                        tm = re.search(r"\[\[.*?\]\]", para_text(pi.twin))
                        if tm:
                            replace_span(pi.twin, tm.start(), tm.end(), "")
                    self.dirty.add(pi.part)
            if op.get("highlight_on_tags", False):
                for r in [r for r in p.iter(R) if nearest(r, P) is p]:
                    txt = "".join(t.text or "" for t in r.findall("w:t", NS))
                    if ("{" in txt or "}" in txt) and r.find("w:rPr/w:highlight", NS) is not None:
                        strip_highlight(r)
                        self.stripped["highlights"] += 1
                        self.dirty.add(pi.part)
        if op.get("comments", True):
            n = 0
            for part in self.doc.parts():
                root = self.doc.trees[part]
                for tag in ("w:commentRangeStart", "w:commentRangeEnd"):
                    for e in list(root.iter(q(tag))):
                        e.getparent().remove(e); n += 1
                for e in list(root.iter(q("w:commentReference"))):
                    r = e.getparent()
                    r.remove(e)
                    if not [c for c in r if c.tag != RPR]:
                        r.getparent().remove(r)
                    n += 1
                if n:
                    self.dirty.add(part)
            cm = self.doc.trees.get("word/comments.xml")
            if cm is not None:
                self.stripped["comments"] = len(cm.findall("w:comment", NS))
            if cm is not None and n:
                for c in list(cm):
                    cm.remove(c)
                self.dirty.add("word/comments.xml")
        return removed

    def warn(self, msg):
        self.log.append({"op": "warning", "detail": msg})

    def harden_html_runs(self):
        """The html extension (v3) copies the tag run's rPr children and crashes when there are none."""
        from lxml import etree
        for part in self.dirty:
            root = self.doc.trees.get(part)
            if root is None:
                continue
            for t in root.iter(T):
                if t.text and "| html" in t.text.replace("|html", "| html"):
                    r = t.getparent()
                    rpr = r.find("w:rPr", NS)
                    if rpr is None:
                        rpr = etree.Element(RPR)
                        r.insert(0, rpr)
                    if len(rpr) == 0:
                        etree.SubElement(rpr, q("w:lang")).set(q("w:bidi"), "he-IL")

    # ---------- driver ----------
    def run(self, plan):
        """Phases: insert_paragraph -> text ops -> delete_paragraph -> wrap_rows -> wrap_block ->
        delete_rows -> strip_markup. Deletions run before block placement so a block is never
        anchored on a paragraph that is about to disappear."""
        ops = plan.get("ops", [])
        text_ops = ("replace", "delete", "insert", "set_text", "wrap_inline")
        known = text_ops + ("wrap_rows", "wrap_block", "insert_paragraph", "delete_paragraph", "delete_rows",
                            "strip_markup", "set_alt", "delete_drawings")

        def phase(names, fn=None):
            for i, op in enumerate(ops):
                if op.get("op") not in names:
                    continue
                try:
                    res = (fn or getattr(self, "op_" + op["op"]))(op)
                    entry = {"i": i, "op": op["op"], "p": op.get("p"), "note": op.get("note", "")}
                    if isinstance(res, tuple):
                        entry.update(before=res[0], after=res[1])
                    else:
                        entry.update(detail=res, open=op.get("open"), close=op.get("close"))
                    self.log.append(entry)
                except Exception as e:
                    self.errors.append({"i": i, "op": op, "error": str(e)})

        phase(("insert_paragraph",))
        phase(text_ops)
        phase(("set_alt", "delete_drawings"))
        phase(("delete_paragraph",))
        phase(("wrap_rows",))
        # blocks (nesting-aware, boundary based)
        boundaries = {}
        blocks = [(i, op) for i, op in enumerate(ops) if op.get("op") == "wrap_block"]
        order_index = {pi.id: n for n, pi in enumerate(self.paras)}
        tbl_first = {}
        for pi in self.paras:
            if pi.table and pi.table not in tbl_first:
                tbl_first[pi.table] = order_index[pi.id]

        def pos(bid, end=False):
            if bid in order_index:
                return order_index[bid]
            if bid in tbl_first:
                if not end:
                    return tbl_first[bid]
                return max(order_index[pi.id] for pi in self.paras if pi.table == bid)
            if bid in self.by_id:   # paragraph inserted by the plan: place it next to its neighbours
                el = self.by_id[bid].el
                s_ = el.getprevious()
                while s_ is not None:
                    for pi in self.paras:
                        if pi.el is s_:
                            return order_index[pi.id] + 0.5
                    s_ = s_.getprevious()
            return 0
        blocks.sort(key=lambda x: (pos(x[1]["from"]), -pos(x[1]["to"], True)))   # outer first
        for rank, (i, op) in enumerate(blocks):
            try:
                self.plan_wrap_block(op, boundaries, rank)
                self.log.append({"i": i, "op": "wrap_block", "note": op.get("note", ""),
                                 "detail": f"{op['from']}..{op['to']}", "open": op["open"], "close": op["close"]})
                fpi = self.by_id.get(op["from"])
                if fpi is not None and fpi.table:
                    self.warn(f"wrap_block {op['from']}..{op['to']} בתוך תא {fpi.table} r{fpi.row}c{fpi.col}: במנוע v3 "
                              "תנאי שקרי מוחק את כל השורה, ב-v8 רק את התוכן.")
            except Exception as e:
                self.errors.append({"i": i, "op": op, "error": str(e)})
        for note in self.materialize_boundaries(boundaries, plan.get("block_style", "anchor")):
            self.warn(note)
        for t in self.rowless:
            if t not in tbl_first:
                continue
            t_last = max(order_index[pi.id] for pi in self.paras if pi.table == t)
            covered = any(pos(op["from"]) <= tbl_first[t] and pos(op["to"], True) >= t_last for _, op in blocks)
            if not covered:
                self.warn(f"{t}: כל שורות הטבלה בתוך לולאה/תנאי - כשאין פריטים תיווצר טבלה בלי שורות, ו-Word "
                          "מסמן קובץ כזה כפגום. עטוף את הטבלה (וכותרת שלה) ב-wrap_block על ‎.length.")
        phase(("delete_rows",))
        for i, op in enumerate(ops):
            if op.get("op") != "strip_markup":
                continue
            removed = self.op_strip_markup(op)
            self.log.append({"i": i, "op": "strip_markup",
                             "detail": f"הוסרו {len(removed)} סימוני [[...]], {self.stripped['comments']} הערות Word, "
                                       f"{self.stripped['highlights']} הדגשות על תגיות",
                             "removed": removed})
        for op in ops:
            if op.get("op") not in known:
                self.errors.append({"op": op, "error": f"unknown op {op.get('op')!r}"})


def count_tags(path, app):
    """Counts for the report and the chat message, read from the written template."""
    d = Docx(path)
    paras, _ = collect(d)
    tags = []
    for pi in paras:
        if pi.twin is None or True:
            tags += re.findall(r"\{[^{}]+\}", para_text(pi.el))
    openers = [t for t in tags if t.startswith("{#")]
    values = [t for t in tags if not t.startswith(("{#", "{/", "{^"))]
    loops = [t for t in openers if app.is_loop_expr(t)]
    return {"value_tags": len(values), "distinct_values": len(set(values)), "blocks": len(openers),
            "loops": len(loops), "conditions": len(openers) - len(loops),
            "loops_known": app.loop_paths is not None,
            "markup_left": sum(len(re.findall(r"\[\[.*?\]\]", para_text(pi.el))) for pi in paras)}


def write_report(path, plan, app, src, dst, counts=None):
    """Hebrew mapping report. Plan-level fields feed the human part:
       "summary": str, "decisions": [str], "unmatched": [{"where", "text", "note"}], "v8_only": [str]
    validate.py later appends a "בדיקות" section (lint + test renders)."""
    applied = [x for x in app.log if x.get("op") != "warning"]
    L = [f"# דוח מיפוי - {os.path.basename(dst)}", "",
         f"- קובץ מקור: `{os.path.basename(src)}`",
         f"- טופס שומה: {plan.get('form', {}).get('title', '?')} (`{plan.get('form', {}).get('id', '?')}`)",
         f"- פעולות שבוצעו: {len(applied)} | שגיאות: {len(app.errors)}"]
    if counts:
        kinds = (f"{counts['loops']} לולאות, {counts['conditions']} תנאים" if counts["loops_known"]
                 else f"{counts['blocks']} תנאים ולולאות")
        L.append(f"- בתבנית: {counts['value_tags']} תגיות ערך ({counts['distinct_values']} שונות), {kinds}"
                 + (f", {counts['markup_left']} סימוני [[...]] שנשארו" if counts["markup_left"] else ""))
    L.append("- מזהי פסקאות (P0042...) בדוח הזה מתייחסים למסמך המקורי; ה-linter מדווח לפי התבנית")
    L.append("")
    if plan.get("summary"):
        L += ["## סיכום", plan["summary"], ""]
    if plan.get("decisions"):
        L.append("## החלטות לאישור")
        L += [f"{n}. {d}" for n, d in enumerate(plan["decisions"], 1)]
        L.append("")
    if plan.get("unmatched"):
        L += ["## ללא משתנה מתאים (נשאר טקסט קבוע)", "", "| מיקום | טקסט | הערה |", "|---|---|---|"]
        for u in plan["unmatched"]:
            L.append(f"| {u.get('where', '')} | {u.get('text', '')} | {u.get('note', '')} |")
        L.append("")
    if plan.get("v8_only"):
        L.append("## עובד רק אחרי פריסת v8")
        L += [f"- {x}" for x in plan["v8_only"]]
        L.append("")
    if app.errors:
        L.append("## שגיאות (לא בוצעו)")
        for e in app.errors:
            L.append(f"- op #{e.get('i', '?')}: {e['error']}")
        L.append("")
    warns = [x for x in app.log if x.get("op") == "warning"]
    if warns:
        L.append("## אזהרות")
        for w in warns:
            L.append(f"- {w['detail']}")
        L.append("")
    L.append("## כל השינויים")
    for x in applied:
        note = f" - {x['note']}" if x.get("note") else ""
        if "before" in x:
            L.append(f"- **{x.get('p')}** ({x['op']}){note}")
            L.append(f"  - לפני: `{str(x['before'])[:160]}`")
            L.append(f"  - אחרי: `{str(x['after'])[:160]}`")
        else:
            extra = f" `{x.get('open', '')}` … `{x.get('close', '')}`" if x.get("open") else ""
            L.append(f"- ({x['op']}) {x.get('detail', '')}{extra}{note}")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    args = sys.argv[1:]
    report = catalog = None
    if "--report" in args:
        i = args.index("--report"); report = args[i + 1]; del args[i:i + 2]
    if "--catalog" in args:
        i = args.index("--catalog"); catalog = json.load(open(args[i + 1], encoding="utf-8")); del args[i:i + 2]
    src, plan_path, dst = args
    plan = json.load(open(plan_path, encoding="utf-8"))
    doc = Docx(src)
    app = Applier(doc, catalog)
    app.run(plan)
    pruned = doc.save(dst, dirty=app.dirty)
    counts = count_tags(dst, app)
    report = report or os.path.splitext(dst)[0] + "_mapping_report.md"
    write_report(report, plan, app, src, dst, counts)
    ok = len([x for x in app.log if x.get("op") != "warning"])
    print(json.dumps({"output": dst, "report": report, "applied": ok, "errors": app.errors, "counts": counts,
                      "pruned_media": pruned or [],
                      "warnings": [w["detail"] for w in app.log if w.get("op") == "warning"]},
                     ensure_ascii=False, indent=1))
    sys.exit(1 if app.errors else 0)


if __name__ == "__main__":
    main()
