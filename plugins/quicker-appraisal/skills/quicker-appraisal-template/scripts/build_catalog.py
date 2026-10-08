#!/usr/bin/env python3
"""
Build a variable catalog for a Quicker appraisal form.

Input : JSON saved from the Quicker connector:
        * the FULL form (get_form_template / get_project_form_template -> has "schema") - structure,
          display conditions, units (suffix) and linked fields;
        * replies of get_word_template_variables (--vars, any number of files: the first reply and the
          follow-ups for omittedSections) - the authoritative list of system variables (`general`),
          filters and form variables as the export engine reads them. A file may also hold just
          {"general": [...], "filters": [...]} copied from a reply.
        * fallback: the flat list (get_form_template_schema -> {"items": [...]}).
Output: catalog.json  (machine-readable, used by lint_template.py / make_sample_data.py)
        catalog.md    (compact listing for the model to read while mapping)

Usage:
    python3 build_catalog.py <form.json> <out_dir> [--vars v1.json v2.json ...] [--extra-system extra.json]
    python3 build_catalog.py --vars v1.json [v2.json ...] <out_dir>        # no form JSON at hand

With --vars the variables tool wins: its `general` list replaces the built-in SYSTEM_FIELDS, its filter
list becomes the linter's filter list, and fields it lists that the form JSON lacks are added (and
reported). --extra-system: JSON list of {"path","label","kind","tag"} for any further render-context
variables.
"""
import json, re, sys, os

# ---------------------------------------------------------------------------
# Fields that exist in the render context but NOT in the questionnaire.
# Source: Quicker document-context.js / document-data-loader.js (per product owner).
# ---------------------------------------------------------------------------
SYSTEM_FIELDS = [
    # path, label, kind, tag
    ("p.number", "מספר שומה", "number", "{p.number}"),
    ("p.name", "שם הפרויקט", "text", "{p.name}"),
    ("p.address", "כתובת מלאה", "text", "{p.address}"),
    ("p.city", "עיר", "text", "{p.city}"),
    ("p.street", "רחוב", "text", "{p.street}"),
    ("p.house", "מספר בית", "text", "{p.house}"),
    ("p.neighborhood", "שכונה", "text", "{p.neighborhood}"),
    ("p.gush", "גוש", "text", "{p.gush}"),
    ("p.helka", "חלקה", "text", "{p.helka}"),
    ("p.subHelka", "תת חלקה", "text", "{p.subHelka}"),
    ("p.plot", "מגרש", "text", "{p.plot}"),
    ("p.plotByTaba", "מגרש לפי תב\"ע", "text", "{p.plotByTaba}"),
    ("p.apartmentNumber", "מספר דירה", "text", "{p.apartmentNumber}"),
    ("p.floor", "קומה", "text", "{p.floor}"),
    ("p.rooms", "חדרים", "text", "{p.rooms}"),
    ("p.squareMeter", "שטח במ\"ר", "area", "{p.squareMeter | currency} מ\"ר"),
    ("p.appraisalType", "סוג השומה (פרויקט)", "text", "{p.appraisalType}"),
    ("p.appraisalPurpose", "מטרת השומה (פרויקט)", "text", "{p.appraisalPurpose}"),
    ("p.propertyType", "סוג הנכס (פרויקט)", "text", "{p.propertyType}"),
    ("p.propertyDestiny", "ייעוד הנכס (פרויקט)", "text", "{p.propertyDestiny}"),
    ("p.status", "סטטוס הפרויקט", "text", "{p.status}"),
    ("p.referrer", "מזמין / גורם מפנה (פרויקט)", "text", "{p.referrer}"),
    ("p.referrerReference", "מספר הפניה אצל המזמין", "text", "{p.referrerReference}"),
    ("p.referrerCase", "מספר תיק אצל המזמין", "text", "{p.referrerCase}"),
    ("p.apartmentOwner", "בעלי הדירה", "text", "{p.apartmentOwner}"),
    ("p.dueDate", "תאריך יעד", "date", "{p.dueDate | date}"),
    ("p.determinesDate", "המועד הקובע (פרויקט)", "date", "{p.determinesDate | date}"),
    ("p.visitDate", "מועד הביקור המתוכנן (פרויקט) - לא p.ad.visitDate", "date", "{p.visitDate | date}"),
    ("p.visitContactName", "איש קשר לביקור", "text", "{p.visitContactName}"),
    ("p.visitContactPhone", "טלפון איש קשר לביקור", "text", "{p.visitContactPhone}"),
    ("p.agentName", "שם השמאי", "text", "{p.agentName}"),
    ("c.name", "שם הלקוח הראשי", "text", "{c.name}"),
    ("c.phone", "טלפון הלקוח הראשי", "text", "{c.phone}"),
    ("c.email", "דוא\"ל הלקוח הראשי", "text", "{c.email}"),
    ("c.address", "כתובת הלקוח הראשי", "text", "{c.address}"),
    ("c.city", "עיר הלקוח הראשי", "text", "{c.city}"),
    ("c.personalIdentity", "ת.ז / ח.פ של הלקוח הראשי", "text", "{c.personalIdentity}"),
    ("customers", "כל הלקוחות (לולאה; לכל לקוח name, phone, email, address, city, personalIdentity, isPrimary)", "loop",
     "{#customers}{name}{/customers}"),
    ("today", "תאריך היום (כבר בפורמט DD/MM/YYYY - בלי פילטר date)", "text", "{today}"),
    ("todayISO", "תאריך היום ISO (לעיצוב בפילטר date)", "date", "{todayISO | date}"),
    ("ownerName", "שם הארגון / המשרד", "text", "{ownerName}"),
    ("ownerManagerName", "שם מנהל המשרד (חותם הדוח)", "text", "{ownerManagerName}"),
    ("appraisalHeaderImage", "תמונת כותרת עליונה של הארגון", "image", "{appraisalHeaderImage | maxSize:600:150}"),
    ("appraisalFooterImage", "תמונת כותרת תחתונה של הארגון", "image", "{appraisalFooterImage | maxSize:600:150}"),
    ("appraisalSignatureImage", "חתימת הארגון", "image", "{appraisalSignatureImage | maxSize:220:120}"),
    ("govMapImage", "צילום GovMap של הגוש/חלקה", "image", "{govMapImage | maxSize:500:400}"),
]

