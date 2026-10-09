"""
Shared low-level helpers for reading and surgically editing .docx files while keeping
the original formatting (runs, styles, RTL, tables, text boxes, headers/footers).

Paragraph IDs are deterministic for a given input file:
  document.xml -> P0001, P0002 ...
  headerN.xml  -> H{N}-001 ...
  footerN.xml  -> F{N}-001 ...
Tables:        T1, T2 ... (document) / H1-T1 / F2-T1 (headers/footers)
Paragraphs inside mc:Fallback (legacy VML copy of a text box) are NOT listed - they are kept
in sync automatically as the "twin" of the matching mc:Choice paragraph.
"""
import copy
import os
import re
import zipfile
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W, "mc": MC}


def q(tag):
    p, t = tag.split(":")
    return "{%s}%s" % ({"w": W, "mc": MC}[p], t)


T, R, P, TBL, TR, TC, TAB, BR, CR = (q("w:t"), q("w:r"), q("w:p"), q("w:tbl"), q("w:tr"),
                                     q("w:tc"), q("w:tab"), q("w:br"), q("w:cr"))
RPR, PPR = q("w:rPr"), q("w:pPr")
FALLBACK, CHOICE, ALTC = q("mc:Fallback"), q("mc:Choice"), q("mc:AlternateContent")
TXBX = q("w:txbxContent")
CONTAINERS = {q("w:hyperlink"), q("w:ins"), q("w:smartTag"), q("w:sdt"), q("w:sdtContent"),
              q("w:fldSimple"), q("w:customXml"), q("w:moveTo"), q("w:dir"), q("w:bdo")}
SKIP_CONTAINERS = {q("w:del"), q("w:moveFrom")}
OBJECT_TAGS = {q("w:drawing"), q("w:pict"), q("w:object"), ALTC}
CRS, CRE = q("w:commentRangeStart"), q("w:commentRangeEnd")

PART_RE = re.compile(r"^word/(document|header(\d*)|footer(\d*))\.xml$")


