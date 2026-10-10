#!/usr/bin/env python3
"""
Check a list of form-change operations against the form BEFORE calling plan_form_template_changes,
and write the Hebrew preview the user reviews.

Usage:
    python3 check_ops.py form.json work/ops.json [--md work/preview.md] [--payload work/payload.json]

form.json  - get_form_template reply (the form the ops will be planned on)
ops.json   - either a list of ops, or {"templateId": "...", "note": "...", "ops": [...],
             "why": {"<op index or path>": "Hebrew reason shown in the preview"}}

The script replays the ops in order on a copy of the form (so a later op may use a field an earlier
op added), the way the server engine does, and reports per op:
    OK    the server should accept it
    WARN  accepted, but look again (missing AI prompt, likely unit, possible duplicate field...)
    ERR   the server will reject it - fix before planning (a rejected op rejects the whole plan)
Exit code: 0 = no errors, 1 = errors.

After the ops, the display logic of the fields the plan touches is audited on the resulting form
(formlogic.py - the same checks as audit_form.py): a detail shown for every answer of its question, a
condition comparing to an option that doesn't exist, a negated condition, a broken chain. Those are
WARN on the op that touched the field; findings the form already had are marked as such. The preview
gets a "מפת התנאים" section: what each answer of the questions involved shows.

The server (plan_form_template_changes) stays the authority: only it knows how many projects hold
data in a field and which Word templates read it, so removals and option removals are only WARN here.
Rules mirror the Quicker engine as of October 2026 (server/controllers/form-template-ops.js).
"""
import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formlib import (ORG_LIST_BY_COLUMN, TYPE_LABELS_HE, is_allowed_system_path, key_of, label_of,  # noqa: E402
                     load_form, load_json_any, norm, section_keys, section_title, similarity, walk)
from formlib import options_of  # noqa: E402
from formlogic import NARRATIVE, audit, is_gate, matrix, reads, value_tests, visibility_conds  # noqa: E402

OPS = ["set_form_props", "add_section", "add_field", "add_group", "update_field", "add_options",
       "remove_options", "move_field", "hide_field", "show_field", "remove_field", "update_row", "update_section"]
MAX_OPS = 60
NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
RESERVED = {"true", "false", "null", "undefined", "this", "constructor", "prototype", "project", "toString",
            "valueOf", "hasOwnProperty", "isPrototypeOf", "length", "x", "y", "z", "i"}
FORBIDDEN_MEMBERS = {"constructor", "__proto__", "prototype", "__defineGetter__", "__defineSetter__",
                     "__lookupGetter__", "__lookupSetter__", "valueOf", "toString", "toLocaleString",
                     "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "call", "apply", "bind"}
AGENT_TYPES = ["text", "textarea", "richtext", "number", "currency", "date", "select", "selectOther", "radio",
               "checkbox", "checkboxList", "image", "textPom", "textSod"]
NEEDS_VALUES = {"select", "selectOther", "radio", "checkboxList"}
TYPE_CONVERSIONS = {"text": ["textarea", "textSod", "textPom"], "textSod": ["text", "textPom"],
                    "textPom": ["text", "textSod"], "textarea": ["richtext"], "select": ["selectOther", "radio"],
                    "radio": ["select", "selectOther"], "number": ["currency"]}
FIELD_KEYS = {"name", "label", "type", "values", "suffix", "class", "explan", "aiConfig", "if", "systemPath", "defaultValue",
              "limit", "placeholder", "required"}
GROUP_KEYS = {"groupName", "title", "subTitle", "explan", "if", "aiConfig", "fields"}
STRUCT_OPERATORS = {"equals", "notEquals", "greaterThan", "lessThan", "greaterOrEqual", "lessOrEqual",
                    "contains", "notContains", "isEmpty", "isNotEmpty", "isTrue", "isFalse"}
CLASS_TOKEN = re.compile(r"^(col-(xs|sm|md|lg)-(1[0-2]|[1-9])|col-auto)$")
MAX_DEPTH_ROW_GROUP, MAX_DEPTH_FIELD_GROUP = 3, 2

AREA_HINT = re.compile(r"שטח|מ\"ר|מ״ר|\bמטר\b|\bמטרים\b|\bמ\"ר\b|דונם")
MONEY_HINT = re.compile(r"שווי|ערך|סכום|מחיר|עלות|דמי|היטל|מס |₪|תשלום|פיצוי|הכנסה|הוצא")
DATE_HINT = re.compile(r"תאריך|מועד|יום ה")
PERCENT_HINT = re.compile(r"שיעור|אחוז|%")


class OpErr(Exception):
    pass


# --------------------------------------------------------------------------- the form being edited
class Form:
    def __init__(self, form):
        self.schema = copy.deepcopy(form["schema"])
        self.md = copy.deepcopy(form.get("metadata") or {})
        self.computed = json.dumps(form.get("computedFields") or [], ensure_ascii=False)
        self.is_system = bool(form.get("isSystem"))

    def index(self):
        out = {}
        for info in walk(self.schema):
            out.setdefault(info["path"], []).append(info)
        return out

    def top_names(self):
        return {i["key"] for i in walk(self.schema) if i["top"]}

    def locate(self, path):
        if not isinstance(path, str) or not path.strip():
            raise OpErr('path is required, e.g. "squareMeter" or "borrowers.borrowerName"')
        hits = self.index().get(path, [])
        if not hits:
            root = path.split(".")[0]
            if root not in self.top_names():
                raise OpErr(f'השדה "{root}" לא קיים בטופס')
            raise OpErr(f'"{path}" לא קיים בטופס')
        if len(hits) > 1:
            raise OpErr(f'"{path}" מופיע בטופס יותר מפעם אחת - אי אפשר לשנות אותו בפעולה, רק בבונה הטפסים')
        return hits[0]

    def container_of(self, info):
        """(list holding the node, index) - for a group row, the section's row list."""
        if info["top"]:
            rows = self.schema[info["section"]]
            for ri, row in enumerate(rows):
                if row is info["node"]:
                    return rows, ri
                if isinstance(row, dict) and not row.get("repeatable"):
                    for fi, n in enumerate(row.get("fields") or []):
                        if n is info["node"]:
                            return row["fields"], fi
        else:
            parent = self.locate(info["parent"])["node"]
            for fi, n in enumerate(parent.get("fields") or []):
                if n is info["node"]:
                    return parent["fields"], fi
        raise OpErr(f"internal: {info['path']} not found")

    def tabs(self):
        return (self.md.get("formGroups") or {}).get("tabs") or []


# --------------------------------------------------------------------------- input checks
def text(value, what, maxlen, required=False):
    if value is None:
        if required:
            raise OpErr(f"{what} is required")
        return None
    if not isinstance(value, str):
        raise OpErr(f"{what} must be text")
    t = value.strip()
    if required and not t:
        raise OpErr(f"{what} is required")
    if len(t) > maxlen:
        raise OpErr(f"{what} may be at most {maxlen} characters ({len(t)})")
    if "{{" in t or "}}" in t:
        raise OpErr(f"{what} may not contain {{{{ or }}}}")
    return t


def new_name(name, what="name"):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise OpErr(f'{what} "{name}" is invalid - English camelCase starting with a lowercase letter (e.g. "bankFileNumber")')
    if len(name) > 60:
        raise OpErr(f'{what} "{name}" is longer than 60 characters')
    if name in RESERVED or name in FORBIDDEN_MEMBERS:
        raise OpErr(f'{what} "{name}" is reserved - choose a more specific name')
    return name


def options(values, what="values"):
    if not isinstance(values, list) or not values:
        raise OpErr(f"{what} must be a non-empty list")
    if len(values) > 300:
        raise OpErr(f"{what} may hold at most 300 options")
    out = []
    for v in values:
        t = text(str(v) if isinstance(v, (int, float)) else v, "an option", 200, required=True)
        if t not in out:
            out.append(t)
    return out


def check_class(value):
    t = text(value, "class", 80)
    if not t:
        return None
    toks = t.split()
    if len(toks) > 4 or not all(CLASS_TOKEN.match(x) for x in toks):
        raise OpErr(f'class "{value}" is not a column layout - e.g. "col-md-4 col-sm-6 col-xs-12"')
    return " ".join(toks)


def check_ai(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"prompt"}:
        raise OpErr('aiConfig must be {"prompt": "..."} - nothing else')
    return {"prompt": text(value.get("prompt"), "aiConfig.prompt", 4000, required=True)}


COND_ROOT = re.compile(r"project\s*\.\s*additionalDetails\s*\.\s*([A-Za-z_$][\w$]*)")


def check_if(cond, top_names):
    """Light version of the server's condition grammar (form-template-conditions.js)."""
    if cond is None:
        return None
    if isinstance(cond, dict):
        conds = cond.get("conditions")
        if set(cond) - {"logic", "conditions"}:
            raise OpErr(f"unknown condition keys: {', '.join(sorted(set(cond) - {'logic', 'conditions'}))}")
        if cond.get("logic") not in (None, "and", "or"):
            raise OpErr('logic must be "and" or "or"')
        if not isinstance(conds, list) or not 1 <= len(conds) <= 20:
            raise OpErr('a structured condition is {"logic": "and"|"or", "conditions": [1-20 x {field, operator, value}]}')
        for c in conds:
            if not isinstance(c, dict) or set(c) - {"field", "operator", "value"}:
                raise OpErr("each condition is {field, operator, value}")
            if c.get("operator") not in STRUCT_OPERATORS:
                raise OpErr(f"condition operator must be one of {', '.join(sorted(STRUCT_OPERATORS))}")
            f = c.get("field")
            if not isinstance(f, str) or not re.match(r"^[A-Za-z_$][\w$]*$", f) or f in FORBIDDEN_MEMBERS:
                raise OpErr(f'"{f}" is not a field name - a structured condition reads a top-level field by name')
            if top_names is not None and f not in top_names:
                raise OpErr(f'תנאי התצוגה מתייחס לשדה שלא קיים בטופס: {f}')
            if isinstance(c.get("value"), (dict, list)):
                raise OpErr("a condition value must be text, a number or true/false")
        return cond
    if not isinstance(cond, str) or not cond.strip():
        raise OpErr("if must be an expression or a structured condition")
    if len(cond) > 1000:
        raise OpErr("the condition is longer than 1000 characters")
    s = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", cond)   # drop string literals
    if re.search(r"(?<![=!<>])=(?!=)", s):
        raise OpErr("a condition may not assign (=) - compare with === or ==")
    for m in re.finditer(r"\.\s*([A-Za-z_$][\w$]*)\s*\(", s):
        if m.group(1) not in ("includes", "indexOf"):
            raise OpErr(f'only .includes() and .indexOf() may be called in a condition (found .{m.group(1)}())')
    if re.search(r"(^|[^.\w$])[A-Za-z_$][\w$]*\s*\(", s):
        raise OpErr("a condition may not call functions")
    for w in re.findall(r"[A-Za-z_$][\w$]*", s):
        if w in FORBIDDEN_MEMBERS:
            raise OpErr(f'"{w}" may not appear in a condition')
    idents = re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)", s)
    for w in idents:
        if w not in ("project", "true", "false", "null", "undefined", "x", "y", "z", "filter"):
            raise OpErr(f'a value must start with project.additionalDetails (found "{w}")')
    roots = COND_ROOT.findall(s)
    if "project" in idents and not roots:
        raise OpErr("a value must start with project.additionalDetails.<field>")
    unknown = sorted({r for r in roots if r not in top_names}) if top_names is not None else []
    if unknown:
        raise OpErr(f"תנאי התצוגה מתייחס לשדות שלא קיימים בטופס: {', '.join(unknown)}")
    return cond.strip()


