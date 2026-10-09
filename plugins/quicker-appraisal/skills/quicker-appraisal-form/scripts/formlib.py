"""
Shared helpers for the quicker-appraisal-form scripts: load a Quicker appraisal form as the
connector returns it, walk its fields and groups the way the server does, and compare Hebrew
labels loosely.

A form (get_form_template) is:
    schema   = { <sectionKey>: [ row, ... ], "_aiDefaults": {...} }
    row      = { fields: [node, ...], if?, title?, ... }           a plain row
             | { repeatable: true, groupName, title?, fields: [...] }  a group row
    node     = { name, type, label, values?, if?, systemPath?, aiConfig?, hidden?, ... }   a field
             | { repeatable: true, groupName, subTitle?, fields: [...] }                   a nested group
    metadata = { sections: {key: {title, icon, aiConfig?}}, formGroups: {tabs: [...]},
                 projectFieldsMap: {projectColumn: formPath}, ... }

A node's data key is its groupName (groups) or name (fields). additionalDetails (`p.ad`) is ONE flat
object for the whole form, so top-level keys must be unique across all sections. Paths join keys with
dots: "squareMeter", "borrowers.borrowerName", "perutNesachTabo.nesachTaboOwner.nesachTaboName".
"""
import json
import re
import unicodedata

# Project columns whose options are the organization's own lists (הגדרות ← אפשרויות בחירה ← אפשרויות בחירה בפרטי פרויקט).
# Mirrors server/shared/project/form-option-lists.js (October 2026).
ORG_LIST_BY_COLUMN = {
    "referrer": "referrerOptions",
    "appraisalPurpose": "appraisalPurposeOptions",
    "propertyType": "propertyTypeOptions",
    "propertyDestiny": "propertyDestinyOptions",
    "appraisalType": "appraisalTypeOptions",
}

# Bindings a new field may carry (server/utils/form-sync-fields.js, October 2026).
SYNCABLE_PROJECT_FIELDS = {
    "name", "city", "street", "house", "apartmentNumber", "neighborhood",
    "gush", "helka", "subHelka", "plot", "plotByTaba", "floor", "rooms", "squareMeter",
    "appraisalType", "appraisalPurpose", "propertyType", "propertyDestiny",
    "referrer", "referrerCase", "referrerReference", "apartmentOwner",
    "dueDate", "determinesDate", "visitDate",
}
CUSTOMER_FIELDS = {"name", "phone", "email", "address", "city", "personalIdentity"}
VIRTUAL_PATHS = {"p.agentName", "today"}

TYPE_LABELS_HE = {
    "text": "טקסט", "textarea": "טקסט ארוך", "richtext": "טקסט מעוצב", "number": "מספר",
    "currency": "סכום / כמות", "date": "תאריך", "select": "בחירה מרשימה",
    "selectOther": "בחירה מרשימה + ערך חופשי", "radio": "כפתורי בחירה", "checkbox": "תיבת סימון",
    "checkboxList": "בחירה מרובה", "image": "תמונות", "textPom": "טקסט + כפתורי % / מ\"ר",
    "textSod": "טקסט + כפתורי מקור נתון", "read": "לקריאה בלבד", "readNumber": "חישוב",
    "html": "תוכן קבוע",
}


def is_allowed_system_path(value):
    if not isinstance(value, str):
        return False
    if value in VIRTUAL_PATHS:
        return True
    m = re.match(r"^([pc])\.([A-Za-z][A-Za-z0-9]*)$", value)
    if not m:
        return False
    return (m.group(2) in SYNCABLE_PROJECT_FIELDS) if m.group(1) == "p" else (m.group(2) in CUSTOMER_FIELDS)


# --------------------------------------------------------------------------- loading
def _parse_text(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [0])
        return json.loads(text[start:])


def load_json_any(path):
    """JSON as a tool returned it: the object itself, or an MCP reply wrapping it as text."""
    with open(path, encoding="utf-8") as f:
        data = _parse_text(f.read())
    if isinstance(data, dict) and isinstance(data.get("content"), list):
        data = data["content"]
    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("type") == "text":
        data = _parse_text(data[0].get("text", ""))
    if isinstance(data, dict) and isinstance(data.get("structuredContent"), dict):
        data = data["structuredContent"]
    return data


def load_form(path):
    data = load_json_any(path)
    if isinstance(data, dict) and "template" in data and isinstance(data["template"], dict) and "schema" in data["template"]:
        data = data["template"]
    if not isinstance(data, dict) or not isinstance(data.get("schema"), dict):
        raise SystemExit(f"{path}: not a form - expected the JSON of get_form_template (with schema and metadata)")
    data.setdefault("metadata", {})
    data["metadata"] = data["metadata"] or {}
    return data


# --------------------------------------------------------------------------- walking
def section_keys(schema):
    return [k for k, v in (schema or {}).items() if not k.startswith("_") and isinstance(v, list)]


def key_of(node):
    if not isinstance(node, dict):
        return None
    if node.get("repeatable"):
        return node.get("groupName") or node.get("name")
    return node.get("name")


def label_of(node):
    if not isinstance(node, dict):
        return ""
    return node.get("label") or node.get("title") or node.get("subTitle") or key_of(node) or ""


def section_title(metadata, key):
    return ((metadata or {}).get("sections") or {}).get(key, {}).get("title") or key


def tabs_of(form):
    """Tabs with their sections; sections no tab lists come last in a pseudo-tab (the page hides them)."""
    md = form.get("metadata") or {}
    tabs = [t for t in ((md.get("formGroups") or {}).get("tabs") or []) if isinstance(t, dict)]
    keys = section_keys(form["schema"])
    listed = {s for t in tabs for s in (t.get("sections") or [])}
    out = [{"key": t.get("key"), "title": t.get("title") or t.get("key"),
            "sections": [s for s in (t.get("sections") or []) if s in keys]} for t in tabs]
    orphans = [k for k in keys if k not in listed]
    if orphans:
        out.append({"key": None, "title": "(לא בלשונית - לא מוצג בטופס)", "sections": orphans})
    return out