CUSTOMER_FIELDS = ["name", "phone", "email", "address", "city", "personalIdentity", "isPrimary"]
DEFAULT_FILTERS = ["date", "currency", "fixed", "list", "includes", "isEmpty", "stripTag", "html", "lower",
                   "maxSize", "frame", "rounded", "align", "gap", "grid", "inc", "loopSep"]

# Raw Quicker field type -> (kind, tag template).  {P} is replaced with the path.
TYPE_RULES = {
    "text":        ("text",     "{P}"),
    "textSod":     ("text",     "{P}"),
    "textPom":     ("text",     "{P}"),
    "read":        ("text",     "{P}"),
    "textarea":    ("textarea", "{P}"),
    "richtext":    ("richtext", "{P | html}"),
    "select":      ("select",   "{P}"),
    "selectOther": ("select",   "{P}"),
    "radio":       ("select",   "{P}"),
    "checkboxList":("multi",    "{P | list:', '}"),
    "checkbox":    ("bool",     "{#P}...{/P}"),
    "boolean":     ("bool",     "{#P}...{/P}"),
    "date":        ("date",     "{P | date}"),
    "number":      ("number",   "{P}"),
    "currency":    ("money",    "{P | currency} ₪"),
    "readNumber":  ("money",    "{P | currency} ₪"),
    "image":       ("image",    "{P | maxSize:500:350}"),
    "html":        ("widget",   "{P}"),
}

PREFIX = "p.ad."

# projectFieldsMap links that must NOT be printed through p.*: the variables tool states that p.visitDate
# (the visit scheduled on the project) and p.ad.visitDate (the form field) are different values.
LINK_EXCEPTIONS = {"visitDate": "p.visitDate is the scheduled visit; the report's visit date is the form field "
                                "p.ad.visitDate (variables tool rule)"}