class Docx:
    def __init__(self, path):
        self.path = path
        z = zipfile.ZipFile(path)
        self.files = {n: z.read(n) for n in z.namelist()}
        self.infos = {i.filename: i for i in z.infolist()}
        self.trees = {}
        for n in self.files:
            if PART_RE.match(n) or n == "word/comments.xml" or n == "word/styles.xml":
                self.trees[n] = etree.fromstring(self.files[n])

    # ordered list of editable parts: document first, then headers, then footers
    def parts(self):
        def key(n):
            m = PART_RE.match(n)
            kind = m.group(1)
            num = int(re.sub(r"\D", "", kind) or 0)
            return (0 if kind == "document" else 1 if kind.startswith("header") else 2, num)
        return sorted([n for n in self.trees if PART_RE.match(n)], key=key)

    def save(self, out_path, dirty=None):
        """Write the package. Image relationships that no longer appear in an edited part, and media files
        no relationship points to, are dropped - a deleted sample photo must not stay inside the zip.
        Returns the list of removed media files."""
        out = {}
        for n, data in self.files.items():
            if n in self.trees and (dirty is None or n in dirty):
                data = etree.tostring(self.trees[n], xml_declaration=True, encoding="UTF-8", standalone=True)
            out[n] = data
        removed = self._prune_images(out, dirty)
        z = zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED)
        for n, data in out.items():
            info = self.infos.get(n) or zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        z.close()
        return removed

    @staticmethod
    def _prune_images(out, dirty):
        RNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        IMG = "/relationships/image"
        for rels_name in [n for n in out if n.endswith(".rels") and "/_rels/" in n]:
            part = rels_name.replace("_rels/", "").rsplit(".rels", 1)[0]
            if part not in out or (dirty is not None and part not in dirty):
                continue
            xml = out[part].decode("utf-8", "ignore")
            rels = etree.fromstring(out[rels_name])
            changed = False
            for r in list(rels):
                if r.get("Type", "").endswith(IMG) and r.get("TargetMode") != "External" \
                        and f'"{r.get("Id")}"' not in xml:
                    rels.remove(r)
                    changed = True
            if changed:
                out[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
        referenced = set()
        for rels_name in [n for n in out if n.endswith(".rels")]:
            base = rels_name.split("_rels/")[0]
            for r in etree.fromstring(out[rels_name]):
                t = r.get("Target", "")
                if r.get("TargetMode") == "External":
                    continue
                path = t.lstrip("/") if t.startswith("/") else os.path.normpath(base + t).replace(os.sep, "/")
                referenced.add(path)
        removed = [n for n in out if re.match(r"^word/media/.", n) and not n.endswith("/") and n not in referenced]
        for n in removed:
            del out[n]
        return removed

    # ---- media helpers (neutral image placeholders) ----
    def add_part_image(self, part, png_bytes, name):
        """Add a PNG to word/media and a relationship from `part`; returns the new rId."""
        media = f"word/media/{name}"
        self.files[media] = png_bytes
        rels_name = re.sub(r"^word/(.*)$", r"word/_rels/\1.rels", part)
        RNS = "http://schemas.openxmlformats.org/package/2006/relationships"
        if rels_name in self.files:
            rels = etree.fromstring(self.files[rels_name])
        else:
            rels = etree.Element("{%s}Relationships" % RNS, nsmap={None: RNS})
        ids = {r.get("Id") for r in rels}
        n = 1
        while f"rIdQ{n}" in ids:
            n += 1
        rid = f"rIdQ{n}"
        r = etree.SubElement(rels, "{%s}Relationship" % RNS)
        r.set("Id", rid)
        r.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
        r.set("Target", f"media/{name}")
        self.files[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
        ct = etree.fromstring(self.files["[Content_Types].xml"])
        CNS = "http://schemas.openxmlformats.org/package/2006/content-types"
        if not any(d.get("Extension", "").lower() == "png" for d in ct.findall("{%s}Default" % CNS)):
            d = etree.Element("{%s}Default" % CNS)
            d.set("Extension", "png")
            d.set("ContentType", "image/png")
            ct.insert(0, d)
            self.files["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)
        return rid

    def style_names(self):
        st = self.trees.get("word/styles.xml")
        out = {}
        if st is None:
            return out
        for s in st.iter(q("w:style")):
            sid = s.get(q("w:styleId"))
            nm = s.find("w:name", NS)
            out[sid] = nm.get(q("w:val")) if nm is not None else sid
        return out

    def comments(self):
        c = self.trees.get("word/comments.xml")
        out = {}
        if c is None:
            return out
        for cm in c.iter(q("w:comment")):
            txt = " ".join("".join(t.text or "" for t in p.iter(T)) for p in cm.iter(P)).strip()
            out[cm.get(q("w:id"))] = {"author": cm.get(q("w:author")), "text": txt}
        return out


def part_prefix(part):
    m = PART_RE.match(part)
    kind = m.group(1)
    if kind == "document":
        return "P", ""
    num = re.sub(r"\D", "", kind) or "0"
    return ("H" if kind.startswith("header") else "F") + num + "-", ("H" if kind.startswith("header") else "F") + num + "-"


def in_fallback(el):
    return any(a.tag == FALLBACK for a in el.iterancestors())


def nearest(el, tag):
    for a in el.iterancestors():
        if a.tag == tag:
            return a
    return None


# --------------------------------------------------------------------------------------
# Paragraph content model ("atoms")
# --------------------------------------------------------------------------------------
class Atom:
    __slots__ = ("kind", "el", "run", "text", "start", "end", "hl", "comments")

    def __init__(self, kind, el, run, text, hl=None, comments=()):
        self.kind, self.el, self.run, self.text = kind, el, run, text
        self.hl, self.comments = hl, tuple(comments)
        self.start = self.end = 0


def run_highlight(run):
    rpr = run.find("w:rPr", NS)
    if rpr is None:
        return None
    h = rpr.find("w:highlight", NS)
    if h is not None and h.get(q("w:val")) not in (None, "none"):
        return h.get(q("w:val"))
    shd = rpr.find("w:shd", NS)
    if shd is not None and shd.get(q("w:fill")) not in (None, "auto", "FFFFFF", "ffffff"):
        return "shd:" + shd.get(q("w:fill"))
    return None


def paragraph_atoms(p):
    """Ordered atoms of a paragraph (only its own runs - not runs of nested text boxes)."""
    atoms, open_comments = [], []

    def walk(node):
        for ch in node:
            tag = ch.tag
            if tag == R:
                hl = run_highlight(ch)
                for rc in ch:
                    t = rc.tag
                    if t == T:
                        atoms.append(Atom("t", rc, ch, rc.text or "", hl, open_comments))
                    elif t == TAB:
                        atoms.append(Atom("tab", rc, ch, "\t", hl, open_comments))
                    elif t in (BR, CR):
                        atoms.append(Atom("br", rc, ch, "\n", hl, open_comments))
                    elif t == q("w:noBreakHyphen"):
                        atoms.append(Atom("sym", rc, ch, "-", hl, open_comments))
                    elif t == q("w:sym"):
                        atoms.append(Atom("sym", rc, ch, "•", hl, open_comments))
                    elif t in OBJECT_TAGS:
                        atoms.append(Atom("obj", rc, ch, "￼", hl, open_comments))
            elif tag == CRS:
                open_comments.append(ch.get(q("w:id")))
            elif tag == CRE:
                cid = ch.get(q("w:id"))
                if cid in open_comments:
                    open_comments.remove(cid)
            elif tag in SKIP_CONTAINERS or tag == PPR:
                continue
            elif tag in CONTAINERS:
                walk(ch)
    walk(p)
    pos = 0
    for a in atoms:
        a.start = pos
        pos += len(a.text)
        a.end = pos
    return atoms


def para_text(p):
    return "".join(a.text for a in paragraph_atoms(p))


def set_preserve(t_el):
    t_el.set("{%s}space" % XML, "preserve")


def new_run_like(run, text):
    r = etree.Element(R)
    rpr = run.find("w:rPr", NS) if run is not None else None
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = etree.SubElement(r, T)
    t.text = text
    set_preserve(t)
    return r


def run_from_paragraph_mark(p, text):
    """Create a run whose formatting copies the paragraph-mark run properties."""
    r = etree.Element(R)
    ppr = p.find("w:pPr", NS)
    if ppr is not None and ppr.find("w:rPr", NS) is not None:
        rpr = copy.deepcopy(ppr.find("w:rPr", NS))
        rpr.tag = RPR
        for bad in ("w:ins", "w:del", "w:moveFrom", "w:moveTo", "w:rPrChange"):
            for e in rpr.findall(bad, NS):
                rpr.remove(e)
        r.append(rpr)
    t = etree.SubElement(r, T)
    t.text = text
    set_preserve(t)
    return r


def isolate(t_el):
    """Make t_el the only content child of its run (split the run, cloning rPr). Returns its run."""
    run = t_el.getparent()
    kids = [c for c in run if c.tag != RPR]
    idx = kids.index(t_el)
    before, after = kids[:idx], kids[idx + 1:]
    rpr = run.find("w:rPr", NS)
    if after:
        r2 = etree.Element(R)
        if rpr is not None:
            r2.append(copy.deepcopy(rpr))
        for c in after:
            r2.append(c)
        run.addnext(r2)
    if before:
        r0 = etree.Element(R)
        if rpr is not None:
            r0.append(copy.deepcopy(rpr))
        for c in before:
            r0.append(c)
        run.addprevious(r0)
    return run


def drop_empty_runs(p):
    for r in list(p.iter(R)):
        if nearest(r, P) is not p:
            continue
        if not [c for c in r if c.tag != RPR]:
            r.getparent().remove(r)


def strip_highlight(run):
    rpr = run.find("w:rPr", NS)
    if rpr is None:
        return
    for tag in ("w:highlight",):
        for e in rpr.findall(tag, NS):
            rpr.remove(e)
    shd = rpr.find("w:shd", NS)
    if shd is not None:
        rpr.remove(shd)


def replace_span(p, start, end, new_text, unhighlight=False, allow_objects=False):
    """Replace characters [start, end) of the paragraph text with new_text.
    The new text goes into its own run, cloned from the formatting of the run where the span
    starts (or the run just before an insertion point). Returns the new w:t element."""
    atoms = paragraph_atoms(p)
    total = atoms[-1].end if atoms else 0
    if not (0 <= start <= end <= total):
        raise ValueError(f"span {start}-{end} outside paragraph (len {total})")
    # split text atoms at boundaries
    for b in (start, end):
        for a in atoms:
            if a.kind == "t" and a.start < b < a.end:
                cut = b - a.start
                t2 = etree.Element(T)
                t2.text = a.text[cut:]
                set_preserve(t2)
                a.el.text = a.text[:cut]
                set_preserve(a.el)
                a.el.addnext(t2)
                break
        atoms = paragraph_atoms(p)
    inside = [a for a in atoms if a.start >= start and a.end <= end and a.end > a.start]
    if any(a.kind == "obj" for a in inside) and not allow_objects:
        raise ValueError("span covers an image/text box - refusing to delete it")
    prev = [a for a in atoms if a.end <= start and a.end > a.start]
    nxt = [a for a in atoms if a.start >= end and a.end > a.start]
    new_t = etree.Element(T)
    new_t.text = new_text
    set_preserve(new_t)
    if inside:
        anchor = inside[0]
        anchor.el.addprevious(new_t)
        src_run_hl = anchor.hl
    elif prev:
        anchor = prev[-1]
        anchor.el.addnext(new_t)
        src_run_hl = anchor.hl
    elif nxt:
        anchor = nxt[0]
        anchor.el.addprevious(new_t)
        src_run_hl = anchor.hl
    else:
        r = run_from_paragraph_mark(p, new_text)
        ppr = p.find("w:pPr", NS)
        if ppr is not None:
            ppr.addnext(r)
        else:
            p.insert(0, r)
        return r.find("w:t", NS)
    for a in inside:
        a.el.getparent().remove(a.el)
    run = isolate(new_t)
    if unhighlight and src_run_hl:
        strip_highlight(run)
    drop_empty_runs(p)
    return new_t


def apply_format(run, fmt):
    """fmt: {"bold": bool, "italic": bool, "underline": bool} - set or clear on this run only."""
    if not fmt:
        return
    rpr = run.find("w:rPr", NS)
    if rpr is None:
        rpr = etree.Element(RPR)
        run.insert(0, rpr)
    pairs = {"bold": ("w:b", "w:bCs"), "italic": ("w:i", "w:iCs"), "underline": ("w:u",)}
    for key, tags in pairs.items():
        if key not in fmt:
            continue
        for t in tags:
            for e in rpr.findall(t, NS):
                rpr.remove(e)
        if fmt[key]:
            for t in tags:
                e = etree.SubElement(rpr, q(t))
                if t == "w:u":
                    e.set(q("w:val"), "single")


def find_span(p, needle, nth=1):
    text = para_text(p)
    idx, pos = -1, 0
    for _ in range(nth):
        idx = text.find(needle, pos)
        if idx < 0:
            return None
        pos = idx + 1
    return idx, idx + len(needle)


# --------------------------------------------------------------------------------------
# Collect paragraphs and tables with stable IDs
# --------------------------------------------------------------------------------------
class ParaInfo:
    def __init__(self, pid, part, el):
        self.id, self.part, self.el = pid, part, el
        self.twin = None
        self.table = None      # table id
        self.row = self.col = None
        self.textbox = False
        self.numbered = False  # direct w:numPr in the paragraph (engine v3 treats blocks opened here as list loops)
        self.container = None  # parent element


def fallback_twin(p):
    ch = nearest(p, CHOICE)
    if ch is None:
        return None
    alt = ch.getparent()
    fb = alt.find("mc:Fallback", NS)
    if fb is None:
        return None
    cps = [x for x in ch.iter(P)]
    fps = [x for x in fb.iter(P)]
    if len(cps) != len(fps):
        return None
    return fps[cps.index(p)]


def collect(doc):
    paras, tables = [], {}
    for part in doc.parts():
        root = doc.trees[part]
        pre, tpre = part_prefix(part)
        tcount = 0
        tbl_ids = {}
        for tbl in root.iter(TBL):
            if in_fallback(tbl):
                continue
            tcount += 1
            tid = f"{tpre}T{tcount}"
            tbl_ids[tbl] = tid
            tables[tid] = {"id": tid, "part": part, "el": tbl}
        n = 0
        for p in root.iter(P):
            if in_fallback(p):
                continue
            n += 1
            width = 4 if pre == "P" else 3
            pi = ParaInfo(f"{pre}{n:0{width}d}", part, p)
            pi.container = p.getparent()
            inner = None
            for a in p.iterancestors():
                if a.tag in (TC, TXBX):
                    inner = a
                    break
            if inner is not None and inner.tag == TXBX:
                pi.textbox = True
            if inner is not None and inner.tag == TC:
                tc = inner
                tr = tc.getparent()
                tbl = tr.getparent()
                if tbl in tbl_ids:
                    rows = [x for x in tbl if x.tag == TR]
                    cells = [x for x in tr if x.tag == TC]
                    pi.table = tbl_ids[tbl]
                    pi.row = rows.index(tr) + 1
                    pi.col = cells.index(tc) + 1
            pi.twin = fallback_twin(p)
            pi.numbered = has_direct_numbering(p)
            paras.append(pi)
    return paras, tables


def has_direct_numbering(p):
    ppr = p.find("w:pPr", NS) if p is not None and p.tag == P else None
    return ppr is not None and ppr.find("w:numPr", NS) is not None


WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_PX = 9525


def paragraph_drawings(p):
    """Pictures / text boxes that belong to this paragraph's own runs (not nested paragraphs).
    Returns dicts: kind ('picture'|'textbox'|'other'), docPr element, cNvPr element (pictures),
    alt (descr), width/height in px."""
    out = []
    for a in paragraph_atoms(p):
        if a.kind != "obj":
            continue
        el = a.el
        if el.tag == ALTC:  # use the modern (Choice) branch
            ch = el.find("mc:Choice", NS)
            el = ch if ch is not None else el
        docpr = next(el.iter("{%s}docPr" % WP), None)   # the outermost drawing of this run child
        if docpr is None:
            continue
        container = docpr.getparent()
        ext = container.find("{%s}extent" % WP)
        w = h = None
        if ext is not None:
            w = round(int(ext.get("cx", "0")) / EMU_PER_PX)
            h = round(int(ext.get("cy", "0")) / EMU_PER_PX)
        gd = container.find("{%s}graphic/{%s}graphicData" % (A_NS, A_NS))
        pic = gd.find("{%s}pic" % PIC) if gd is not None else None
        wsp = gd.find("{%s}wsp" % WPS) if gd is not None else None
        kind = "picture" if pic is not None else ("textbox" if wsp is not None else "other")
        cnv = pic.find("{%s}nvPicPr/{%s}cNvPr" % (PIC, PIC)) if pic is not None else None
        out.append({"kind": kind, "docPr": docpr, "cNvPr": cnv, "alt": docpr.get("descr") or "",
                    "width": w, "height": h, "anchored": container.tag.endswith("anchor")})
    return out


def placeholder_png(w, h):
    """A neutral grey picture with a darker border - stands in for a sample photo in a template."""
    import struct
    import zlib
    w, h = max(8, int(w or 240)), max(8, int(h or 160))
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            edge = x < 2 or y < 2 or x >= w - 2 or y >= h - 2
            diag = abs(x * h - y * w) < max(w, h) * 1.2 or abs((w - x) * h - y * w) < max(w, h) * 1.2
            c = (150, 150, 150) if edge else ((200, 200, 200) if diag else (228, 228, 228))
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def table_grid(tbl):
    rows = [x for x in tbl if x.tag == TR]
    return [[c for c in r if c.tag == TC] for r in rows]


def cell_paragraphs(tc):
    return [p for p in tc if p.tag == P]
