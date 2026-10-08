#!/usr/bin/env python3
"""
Static checks for a Quicker easy-template-x Word template against a form catalog.

Usage:
    python3 lint_template.py <template.docx> <catalog.json> [--json issues.json] [--quiet]

Checks
  errors   : unbalanced / mismatched {#..}{/..}, unknown variables, unknown filters,
             bare field names outside their loop, '!x == y' precedence bug, tags ending with ']',
             tags broken across paragraphs, groups printed as values
  warnings : '{/}' anonymous closers, empty condition blocks, filter/type mismatches,
             booleans or lists printed raw, richtext without | html, images without maxSize,
             legacy top-level image names, undocumented p.* fields, smart quotes,
             single-column row loops
Exit code 1 when there are errors.
"""
import json
import re
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from docxlib import Docx, collect, para_text, paragraph_drawings  # noqa: E402

FILTERS = {"date", "currency", "fixed", "list", "includes", "isEmpty", "stripTag", "html", "lower",
           "maxSize", "frame", "rounded", "align", "gap", "grid", "inc", "loopSep"}
IMAGE_FILTERS = {"maxSize", "frame", "rounded", "align", "gap", "grid"}
P_FIELDS = {"number", "name", "address", "city", "street", "house", "neighborhood", "gush", "helka", "plot",
            "plotByTaba", "floor", "rooms", "squareMeter", "appraisalType", "appraisalPurpose", "propertyType",
            "propertyDestiny", "status", "referrer", "dueDate", "determinesDate", "visitDate", "agentName"}
P_UNDOCUMENTED = set()          # p.* names that render but are not part of the documented contract
C_FIELDS = {"name", "phone", "email", "address", "city", "personalIdentity", "isPrimary"}
TOP = {"today", "todayISO", "ownerName", "ownerManagerName", "customers", "appraisalHeaderImage",
       "appraisalFooterImage", "appraisalSignatureImage", "govMapImage", "HEADER_IMAGE_WIDTH",
       "FOOTER_IMAGE_WIDTH", "p", "project", "c"}
LEGACY_TOP = {"govmapImage", "quickSalePrice", "image"}
LOOP_META = {"_idx", "_isFirst", "_isLast"}
KEYWORDS = {"true", "false", "null", "undefined", "this"}

STR_RE = re.compile(r"'[^']*'|\"[^\"]*\"|[‘’][^‘’]*[‘’]|[“”][^“”]*[“”]")
IDENT = r"[A-Za-z_$֐-׿][\w$֐-׿]*(?:-[֐-׿][\w֐-׿]*)*"
PATH_RE = re.compile(r"(?<![\w$.֐-׿])(" + IDENT + r"(?:\s*\.\s*" + IDENT + r"|\s*\[\s*\d+\s*\])*)")
NEG_PREC_RE = re.compile(r"(?<![!=<>])!\s*(?!\()[A-Za-z_֐-׿][\w.\[\]֐-׿]*\s*(===|!==|==|!=|>=|<=|>|<)")