# Custom UI widgets (type "html") whose stored value is a list of rows. Their row fields are not
# described in the schema; these are the ones known from production templates.
KNOWN_WIDGET_GROUPS = {
    "planDataStatus": [("planNumber", "מספר תכנית", "text"), ("date", "תאריך", "date"),
                       ("mahut", "מהות", "text"), ("status", "סטטוס", "text")],
}


def translate_condition(raw, group_stack):
    """Translate a Quicker UI 'if' (JS) into an easy-template-x angular expression.
    Returns (expr, needs_review)."""
    if not raw:
        return None, False
    s = raw.strip()
    review = False
    s = s.replace("project.additionalDetails.", "p.ad.").replace("project.", "p.")
    s = s.replace("!==", "!=").replace("===", "==")
    # Inside a repeatable group, "p.ad.group[x].field" -> "field" (loop scope)
    s = re.sub(r"p\.ad\.(?:[A-Za-z0-9_]+\[x\]\.)+", "", s)
    # ... and "p.ad.group[0].field" written by the form inside that same group -> the current item's field
    for g in group_stack or []:
        s = re.sub(r"p\.ad\.(?:[A-Za-z0-9_]+\[[0x]\]\.)*" + re.escape(g["name"]) + r"\[0\]\.", "", s)
    # ['a','b'].includes(X)  ->  (X == 'a' || X == 'b')
    def list_includes(m):
        items = re.findall(r"'([^']*)'|\"([^\"]*)\"", m.group(1))
        vals = [a or b for a, b in items]
        target = m.group(2).strip()
        return "(" + " || ".join(f"{target} == '{v}'" for v in vals) + ")"
    s = re.sub(r"\[([^\]]*)\]\s*\.includes\(\s*([A-Za-z0-9_.\[\]]+)\s*\)", list_includes, s)
    # X.includes('v')  ->  (X | includes:'v')
    s = re.sub(r"([A-Za-z_][A-Za-z0-9_.\[\]]*)\.includes\(\s*('[^']*'|\"[^\"]*\")\s*\)",
               lambda m: f"({m.group(1)} | includes:{m.group(2)})", s)
    if re.search(r"\.includes\(|\bfilter\s*:|\[x\]|=>|\bfunction\b", s):
        review = True
    s = re.sub(r"\s+", " ", s).strip()
    return s, review


def kind_and_tag(ftype, path, suffix=None, limit=None):
    kind, tpl = TYPE_RULES.get(ftype, ("text", "{P}"))
    tag = tpl.replace("P", path)
    if kind == "money" and suffix and "ר" in suffix:  # square meters, not shekels
        kind = "area"
        tag = "{" + path + " | currency} מ\"ר"
    if kind == "image" and limit and int(limit) > 1:
        kind = "images"
    return kind, tag


