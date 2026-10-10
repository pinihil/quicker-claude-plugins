#!/usr/bin/env python3
"""
Write the Hebrew changes file for a form plan (step 9): what changes and why, what each answer shows,
the exact spec for entering the changes by hand in the form builder, open findings, how to undo.

Usage:
    python3 change_report.py form.json work/ops.json --out "out/<form title>_form_changes.md"
            [--reply work/plan_reply.json] [--findings work/findings.md] [--applied <new version>]

form.json      the form BEFORE the plan (get_form_template)
ops.json       the ops with their "why" (the same file check_ops.py read)
--reply        the plan_form_template_changes reply: plan id, expiry (written in Israel time), projects
--findings     a Hebrew markdown fragment with the findings left open (standards gaps, organization
               lists to change in the settings, default texts, card conditions, declined fields)
--applied N    the plan was applied and the form is now version N (default: planned, not applied)

The manual-entry part is what the form builder needs when apply is off: every field's exact internal
name (templates find fields by it), type, place, options, unit, condition (as written and in words),
help text and AI Fill prompt.
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_ops  # noqa: E402
from formlib import TYPE_LABELS_HE, label_of, load_form, load_json_any, section_title, walk  # noqa: E402

KEY_HE = {"label": "תווית", "explan": "הסבר (?)", "aiConfig": "הנחיית AI Fill", "if": "תנאי תצוגה", "class": "רוחב",
          "suffix": "יחידה", "limit": "מספר תמונות", "placeholder": "טקסט דוגמה", "required": "שדה חובה",
          "type": "סוג", "title": "כותרת", "subTitle": "כותרת משנה", "subHeader": "כותרת משנה",
          "defaultValue": "ערך ברירת מחדל (נכנס רק לשדה ריק)", "icon": "סמל"}


def israel_time(iso):
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(iso)


def cond_he(cond, labels):
    """A condition in words, field names replaced by their labels."""
    if not cond:
        return ""
    if isinstance(cond, dict):
        s = check_ops._short(cond)
    else:
        s = cond.replace("project.additionalDetails.", "")
        s = re.sub(r"\s*!==?\s*", " ≠ ", s)
        s = re.sub(r"\s*===?\s*", " = ", s)
        s = s.replace("&&", " וגם ").replace("||", " או ")
        s = re.sub(r"\[([^\]]*)\]\.includes\(\s*([\w.\[\]]+)\s*\)", r"\2 אחד מ-[\1]", s)
        s = re.sub(r"\.includes\(\s*", " כולל (", s)
        s = re.sub(r"\s+", " ", s).strip()
    for key in sorted(labels, key=len, reverse=True):
        s = re.sub(rf"(?<![\w.]){re.escape(key)}(?![\w])", f'"{labels[key]}"', s)
    return s


def type_he(t):
    return f"{TYPE_LABELS_HE.get(t, t)} (`{t}`)"


def field_spec(f, where, labels, indent=""):
    lines = [f"{indent}- **{f.get('label') or f.get('name')}**",
             f"{indent}  - שם פנימי: `{f.get('name')}` - בדיוק כך (התבניות מוצאות את השדה לפי השם)",
             f"{indent}  - סוג: {type_he(f.get('type', 'text'))}"]
    if where:
        lines.append(f"{indent}  - מיקום: {where}")
    if f.get("values"):
        lines.append(f"{indent}  - אפשרויות (בדיוק בנוסח הזה): " + " / ".join(f["values"]))
    if f.get("suffix"):
        lines.append(f"{indent}  - יחידה: {f['suffix']}")
    if f.get("if"):
        raw = f["if"] if isinstance(f["if"], str) else json.dumps(f["if"], ensure_ascii=False)
        lines.append(f"{indent}  - מוצג רק כש: {cond_he(f['if'], labels)}")
        lines.append(f"{indent}    - התנאי כפי שנכתב: `{raw}`")
    if f.get("explan"):
        lines.append(f"{indent}  - הסבר (?): {f['explan']}")
    if f.get("placeholder"):
        lines.append(f"{indent}  - טקסט דוגמה: {f['placeholder']}")
    if f.get("systemPath"):
        lines.append(f"{indent}  - מקושר לעמודת הפרויקט: `{f['systemPath']}`")
    if (f.get("aiConfig") or {}).get("prompt"):
        lines.append(f"{indent}  - הנחיית AI Fill: {f['aiConfig']['prompt']}")
    if f.get("limit"):
        lines.append(f"{indent}  - עד {f['limit']} תמונות")
    if f.get("defaultValue") is not None:
        dv = f["defaultValue"]
        lines.append(f"{indent}  - ערך ברירת מחדל (נכנס רק לשדה ריק): "
                     + (" / ".join(dv) if isinstance(dv, list) else str(dv)))
    return lines


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] in ("-h", "--help") or "--out" not in args:
        print(__doc__)
        return
    form = load_form(args[0])
    spec = load_json_any(args[1])
    if isinstance(spec, list):
        spec = {"ops": spec}
    ops = spec.get("ops") or []
    out_path = args[args.index("--out") + 1]
    reply = load_json_any(args[args.index("--reply") + 1]) if "--reply" in args else {}
    findings = open(args[args.index("--findings") + 1], encoding="utf-8").read() if "--findings" in args else ""
    applied = args[args.index("--applied") + 1] if "--applied" in args else None

    # replay: places, labels, the form after the plan
    F = check_ops.Form(form)
    notes = {"added": [], "new_sections": set()}
    results = []
    for op in ops:
        try:
            r = check_ops.run_op(F, {k: v for k, v in op.items() if k != "why"}, lambda m: None, notes)
            r["ok"] = True
        except check_ops.OpErr as e:
            r = {"what": op.get("op"), "path": check_ops._op_target(op), "where": "", "detail": "", "ok": False,
                 "error": str(e)}
        r["op"], r["why"], r["raw"] = op.get("op"), op.get("why") or "", op
        results.append(r)
    labels, old_labels = {}, {}
    for i in walk(F.schema):                     # conditions read with the labels the form will have
        labels.setdefault(i["key"], label_of(i["node"]) or i["key"])
    for i in walk(form["schema"]):               # an updated field is found by the label it has today
        old_labels.setdefault(i["key"], label_of(i["node"]) or i["key"])
        labels.setdefault(i["key"], old_labels[i["key"]])
    md = F.md

    version = form.get("version")
    title = form.get("title") or form.get("name")
    L = [f'# שינויים בטופס "{title}"', ""]
    if applied:
        L.append(f"- **מצב: בוצע** - הטופס עבר מגרסה {version} לגרסה {applied}")
    else:
        L.append(f"- **מצב: מתוכנן - טרם בוצע** (גרסה נוכחית {version}; אחרי הביצוע {reply.get('resultVersion') or (version or 0) + 1})")
    if reply.get("planId"):
        exp = f", בתוקף עד {israel_time(reply['expiresAt'])} (שעון ישראל)" if reply.get("expiresAt") else ""
        L.append(f"- תוכנית: `{reply['planId']}`{exp}")
    proj = (reply.get("impact") or {}).get("projectsOnForm")
    if proj is not None:
        L.append(f"- הטופס משמש {proj} פרויקטים")
    if spec.get("note"):
        L.append(f"- למה: {spec['note']}")
    L += ["", "## מה משתנה ולמה", "", "| # | שינוי | מיקום | פרטים | סיבה |", "|---|---|---|---|---|"]
    for n, r in enumerate(results, 1):
        cells = [str(n), r["what"] + ("" if r["ok"] else " ❌"), r.get("where") or "", (r.get("detail") or "").replace("|", "/"),
                 (r["why"] or "").replace("|", "/")]
        L.append("| " + " | ".join(cells) + " |")
    if reply.get("summaryHe"):
        L += ["", "**סיכום התוכנית כפי ש-Quicker החזיר:**", ""] + [f"- {x}" for x in reply["summaryHe"]]

    # what each answer shows
    from audit_form import render_map
    from formlogic import audit, is_gate, matrix, reads, visibility_conds
    after = {**form, "schema": F.schema, "metadata": md}
    infos = list(walk(F.schema))
    index = {i["path"]: i for i in infos}
    top = {i["key"]: i for i in infos if i["top"]}
    touched = {r["path"] for r in results if r["ok"] and r.get("path")}
    gates = set()
    for p in touched:
        info = index.get(p)
        if not info:
            continue
        if info["kind"] == "field" and is_gate(info["node"]):
            gates.add(p)
        for c in visibility_conds(info, index):
            gates |= {k for k in reads(c) if k in top and is_gate(top[k]["node"])}
    everything = audit(after)
    gates |= {f["gate"] for f in everything if f["kind"] == "ungated" and f["path"] in touched and f.get("gate") in index}
    if gates:
        L += ["", "## מה כל תשובה מציגה", ""]
        for g in sorted(gates):
            always = [label_of(index[f["path"]]["node"]) for f in everything
                      if f["kind"] == "ungated" and f.get("gate") == g and f["path"] in index]
            L += [render_map(index[g], matrix(index[g], infos, index), index, md, always), ""]

    # manual entry
    L += ["", "## הזנה ידנית בבונה הטפסים (הגדרות ← טפסי שומה מותאמים)", "",
          "בסדר הזה. השמות הפנימיים חייבים להיות בדיוק כמו כאן.", ""]
    for n, r in enumerate(results, 1):
        op = r["raw"]
        kind = op.get("op")
        L.append(f"### {n}. {r['what']}")
        if not r["ok"]:
            L += [f"לא יבוצע: {r.get('error')}", ""]
            continue
        if kind == "add_field":
            L += field_spec(op["field"], r.get("where"), labels)
        elif kind == "add_group":
            d = op.get("definition") or {}
            L += [f"- **קבוצה חוזרת (טבלה): {d.get('title') or d.get('groupName')}**",
                  f"  - שם פנימי: `{d.get('groupName')}`", f"  - מיקום: {r.get('where')}"]
            if d.get("if"):
                L.append(f"  - מוצגת רק כש: {cond_he(d['if'], labels)} (`{d['if']}`)")
            if (d.get("aiConfig") or {}).get("prompt"):
                L.append(f"  - הנחיית AI Fill: {d['aiConfig']['prompt']}")
            L.append("  - עמודות:")
            for c in d.get("fields") or []:
                L += field_spec(c, "", labels, indent="    ")
        elif kind == "update_field":
            L.append(f"- שדה: \"{old_labels.get(op['path'].split('.')[-1], op['path'])}\" (`{op['path']}`)")
            for k, v in (op.get("set") or {}).items():
                if k == "if":
                    raw = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    L.append(f"  - {KEY_HE[k]}: {cond_he(v, labels) or 'בלי תנאי'}" + (f" (`{raw}`)" if v else ""))
                elif k == "aiConfig":
                    L.append(f"  - {KEY_HE[k]}: {(v or {}).get('prompt') or '(תוסר)'}")
                elif k == "type":
                    L.append(f"  - {KEY_HE[k]}: {type_he(v)}")
                else:
                    L.append(f"  - {KEY_HE.get(k, k)}: {v}")
        elif kind in ("add_options", "remove_options"):
            verb = "להוסיף" if kind == "add_options" else "להסיר"
            L.append(f"- {verb} ב\"{labels.get(op['path'].split('.')[-1], op['path'])}\" (`{op['path']}`): "
                     + " / ".join(op.get("values") or []))
        elif kind in ("hide_field", "show_field"):
            L.append(f"- {'להסתיר' if kind == 'hide_field' else 'להציג שוב'} את `{op['path']}` (הנתונים נשמרים)")
        elif kind == "move_field":
            L.append(f"- להעביר את `{op['path']}` {r.get('where')}" + (f" אחרי `{op['after']}`" if op.get("after") else ""))
        elif kind == "add_section":
            L.append(f"- סעיף חדש \"{op.get('title')}\" (מפתח `{op.get('key')}`) בלשונית `{op.get('tab')}`"
                     + (f", אחרי הסעיף \"{section_title(md, op['after'])}\"" if op.get("after") else ""))
        elif kind == "update_row":
            L.append(f"- הכרטיס שבו נמצא \"{old_labels.get(op['field'], op['field'])}\" (`{op['field']}`), {r.get('where')}:")
            for k, v in (op.get("set") or {}).items():
                if k == "if":
                    raw = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    L.append(f"  - {KEY_HE[k]}: {cond_he(v, labels) or 'בלי תנאי'}" + (f" (`{raw}`)" if v else ""))
                elif k == "aiConfig":
                    L.append(f"  - {KEY_HE[k]}: {(v or {}).get('prompt') or '(תוסר)'}")
                else:
                    L.append(f"  - {KEY_HE.get(k, k)}: {v if v is not None else '(הסרה)'}")
        elif kind == "update_section":
            L.append(f"- הסעיף \"{section_title(form.get('metadata') or {}, op.get('key'))}\" (`{op.get('key')}`):")
            for k, v in (op.get("set") or {}).items():
                L.append(f"  - {KEY_HE.get(k, 'שם' if k == 'title' else k)}: "
                         + ((v or {}).get("prompt") if k == "aiConfig" and v else str(v)))
        elif kind == "set_form_props":
            L += [f"- {k}: {v}" for k, v in op.items() if k != "op"]
        else:
            L.append(f"- {json.dumps(op, ensure_ascii=False)}")
        if r["why"]:
            L.append(f"- למה: {r['why']}")
        L.append("")

    if findings.strip():
        L += ["## ממצאים פתוחים", "", findings.strip(), ""]
    L += ["## איך מחזירים", "",
          f"כל שינוי אפשר להחזיר: \"restore_form_template_version לגרסה {version}\" - או לבקש מ-Claude להחזיר את הטופס "
          f"לגרסה {version}. נתוני הפרויקטים לא נמחקים בשום מקרה.", ""]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"-> {out_path} ({len(results)} changes)")


if __name__ == "__main__":
    main()
