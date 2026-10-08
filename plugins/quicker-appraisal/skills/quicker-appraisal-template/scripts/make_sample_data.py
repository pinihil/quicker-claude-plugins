#!/usr/bin/env python3
"""
Generate sample render data from catalog.json, shaped like Quicker's render context
(p / p.ad / c / customers / today / images ...).

Variants:
  full   - every field filled, every checkbox on, 2 rows per repeatable group, selects = FIRST option
  alt    - like full, but selects = LAST option (exercises the other branch of option conditions)
  empty  - everything empty / false / [] (checks that conditional blocks disappear cleanly)
  mixed  - deterministic pseudo-random mix (seeded) - exercises both branches of conditions
  off    - selects = LAST option (like alt), but every checkbox off, every group and image field empty:
           the "option chosen, optional parts missing" case (e.g. שומה מורחבת without טופס 4 / permits)

Usage:
    python3 make_sample_data.py <catalog.json> <out_dir> [--image <png>]
Writes data_full.json, data_alt.json, data_empty.json, data_mixed.json
Images are written as {"_type":"image","path":<png>,"width":W,"height":H}; render_check.mjs
loads the file.
"""
import json, sys, os, random, copy

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IMG = os.path.normpath(os.path.join(HERE, "..", "assets", "sample.png"))


def image_obj(img, w=590, h=435):
    # Quicker passes display-sized images: form images <= 590x435, org images <= 680x800
    return {"_type": "image", "path": img, "width": w, "height": h}


def value_for(f, mode, rnd, img):
    kind, opts, label = f["kind"], f.get("options") or [], f.get("label") or f["name"]
    if mode == "empty" or (mode == "off" and kind in ("bool", "multi", "image", "images")):
        # Quicker sends an empty image field as [] (variables tool sample data)
        return {"bool": False, "multi": [], "images": [], "image": []}.get(kind, "")
    if mode == "off":
        mode = "alt"
    on = True if mode in ("full", "alt") else rnd.random() < 0.6
    if kind == "bool":
        return on
    if kind == "multi":
        if not opts:
            return ["פריט א", "פריט ב"] if on else []
        return list(opts) if mode in ("full", "alt") else [o for o in opts if rnd.random() < 0.5]
    if kind == "select":
        if opts:
            if mode == "alt":
                return opts[-1]
            return opts[0] if mode == "full" else (rnd.choice(opts) if on else "")
        return f"{label} לדוגמה" if on else ""
    if kind == "date":
        return "2026-03-15T08:30:00.000Z" if on else ""          # stored as ISO timestamps
    if kind == "money":
        return 1850000 if on else ""
    if kind == "area":
        return 96.5 if on else ""
    if kind == "number":
        return 3 if on else ""
    if kind == "image":
        return image_obj(img) if on else None
    if kind == "images":
        # Quicker: a field holding ONE image is an object, several -> an array
        if mode in ("full", "alt"):
            return [image_obj(img), image_obj(img)]
        return rnd.choice([None, image_obj(img), [image_obj(img), image_obj(img), image_obj(img)]]) if on else None
    if kind == "richtext":
        return f"<b>{label}</b> טקסט <i>מעוצב</i> לדוגמה" if on else ""
    if kind == "textarea":
        return f"{label} - שורה ראשונה\n{label} - שורה שנייה" if on else ""
    if kind == "widget":
        # display widgets (customHtml) without known rows: a number is the safest stand-in (prints as text
        # and survives | currency). Widgets that hold rows (planDataStatus) are groups in the catalog.
        return 1665000 if on else ""
    return f"{label} לדוגמה" if on else ""