def from_full(form):
    schema = form.get("schema") or {}
    sections_meta = (form.get("metadata") or {}).get("sections") or {}
    fields, groups = [], []

    def add_field(f, section, sub, stack, inherited_if):
        name = f.get("name")
        if not name:
            return
        if f.get("type") == "html" and name in KNOWN_WIDGET_GROUPS and not stack:
            cond, review = translate_condition(f.get("if"), stack)
            g = {"path": PREFIX + name, "name": name, "label": f.get("label") or sub or name, "section": section,
                 "parent": None, "if_raw": f.get("if"), "if_tpl": cond or inherited_if, "if_needs_review": review,
                 "fields": [x[0] for x in KNOWN_WIDGET_GROUPS[name]], "subgroups": [], "widget": True}
            groups.append(g)
            for fname, flabel, ftype in KNOWN_WIDGET_GROUPS[name]:
                kind, tag = kind_and_tag(ftype, fname)
                fields.append({"path": fname, "name": fname, "label": flabel, "type": ftype, "kind": kind,
                               "section": section, "subsection": sub, "loop": g["path"],
                               "full_path": f"{name}.{fname}", "options": [], "suffix": None, "limit": None,
                               "if_raw": None, "if_tpl": None, "if_needs_review": False,
                               "group_if_tpl": None, "tag": tag})
            return
        if f.get("type") == "html" and not f.get("label") and f.get("customHtml"):
            pass
        ftype = f.get("type", "text")
        if stack:
            path = name                       # inside a loop -> bare name
            loop = stack[-1]["path"]
        else:
            path = PREFIX + name
            loop = None
        kind, tag = kind_and_tag(ftype, path, f.get("suffix"), f.get("limit"))
        cond, review = translate_condition(f.get("if"), stack)
        fields.append({
            "path": path, "name": name, "label": f.get("label", ""), "type": ftype, "kind": kind,
            "section": section, "subsection": sub, "loop": loop,
            "full_path": ".".join([g["name"] for g in stack] + [name]) if stack else path,
            "options": f.get("values") or [], "suffix": f.get("suffix"), "limit": f.get("limit"),
            "if_raw": f.get("if"), "if_tpl": cond, "if_needs_review": review,
            "group_if_tpl": inherited_if, "tag": tag,
        })

    def walk(items, section, sub, stack, inherited_if):
        for it in items:
            if "fields" in it and isinstance(it["fields"], list) and "type" not in it:
                g_sub = it.get("title") or it.get("subTitle") or sub
                cond, review = translate_condition(it.get("if"), stack)
                if it.get("repeatable") and it.get("groupName"):
                    gname = it["groupName"]
                    gpath = (PREFIX + gname) if not stack else gname
                    g = {"path": gpath, "name": gname, "label": g_sub or gname, "section": section,
                         "parent": stack[-1]["path"] if stack else None, "if_raw": it.get("if"),
                         "if_tpl": cond, "if_needs_review": review,
                         "fields": [x.get("name") for x in it["fields"] if x.get("name")],
                         "subgroups": [x.get("groupName") for x in it["fields"] if x.get("repeatable")]}
                    groups.append(g)
                    walk(it["fields"], section, g_sub, stack + [g], cond)
                else:
                    walk(it["fields"], section, g_sub, stack, cond or inherited_if)
            else:
                add_field(it, section, sub, stack, inherited_if)

    for sec_key, items in schema.items():
        if sec_key.startswith("_") or not isinstance(items, list):
            continue
        title = (sections_meta.get(sec_key) or {}).get("title") or sec_key
        walk(items, title, None, [], None)
    return fields, groups


def from_flat(data):
    """Fallback for get_form_template_schema output ({items:[...]})."""
    fields, groups = [], []
    flat_map = {"text": "text", "number": "number", "select": "select", "date": "date",
                "boolean": "checkbox", "array": "array"}

    def walk(items, stack):
        for f in items:
            name, t = f["name"], f.get("type")
            help_ = f.get("help", "")
            m = re.search(r"\[([^\]]+)\]", help_)
            section = m.group(1) if m else ""
            spec = f.get("spec") or {}
            sub = spec.get("spec") if isinstance(spec, dict) else None
            if t == "array" and sub:
                gpath = (PREFIX + name) if not stack else name
                g = {"path": gpath, "name": name, "label": f.get("label", name), "section": section,
                     "parent": stack[-1]["path"] if stack else None, "if_raw": None, "if_tpl": None,
                     "if_needs_review": False, "fields": [x["name"] for x in sub], "subgroups": []}
                groups.append(g)
                walk(sub, stack + [g])
                continue
            raw_t = "checkboxList" if t == "array" else ("textarea" if f.get("multiline") else flat_map.get(t, "text"))
            path = name if stack else PREFIX + name
            kind, tag = kind_and_tag(raw_t, path)
            cm = re.search(r"תנאי הצגה ב-Quicker:\s*(.+?)\s*\(Make", help_)
            cond, review = translate_condition(cm.group(1) if cm else None, stack)
            fields.append({"path": path, "name": name, "label": f.get("label", ""), "type": raw_t,
                           "kind": kind, "section": section, "subsection": None,
                           "loop": stack[-1]["path"] if stack else None, "full_path": path,
                           "options": [o.get("value") for o in f.get("options", [])],
                           "suffix": None, "limit": None, "if_raw": cm.group(1) if cm else None,
                           "if_tpl": cond, "if_needs_review": review, "group_if_tpl": None, "tag": tag})
    walk(data.get("items", []), [])
    return fields, groups