def _is_number(v):
    try:
        float(str(v).strip())
        return True
    except ValueError:
        return False


def check_default(value, field):
    """A default value as the field type stores it (server: checkDefaultValue)."""
    t = field.get("type") or "text"
    if t in ("image", "html", "read", "readNumber"):
        raise OpErr(f"a {t} field has no default value")
    if t in ("text", "textarea", "textPom", "textSod"):
        return text(value, "defaultValue", 4000, required=True)
    if t == "richtext":
        return text(value, "defaultValue", 8000, required=True)   # plain text becomes <p> paragraphs on the server
    if t == "checkbox":
        if not isinstance(value, bool):
            raise OpErr("the default of a checkbox is true or false")
        return value
    if t in ("number", "currency"):
        if isinstance(value, bool) or not _is_number(value):
            raise OpErr("the default of a number field is a number")
        return float(value) if not isinstance(value, (int, float)) else value
    if t == "date":
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            raise OpErr("the default of a date field is YYYY-MM-DD")
        return value
    opts = options_of(field) if field.get("values") else None
    if t == "checkboxList":
        if not isinstance(value, list) or not value:
            raise OpErr("the default of a multiple-choice field is a list of its options")
        lst = [text(str(v), "a default option", 200, required=True) for v in value]
        bad = [v for v in lst if opts is not None and v not in opts]
        if bad:
            raise OpErr(f"ברירת המחדל כוללת ערכים שאינם אפשרויות של השדה: {', '.join(bad)}")
        return list(dict.fromkeys(lst))
    v = text(str(value), "defaultValue", 200, required=True)
    if t in ("select", "radio") and opts is not None and v not in opts:
        raise OpErr(f'ברירת המחדל "{v}" אינה אחת מהאפשרויות של השדה')
    return v


def _closest(value, opts):
    hits = [o for o in opts if value.replace('"', "") in o.replace('"', "") or o.replace('"', "") in value.replace('"', "")]
    if hits:
        return hits[:3]
    return [o for o in sorted(opts, key=lambda o: -similarity(value, o))[:2] if similarity(value, o) > 0.3]


