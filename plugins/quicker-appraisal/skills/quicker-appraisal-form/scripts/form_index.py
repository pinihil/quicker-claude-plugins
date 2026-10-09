#!/usr/bin/env python3
"""
Index a Quicker appraisal form so you can plan changes to it without reading 100KB of JSON.

Usage:
    python3 form_index.py form.json work/              # -> work/form_index.md + work/form_index.json
    python3 form_index.py form.json --find "שטח"       # fields whose label/name looks like the text
    python3 form_index.py form.json --path borrowers   # one node (and a group's children) in full

form.json is the reply of get_form_template - the file the connector saved, or the JSON itself.

form_index.md lists, tab by tab and section by section, every field and group with:
    path  (what ops address: "squareMeter", "borrowers.borrowerName")
    label, type, options (first few + count), and flags:
      [hidden]           hidden in the form (data kept)
      [if ...]           display condition (own, or of its row)
      [-> p.x]           linked to a project column (systemPath or projectFieldsMap)
      [org list: X]      options come from the organization's settings, not the form
      [AI]               has an AI Fill prompt
      [depth 3]          a group three levels down (its fields are missing from
                         get_word_template_variables as of October 2026)
form_index.json holds the same, keyed by path, plus the name registry check_ops.py uses.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formlib import (TYPE_LABELS_HE, bindings, label_of, load_form, options_of, org_list_of,  # noqa: E402
                     key_of, section_keys, section_title, similarity, tabs_of, walk, camel_words)


def build(form):
    schema, md = form["schema"], form.get("metadata") or {}
    links = bindings(md)
    nodes, order, top_names, dup = {}, [], {}, {}
    for info in walk(schema):
        n = info["node"]
        entry = {
            "path": info["path"], "key": info["key"], "kind": info["kind"], "section": info["section"],
            "label": label_of(n), "depth": info["depth"], "parent": info["parent"],
        }
        if info["kind"] == "field":
            entry["type"] = n.get("type") or "text"
            opts = options_of(n)
            if opts:
                entry["options"] = opts
            if n.get("defaultValue") not in (None, "", []):
                entry["hasDefault"] = True
            for k in ("suffix", "systemPath", "explan", "placeholder", "class", "limit"):
                if n.get(k) not in (None, ""):
                    entry[k] = n[k]
            if n.get("required"):
                entry["required"] = True
        else:
            entry["children"] = []  # filled below
        if n.get("if") is not None:
            entry["if"] = n["if"]
        elif info.get("row_if") is not None:
            entry["rowIf"] = info["row_if"]
        if n.get("hidden"):
            entry["hidden"] = True
        if (n.get("aiConfig") or {}).get("prompt"):
            entry["ai"] = True
        lst = org_list_of(info, md)
        if lst:
            entry["orgList"] = lst
        if info["path"] in links:
            entry["linkedTo"] = links[info["path"]]
        if info["top"]:
            if info["key"] in top_names:
                dup.setdefault(info["key"], [top_names[info["key"]]]).append(info["section"])
            top_names[info["key"]] = info["section"]
        nodes.setdefault(info["path"], entry)
        order.append(info["path"])
    for path, e in nodes.items():
        if e["kind"] == "group":
            e["children"] = [p for p in order if nodes[p]["parent"] == path]
    # projectFieldsMap entries pointing into groups ("addressDetails[0].apartmentNumber")
    for target, cols in links.items():
        base = target.replace("[0]", "")
        if base in nodes and "linkedTo" not in nodes[base]:
            nodes[base]["linkedTo"] = cols
    broken = sorted(t for t in links if t.replace("[0]", "") not in nodes)
    by_value = conditions_by_value(schema)
    rows = {}
    for sec_key in section_keys(schema):
        rows[sec_key] = []
        for row in schema[sec_key]:
            if not isinstance(row, dict):
                continue
            if row.get("repeatable"):
                k = row.get("groupName") or row.get("name")
                rows[sec_key].append({"card": None, "top": [k] if k in nodes else []})
            else:
                keys = [n.get("groupName") if n.get("repeatable") else n.get("name") for n in row.get("fields") or [] if isinstance(n, dict)]
                rows[sec_key].append({"card": row.get("title") or row.get("subHeader"), "if": row.get("if"),
                                      "top": [k for k in keys if k in nodes]})
    return {
        "form": {k: form.get(k) for k in ("id", "name", "title", "description", "isSystem", "isDefault",
                                           "enabled", "version", "appraisalTypes", "appraisalType", "basedOnTemplateId")},
        "tabs": tabs_of(form),
        "sections": {k: {"title": section_title(md, k), "top": [p for p in order if nodes[p]["section"] == k and nodes[p]["parent"] is None]}
                     for k in section_keys(schema)},
        "nodes": nodes,
        "order": order,
        "topLevelNames": sorted(top_names),
        "duplicateTopLevelNames": dup,
        "projectFieldsMap": md.get("projectFieldsMap") or {},
        "brokenBindings": broken,
        "computedFieldsText": json.dumps(form.get("computedFields") or [], ensure_ascii=False),
        "conditionsByValue": by_value,
        "rows": rows,
    }


_LIT = r"(?:'([^']*)'|\"([^\"]*)\")"
VALUE_PATTERNS = [
    # additionalDetails.X === 'v'  /  == 'v'  /  !== 'v'
    re.compile(r"additionalDetails\.(\w+)(?:\[\w+\])?(?:\.\w+)*\s*!?==?=?\s*" + _LIT),
    # additionalDetails.X.includes('v')
    re.compile(r"additionalDetails\.(\w+)(?:\[\w+\])?(?:\.\w+)*\.includes\(\s*" + _LIT),
]
LIST_INCLUDES = re.compile(r"\[([^\]]*)\]\s*\.includes\(\s*project\.additionalDetails\.(\w+)")


def conditions_by_value(schema):
    """{field: {value: [paths, 'card: <title>' or 'row in <section>: <fields>' whose condition names that
    value]}} - e.g. which fields
    a bank (referrer value) or "שומה מורחבת" turns on."""
    out = {}

    def note(cond, where):
        text = cond if isinstance(cond, str) else json.dumps(cond, ensure_ascii=False)
        if isinstance(cond, dict):
            for c in cond.get("conditions") or []:
                if isinstance(c, dict) and isinstance(c.get("value"), str):
                    out.setdefault(c.get("field"), {}).setdefault(c["value"], []).append(where)
            return
        for rx in VALUE_PATTERNS:
            for f, v1, v2 in rx.findall(text):
                out.setdefault(f, {}).setdefault(v1 or v2, []).append(where)
        for vals, f in LIST_INCLUDES.findall(text):
            for v1, v2 in re.findall(_LIT, vals):
                out.setdefault(f, {}).setdefault(v1 or v2, []).append(where)

    for section in section_keys(schema):
        for row in schema[section]:
            if isinstance(row, dict) and not row.get("repeatable") and row.get("if") is not None:
                if row.get("title"):
                    where = f"card: {row['title']}"
                else:
                    names = [key_of(f) for f in row.get("fields") or [] if isinstance(f, dict)]
                    where = f"row in {section}: {', '.join(n for n in names if n)}"
                note(row["if"], where)
    for info in walk(schema):
        if info["node"].get("if") is not None:
            note(info["node"]["if"], info["path"])
    for f in out:
        for v in out[f]:
            out[f][v] = sorted(set(out[f][v]))
    return out


def short_if(cond):
    s = cond if isinstance(cond, str) else json.dumps(cond, ensure_ascii=False)
    s = s.replace("project.additionalDetails.", "")
    return s if len(s) <= 90 else s[:87] + "..."


def line_for(e, indent=""):
    bits = [f"{indent}- `{e['path']}`", e["label"] or "(no label)"]
    if e["kind"] == "group":
        bits.append(f"[group, {len(e['children'])} items]")
    else:
        t = e["type"]
        bits.append(f"({t}{' ' + e['suffix'] if e.get('suffix') else ''})")
    flags = []
    if e.get("hidden"):
        flags.append("hidden")
    if e.get("if") is not None:
        flags.append("if " + short_if(e["if"]))
    elif e.get("rowIf") is not None:
        flags.append("row if " + short_if(e["rowIf"]))
    if e.get("systemPath"):
        flags.append("-> " + e["systemPath"])
    if e.get("linkedTo"):
        flags.append("-> p." + "/p.".join(e["linkedTo"]))
    if e.get("orgList"):
        flags.append("org list: " + e["orgList"])
    if e.get("ai"):
        flags.append("AI")
    if e.get("hasDefault"):
        flags.append("default text")
    if e["kind"] == "group" and e["depth"] >= 3:
        flags.append(f"depth {e['depth']}")
    if flags:
        bits.append("[" + "] [".join(flags) + "]")
    if e.get("options"):
        o = e["options"]
        bits.append("options: " + " / ".join(o[:8]) + (f" ... (+{len(o) - 8})" if len(o) > 8 else ""))
    return " ".join(bits)


def render_md(idx):
    f = idx["form"]
    out = [f"# Form index: {f.get('title')}",
           "",
           f"- id: `{f.get('id')}` | name: `{f.get('name')}` | version: {f.get('version')} | "
           f"{'SYSTEM form - copy it before changing (create_custom_form_template)' if f.get('isSystem') else 'organization form'}"
           f"{' | default' if f.get('isDefault') else ''}",
           f"- appraisal types: {', '.join(f.get('appraisalTypes') or []) or '-'}",
           f"- top-level names: {len(idx['topLevelNames'])} | nodes: {len(idx['nodes'])}",
           ""]
    if idx["duplicateTopLevelNames"]:
        out.append("**Names repeated across sections** (ops cannot address them - leave them to the form builder): " +
                   ", ".join(f"`{k}` ({', '.join(v)})" for k, v in idx["duplicateTopLevelNames"].items()))
        out.append("")
    if idx["brokenBindings"]:
        out.append("**projectFieldsMap points at fields the form does not have:** " + ", ".join(f"`{b}`" for b in idx["brokenBindings"]))
        out.append("")
    for tab in idx["tabs"]:
        out.append(f"## Tab `{tab['key']}` - {tab['title']}")
        for sec_key in tab["sections"]:
            sec = idx["sections"][sec_key]
            out.append(f"\n### Section `{sec_key}` - {sec['title']}  ({len(sec['top'])} top-level)")
            for row in idx["rows"].get(sec_key, []):
                if row.get("card"):
                    cond = f" [row if {short_if(row['if'])}]" if row.get("if") is not None else ""
                    out.append(f"- **card \"{row['card']}\"**{cond}")
                for p in row["top"]:
                    out.extend(_render_tree(idx, p, "  " if row.get("card") else ""))
        out.append("")
    cbv = idx.get("conditionsByValue") or {}
    if cbv:
        out.append("## Conditions that name option values")
        out.append("Which fields / cards each value turns on or off (exact text - a condition compares it as written).")
        for f in sorted(cbv):
            out.append(f"- `{f}`:")
            for v, where in sorted(cbv[f].items()):
                out.append(f"  - '{v}' -> {', '.join(where[:12])}{' ...' if len(where) > 12 else ''}")
        out.append("")
    return "\n".join(out) + "\n"


def _render_tree(idx, path, indent):
    e = idx["nodes"][path]
    lines = [line_for(e, indent)]
    if e["kind"] == "group":
        for c in e["children"]:
            lines.extend(_render_tree(idx, c, indent + "  "))
    return lines


def find(idx, text, limit=15):
    scored = []
    for p, e in idx["nodes"].items():
        s = max(similarity(text, e["label"]), similarity(text, camel_words(e["key"])), 1.0 if text == e["key"] else 0)
        if s >= 0.34:
            scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], idx["order"].index(x[1])))
    return [(s, idx["nodes"][p]) for s, p in scored[:limit]]


def check_tags(idx, path):
    """Do the p.ad tags a Word template uses exist in this form? path = the template skill's plan.json,
    an outline JSON, or any text/JSON holding the tags."""
    raw = open(path, encoding="utf-8").read()
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        pass
    if isinstance(data, dict) and isinstance(data.get("form"), dict):
        fid = data["form"].get("id")
        if fid and fid != idx["form"].get("id"):
            print(f"NOTE: the template was mapped against form {fid} ({data['form'].get('title')}), "
                  f"not this form ({idx['form'].get('id')}, {idx['form'].get('title')}).")
    roots = sorted(set(re.findall(r"p\.ad\.([A-Za-z_$\u0590-\u05FF][\w$\u0590-\u05FF-]*)", raw)))
    top = set(idx["topLevelNames"])
    missing = [r for r in roots if r not in top]
    print(f"{len(roots)} p.ad fields used; {len(roots) - len(missing)} exist in this form")
    for r in missing:
        print(f"  MISSING in this form: p.ad.{r}")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    form = load_form(args[0])
    idx = build(form)
    if "--find" in args:
        text = args[args.index("--find") + 1]
        hits = find(idx, text)
        for sc, e in hits:
            print(f"{sc:.2f}  {line_for(e)}   <{e['section']}>")
        if not hits:
            print(f"no field looks like \"{text}\" (searched labels and names)")
        return
    if "--check-tags" in args:
        check_tags(idx, args[args.index("--check-tags") + 1])
        return
    if "--path" in args:
        p = args[args.index("--path") + 1]
        if p not in idx["nodes"]:
            sys.exit(f"no node at {p}")
        print(json.dumps(idx["nodes"][p], ensure_ascii=False, indent=1))
        for c in idx["nodes"][p].get("children", []):
            print(line_for(idx["nodes"][c], "  "))
        return
    out_dir = args[1] if len(args) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "form_index.json"), "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=1)
    md = render_md(idx)
    with open(os.path.join(out_dir, "form_index.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    f = idx["form"]
    print(f"{f.get('title')} (v{f.get('version')}, {'system' if f.get('isSystem') else 'organization'}): "
          f"{len(idx['sections'])} sections, {len(idx['nodes'])} nodes -> {out_dir}/form_index.md")


if __name__ == "__main__":
    main()