# ---------------------------------------------------------------------------
# get_word_template_variables replies
# ---------------------------------------------------------------------------
def load_vars(paths):
    """Merge one or more replies of get_word_template_variables (or partial files holding some keys)."""
    out = {"form": None, "general": [], "filters": [], "rules": [], "sections": []}
    seen_sections = set()
    for path in paths:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d, list):                      # a bare list = the `general` array
            d = {"general": d}
        out["form"] = out["form"] or d.get("form")
        if d.get("general"):
            out["general"] = d["general"]
        if d.get("filters"):
            out["filters"] = d["filters"]
        if d.get("rules"):
            out["rules"] = d["rules"]
        for sec in d.get("formVariables") or []:
            if sec.get("section") not in seen_sections:
                seen_sections.add(sec.get("section"))
                out["sections"].append(sec)
        if d.get("omittedSections"):
            out.setdefault("omitted", set()).update(d["omittedSections"])
    out["omitted"] = sorted(set(out.get("omitted", set())) - seen_sections)
    return out


def vars_kind_and_tag(v, path):
    t = v.get("type", "text")
    kind, tag = kind_and_tag(t, path)
    if v.get("syntax") and t not in ("loop", "checkbox", "boolean"):
        tag = v["syntax"]
        if kind == "money" and "₪" not in tag:
            tag += " ₪"
    return t, kind, tag


def from_vars(vs):
    """Fields and groups from formVariables (used when no form JSON is available)."""
    fields, groups = [], []

    def walk(variables, section, stack):
        for v in variables:
            raw = v.get("path")
            if not raw:
                continue                              # nameless schema items (separators) - not data
            name = raw.split(".")[-1] if not stack else raw
            if v.get("type") == "loop":
                gpath = raw if not stack else raw
                g = {"path": gpath, "name": name, "label": v.get("label", name).replace("לולאה מקוננת: ", "").replace("לולאה: ", ""),
                     "section": section, "parent": stack[-1]["path"] if stack else None, "if_raw": None,
                     "if_tpl": None, "if_needs_review": False,
                     "fields": [x.get("path") for x in v.get("fields", []) if x.get("path") and x.get("type") != "loop"],
                     "subgroups": [x.get("path") for x in v.get("fields", []) if x.get("type") == "loop"]}
                groups.append(g)
                walk(v.get("fields", []), section, stack + [g])
                continue
            t, kind, tag = vars_kind_and_tag(v, raw)
            fields.append({"path": raw, "name": name, "label": v.get("label", ""), "type": t, "kind": kind,
                           "section": section, "subsection": None, "loop": stack[-1]["path"] if stack else None,
                           "full_path": raw, "options": v.get("options") or [], "suffix": None, "limit": None,
                           "if_raw": None, "if_tpl": None, "if_needs_review": False, "group_if_tpl": None,
                           "tag": tag})
    for sec in vs["sections"]:
        walk(sec.get("variables", []), sec.get("title") or sec.get("section"), [])
    return fields, groups


def vars_system(general):
    system = []
    for v in general:
        path = v.get("path")
        if not path:
            continue
        t = v.get("type", "text")
        if t == "loop":
            sub = [x.get("path") for x in v.get("fields", []) if x.get("path")]
            system.append({"path": path, "label": f"{v.get('label', path)} (לכל פריט: {', '.join(sub)})",
                           "kind": "loop", "tag": v.get("syntax") or "{#" + path + "}...{/" + path + "}",
                           "fields": sub})
            continue
        kind, tag = kind_and_tag(t, path)
        if t == "image":
            kind = "image"
        tag = v.get("syntax") or tag
        if kind == "bool":
            tag = "{#" + path + "}...{/" + path + "}"
        system.append({"path": path, "label": v.get("label", ""), "kind": kind, "tag": tag})
    return system