def validate_condition(F, cond, warn):
    """A condition read against the form it lands in (server: validateConditionInForm): the fields it reads
    exist, a checkbox is compared with true/false, a number field with a number, a choice field with one of
    its options. Otherwise the field would never show - the server rejects the plan."""
    if cond is None:
        return
    top = F.top_names()
    unknown = sorted(r for r in reads(cond) if r not in top)
    if unknown:
        raise OpErr(f"תנאי התצוגה מתייחס לשדות שלא קיימים בטופס: {', '.join(unknown)}")
    idx = {i["path"]: i for i in walk(F.schema)}
    for path, value, how in value_tests(cond):
        info = idx.get(path)
        if not info:
            if "." in path:
                raise OpErr(f'תנאי התצוגה מתייחס לשדה "{path}" שלא קיים בטופס')
            continue
        if info["kind"] != "field":
            continue
        node = info["node"]
        t = node.get("type") or "text"
        subj = label_of(node) or info["key"]
        if t == "checkbox":
            if how in ("eq", "ne"):
                raise OpErr(f'תנאי התצוגה משווה את "{subj}" ל"{value}", אבל זו תיבת סימון ששומרת כן/לא - '
                            "משווים ל-true או false")
            continue
        if t in ("number", "currency"):
            if how in ("eq", "ne") and value.strip() and not _is_number(value):
                raise OpErr(f'תנאי התצוגה משווה את "{subj}", שדה מספרי, לטקסט "{value}"')
            continue
        if t not in NEEDS_VALUES or not value:
            continue
        lst = _org_list(F, info)
        own = options_of(node)
        if lst:
            if value not in own:
                warn(f'"{value}" בתנאי על "{subj}" נבדק בשרת מול רשימת הארגון ({lst}) - הנוסח המדויק ב-get_option_list')
            continue
        if not own:
            continue
        exact = how in ("eq", "ne") or t == "checkboxList"
        if (value in own) if exact else any(value.lower() in o.lower() for o in own):
            continue
        sugg = _closest(value, own)
        msg = (f'תנאי התצוגה משווה את "{subj}" ל"{value}", שאינו אחת מהאפשרויות שלו - השדה לא היה מוצג אף פעם.'
               + (f" האם התכוונת ל: {', '.join(chr(34) + o + chr(34) for o in sugg)}?" if sugg else ""))
        if t == "selectOther":
            warn(msg + " (השרת מקבל ערך כזה רק אם פרויקטים כבר שמרו אותו)")
        else:
            raise OpErr(msg)


def validate_node_conditions(F, node, warn):
    if node.get("if") is not None:
        validate_condition(F, node["if"], warn)
    for child in node.get("fields") or []:
        if isinstance(child, dict):
            validate_node_conditions(F, child, warn)


def build_field(inp, top_level, top_names):
    if not isinstance(inp, dict):
        raise OpErr("field must be an object")
    bad = set(inp) - FIELD_KEYS
    if bad:
        raise OpErr(f"unknown field keys: {', '.join(sorted(bad))}. Allowed: {', '.join(sorted(FIELD_KEYS))}")
    name = new_name(inp.get("name"), "field name")
    ftype = inp.get("type", "text")
    if ftype not in AGENT_TYPES:
        raise OpErr(f'type "{ftype}" is not available to agents. Use one of: {", ".join(AGENT_TYPES)}')
    f = {"name": name, "type": ftype, "label": text(inp.get("label"), "label", 120, required=True)}
    if inp.get("class") is not None:
        f["class"] = check_class(inp["class"])
    if ftype in NEEDS_VALUES:
        f["values"] = options(inp.get("values"))
    elif inp.get("values") is not None:
        raise OpErr(f"values apply only to {', '.join(sorted(NEEDS_VALUES))} fields")
    if inp.get("suffix"):
        if ftype != "currency":
            raise OpErr("suffix is shown only on currency fields")
        f["suffix"] = text(inp["suffix"], "suffix", 20)
    for k, m in (("placeholder", 120), ("explan", 500)):
        if inp.get(k):
            f[k] = text(inp[k], k, m)
    if inp.get("required") is not None:
        if not isinstance(inp["required"], bool):
            raise OpErr("required must be true or false")
        if inp["required"]:
            f["required"] = True
    if inp.get("limit") is not None:
        if ftype != "image" or not isinstance(inp["limit"], int) or not 1 <= inp["limit"] <= 30:
            raise OpErr("limit applies only to image fields, a whole number 1-30")
        f["limit"] = inp["limit"]
    if inp.get("systemPath") is not None:
        if not top_level:
            raise OpErr("systemPath applies only to fields outside a group")
        if not is_allowed_system_path(inp["systemPath"]):
            raise OpErr(f'systemPath "{inp["systemPath"]}" is not a binding a form may have')
        f["systemPath"] = inp["systemPath"]
    if inp.get("if") is not None:
        f["if"] = check_if(inp["if"], None)          # what it reads is checked once the field is in place
    if inp.get("aiConfig") is not None:
        f["aiConfig"] = check_ai(inp["aiConfig"])
    if inp.get("defaultValue") is not None:
        f["defaultValue"] = check_default(inp["defaultValue"], f)
    return f


def build_group(inp, depth, max_depth, row_group, top_names):
    if not isinstance(inp, dict):
        raise OpErr("group definition must be an object")
    bad = set(inp) - GROUP_KEYS
    if bad:
        raise OpErr(f"unknown group keys: {', '.join(sorted(bad))}. Allowed: {', '.join(sorted(GROUP_KEYS))}")
    if depth > max_depth:
        raise OpErr(f"קבוצה בעומק {depth} לא מוצגת בטופס (העומק המרבי כאן הוא {max_depth})")
    name = new_name(inp.get("groupName"), "groupName")
    fields = inp.get("fields")
    if not isinstance(fields, list) or not fields:
        raise OpErr("a group needs at least one field")
    if len(fields) > 80:
        raise OpErr("a group may hold at most 80 fields")
    title = text(inp.get("title"), "title", 120)
    sub = text(inp.get("subTitle"), "subTitle", 120)
    if not title and not sub:
        raise OpErr("a group needs a title (the heading shown above its rows)")
    g = {"repeatable": True, "groupName": name}
    if row_group:
        if title:
            g["title"] = title
        if sub:
            g["subTitle"] = sub
    else:
        g["subTitle"] = sub or title
    if inp.get("explan"):
        g["explan"] = text(inp["explan"], "explan", 500)
    if inp.get("if") is not None:
        g["if"] = check_if(inp["if"], None)
    if inp.get("aiConfig") is not None:
        g["aiConfig"] = check_ai(inp["aiConfig"])
    taken, kids = set(), []
    for child in fields:
        if isinstance(child, dict) and "groupName" in child:
            node = build_group(child, depth + 1, max_depth, False, top_names)
        else:
            node = build_field(child, False, top_names)
        k = key_of(node)
        if k in taken:
            raise OpErr(f'the name "{k}" appears twice in group "{name}"')
        taken.add(k)
        kids.append(node)
    g["fields"] = kids
    return g


def keys_only(op, allowed):
    bad = set(op) - set(allowed) - {"op", "why"}
    if bad:
        raise OpErr(f"unknown keys: {', '.join(sorted(bad))}")


def parent_of(F, op):
    has_s, has_g = op.get("section") is not None, op.get("group") is not None
    if has_s == has_g:
        raise OpErr('give exactly one of "section" (a section key) or "group" (a group path) as the parent')
    if has_s:
        if op["section"] not in section_keys(F.schema):
            raise OpErr(f'הסעיף "{op["section"]}" לא קיים בטופס. סעיפים: {", ".join(section_keys(F.schema))}')
        return {"section": op["section"]}
    g = F.locate(op["group"])
    if g["kind"] != "group":
        raise OpErr(f'"{op["group"]}" הוא שדה ולא קבוצה')
    return {"group": g}


def place_in_section(F, section, node, after, as_row):
    rows = F.schema[section]
    if after is not None:
        anchor = next((i for i in walk(F.schema) if i["top"] and i["key"] == after), None)
        if not anchor:
            raise OpErr(f'השדה "{after}" (after) לא קיים בטופס')
        if anchor["section"] != section:
            raise OpErr(f'השדה "{after}" נמצא בסעיף "{anchor["section"]}", לא בסעיף "{section}"')
        cont, idx = F.container_of(anchor)
        if as_row or anchor["row_group"]:
            ri = next(i for i, r in enumerate(rows) if r is anchor["node"] or (isinstance(r, dict) and r.get("fields") is cont))
            rows.insert(ri + 1, node if as_row else {"fields": [node]})
        else:
            cont.insert(idx + 1, node)
        return anchor["node"]
    if as_row:
        rows.append(node)
    elif rows and isinstance(rows[-1], dict) and not rows[-1].get("repeatable") and not rows[-1].get("if") \
            and not rows[-1].get("title") and isinstance(rows[-1].get("fields"), list):
        rows[-1]["fields"].append(node)
    else:
        rows.append({"fields": [node]})
    return None