def build(catalog, mode, seed, img):
    rnd = random.Random(seed)
    fields, groups = catalog["fields"], catalog["groups"]
    by_loop = {}
    for f in fields:
        by_loop.setdefault(f["loop"], []).append(f)
    children = {}
    for g in groups:
        children.setdefault(g["parent"], []).append(g)

    def fill_scope(loop_path, depth=0):
        obj = {}
        for f in by_loop.get(loop_path, []):
            obj[f["name"]] = value_for(f, mode, rnd, img)
        for g in children.get(loop_path, []):
            if g["path"] == loop_path or depth > 5:
                continue
            obj[g["name"]] = rows_for(g, depth + 1)
        return obj

    def rows_for(g, depth):
        if mode in ("empty", "off"):
            return []
        n = 2 if mode in ("full", "alt") else rnd.choice([0, 1, 2])
        rows = []
        for i in range(n):
            r = fill_scope(g["path"], depth)
            r.update({"_idx": i, "_isFirst": i == 0, "_isLast": i == n - 1})      # _idx counts from 0
            rows.append(r)
        return rows

    ad = fill_scope(None)
    full = mode != "empty"
    # project / customer fields: realistic values for the known ones, a kind-based value for any other
    # system field the catalog lists (so new render-context fields are exercised too)
    real_p = {
        "number": 1042, "name": "פרויקט לדוגמה", "address": "הרצל 12, תל אביב-יפו", "city": "תל אביב-יפו",
        "street": "הרצל", "house": "12", "neighborhood": "פלורנטין", "gush": "6938", "helka": "112",
        "subHelka": "7", "plot": "", "plotByTaba": "", "floor": "3", "rooms": "4", "apartmentNumber": "9",
        "squareMeter": 96.5, "appraisalType": "שומה לבנק", "appraisalPurpose": "בטוחה לאשראי בנקאי",
        "propertyType": "דירת מגורים", "propertyDestiny": "מגורים", "status": "בעבודה", "referrer": "בנק לאומי",
        "referrerReference": "2026-4471", "referrerCase": "88123", "apartmentOwner": "דוד ורחל כהן",
        "dueDate": "2026-03-20T08:30:00.000Z", "determinesDate": "2026-03-15T08:30:00.000Z",
        "visitDate": "2026-03-14T08:30:00.000Z", "visitContactName": "רחל כהן", "visitContactPhone": "050-7654321",
        "agentName": "ישראל ישראלי",
    }
    real_c = {"name": "דוד כהן", "phone": "050-1234567", "email": "d@example.com", "address": "הרצל 12",
              "city": "תל אביב-יפו", "personalIdentity": "012345678"}
    p, c, cust_fields = {}, {}, ["name", "phone", "email", "address", "city", "personalIdentity", "isPrimary"]
    for sf in catalog.get("system_fields", []):
        parts = sf["path"].split(".")
        if sf["path"] == "customers":
            cust_fields = sf.get("fields") or cust_fields
        if len(parts) != 2 or parts[0] not in ("p", "c"):
            continue
        real = real_p if parts[0] == "p" else real_c
        tgt = p if parts[0] == "p" else c
        if not full:
            tgt[parts[1]] = [] if sf["kind"] in ("image", "images") else ""
        elif parts[1] in real:
            tgt[parts[1]] = real[parts[1]]
        else:
            tgt[parts[1]] = value_for({"kind": sf["kind"], "name": parts[1], "label": sf.get("label")}, mode, rnd, img)
    for k, v in real_p.items():
        p.setdefault(k, v if full else "")
    for k, v in real_c.items():
        c.setdefault(k, v if full else "")
    c["isPrimary"] = True
    p["ad"] = ad
    second = {k: c.get(k, "") for k in cust_fields}
    second.update({"name": "רחל כהן", "personalIdentity": "987654321", "isPrimary": False})
    data = {
        "p": p, "project": p, "c": c,
        "customers": ([{k: c.get(k, "") for k in cust_fields}, second] if full else []),
        "today": "07/10/2026", "todayISO": "2026-10-07T08:30:00.000Z",
        "ownerName": "משרד שמאות לדוגמה", "ownerManagerName": "ישראל ישראלי",
        "appraisalHeaderImage": image_obj(img, 680, 160), "appraisalFooterImage": image_obj(img, 680, 120),
        "appraisalSignatureImage": image_obj(img, 300, 150), "govMapImage": image_obj(img) if full else None,
        "HEADER_IMAGE_WIDTH": 600, "FOOTER_IMAGE_WIDTH": 600,
    }
    p["additionalDetails"] = ad
    return data


def main():
    args = sys.argv[1:]
    img = DEFAULT_IMG
    if "--image" in args:
        i = args.index("--image"); img = os.path.abspath(args[i + 1]); del args[i:i + 2]
    cat_path, out_dir = args[0], args[1]
    os.makedirs(out_dir, exist_ok=True)
    catalog = json.load(open(cat_path, encoding="utf-8"))
    for mode, seed in (("full", 1), ("alt", 4), ("empty", 2), ("mixed", 3), ("off", 5)):
        data = build(catalog, mode, seed, img)
        # p and project share one object in Quicker; JSON can't express aliasing, so drop the
        # duplicate here and let render_check.mjs re-create the aliases.
        data.pop("project", None)
        data["p"].pop("additionalDetails", None)
        json.dump(data, open(os.path.join(out_dir, f"data_{mode}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print("wrote data_full.json, data_alt.json, data_empty.json, data_mixed.json, data_off.json ->", out_dir)


if __name__ == "__main__":
    main()