def cross_check(fields, groups, vs_fields, vs_groups):
    """Compare form-JSON catalog with the variables tool. Returns (added_fields, added_groups, notes)."""
    have_f = {(f["loop"], f["name"]) for f in fields}
    have_g = {g["path"] for g in groups}
    vs_have_f = {(f["loop"], f["name"]) for f in vs_fields}
    vs_have_g = {g["path"] for g in vs_groups}
    add_g = [g for g in vs_groups if g["path"] not in have_g]
    add_f = [f for f in vs_fields if (f["loop"], f["name"]) not in have_f
             and not (f["loop"] is None and f["path"] in have_g)]     # widget groups the tool lists as html
    notes = []
    for f in add_f:
        notes.append(f"only in variables tool: {f['loop'] + ' > ' if f['loop'] else ''}{f['path']} [{f['type']}]")
    for g in add_g:
        notes.append(f"only in variables tool: loop {g['path']}")
    covered = {f["section"] for f in vs_fields} | {g["section"] for g in vs_groups}
    widget_loops = {g["path"] for g in groups if g.get("widget")}
    for f in fields:
        if f["section"] in covered and (f["loop"], f["name"]) not in vs_have_f and f["kind"] != "widget" \
                and f["loop"] not in widget_loops:
            notes.append(f"not in variables tool (engine may not see it): {f['loop'] + ' > ' if f['loop'] else ''}{f['path']}")
    for g in groups:
        if g["section"] in covered and g["path"] not in vs_have_g and not g.get("widget"):
            notes.append(f"loop not in variables tool: {g['path']}")
    # option lists that differ
    vs_by = {(f["loop"], f["name"]): f for f in vs_fields}
    for f in fields:
        v = vs_by.get((f["loop"], f["name"]))
        if v and v["options"] and f["options"] and [str(x) for x in v["options"]] != [str(x) for x in f["options"]]:
            notes.append(f"options differ for {f['path']}: using the variables tool's list")
            f["options"] = v["options"]
    return add_f, add_g, notes