def card_of(F, section, node):
    """' בכרטיס "<title>"' when the plain row holding node has a title, else ''."""
    for row in F.schema.get(section) or []:
        if isinstance(row, dict) and not row.get("repeatable") and any(f is node for f in row.get("fields") or []):
            return f' בכרטיס "{row["title"]}"' if row.get("title") else ""
    return ""


def scope_labels(F, parent_path):
    """(path, label) of the fields a new field sits next to: top-level fields, or one group's columns.
    A label is compared only within its scope - a "קומה" column in a table isn't the form's "קומה"."""
    out = []
    for i in walk(F.schema):
        if i["kind"] != "field":
            continue
        par = i["path"].rsplit(".", 1)[0] if "." in i["path"] else ""
        if par == (parent_path or ""):
            out.append((i["path"], label_of(i["node"])))
    return out


def warn_card(F, section, after, warn, field_if=None):
    """A field placed after a field of a conditional card joins that card - and its condition."""
    if after is None:
        return
    a = next((i for i in walk(F.schema) if i["top"] and i["key"] == after and i["section"] == section), None)
    if not a or a["row_group"] or not a["row_if"]:
        return
    msg = f'"{label_of(a["node"]) or after}" נמצא בכרטיס עם תנאי ({_short(a["row_if"])}) - השדה ייכנס לכרטיס ויוצג רק כשהתנאי מתקיים'
    if field_if:
        msg += ", בנוסף לתנאי של השדה"
    warn(msg + ". אם זה לא מכוון - after על שדה מחוץ לכרטיס")

def place_in_group(group_node, node, after):
    fields = group_node.setdefault("fields", [])
    if after is not None:
        i = next((i for i, c in enumerate(fields) if key_of(c) == after), None)
        if i is None:
            raise OpErr(f'השדה "{after}" (after) לא קיים בקבוצה "{key_of(group_node)}"')
        fields.insert(i + 1, node)
        return fields[i]
    fields.append(node)
    return None


# --------------------------------------------------------------------------- advice (warnings)
def advise(field, warn, existing_labels, path):
    lab = field.get("label") or ""
    t = field.get("type")
    if not re.search(r"[א-ת]", lab):
        warn(f'התווית "{lab}" לא בעברית - המשתמשים רואים אותה בטופס')
    if not (field.get("aiConfig") or {}).get("prompt"):
        warn("אין aiConfig.prompt - AI Fill ינחש לפי התווית בלבד. כדאי לכתוב מאיזה מסמך ובאיזה פורמט")
    distance = re.search(r"מרחק|גובה|אורך|רוחב|עומק|רדיוס", lab)
    if AREA_HINT.search(lab) and not distance and t in ("text", "number") and not PERCENT_HINT.search(lab):
        warn('נראה כמו שטח: מקובל currency עם suffix "מ\\"ר" (מפרידי אלפים ועשרוניים)')
    if AREA_HINT.search(lab) and not distance and t == "currency" and not field.get("suffix"):
        warn('שטח בשדה currency בלי suffix יוצג עם ₪ - הוסיפו suffix "מ\\"ר"')
    if MONEY_HINT.search(lab) and t in ("text", "number") and not PERCENT_HINT.search(lab) and not AREA_HINT.search(lab):
        warn("נראה כמו סכום כסף: מקובל currency (₪ ומפרידי אלפים)")
    if DATE_HINT.search(lab) and t not in ("date",) and "תקופה" not in lab:
        warn("נראה כמו תאריך: type date מאפשר עיצוב | date בתבנית ומיון")
    if PERCENT_HINT.search(lab) and t == "number":
        warn('שיעור/אחוז בשדה number: אין עשרוניים ושליליים נוחים - שקלו textPom או currency עם suffix "%"')
    if t == "textarea" and NARRATIVE.search(" " + norm(lab) + " "):
        warn('טקסט מפורט ("' + lab + '"): עדיף richtext - פסקאות, הדגשות ורשימות; בתבנית {p.ad.x | html}')
    vals = field.get("values") or []
    if t in ("select", "radio") and len(vals) > 15:
        warn("רשימה ארוכה ב-select/radio - שקלו selectOther (מאפשר ערך חופשי)")
    # similar labels are checked once the whole plan has run (main) - a later op may rename either field