class Lint:
    def __init__(self, catalog):
        self.cat = catalog
        if catalog.get("filters"):
            # the variables tool's filter list is authoritative (an unknown filter renders the tag empty)
            FILTERS.clear()
            FILTERS.update(catalog["filters"])
        if catalog.get("system_source") == "variables-tool":
            # authoritative render context: drop the built-in guesses, keep only what the engine provides
            P_FIELDS.clear()
            P_UNDOCUMENTED.clear()
            C_FIELDS.clear()
            TOP.intersection_update({"p", "project", "c", "HEADER_IMAGE_WIDTH", "FOOTER_IMAGE_WIDTH"})
        for sf in catalog.get("system_fields", []):
            if sf.get("path") == "customers":
                C_FIELDS.update(sf.get("fields") or [])
            path = sf.get("path", "")
            parts = path.split(".")
            if parts[0] in ("p", "project") and len(parts) == 2:
                P_FIELDS.add(parts[1])
            elif parts[0] == "c" and len(parts) == 2:
                C_FIELDS.add(parts[1])
            elif len(parts) == 1 and parts[0]:
                TOP.add(parts[0])
        self.top_fields = {f["name"]: f for f in catalog["fields"] if not f["loop"]}
        self.groups_by_path = {}
        for g in catalog["groups"]:
            self.groups_by_path.setdefault(g["path"], g)
        self.top_groups = {g["name"]: g for g in catalog["groups"] if not g["parent"]}
        self.loop_fields = {}
        for f in catalog["fields"]:
            if f["loop"]:
                self.loop_fields.setdefault(f["loop"], {})[f["name"]] = f
        self.all_fields_by_name = {}
        for f in catalog["fields"]:
            self.all_fields_by_name.setdefault(f["name"], f)
        self.issues = []
        self.used = Counter()

    def add(self, level, code, where, tag, msg):
        self.issues.append({"level": level, "code": code, "where": where, "tag": tag, "message": msg})

    # ---------------- expression helpers ----------------
    @staticmethod
    def split_filters(expr):
        parts = re.split(r"(?<!\|)\|(?!\|)", expr)
        return parts[0], [x.strip() for x in parts[1:]]

    def resolve(self, segs, stack):
        """Return (kind, info) for a path given the loop stack."""
        if not segs:
            return "unknown", None
        s0 = segs[0]
        if s0 in ("p", "project"):
            if len(segs) == 1:
                return "obj", None
            if segs[1] in ("ad", "additionalDetails"):
                if len(segs) == 2:
                    return "obj", None
                name = segs[2]
                if name in self.top_groups:
                    g = self.top_groups[name]
                    if len(segs) == 3:
                        return "group", g
                    rest = segs[3]
                    if rest == "length":
                        return "length", g
                    sub = self.loop_fields.get(g["path"], {})
                    if rest in sub:
                        return "field", sub[rest]
                    for sg in self.cat["groups"]:
                        if sg["parent"] == g["path"] and sg["name"] == rest:
                            if len(segs) == 4:
                                return "group", sg
                            if segs[4] == "length":
                                return "length", sg
                            ssub = self.loop_fields.get(sg["path"], {})
                            if segs[4] in ssub:
                                return "field", ssub[segs[4]]
                    return "unknown", f"'{rest}' is not a field of group p.ad.{name}"
                if name in self.top_fields:
                    f = self.top_fields[name]
                    if len(segs) > 3 and segs[3] != "length":
                        return "unknown", f"p.ad.{name} has no member '{segs[3]}'"
                    return ("length" if len(segs) > 3 else "field"), f
                return "unknown", f"p.ad.{name} is not in the selected form"
            name = segs[1]
            if name in P_FIELDS:
                return "system", name
            if name in P_UNDOCUMENTED:
                return "undocumented", name
            return "unknown", f"p.{name} is not a documented project field"
        if s0 == "c":
            if len(segs) == 1 or segs[1] in C_FIELDS:
                return "system", s0
            return "unknown", f"c.{segs[1]} is not a customer field"
        if s0 in LOOP_META:
            return ("meta", s0) if stack else ("unknown", f"{s0} is only available inside a loop")
        if s0 in TOP:
            return "system", s0
        # bare name -> innermost loop first
        for fr in reversed(stack):
            if fr["kind"] == "group":
                gp = fr["group"]["path"]
                sub = self.loop_fields.get(gp, {})
                if s0 in sub:
                    return "field", sub[s0]
                for g in self.cat["groups"]:
                    if g["parent"] == gp and g["name"] == s0:
                        return ("group" if len(segs) == 1 else "length"), g
            if fr["kind"] == "customers" and s0 in C_FIELDS:
                return "system", s0
            if fr["kind"] == "legacy" and s0 == "image":
                return "legacy", s0
            if fr["kind"] == "imageloop" and s0 == "image":
                return "system", "image"
        if s0 in LEGACY_TOP:
            return "legacy", s0
        if s0 in self.top_fields and self.top_fields[s0]["kind"] in ("image", "images"):
            return "legacy", s0
        if s0 in self.all_fields_by_name:
            f = self.all_fields_by_name[s0]
            where = f"inside loop {f['loop']}" if f["loop"] else f"as p.ad.{s0}"
            return "unknown", f"'{s0}' exists only {where}"
        return "unknown", f"'{s0}' is not a known variable"

    def check_expr(self, expr, where, tag, stack, role):
        """role: value | open | close. Returns resolution of the main path (for loops)."""
        if re.search(r"[‘’“”]", expr):
            self.add("info", "smart-quotes", where, tag, "curly quotes inside a tag (Quicker normalises them; straight ' is cleaner)")
        if NEG_PREC_RE.search(STR_RE.sub("''", expr)):
            self.add("error", "negation-precedence", where, tag,
                     "'!x == y' negates x before comparing (always false). Write 'x != y' or '!(x == y)'.")
        if "===" in expr or "!==" in expr:
            self.add("info", "strict-equality", where, tag, "use == / != (house convention)")
        if len(expr) > 200:
            self.add("warning", "long-expression", where, tag[:60] + "...",
                     f"{len(expr)}-character expression - hard to maintain (and some angular-expressions builds cap "
                     "strings at 250). Simplify, or ask whether Quicker can provide the value as a field")
        if "[%" in expr:
            self.add("info", "tag-options", where, tag, "tag options [% ... %] work on the v8 branch only")
            expr = re.sub(r"\[%.*?%\]", "", expr)
        stripped_all = STR_RE.sub("''", expr)
        # filters can appear at top level or inside parentheses (ternary branches)
        FILTER_SEG = re.compile(r"(?<!\|)\|(?!\|)\s*([A-Za-z_]\w*)((?:\s*:\s*(?:''|-?\d+(?:\.\d+)?|[A-Za-z_][\w.]*))*)")
        filters = [m.group(1) + m.group(2) for m in FILTER_SEG.finditer(stripped_all)]
        value = FILTER_SEG.sub("", stripped_all)
        stripped = value
        main = None
        paths = PATH_RE.findall(stripped)
        for raw in paths:
            segs = [s for s in re.split(r"\s*\.\s*|\s*\[\s*\d+\s*\]\s*", raw) if s]
            if not segs or segs[0] in KEYWORDS:
                continue
            kind, info = self.resolve(segs, stack)
            norm = ".".join(segs)
            self.used[norm] += 1
            if main is None:
                main = (kind, info, segs)
            if kind == "unknown":
                self.add("error", "unknown-variable", where, tag, info)
            elif kind == "undocumented":
                self.add("warning", "undocumented-field", where, tag,
                         f"p.{info} works in existing templates but is not in the documented contract - verify")
            elif kind == "legacy":
                self.add("warning", "legacy-name", where, tag,
                         f"'{segs[0]}' is a legacy top-level name; prefer the documented form (p.ad.<field> / govMapImage)")
            elif kind == "group" and role == "value" and not filters:
                self.add("error", "group-as-value", where, tag, f"'{norm}' is a repeatable group - loop over it with {{#...}}")
        for raw in paths:
            segs0 = [x for x in re.split(r"\s*\.\s*", re.sub(r"\s*\[\s*\d+\s*\]", "[]", raw)) if x]
            base = [x.replace("[]", "") for x in segs0]
            if len(base) >= 3 and base[0] in ("p", "project") and base[1] in ("ad", "additionalDetails"):
                f = self.top_fields.get(base[2])
                if f and f.get("kind") in ("image", "images"):
                    if len(base) > 3 and base[3] == "length":
                        self.add("error", "image-length", where, tag,
                                 f".length on image field p.ad.{base[2]} - a field holding ONE image is an object, so this is "
                                 "undefined and hides the only image. Test with !(p.ad.x | isEmpty)")
                    elif "[]" in segs0[2]:
                        self.add("warning", "image-index", where, tag,
                                 f"[n] on image field p.ad.{base[2]} - with one image the field is an object and [0] is empty. "
                                 f"Prefer {{p.ad.{base[2]} | maxSize:w:h}} (all images) or a placeholder")
                    if role == "open" and value.strip() == raw.strip():
                        self.add("info", "image-loop", where, tag,
                                 f"loop over images - inside it write {{image | maxSize:w:h}} (needs Quicker's image-loop fix). "
                                 f"For a plain gallery {{p.ad.{base[2]} | maxSize:w:h}} / | grid:N is simpler")
        fnames = []
        for fpart in filters:
            fname = re.split(r"[\s:]", fpart, maxsplit=1)[0]
            fnames.append(fname)
            if fname not in FILTERS:
                self.add("error", "unknown-filter", where, tag, f"filter '{fname}' does not exist in Quicker (output will be empty)")
            for arg in PATH_RE.findall(fpart[len(fname):]):
                if arg not in TOP and not re.fullmatch(r"\d+", arg):
                    self.add("warning", "filter-arg", where, tag, f"filter argument '{arg}' is an identifier - quote literal strings")
        if main and role == "value" and len(paths) == 1 and stripped.strip() == paths[0].strip():
            kind, info, segs = main
            f = info if isinstance(info, dict) and kind == "field" else None
            if f:
                k = f.get("kind")
                if k == "bool":
                    self.add("warning", "bool-printed", where, tag, f"{f['path']} is a checkbox - printing it shows true/false; use a condition")
                if k == "multi" and "list" not in fnames:
                    self.add("warning", "list-printed", where, tag, f"{f['path']} is a multi-select array - use | list:', '")
                if k == "richtext" and "html" not in fnames:
                    self.add("warning", "richtext-no-html", where, tag, f"{f['path']} is richtext - add | html")
                if k in ("image", "images") and not (set(fnames) & IMAGE_FILTERS):
                    self.add("warning", "image-no-size", where, tag, f"{f['path']} is an image - add | maxSize:w:h")
                if "date" in fnames and k not in ("date",):
                    self.add("warning", "filter-type", where, tag, f"| date on a {k} field")
                if "currency" in fnames and k not in ("money", "area", "number"):
                    self.add("warning", "filter-type", where, tag, f"| currency on a {k} field")
                if k == "date" and "date" not in fnames:
                    self.add("warning", "date-unformatted", where, tag, f"{f['path']} is a date - add | date")
                if k in ("money",) and "currency" not in fnames and "fixed" not in fnames:
                    self.add("info", "money-unformatted", where, tag, f"{f['path']} is an amount - usually | currency")
            if segs and segs[0] == "today" and "date" in fnames:
                self.add("warning", "today-date", where, tag, "today is already DD/MM/YYYY - drop | date")
        return main, value.strip(), fnames

    # ---------------- document walk ----------------
    def run(self, path):
        doc = Docx(path)
        paras, tables = collect(doc)
        stack = []
        last_part = None
        for pi in paras:
            if pi.part != last_part:
                if stack and last_part:
                    for fr in stack:
                        self.add("error", "unclosed", fr["where"], fr["tag"], f"opened in {last_part} and never closed")
                stack = []
                last_part = pi.part
            text = para_text(pi.el)
            where = pi.id + (f" ({pi.table} r{pi.row}c{pi.col})" if pi.table else "") + (" textbox" if pi.textbox else "")
            if text.count("{") != text.count("}"):
                self.add("error", "broken-tag", where, text[:80],
                         "unbalanced { } in this paragraph - a tag is split across paragraphs or a brace is stray")
            for mk in re.findall(r"\[\[.*?\]\]", text):
                self.add("warning", "leftover-markup", where, mk, "author instruction still in the template - resolve it or confirm it has no matching field")
            if "{{" in text or "}}" in text:
                self.add("error", "double-brace", where, text[:80], "double braces - Quicker uses single { }")
            self.check_alt(pi, where, stack)
            for m in re.finditer(r"\{([^{}]*)\}", text):
                tag = m.group(0)
                inner = m.group(1).strip()
                if "\t" in inner or "\n" in inner:
                    self.add("error", "tag-whitespace", where, tag, "tab / line break inside a tag")
                if not inner:
                    self.add("error", "empty-tag", where, tag, "empty tag {}")
                    continue
                if inner.startswith("^"):
                    self.add("info", "inverted-block", where, tag, "{^x} works on the v8 branch only - {#!x} works everywhere")
                    inner = "#!(" + inner[1:].strip() + ")"
                if inner.startswith("#"):
                    expr = inner[1:].strip()
                    main, value, fnames = self.check_expr(expr, where, tag, stack, "open")
                    neg = re.fullmatch(r"!\s*([\w.]+)", expr)
                    if neg:
                        segs = neg.group(1).split(".")
                        k, info = self.resolve(segs, stack)
                        if k == "group":
                            self.add("warning", "empty-array-truthy", where, tag,
                                     f"an empty group is an empty array, which is truthy - '!{neg.group(1)}' never shows. Use '!{neg.group(1)}.length'")
                    kind = "cond"
                    frame = {"kind": kind, "expr": expr, "tag": tag, "where": where, "pi": pi, "pos": m.end(),
                             "text_at_open": text}
                    if main and value == expr.strip() and main[0] == "group":
                        frame.update(kind="group", group=main[1])
                    elif main and main[2] and main[2][0] == "customers" and value == expr.strip():
                        frame.update(kind="customers")
                    elif main and main[0] == "legacy" and value == expr.strip():
                        frame.update(kind="legacy")
                    elif main and main[0] == "field" and isinstance(main[1], dict) and main[1].get("kind") in ("image", "images") \
                            and value == expr.strip():
                        frame.update(kind="imageloop")
                    if pi.numbered and not pi.table:
                        self.add("warning", "list-paragraph-block", where, tag,
                                 "block opened inside a numbered list paragraph - on engine v3 the engine "
                                 "repeats/removes whole list paragraphs, so a false condition deletes the entire line "
                                 "(and multi-paragraph blocks get scrambled). Use a ternary value tag, or open the block "
                                 "in an un-numbered paragraph.")
                    stack.append(frame)
                elif inner.startswith("/"):
                    expr = inner[1:].strip()
                    if not stack:
                        self.add("error", "unopened-close", where, tag, "closing tag without an open block")
                        continue
                    fr = stack.pop()
                    if not expr:
                        self.add("warning", "anonymous-close", where, tag,
                                 f"closing tag should repeat the opening expression: {{/{fr['expr']}}}")
                    elif re.sub(r"\s+", "", expr) != re.sub(r"\s+", "", fr["expr"]) and \
                            re.sub(r"\s+", "", "!(" + expr + ")") != re.sub(r"\s+", "", fr["expr"]):
                        self.add("error", "mismatched-close", where, tag,
                                 f"closes '{fr['expr']}' (opened at {fr['where']}) - nesting is wrong or a closer is missing")
                    # empty block?
                    if fr["pi"] is pi:
                        between = text[fr["pos"]:m.start()]
                        if not between.strip():
                            self.add("warning", "empty-block", where, tag, f"block '{fr['expr']}' has no content")
                    # block inside one table cell: engine v3 (production) hides/repeats the whole row
                    if fr["pi"].table and pi.table == fr["pi"].table and fr["pi"].row == pi.row and fr["pi"].col == pi.col \
                            and fr.get("kind") != "group":
                        self.add("warning", "cell-block", where, tag,
                                 f"condition '{fr['expr']}' sits inside one table cell - on engine v3 a false "
                                 "condition removes the WHOLE ROW. Fine if that is the intent; otherwise use a ternary value tag.")
                    # row loop in a single column?
                    if fr["pi"].table and pi.table == fr["pi"].table and fr["pi"].row != pi.row and fr["pi"].col == pi.col:
                        self.add("warning", "column-loop", where, tag,
                                 "open and close are in the same table column but different rows - the engine will repeat the COLUMN, not the rows")
                else:
                    self.check_expr(inner, where, tag, stack, "value")
                    if re.search(r"\|\s*html\b", inner):
                        rest = (text[:m.start()] + text[m.end():]).strip()
                        if rest:
                            lvl = "error" if re.search(r"\{[#/^]", rest) else "warning"
                            self.add(lvl, "html-not-alone", where, tag,
                                     "rich text with block elements (paragraphs, lists, tables, headings) replaces the WHOLE "
                                     "paragraph - the other text here would be lost" +
                                     (" (including a block tag - the template breaks)" if lvl == "error" else "") +
                                     ". Put {x | html} alone in its paragraph")
                    elif re.search(r"\|\s*grid\b", inner):
                        rest = (text[:m.start()] + text[m.end():]).strip()
                        if rest:
                            self.add("warning", "grid-not-alone", where, tag,
                                     "an image grid inserts a table before its paragraph - keep {x | grid:N} alone in its "
                                     "paragraph (a condition goes on the heading, not here)")
        for fr in stack:
            self.add("error", "unclosed", fr["where"], fr["tag"], "opened and never closed")
        return self.issues

    def check_alt(self, pi, where, stack):
        """Image placeholders: a tag in a picture's alt text (engine 7+ swaps the picture)."""
        for n, d in enumerate(paragraph_drawings(pi.el), 1):
            for m in re.finditer(r"\{([^{}]*)\}", d["alt"] or ""):
                tag, inner = m.group(0), m.group(1).strip()
                w = f"{where} picture {n} alt-text"
                if d["kind"] != "picture":
                    self.add("error", "alt-not-picture", w, tag, "image placeholder tags only work in a picture's alt text")
                    continue
                if inner.startswith("#") or inner.startswith("/"):
                    self.add("error", "alt-block", w, tag, "only a value tag can go in alt text")
                    continue
                main, value, fnames = self.check_expr(inner, w, tag, stack, "alt")
                if main:
                    kind, info, segs = main
                    k = info.get("kind") if isinstance(info, dict) else None
                    is_img = k in ("image", "images") or (segs and segs[0] in (
                        "appraisalHeaderImage", "appraisalFooterImage", "appraisalSignatureImage", "govMapImage", "image"))
                    if not is_img and kind not in ("legacy",):
                        self.add("warning", "alt-not-image", w, tag, "the placeholder tag does not point at an image field")
                rest = (d["alt"][:m.start()] + d["alt"][m.end():]).strip()
                if rest:
                    self.add("error", "alt-extra-text", w, tag, "the alt text must contain ONLY the tag")
                self.add("info", "placeholder", w, tag, "image placeholder - v8 branch only (on v3 the template's picture prints)")


def main():
    args = sys.argv[1:]
    js = None
    quiet = "--quiet" in args
    if quiet:
        args.remove("--quiet")
    if "--json" in args:
        i = args.index("--json"); js = args[i + 1]; del args[i:i + 2]
    tpl, cat_path = args
    catalog = json.load(open(cat_path, encoding="utf-8"))
    lint = Lint(catalog)
    issues = lint.run(tpl)
    cnt = Counter(i["level"] for i in issues)
    by_code = Counter((i["level"], i["code"]) for i in issues)
    print(f"lint {os.path.basename(tpl)}: {cnt.get('error', 0)} errors, {cnt.get('warning', 0)} warnings, "
          f"{cnt.get('info', 0)} info | distinct variables used: {len(lint.used)}")
    for (lvl, code), n in sorted(by_code.items()):
        print(f"  {lvl:7} {code:22} x{n}")
    if not quiet:
        for i in issues:
            if i["level"] == "info":
                continue
            print(f"- [{i['level']}] {i['code']} @ {i['where']}: {i['tag'][:90]}  -> {i['message']}")
    if js:
        json.dump({"issues": issues, "used": dict(lint.used)}, open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(1 if cnt.get("error") else 0)


if __name__ == "__main__":
    main()