def main():
    args = sys.argv[1:]
    extra = []
    if "--extra-system" in args:
        i = args.index("--extra-system")
        extra = json.load(open(args[i + 1], encoding="utf-8"))
        del args[i:i + 2]
    var_files = []
    if "--vars" in args:
        i = args.index("--vars")
        j = i + 1
        while j < len(args) and not args[j].startswith("--"):
            j += 1
        var_files = args[i + 1:j]
        del args[i:j]
        # the last positional left after the files may be the out dir: `--vars a.json b.json out/`
        if var_files and len(args) == 0 and not var_files[-1].endswith(".json"):
            args = [var_files.pop()]
    vs = load_vars(var_files) if var_files else None
    if len(args) == 2:
        src, out_dir = args
    elif len(args) == 1 and vs:
        src, out_dir = None, args[0]
    else:
        sys.exit("usage: build_catalog.py <form.json> <out_dir> [--vars v1.json ...] [--extra-system x.json]\n"
                 "       build_catalog.py --vars v1.json [v2.json ...] <out_dir>")
    os.makedirs(out_dir, exist_ok=True)
    data = json.load(open(src, encoding="utf-8")) if src else {}
    if isinstance(data, dict) and ("formVariables" in data or "general" in data) and "schema" not in data:
        vs = load_vars([src] + var_files)              # the "form" given is itself a variables reply
        data = {}
    notes = []
    if isinstance(data, dict) and "schema" in data:
        fields, groups = from_full(data)
        form = {k: data.get(k) for k in ("id", "name", "title", "isSystem", "isDefault", "version")}
        source = "full"
    elif isinstance(data, dict) and "items" in data:
        fields, groups = from_flat(data)
        form = {"title": "(flat schema)"}
        source = "flat"
    elif vs:
        fields, groups = from_vars(vs)
        form = {k: (vs.get("form") or {}).get(k) for k in ("id", "name", "title")}
        source = "variables-tool"
    else:
        sys.exit("Unrecognised form JSON - expected get_form_template output (with 'schema'), "
                 "get_word_template_variables output (--vars) or get_form_template_schema output (with 'items').")
    if vs and source != "variables-tool" and vs["sections"]:
        vf, vg = from_vars(vs)
        add_f, add_g, notes = cross_check(fields, groups, vf, vg)
        groups += add_g
        fields += add_f
        source += "+variables-tool"
    if vs and source not in ("variables-tool",) and not vs["sections"]:
        notes.append("cross-check with the variables tool not run (no formVariables in the --vars files) - "
                     "compare the replies you read with this catalog by eye for the fields you use")
    if vs and vs.get("omitted"):
        notes.append("variables tool reply incomplete - sections still omitted: " + ", ".join(vs["omitted"]))

    if vs and vs["general"]:
        system = vars_system(vs["general"])
        system_source = "variables-tool"
    else:
        system = [{"path": p, "label": l, "kind": k, "tag": t} for p, l, k, t in SYSTEM_FIELDS]
        system_source = "built-in"
    for x in system:
        if x["path"] == "customers" and not x.get("fields"):
            x["fields"] = CUSTOMER_FIELDS
    known = {x["path"] for x in system}
    # Linked fields: metadata.projectFieldsMap maps a project field (p.<key>) to a form path. House rule:
    # print linked values through p.<key>.
    links = ((data.get("metadata") or {}).get("projectFieldsMap") or {}) if isinstance(data, dict) else {}
    by_top = {f["name"]: f for f in fields if not f["loop"]}
    for pkey, fpath in links.items():
        ppath = "p." + pkey
        if pkey in LINK_EXCEPTIONS:
            notes.append(f"{ppath} is linked to '{fpath}' but is NOT used for it: {LINK_EXCEPTIONS[pkey]}")
            continue
        m = re.fullmatch(r"(\w+)\[0\]\.(\w+)", fpath)
        src_f = None
        if m:
            gpath = PREFIX + m.group(1)
            src_f = next((f for f in fields if f["loop"] == gpath and f["name"] == m.group(2)), None)
            if src_f:
                src_f["linked_first_row"] = ppath
        elif fpath in by_top:
            src_f = by_top[fpath]
            src_f["linked"] = ppath
            src_f["tag_form"] = src_f["tag"]
            src_f["tag"] = src_f["tag"].replace(src_f["path"], ppath)
        if not src_f:
            notes.append(f"projectFieldsMap: {ppath} -> '{fpath}', but the form has no such field - "
                         f"{ppath} is not filled from the questionnaire")
        if ppath not in known:
            kind, tag = kind_and_tag(src_f["type"], ppath, src_f.get("suffix")) if src_f else ("text", "{" + ppath + "}")
            system.append({"path": ppath, "label": (src_f["label"] if src_f else pkey) + " (שדה מקושר)", "kind": kind, "tag": tag})
            known.add(ppath)
        else:
            for x in system:
                if x["path"] == ppath and src_f:
                    x["label"] += f" - מקושר לשאלון: {fpath}"
                    if src_f.get("kind") == "area" and x["kind"] in ("number", "money", "text"):
                        x["kind"], x["tag"] = "area", "{" + ppath + " | currency} מ\"ר"
    for x in extra:
        if x.get("path") and x["path"] not in known:
            system.append({"path": x["path"], "label": x.get("label", ""), "kind": x.get("kind", "text"),
                           "tag": x.get("tag") or "{" + x["path"] + "}"})
    for g in groups:
        if g.get("parent") and g["parent"].split(".")[-1] == g["name"]:
            notes.append(f"form: group '{g['name']}' ({g['label']}) is nested in a group with the SAME name - inside the "
                         f"outer loop, {{#{g['name']}}} opens the inner one; check the structure in form.json")
    filters = [f.get("name") if isinstance(f, dict) else f for f in (vs or {}).get("filters", [])]
    filters = [f for f in filters if f] or DEFAULT_FILTERS
    filters_source = "variables-tool" if vs and vs.get("filters") else "built-in"
    catalog = {"form": form, "source": source, "system_source": system_source, "system_fields": system,
               "filters": filters, "filters_source": filters_source, "rules": (vs or {}).get("rules", []),
               "fields": fields, "groups": groups, "notes": notes}
    json.dump(catalog, open(os.path.join(out_dir, "catalog.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- compact markdown for the model -------------------------------------------------
    L = []
    L.append(f"# Variable catalog - {form.get('title')} ({form.get('name')}, id {form.get('id')})")
    L.append(f"source: {source} | system variables: {system_source} | {len(fields)} questionnaire fields | "
             f"{len(groups)} repeatable groups\n")
    if notes:
        L.append("## Notes - check before mapping")
        L += [f"- {n}" for n in notes]
        L.append("")
    L.append("Legend: `shown-if` = the field's own display condition | `block-if` = the condition of the form block "
             "it sits in | `group condition` = the condition of a repeatable group | `LINKED` = print through p.* | "
             "(REVIEW) = translate by hand\n")
    L.append("## System fields (outside the questionnaire)")
    for s in system:
        L.append(f"- `{s['tag']}` - {s['label']}")
    L.append(f"\n## Filters ({filters_source}) - any other filter renders the tag EMPTY")
    L.append(", ".join(f"`{f}`" for f in filters))
    if catalog["rules"]:
        L.append("\n## Engine rules (variables tool)")
        L += [f"- {r}" for r in catalog["rules"]]
    cur, cur_loop = None, None
    gmap = {g["path"]: g for g in groups}
    depth = {}
    for g in groups:
        d, p = 0, g.get("parent")
        seen = {g["path"]}
        while p and p not in seen and d < 6:
            seen.add(p)
            d += 1
            p = gmap.get(p, {}).get("parent")
        if p and p in seen and p == g["path"]:
            d += 1  # group nested in a same-named group (exists in Quicker forms)
        depth[g["path"]] = d
    printed_loops = set()
    for f in fields:
        if f["section"] != cur:
            cur = f["section"]
            L.append(f"\n## {cur}")
        if f["loop"] != cur_loop:
            cur_loop = f["loop"]
            if cur_loop:
                g = gmap.get(cur_loop, {})
                ind = "  " * depth.get(cur_loop, 0)
                if cur_loop in printed_loops:
                    L.append(f"{ind}### (continued) loop `{{#{g.get('path')}}}` - {g.get('label') or g.get('name')}")
                else:
                    printed_loops.add(cur_loop)
                    cond = f" | group condition: `{g.get('if_tpl')}`" if g.get("if_tpl") else ""
                    parent = f" | nested in `{g.get('parent')}`" if g.get("parent") else ""
                    L.append(f"{ind}### loop `{{#{g.get('path')}}}...{{/{g.get('path')}}}` - "
                             f"{g.get('label') or g.get('name')}{parent}{cond}")
        indent = "  " * (depth.get(f["loop"], 0) + 1) if f["loop"] else ""
        extra = []
        if f["options"]:
            extra.append("options: " + json.dumps([str(o) for o in f["options"]], ensure_ascii=False))
        if f["if_tpl"]:
            extra.append(f"shown-if: `{f['if_tpl']}`" + (" (REVIEW)" if f["if_needs_review"] else ""))
        elif f.get("group_if_tpl") and not f["loop"]:
            extra.append(f"block-if: `{f['group_if_tpl']}`")
        if f.get("linked"):
            extra.insert(0, f"LINKED - use {f['linked']} (questionnaire copy: {f['path']})")
        if f.get("linked_first_row"):
            extra.insert(0, f"first row also available as {f['linked_first_row']}")
        L.append(f"{indent}- `{f['tag']}` - {f['label'] or '(' + f['name'] + ')'} [{f['type']}]"
                 + (" | " + " | ".join(extra) if extra else ""))
    open(os.path.join(out_dir, "catalog.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"catalog: {len(fields)} fields, {len(groups)} groups, {len(system)} system fields ({system_source}), "
          f"{len(filters)} filters ({filters_source}) -> {out_dir}")
    for n in notes[:30]:
        print("note:", n)
    if len(notes) > 30:
        print(f"note: ... {len(notes) - 30} more in catalog.md")
    rev = [f["path"] for f in fields if f["if_needs_review"]] + [g["path"] for g in groups if g["if_needs_review"]]
    if rev:
        print("conditions that could not be auto-translated (write by hand):", ", ".join(rev))


if __name__ == "__main__":
    main()