# --------------------------------------------------------------------------- ops
def run_op(F, op, warn, notes):
    name = op.get("op")
    top = F.top_names()
    if name == "set_form_props":
        keys_only(op, ["title", "description", "appraisalTypes", "isDefault"])
        if not any(k in op for k in ("title", "description", "appraisalTypes", "isDefault")):
            raise OpErr("nothing to set - give title, description, appraisalTypes or isDefault")
        if "title" in op:
            text(op["title"], "title", 120, required=True)
        if "appraisalTypes" in op:
            if not isinstance(op["appraisalTypes"], list) or len(op["appraisalTypes"]) > 20:
                raise OpErr("appraisalTypes must be a list of up to 20 appraisal types")
            warn("השרת דוחה סוג שומה שכבר משויך לטופס אחר של הארגון; התוכנית תראה כמה פרויקטים יעברו טופס")
        if "isDefault" in op and not isinstance(op["isDefault"], bool):
            raise OpErr("isDefault must be true or false")
        return {"what": "מאפייני הטופס", "where": "-", "detail": ", ".join(f"{k}={op[k]}" for k in op if k not in ("op", "why"))}

    if name == "add_section":
        keys_only(op, ["key", "title", "icon", "tab", "after", "aiConfig"])
        key = new_name(op.get("key"), "section key")
        ai = check_ai(op.get("aiConfig"))
        title = text(op.get("title"), "title", 80, required=True)
        icon = op.get("icon", "fa-th-list")
        if not isinstance(icon, str) or not re.match(r"^fa-[a-z0-9-]{1,40}$", icon):
            raise OpErr('icon must be a Font Awesome 4 name like "fa-bank"')
        tab = next((t for t in F.tabs() if t.get("key") == op.get("tab")), None)
        if not tab:
            raise OpErr(f'הלשונית "{op.get("tab")}" לא קיימת. לשוניות: {", ".join(str(t.get("key")) for t in F.tabs())}')
        if key in F.schema or key in (F.md.get("sections") or {}):
            raise OpErr(f'הסעיף "{key}" כבר קיים בטופס')
        if op.get("after") is not None and op["after"] not in (tab.get("sections") or []):
            raise OpErr(f'הסעיף "{op["after"]}" (after) לא נמצא בלשונית "{tab.get("key")}"')
        F.schema[key] = []
        F.md.setdefault("sections", {})[key] = {"title": title, "icon": icon, **({"aiConfig": ai} if ai else {})}
        secs = list(tab.get("sections") or [])
        secs.insert(secs.index(op["after"]) + 1 if op.get("after") else len(secs), key)
        tab["sections"] = secs
        notes["new_sections"].add(key)
        return {"what": f'סעיף חדש "{title}"', "where": f'לשונית {tab.get("title") or tab.get("key")}', "detail": ""}

    if name == "add_field":
        keys_only(op, ["section", "group", "after", "field"])
        par = parent_of(F, op)
        f = build_field(op.get("field"), "section" in par, top)
        path = f["name"] if "section" in par else f'{par["group"]["path"]}.{f["name"]}'
        if ("section" in par and f["name"] in top) or F.index().get(path):
            raise OpErr(f'השם "{f["name"]}" כבר בשימוש בטופס - לשינוי שדה קיים update_field, לשדה חדש שם אחר')
        advise(f, warn, scope_labels(F, None if "section" in par else par["group"]["path"]), path)
        if "section" in par:
            warn_card(F, par["section"], op.get("after"), warn, f.get("if"))
            anchor = place_in_section(F, par["section"], f, op.get("after"), False)
            where = f'סעיף "{section_title(F.md, par["section"])}"' + card_of(F, par["section"], f)
        else:
            anchor = place_in_group(par["group"]["node"], f, op.get("after"))
            where = f'קבוצה "{label_of(par["group"]["node"])}"'
        validate_node_conditions(F, f, warn)
        notes["added"].append(path)
        return {"what": f'שדה חדש "{f["label"]}"', "path": path, "type": f["type"],
                "where": where + (f' אחרי "{label_of(anchor)}"' if anchor else " (בסוף)"),
                "detail": _field_detail(f)}

    if name == "add_group":
        keys_only(op, ["section", "group", "after", "definition"])
        par = parent_of(F, op)
        if "section" in par:
            depth, maxd, row_group = 1, MAX_DEPTH_ROW_GROUP, True
        else:
            g = par["group"]
            depth = g["depth"] + 1
            root = F.locate(g["path"].split(".")[0])
            maxd = MAX_DEPTH_ROW_GROUP if root["row_group"] else MAX_DEPTH_FIELD_GROUP
            row_group = False
        grp = build_group(op.get("definition"), depth, maxd, row_group, top)
        path = grp["groupName"] if "section" in par else f'{par["group"]["path"]}.{grp["groupName"]}'
        if ("section" in par and grp["groupName"] in top) or F.index().get(path):
            raise OpErr(f'השם "{grp["groupName"]}" כבר בשימוש - להוספת שדה לקבוצה קיימת add_field עם group')
        for child in grp["fields"]:
            if not child.get("repeatable"):
                advise(child, lambda m, c=child: warn(f'{c["name"]}: {m}'), [], None)
        for i in walk(F.schema):
            if i["kind"] == "group" and similarity(label_of(grp), label_of(i["node"])) >= 0.8:
                warn(f'כותרת דומה לקבוצה קיימת `{i["path"]}` ("{label_of(i["node"])}") - לוודא שזו לא אותה טבלה')
                break
        if not (grp.get("aiConfig") or {}).get("prompt"):
            warn("לקבוצה אין aiConfig.prompt - AI Fill לא יודע מאיזה מסמך למלא את השורות")
        if "section" in par:
            anchor = place_in_section(F, par["section"], grp, op.get("after"), True)
            where = f'סעיף "{section_title(F.md, par["section"])}"'
        else:
            anchor = place_in_group(par["group"]["node"], grp, op.get("after"))
            where = f'בתוך הקבוצה "{label_of(par["group"]["node"])}"'
        validate_node_conditions(F, grp, warn)
        notes["added"].append(path)
        cols = ", ".join(label_of(c) for c in grp["fields"])
        return {"what": f'קבוצה חוזרת "{label_of(grp)}"', "path": path, "type": "group",
                "where": where + (f' אחרי "{label_of(anchor)}"' if anchor else " (בסוף)"),
                "detail": f"שדות: {cols}" + (f" | תנאי: {_short(grp['if'])}" if grp.get("if") else "")}

    if name == "update_field":
        keys_only(op, ["path", "set"])
        info = F.locate(op.get("path"))
        st = op.get("set")
        if not isinstance(st, dict) or not st:
            raise OpErr("set must name at least one property to change")
        if "name" in st or "groupName" in st:
            raise OpErr("השם הפנימי לא משתנה (הוא מפתח הנתונים ותגיות ה-Word) - משנים label")
        allowed = ["title", "subTitle", "explan", "if", "aiConfig"] if info["kind"] == "group" else \
            ["label", "explan", "aiConfig", "if", "class", "suffix", "limit", "placeholder", "required", "type",
             "defaultValue"]
        bad = set(st) - set(allowed)
        if bad:
            raise OpErr(f"cannot set {', '.join(sorted(bad))} on a {info['kind']}. Allowed: {', '.join(allowed)}")
        node = info["node"]
        changes = []
        for k, v in st.items():
            if k == "type":
                frm = node.get("type") or "text"
                if v != frm and v not in TYPE_CONVERSIONS.get(frm, []):
                    raise OpErr(f"אי אפשר לשנות סוג מ-{frm} ל-{v} בלי לפגוע בנתונים. אפשרי: "
                                f"{', '.join(TYPE_CONVERSIONS.get(frm, [])) or 'אין'}. במקום זה - שדה חדש")
                if v in NEEDS_VALUES and not node.get("values") and not node.get("valuesSource"):
                    raise OpErr(f"a {v} field needs options - add_options first")
                if v == "richtext":
                    warn("ערכים קיימים יוצגו כטקסט מעוצב; ירידות שורה בטקסט קיים מתאחדות בעריכה הבאה. כל תבנית Word "
                         "שמדפיסה את השדה צריכה לעבור ל-{p.ad.x | html} (בלי זה ה-HTML מודפס כטקסט) - התוכנית "
                         "מפרטת את התבניות בשינוי סוג; לעדכן אותן בסקיל התבניות לפני שמשתמשים בשדה")
            elif k == "suffix" and v is not None and (st.get("type") or node.get("type")) != "currency":
                raise OpErr("suffix is shown only on currency fields")
            elif k == "limit" and v is not None and (node.get("type") != "image" or not isinstance(v, int) or not 1 <= v <= 30):
                raise OpErr("limit applies only to image fields, 1-30")
            elif k == "if" and v is not None:
                v = check_if(v, None)
            elif k == "defaultValue" and v is not None:
                v = check_default(v, {**node, "type": st.get("type") or node.get("type") or "text"})
                warn("ברירת מחדל נכנסת רק לשדה ריק - בפרויקטים חדשים, בפרויקטים שלא מילאו אותו ובייצוא ל-Word; "
                     "ערך שכבר נשמר לא משתנה (התוכנית אומרת בכמה פרויקטים)")
            elif k == "aiConfig" and v is not None:
                check_ai(v)
            elif k == "class" and v is not None:
                check_class(v)
            elif k in ("label", "title", "subTitle") and v is not None:
                text(v, k, 120, required=True)
            elif k in ("explan",) and v is not None:
                text(v, k, 500, required=True)
            elif k == "required" and not isinstance(v, bool):
                raise OpErr("required must be true or false")
            if v is None:
                node.pop(k, None)
            else:
                node[k] = v
            if k == "if" and v is not None:
                validate_condition(F, v, warn)
            names = {"label": "תווית", "explan": "הסבר", "aiConfig": "הנחיית AI", "if": "תנאי תצוגה", "class": "רוחב",
                     "suffix": "יחידה", "limit": "מספר תמונות", "placeholder": "טקסט דוגמה", "required": "חובה",
                     "type": "סוג", "title": "כותרת", "subTitle": "כותרת", "defaultValue": "ברירת מחדל"}
            shown = "(הסרה)" if v is None else ("עודכנה" if k == "aiConfig" else _short(v))
            changes.append(f"{names.get(k, k)}: {shown}")
        return {"what": f'עדכון "{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]),
                "type": "group" if info["kind"] == "group" else (node.get("type") or "text"), "detail": "; ".join(changes)}

    if name in ("add_options", "remove_options"):
        keys_only(op, ["path", "values"])
        info = F.locate(op.get("path"))
        node = info["node"]
        if info["kind"] != "field" or (node.get("type") or "text") not in NEEDS_VALUES:
            raise OpErr(f'"{info["path"]}" is not a choice field ({", ".join(sorted(NEEDS_VALUES))})')
        lst = _org_list(F, info)
        if lst:
            raise OpErr(f'האפשרויות של "{label_of(node)}" הן רשימת ארגון ({lst}) - משנים אותן בהגדרות ← אפשרויות בחירה ← אפשרויות בחירה בפרטי פרויקט, לא בטופס')
        vals = options(op.get("values"))
        cur = [v.get("value", v.get("label")) if isinstance(v, dict) else v for v in (node.get("values") or [])]
        if name == "add_options":
            new = [v for v in vals if v not in cur]
            if not new:
                return {"what": "no_op", "path": info["path"], "where": "", "detail": "האפשרויות כבר קיימות", "noop": True}
            node["values"] = cur + new
            return {"what": f'אפשרויות חדשות ל"{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]),
                    "detail": " / ".join(new)}
        present = [v for v in vals if v in cur]
        if not present:
            return {"what": "no_op", "path": info["path"], "where": "", "detail": "האפשרויות כבר לא קיימות", "noop": True}
        if len(present) == len(cur):
            raise OpErr("a choice field must keep at least one option")
        warn("השרת יסרב אם אפשרות נשמרה באחד הפרויקטים")
        node["values"] = [v for v in cur if v not in present]
        return {"what": f'הסרת אפשרויות מ"{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]),
                "detail": " / ".join(present)}

    if name == "move_field":
        keys_only(op, ["path", "toSection", "after"])
        info = F.locate(op.get("path"))
        if not info["top"]:
            raise OpErr("אפשר להזיז רק שדה או קבוצה שאינם בתוך קבוצה (הנתונים שמורים בשורות הקבוצה)")
        if op.get("toSection") not in section_keys(F.schema):
            raise OpErr(f'הסעיף "{op.get("toSection")}" לא קיים בטופס')
        if op.get("after") == info["key"]:
            raise OpErr("a field cannot be placed after itself")
        if not info["row_group"]:
            warn_card(F, op["toSection"], op.get("after"), warn, info["node"].get("if"))
        cont, idx = F.container_of(info)
        cont.pop(idx)
        rows = F.schema[info["section"]]
        F.schema[info["section"]] = [r for r in rows if not (isinstance(r, dict) and not r.get("repeatable")
                                                          and isinstance(r.get("fields"), list) and not r["fields"])]
        place_in_section(F, op["toSection"], info["node"], op.get("after"), info["row_group"])
        return {"what": f'העברת "{label_of(info["node"])}"', "path": info["path"],
                "where": f'לסעיף "{section_title(F.md, op["toSection"])}"' + card_of(F, op["toSection"], info["node"]),
                "detail": "הנתונים לא משתנים"}

    if name in ("hide_field", "show_field"):
        keys_only(op, ["path"])
        info = F.locate(op.get("path"))
        node = info["node"]
        if name == "hide_field":
            if node.get("hidden"):
                return {"what": "no_op", "path": info["path"], "where": "", "detail": "כבר מוסתר", "noop": True}
            node["hidden"] = True
            return {"what": f'הסתרת "{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]),
                    "detail": "הנתונים נשמרים; AI Fill מדלג; בתבניות קיימות יודפס ריק בפרויקטים חדשים"}
        if not node.get("hidden"):
            return {"what": "no_op", "path": info["path"], "where": "", "detail": "כבר מוצג", "noop": True}
        node.pop("hidden", None)
        return {"what": f'הצגה מחדש של "{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]), "detail": ""}

    if name == "remove_field":
        keys_only(op, ["path"])
        info = F.locate(op.get("path"))
        node = info["node"]
        blockers = []
        root = info["path"].split(".")[0]
        for other in walk(F.schema):
            c = other["node"].get("if")
            if c is not None and other["path"] != info["path"] and not other["path"].startswith(info["path"] + "."):
                if root in json.dumps(c, ensure_ascii=False) and (info["top"] or info["key"] in json.dumps(c)):
                    blockers.append(f"תנאי התצוגה של {other['path']}")
        for col, target in (F.md.get("projectFieldsMap") or {}).items():
            if isinstance(target, str) and target.replace("[0]", "") == info["path"]:
                blockers.append(f"מקושר לעמודת הפרויקט {col}")
        if re.search(rf"(^|[^\w$]){re.escape(info['key'])}([^\w$]|$)", F.computed):
            blockers.append("שדה מחושב משתמש בו")
        if blockers:
            raise OpErr(f'אי אפשר להסיר את "{label_of(node)}": {"; ".join(blockers[:4])}. אפשר hide_field')
        if not info["top"]:
            parent = F.locate(info["parent"])["node"]
            if len(parent.get("fields") or []) == 1:
                raise OpErr(f'"{label_of(node)}" הוא השדה היחיד בקבוצה - יש להסיר את הקבוצה כולה')
        warn("השרת יסרב אם יש בשדה נתונים בפרויקט כלשהו או שתבנית Word קוראת אותו - ואז יציע hide_field")
        cont, idx = F.container_of(info)
        cont.pop(idx)
        return {"what": f'הסרת "{label_of(node)}"', "path": info["path"], "where": section_title(F.md, info["section"]), "detail": ""}

    if name == "update_row":
        keys_only(op, ["section", "field", "set"])
        fld = op.get("field")
        if not isinstance(fld, str) or "." in fld:
            raise OpErr('field must name a field of the card, outside any group (e.g. "bankNotes")')
        info = F.locate(fld)
        if info["row_group"]:
            raise OpErr(f'"{fld}" היא קבוצה חוזרת - את הכותרת, התנאי וההנחיה שלה משנים ב-update_field עם path "{fld}"')
        if op.get("section") is not None and op["section"] != info["section"]:
            raise OpErr(f'השדה "{fld}" נמצא בסעיף "{info["section"]}", לא בסעיף "{op["section"]}"')
        st = op.get("set")
        if not isinstance(st, dict) or not st:
            raise OpErr("set must name at least one property to change")
        permitted = ["title", "subTitle", "subHeader", "explan", "if", "aiConfig", "icon"]
        bad = [k for k in st if k not in permitted]
        if bad:
            raise OpErr(f"cannot set {', '.join(bad)} on a card. Allowed: {', '.join(permitted)}")
        row = next(r for r in F.schema[info["section"]] if isinstance(r, dict) and not r.get("repeatable")
                   and any(n is info["node"] for n in r.get("fields") or []))
        changes, updates = [], {}
        for k, v in st.items():
            if v is None:
                pass
            elif k == "if":
                v = check_if(v, None)
            elif k == "aiConfig":
                v = check_ai(v)
            elif k == "icon":
                if not isinstance(v, str) or not re.match(r"^fa-[a-z0-9-]{1,40}$", v):
                    raise OpErr('icon must be a Font Awesome 4 name like "fa-bank"')
            else:
                v = text(v, k, 500 if k == "explan" else 120, required=True)
            if json.dumps(row.get(k), sort_keys=True, ensure_ascii=False) == json.dumps(v, sort_keys=True, ensure_ascii=False):
                continue
            updates[k] = v
        if not updates:
            return {"what": "no_op", "path": fld, "where": "", "detail": "הערכים כבר כאלה", "noop": True}
        for k, v in updates.items():
            if v is None:
                row.pop(k, None)
            else:
                row[k] = v
            changes.append(f'{ {"title": "כותרת", "subTitle": "כותרת משנה", "subHeader": "כותרת משנה", "explan": "הסבר", "if": "תנאי תצוגה", "aiConfig": "הנחיית AI", "icon": "סמל"}[k] }: '
                           + ("(הסרה)" if v is None else ("עודכנה" if k == "aiConfig" else _short(v))))
        if updates.get("if"):
            validate_condition(F, updates["if"], warn)
            warn("תנאי על כרטיס מסתיר את כל השדות שבו; התוכנית מפרטת תבניות Word שמדפיסות אותם (wordTemplatesStillPrinting)")
        name_ = row.get("title") or ", ".join(label_of(n) for n in (row.get("fields") or [])[:3] if isinstance(n, dict))
        return {"what": f'כרטיס "{name_}"', "path": fld, "where": section_title(F.md, info["section"]),
                "type": "card", "detail": "; ".join(changes)}

    if name == "update_section":
        keys_only(op, ["key", "set"])
        key = op.get("key")
        if key not in section_keys(F.schema):
            raise OpErr(f'הסעיף "{key}" לא קיים בטופס. סעיפים: {", ".join(section_keys(F.schema))}')
        st = op.get("set")
        if not isinstance(st, dict) or not st:
            raise OpErr("set must name at least one property to change")
        bad = [k for k in st if k not in ("title", "icon", "aiConfig")]
        if bad:
            raise OpErr(f"cannot set {', '.join(bad)} on a section. Allowed: title, icon, aiConfig")
        sec = dict((F.md.setdefault("sections", {})).get(key) or {})
        before = section_title(F.md, key)
        changes = []
        for k, v in st.items():
            if k == "title":
                v = text(v, "title", 80, required=True)
            elif k == "aiConfig":
                v = check_ai(v)
            elif not isinstance(v, str) or not re.match(r"^fa-[a-z0-9-]{1,40}$", v):
                raise OpErr('icon must be a Font Awesome 4 name like "fa-bank"')
            if json.dumps(sec.get(k), sort_keys=True, ensure_ascii=False) == json.dumps(v, sort_keys=True, ensure_ascii=False):
                continue
            if v is None:
                sec.pop(k, None)
            else:
                sec[k] = v
            changes.append({"title": f'שם: {v}', "aiConfig": "הנחיית AI Fill של הסעיף" + (" תוסר" if v is None else " עודכנה"),
                            "icon": "סמל"}[k])
        if not changes:
            return {"what": "no_op", "path": key, "where": "", "detail": "הערכים כבר כאלה", "noop": True}
        F.md["sections"][key] = sec
        return {"what": f'סעיף "{before}"', "path": None, "where": before, "detail": "; ".join(changes)}

    raise OpErr(f'unknown op "{name}". Known: {", ".join(OPS)}')


def _op_target(op):
    if not isinstance(op, dict):
        return None
    if op.get("path"):
        return op["path"]
    f = op.get("field") or op.get("definition") or {}
    name = f.get("name") or f.get("groupName") if isinstance(f, dict) else None
    parent = op.get("group")
    if name:
        return f"{parent}.{name}" if parent else name
    return op.get("key")


def _org_list(F, info):
    node = info["node"]
    if node.get("valuesSource"):
        return node["valuesSource"]
    if not info["top"]:
        return None
    sp = node.get("systemPath")
    if isinstance(sp, str) and sp.startswith("p."):
        return ORG_LIST_BY_COLUMN.get(sp[2:])
    for col, target in (F.md.get("projectFieldsMap") or {}).items():
        if target == info["key"] and col in ORG_LIST_BY_COLUMN:
            return ORG_LIST_BY_COLUMN[col]
    return None


def _short(v):
    """A condition or value in words the user can read in the review table."""
    if isinstance(v, dict) and isinstance(v.get("conditions"), list):
        ops_he = {"equals": "=", "notEquals": "≠", "greaterThan": ">", "lessThan": "<", "greaterOrEqual": "≥",
                  "lessOrEqual": "≤", "contains": "כולל", "notContains": "לא כולל", "isEmpty": "ריק",
                  "isNotEmpty": "מולא", "isTrue": "מסומן", "isFalse": "לא מסומן"}
        joiner = " או " if v.get("logic") == "or" else " וגם "
        s = joiner.join(f"{c.get('field')} {ops_he.get(c.get('operator'), c.get('operator'))}"
                        + (f" '{c.get('value')}'" if c.get("value") not in (None, "") else "") for c in v["conditions"])
    else:
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        s = s.replace("project.additionalDetails.", "")
        s = re.sub(r"\s*!==?\s*", " ≠ ", s)
        s = re.sub(r"\s*===?\s*", " = ", s)
        s = s.replace("&&", " וגם ").replace("||", " או ")
        s = re.sub(r"\.includes\(\s*", " כולל (", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= 90 else s[:87] + "..."


def _field_detail(f):
    bits = []
    if f.get("values"):
        bits.append("אפשרויות: " + " / ".join(f["values"][:8]) + (" ..." if len(f["values"]) > 8 else ""))
    if f.get("suffix"):
        bits.append(f"יחידה: {f['suffix']}")
    if f.get("if"):
        bits.append(f"מוצג רק אם: {_short(f['if'])}")
    if f.get("systemPath"):
        bits.append(f"מקושר ל-{f['systemPath']}")
    if (f.get("aiConfig") or {}).get("prompt"):
        bits.append("AI ✓")
    return " | ".join(bits)


# --------------------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    md_out = args[args.index("--md") + 1] if "--md" in args else None
    payload_out = args[args.index("--payload") + 1] if "--payload" in args else None
    form = load_form(args[0])
    spec = load_json_any(args[1])
    if isinstance(spec, list):
        spec = {"ops": spec}
    ops = spec.get("ops") or []
    why = spec.get("why") or {}
    F = Form(form)
    notes = {"added": [], "new_sections": set()}
    results, n_err, n_warn = [], 0, 0
    if F.is_system:
        print("ERR  this is a SYSTEM form - it is never edited. create_custom_form_template first, then plan on the copy.")
        n_err += 1
    if len(ops) > MAX_OPS:
        print(f"ERR  {len(ops)} ops - a plan holds at most {MAX_OPS}; split it")
        n_err += 1
    for i, op in enumerate(ops):
        warns = []
        snapshot = (copy.deepcopy(F.schema), copy.deepcopy(F.md))
        try:
            if not isinstance(op, dict):
                raise OpErr("each operation must be an object")
            res = run_op(F, op, warns.append, notes)
            status = "NOOP" if res.get("noop") else ("WARN" if warns else "OK")
        except OpErr as e:
            F.schema, F.md = snapshot
            res = {"what": op.get("op") if isinstance(op, dict) else "?", "path": _op_target(op), "where": "", "detail": ""}
            warns = [str(e)]
            status = "ERR"
        n_err += status == "ERR"
        n_warn += status == "WARN"
        res.update({"i": i, "op": op.get("op") if isinstance(op, dict) else "?", "status": status, "messages": warns,
                    "why": (op.get("why") if isinstance(op, dict) else None) or why.get(str(i)) or why.get(res.get("path") or "", "")})
        results.append(res)
    for key in notes["new_sections"]:
        if not F.schema.get(key):
            print(f"WARN new section {key} is empty - add its fields in the same plan")
            n_warn += 1

    # labels very close to a field that was already in the form (final labels, same scope)
    orig = {i["path"] for i in walk(form["schema"])}
    final = {i["path"]: i for i in walk(F.schema)}
    for r in results:
        if r["status"] not in ("OK", "WARN") or r["op"] != "add_field" or r.get("path") not in final:
            continue
        me = final[r["path"]]
        scope = me["path"].rsplit(".", 1)[0] if "." in me["path"] else ""
        lab = label_of(me["node"])
        for p, other in final.items():
            if p == me["path"] or p not in orig or other["kind"] != "field":
                continue
            if (p.rsplit(".", 1)[0] if "." in p else "") != scope:
                continue
            if similarity(lab, label_of(other["node"])) >= 0.8:
                r["messages"].append(f'תווית דומה לשדה קיים `{p}` ("{label_of(other["node"])}") - לוודא שזה נתון אחר ולא כפילות')
                if r["status"] == "OK":
                    r["status"] = "WARN"
                    n_warn += 1
                break

    # display logic of what the plan touched, on the form after the plan
    after = {**form, "schema": F.schema, "metadata": F.md}
    touched, if_set = {}, set()
    for op, r in zip(ops, results):
        if r["status"] in ("OK", "WARN") and isinstance(op, dict) and (
                "if" in (op.get("set") or {}) or "if" in (op.get("field") or {}) or "if" in (op.get("definition") or {})):
            if_set.add(r.get("path"))
    for r in results:
        if r["status"] in ("OK", "WARN") and r.get("path") and r["op"] in (
                "add_field", "add_group", "update_field", "add_options", "remove_options", "show_field", "move_field"):
            touched[r["path"]] = r
    logic, gates = [], []
    if touched:
        before = {(f["kind"], f["path"], f.get("gate")) for f in audit(form, only=set(touched))}
        for f in audit(after, only=set(touched)):
            if f["kind"].startswith("richtext"):
                continue            # new fields: advise() spoke; existing ones: converting is the user's call
            f["existing"] = (f["kind"], f["path"], f.get("gate")) in before and f["path"] not in if_set
            if f["kind"] == "ungated" and f["path"] not in touched and f["path"] in orig:
                # an existing field right after a NEW question: a detail only if the user means it
                f["level"] = "check"
                f["message"] += " - שדה קיים: אם הוא באמת פרט של השאלה החדשה, תנאי מעבר (form-design.md §8, כלל 9)"
            logic.append(f)
            owner = touched.get(f["path"]) or touched.get(f.get("gate") or "")
            if owner and f["level"] in ("fix", "check") and not f["existing"]:
                owner["messages"].append(f["message"] + (f' - תנאי מוצע: {f["suggest"]}' if f.get("suggest") else ""))
                if owner["status"] == "OK":
                    owner["status"] = "WARN"
                    n_warn += 1
        infos = list(walk(F.schema))
        index = {i["path"]: i for i in infos}
        top = {i["key"]: i for i in infos if i["top"]}
        names = set()
        for path in touched:
            info = index.get(path)
            if not info:
                continue
            if info["kind"] == "field" and is_gate(info["node"]):
                names.add(path)
            for c in visibility_conds(info, index):
                names |= {k for k in reads(c) if k in top and is_gate(top[k]["node"])}
        for f in logic:
            if f.get("gate") in index and is_gate(index[f["gate"]]["node"]):
                names.add(f["gate"])
        gates = []
        everything = audit(after) if names else []
        for n in sorted(names):
            if n not in index:
                continue
            always = [label_of(index[f["path"]]["node"]) or f["path"] for f in everything
                      if f["kind"] == "ungated" and f.get("gate") == n and f["path"] in index]
            gates.append((index[n], matrix(index[n], infos, index), index, always))
    for r in results:                          # printed once every pass had its say
        tag = {"OK": "OK  ", "WARN": "WARN", "ERR": "ERR ", "NOOP": "NOOP"}[r["status"]]
        print(f"{tag} #{r['i']} {r['op']} {r.get('path') or ''} - {r['what']}")
        for m in r["messages"]:
            print(f"       {m}")
    if logic:
        print("\nDisplay logic after the plan (formlogic):")
        for f in logic:
            tag = {"fix": "FIX ", "check": "CHK ", "advice": "NOTE"}[f["level"]]
            print(f"{tag} {f['path']}: {f['message']}" + (" [כבר בטופס]" if f["existing"] else ""))
            if f.get("suggest"):
                print(f"       תנאי מוצע: {f['suggest']}")
    print(f"\n{len(ops)} ops: {n_err} errors, {n_warn} warnings")

    if md_out:
        write_preview(md_out, form, spec, results, logic, gates)
        print(f"preview -> {md_out}")
    if payload_out and not n_err:
        clean = [{k: v for k, v in op.items() if k != "why"} for op in ops]
        payload = {"templateId": spec.get("templateId") or form.get("id"), "ops": clean}
        if spec.get("note"):
            payload["note"] = spec["note"][:1000]
        with open(payload_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f"payload for plan_form_template_changes -> {payload_out}")
    sys.exit(1 if n_err else 0)


def write_preview(path, form, spec, results, logic=(), gates=()):
    md = form.get("metadata") or {}
    lines = [f"## שינויים מוצעים בטופס \"{form.get('title')}\"", ""]
    if spec.get("note"):
        lines += [f"**למה:** {spec['note']}", ""]
    lines += ["| # | שינוי | נתיב | סוג | מיקום | פרטים | מקור / סיבה |", "|---|---|---|---|---|---|---|"]
    for r in results:
        if r["status"] == "NOOP":
            continue
        t = TYPE_LABELS_HE.get(r.get("type"), "קבוצה" if r.get("type") == "group" else "")
        flag = " ⚠️" if r["status"] == "WARN" else (" ❌" if r["status"] == "ERR" else "")
        cells = [str(r["i"] + 1), r["what"] + flag, f"`{r.get('path') or '-'}`", t, r.get("where") or "",
                 (r.get("detail") or "").replace("|", "/"), (r.get("why") or "").replace("|", "/")]
        lines.append("| " + " | ".join(cells) + " |")
    warn_lines = [f"- #{r['i'] + 1} {m}" for r in results if r["status"] in ("WARN", "ERR") for m in r["messages"]]
    if warn_lines:
        lines += ["", "**לתשומת לב:**", *warn_lines]
    noops = [r for r in results if r["status"] == "NOOP"]
    if noops:
        lines += ["", "כבר קיים בטופס (לא ישתנה): " + ", ".join(f"`{r.get('path')}`" for r in noops)]
    old = [f for f in logic if f.get("existing") and f["level"] != "advice"]
    if old:
        lines += ["", "**בעיות תצוגה שכבר קיימות בטופס (התוכנית לא יצרה אותן - אפשר לתקן בתוכנית נפרדת):**"]
        lines += [f"- `{f['path']}` - {f['message']}" for f in old]
    gates = [g for g in gates if g[1] or g[3]]
    if gates:
        from audit_form import render_map
        lines += ["", "### מפת התנאים (אחרי התוכנית)", "", "מה כל תשובה מציגה:", ""]
        for g, m, index, always in gates:
            lines += [render_map(g, m, index, md, always), ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