def walk(schema):
    """
    Yield one dict per node that has a data key, depth first in form order:
        path, key, kind ('field'|'group'), node, section, depth (groups from the top, this one
        included), parent (path or None), top (bool: a top-level additionalDetails key),
        row_group (bool), row_if (the condition of the plain row holding a top-level field)
    """
    for section in section_keys(schema):
        for row in schema[section]:
            if not isinstance(row, dict):
                continue
            if row.get("repeatable"):
                yield from _walk_node(row, section, None, 0, True, None)
            else:
                for node in row.get("fields") or []:
                    yield from _walk_node(node, section, None, 0, False, row.get("if"))


def _walk_node(node, section, parent, depth, row_group, row_if):
    key = key_of(node)
    if not key:
        return
    path = f"{parent}.{key}" if parent else key
    is_group = bool(node.get("repeatable"))
    d = depth + 1 if is_group else depth
    yield {"path": path, "key": key, "kind": "group" if is_group else "field", "node": node,
           "section": section, "depth": d, "parent": parent, "top": parent is None,
           "row_group": row_group and parent is None, "row_if": row_if}
    if is_group:
        for child in node.get("fields") or []:
            yield from _walk_node(child, section, path, d, False, None)


def org_list_of(info, metadata):
    """The organization option list a field shows (its options are edited in settings), or None."""
    node = info["node"]
    if node.get("valuesSource"):
        return node["valuesSource"]
    if not info["top"]:
        return None
    sp = node.get("systemPath")
    if isinstance(sp, str) and sp.startswith("p."):
        return ORG_LIST_BY_COLUMN.get(sp[2:])
    for column, target in ((metadata or {}).get("projectFieldsMap") or {}).items():
        if target == info["key"] and column in ORG_LIST_BY_COLUMN:
            return ORG_LIST_BY_COLUMN[column]
    return None


def bindings(metadata):
    """projectFieldsMap as {formPath: projectColumn} (the form field <-> project column links)."""
    out = {}
    for column, target in ((metadata or {}).get("projectFieldsMap") or {}).items():
        if isinstance(target, str):
            out.setdefault(target, []).append(column)
    return out


def options_of(node):
    vals = node.get("values")
    if not isinstance(vals, list):
        return []
    out = []
    for v in vals:
        if isinstance(v, dict):
            v = v.get("value", v.get("label"))
        if v not in (None, ""):
            out.append(str(v))
    return out


# --------------------------------------------------------------------------- Hebrew matching
_NIQQUD = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})
_PREFIXES = ("וה", "שה", "בה", "לה", "מה", "כש", "ה", "ו", "ב", "ל", "מ", "ש", "כ")
_STOP = {"של", "את", "על", "עם", "או", "גם", "כל", "לפי", "בנכס", "הנכס", "נכס", "the", "of", "and"}
SYNONYMS = [
    # Words appraisers use interchangeably in labels. Each set is folded to its first word.
    {"שטח", "גודל"}, {"מספר", "מס", "מסי"}, {"תאריך", "מועד"}, {"שווי", "ערך"},
    {"בעלים", "בעל", "בעלי"}, {"חוכר", "חוכרים"}, {"לווה", "לווים"}, {"היתר", "היתרים", "היתרי"},
    {"תכנית", "תוכנית", "תכניות", "תוכניות", "תבע"}, {"מטבח", "מטבחים"}, {"ריצוף", "רצפה"},
    {"משכנתא", "משכנתה", "משכנתאות"}, {"שמאי", "השמאי"}, {"מזמין", "המזמין"},
]
_SYN = {}
for group in SYNONYMS:
    head = sorted(group)[0]
    for w in group:
        _SYN[w] = head


def norm(text):
    """Lowercase, no niqqud/punctuation/quotes, final letters folded."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _NIQQUD.sub("", text).translate(_FINALS).lower()
    text = re.sub(r"[\"'״׳`]", "", text)
    text = re.sub(r"[^\wא-ת]+", " ", text)
    return " ".join(text.split())


def tokens(text):
    """Normalized words of a label, synonyms folded, filler words dropped."""
    out = []
    for t in norm(text).split():
        if t in _STOP:
            continue
        out.append(_SYN.get(t, t))
    return out


def _stems(t):
    """A word and the word without one leading prefix (ה, ו, ב, ל, מ, ש, כ, וה...)."""
    out = {t}
    if re.match(r"^[\u05D0-\u05EA]+$", t):
        for p in _PREFIXES:
            if t.startswith(p) and len(t) - len(p) >= 3:
                out.add(_SYN.get(t[len(p):], t[len(p):]))
    return out


def _same_word(a, b):
    return a == b or bool(_stems(a) & _stems(b)) and (a in _stems(b) or b in _stems(a))


def camel_words(name):
    return " ".join(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name or "")).lower()


def similarity(a, b):
    """0..1 - word overlap of two labels (Dice; a word matches with or without one Hebrew prefix),
    with a floor of 0.75 when one label contains the other."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    used, hits = set(), 0
    for x in ta:
        for j, y in enumerate(tb):
            if j not in used and _same_word(x, y):
                used.add(j)
                hits += 1
                break
    score = 2 * hits / (len(ta) + len(tb))
    na, nb = norm(a), norm(b)
    if na and nb and min(len(na), len(nb)) >= 4 and (na in nb or nb in na):
        score = max(score, 0.75)
    return round(score, 3)
