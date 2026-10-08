#!/usr/bin/env python3
"""
Validate a Quicker template in one step: lint, sample data, test renders on both engines, v3-vs-v8
content diff, and a "בדיקות" section in the mapping report.

Usage:
    python3 validate.py <template.docx> <catalog.json> <work_dir> [--report mapping_report.md]
                        [--engines v3,v8] [--data extra1.json extra2.json ...]

  --data     extra datasets to render as well (e.g. a copy of data_alt.json with one field changed, for a
             combination the five standard datasets don't cover)
Writes <work_dir>/validation.json, sample data in <work_dir>/data/, renders in <work_dir>/render/.
Re-running replaces the report's "בדיקות" section (it is never appended twice).

Exit: 0 = lint clean and every render ok; 1 = lint errors or a failed render; 4 = lint clean but the
render harness could not be installed (no node/npm or no npm registry access) - deliver with that caveat.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diff_renders import lines as render_lines  # noqa: E402

DATASETS = ["full", "alt", "empty", "mixed", "off"]
DS_HE = {"full": "מלא (אפשרות ראשונה)", "alt": "מלא (אפשרות אחרונה)", "empty": "ריק", "mixed": "מעורב",
         "off": "אפשרות אחרונה בלי חלקים אופציונליים"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main():
    args = sys.argv[1:]
    report, engines, extra = None, ["v3", "v8"], []
    if "--report" in args:
        i = args.index("--report"); report = args[i + 1]; del args[i:i + 2]
    if "--engines" in args:
        i = args.index("--engines"); engines = args[i + 1].split(","); del args[i:i + 2]
    if "--data" in args:
        i = args.index("--data")
        j = i + 1
        while j < len(args) and not args[j].startswith("--"):
            j += 1
        extra = args[i + 1:j]
        del args[i:j]
    tpl, cat, work = args
    os.makedirs(os.path.join(work, "render"), exist_ok=True)
    res = {"template": tpl, "lint": {}, "renders": {}, "diff": {}, "render_available": True}

    # 1. lint
    lj = os.path.join(work, "lint.json")
    run([sys.executable, os.path.join(HERE, "lint_template.py"), tpl, cat, "--json", lj, "--quiet"])
    lint = json.load(open(lj, encoding="utf-8"))
    errs = [i for i in lint["issues"] if i["level"] == "error"]
    warns = [i for i in lint["issues"] if i["level"] == "warning"]
    res["lint"] = {"errors": len(errs), "warnings": len(warns),
                   "issues": [f"{i['level']} {i['code']} @ {i['where']}: {i['tag'][:80]}" for i in errs + warns][:40]}

    # 2. data
    ddir = os.path.join(work, "data")
    run([sys.executable, os.path.join(HERE, "make_sample_data.py"), cat, ddir])
    sets = [(d, os.path.join(ddir, f"data_{d}.json")) for d in DATASETS]
    sets += [(os.path.splitext(os.path.basename(x))[0], x) for x in extra]

    # 3. renders
    outs = {}
    for eng in engines:
        st = run(["bash", os.path.join(HERE, "setup_render.sh"), eng])
        if st.returncode != 0:
            res["render_available"] = False
            res["renders"][eng] = {"unavailable": (st.stderr or st.stdout).strip()[:300]}
            continue
        harness = st.stdout.strip().splitlines()[-1]
        res["renders"][eng] = {}
        for name, path in sets:
            out = os.path.join(work, "render", f"{eng}_{name}.docx")
            r = run(["node", os.path.join(harness, "render_check.mjs"), tpl, path, out])
            try:
                j = json.loads(r.stdout)
            except Exception:
                j = {"ok": False, "error": (r.stdout + r.stderr)[:300]}
            res["renders"][eng][name] = {
                "ok": bool(j.get("ok")), "engine": j.get("engine"), "error": j.get("error"),
                "message": (j.get("message") or "")[:200],
                "leftovers": [f"{(l.get('tags') or [''])[0]} - {l.get('context', '')[:90]}" for l in j.get("leftovers", [])][:8],
                "quickerImagePlugin": j.get("quickerImagePlugin")}
            outs[(eng, name)] = out

    # 4. v3 vs v8 content
    if all(isinstance(res["renders"].get(e), dict) and "unavailable" not in res["renders"][e] for e in ("v3", "v8")) \
            and "v3" in engines and "v8" in engines:
        import difflib
        for name, _ in sets:
            a, b = outs.get(("v3", name)), outs.get(("v8", name))
            if not (a and b and os.path.exists(a) and os.path.exists(b)):
                continue
            d = [x for x in difflib.unified_diff(render_lines(a, True), render_lines(b, True), n=0, lineterm="")
                 if x[:1] in "+-" and not x.startswith(("+++", "---"))]
            res["diff"][name] = d[:12] + ([f"... {len(d) - 12} more"] if len(d) > 12 else [])

    json.dump(res, open(os.path.join(work, "validation.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    failed = [(e, n) for e, rs in res["renders"].items() if "unavailable" not in rs for n, r in rs.items() if not r["ok"]]
    diffs = {n: d for n, d in res["diff"].items() if d}

    # 5. console summary
    print(f"lint: {len(errs)} errors, {len(warns)} warnings")
    for e, rs in res["renders"].items():
        if "unavailable" in rs:
            print(f"render {e}: UNAVAILABLE - {rs['unavailable']}")
            continue
        for n, r in rs.items():
            print(f"render {e} {n}: {'ok' if r['ok'] else 'FAILED'}" +
                  ("" if r["ok"] else f" - {r['error'] or ''} {r['message']} {r['leftovers'][:3]}"))
    for n, d in res["diff"].items():
        print(f"v3 vs v8 {n}: " + ("identical content" if not d else f"{len(d)} differing lines"))
        for x in d[:6]:
            print("   ", x[:140])

    # 6. report section (idempotent)
    if report and os.path.exists(report):
        L = ["## בדיקות", "",
             f"- lint: {len(errs)} שגיאות, {len(warns)} אזהרות"]
        L += [f"  - {x}" for x in res["lint"]["issues"][:15]]
        for e, rs in res["renders"].items():
            title = "v3.2.1 (ייצור)" if e == "v3" else "v8 (ענף השדרוג)"
            if "unavailable" in rs:
                L.append(f"- רינדור ניסיון {title}: **לא רץ** (אין node/npm או אין גישה ל-npm). "
                         "יש לנסות את התבנית על פרויקט אמיתי ב-Quicker לפני שימוש בדוחות.")
                continue
            parts = [f"{DS_HE.get(n, n)}: {'תקין' if r['ok'] else 'נכשל'}" for n, r in rs.items()]
            L.append(f"- רינדור ניסיון {title}: " + " | ".join(parts))
            for n, r in rs.items():
                if not r["ok"]:
                    L.append(f"  - {n}: {r['error'] or ''} {r['message']} {'; '.join(r['leftovers'][:3])}")
        if res["diff"]:
            L.append("- השוואת תוכן v3 מול v8: " + ("זהה בכל מערכי הנתונים" if not diffs else
                     "יש הבדלים - " + ", ".join(f"{n} ({len(d)} שורות)" for n, d in diffs.items())))
        if any(isinstance(rs, dict) and any(isinstance(r, dict) and r.get("quickerImagePlugin") is False
                                            for r in rs.values()) for e, rs in res["renders"].items() if e == "v8"):
            L.append("- תמונות מרובות וגרידים נבדקו בתחביר בלבד (תוסף התמונות של Quicker לא כלול בבדיקה).")
        L.append("")
        text = open(report, encoding="utf-8").read()
        text = re.sub(r"\n## בדיקות\n.*?(?=\n## |\Z)", "\n", text, flags=re.S).rstrip() + "\n\n"
        # put the section right after the header block (before "## סיכום" / the first section)
        m = re.search(r"\n## ", text)
        text = (text[:m.start()] + "\n" + "\n".join(L) + text[m.start():]) if m else text + "\n".join(L) + "\n"
        open(report, "w", encoding="utf-8").write(text)

    if errs or failed:
        sys.exit(1)
    if not res["render_available"]:
        sys.exit(4)
    sys.exit(0)


if __name__ == "__main__":
    main()
