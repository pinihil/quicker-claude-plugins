#!/usr/bin/env python3
"""
Regression test for the quicker-appraisal-form scripts on a fictional office form.

    python3 tests/test_form_skill.py <work dir> <fixture.docx>

- form_index: indexes the form (groups, nested groups, hidden, links, org lists), --find works
- check_ops: every op of tests/fixtures/form-ops.json gets the status in its "expect" list (the
  statuses were checked against the Quicker engine), the payload drops "why", a system form is refused
- checklists.json: every item is well-formed and its suggested name passes the server's name rule
- report_inventory + gap_check: run on the fixture report and produce findings
- display logic (formlogic / audit_form): the condition evaluator agrees with the browser's rules, a detail
  shown for every answer of its question is found with a ready condition, a negated condition and an
  option that doesn't exist are found, the suggested fixes pass check_ops, and check_ops flags the
  same mistakes in new ops
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "plugins", "quicker-appraisal", "skills", "quicker-appraisal-form", "scripts")
FIX = os.path.join(ROOT, "tests", "fixtures")
NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
sys.path.insert(0, S)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
from formlogic import UNKNOWN, UDict, classify, condition_value  # noqa: E402
TYPES = {"text", "textarea", "richtext", "number", "currency", "date", "select", "selectOther", "radio",
         "checkbox", "checkboxList", "image", "textPom", "textSod", "group"}


def run(*args, ok=(0,)):
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if p.returncode not in ok:
        sys.exit(f"FAILED ({p.returncode}): {' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def main():
    work, docx = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    form = os.path.join(FIX, "org-form.json")

    # form_index
    run(os.path.join(S, "form_index.py"), form, work)
    idx = json.load(open(os.path.join(work, "form_index.json"), encoding="utf-8"))
    n = idx["nodes"]
    assert "extract.extractOwners.ownerShare" in n, "nested group child indexed"
    assert n["extract.extractOwners"]["depth"] == 2
    assert n["oldNotes"].get("hidden") is True
    assert n["referrer"].get("orgList") == "referrerOptions", "referrer is an organization list (projectFieldsMap)"
    assert n["determinesDate"].get("linkedTo") == ["determinesDate"]
    assert n["leaseEnd"].get("if")
    assert n["extendedNotes"].get("rowIf"), "a field in a conditional card carries the card's condition"
    assert len(idx["topLevelNames"]) == 20, idx["topLevelNames"]
    out = run(os.path.join(S, "form_index.py"), form, "--find", "ריצוף מטבח")
    assert "livingRoomFloorType" in out, out

    # check_ops - statuses equal what the Quicker engine answered for the same ops
    spec = json.load(open(os.path.join(FIX, "form-ops.json"), encoding="utf-8"))
    payload = os.path.join(work, "payload.json")
    out = run(os.path.join(S, "check_ops.py"), form, os.path.join(FIX, "form-ops.json"),
              "--md", os.path.join(work, "preview.md"), ok=(1,))
    got = re.findall(r"^(OK|WARN|ERR|NOOP)\s+#(\d+)", out, re.M)
    statuses = [s for s, _ in got]
    assert len(statuses) == len(spec["expect"]), (len(statuses), out)
    for i, (want, have) in enumerate(zip(spec["expect"], statuses)):
        # an op the engine accepts may carry advice (WARN); an op it refuses must be ERR
        if want in ("OK", "WARN"):
            assert have in ("OK", "WARN"), f"op #{i}: expected accepted, got {have}\n{out}"
        else:
            assert have == want, f"op #{i}: expected {want}, got {have}\n{out}"
    assert "get_word_template_variables" not in out, "depth-3 groups reach the variables tool since October 2026 - no warning"
    assert "השדה ייכנס לכרטיס" in out, "placing after a field of a conditional card warns (the engine joins the card)"
    logic = out[out.index("Display logic"):] if "Display logic" in out else ""
    assert "FIX  antiquitiesDeclaration" in logic and "antiquitiesSite == 'הנכס בתחום אתר עתיקות'" in logic, \
        "a new detail without the question's condition is a FIX with a ready condition\n" + out
    assert re.search(r"ERR  #\d+ add_field antiquitiesImpact", out) and "שאינו אחת מהאפשרויות שלו" in out, \
        "a condition on a value that isn't an option is refused, as the server does"
    import check_ops  # noqa: E402
    tips = []
    check_ops.advise({"name": "x", "type": "textarea", "label": "השפעת אתר העתיקות על השווי",
                      "aiConfig": {"prompt": "x"}}, tips.append, [], "x")
    assert any("עדיף richtext" in t for t in tips), "detailed text in a textarea is advised to be richtext"
    preview = open(os.path.join(work, "preview.md"), encoding="utf-8").read()
    assert "טבלת הגמר בדוח" in preview, "the op's why reaches the review table"

    good = {"templateId": spec["templateId"], "ops": [op for op, want in zip(spec["ops"], spec["expect"]) if want != "ERR"]}
    gpath = os.path.join(work, "good-ops.json")
    json.dump(good, open(gpath, "w", encoding="utf-8"), ensure_ascii=False)
    run(os.path.join(S, "check_ops.py"), form, gpath, "--payload", payload)
    sent = json.load(open(payload, encoding="utf-8"))
    assert all("why" not in op for op in sent["ops"]), "why is stripped (the server rejects unknown keys)"
    assert sent["templateId"] == spec["templateId"]

    rep = os.path.join(work, "out", "changes.md")
    run(os.path.join(S, "change_report.py"), form, gpath, "--out", rep)
    text = open(rep, encoding="utf-8").read()
    assert "מתוכנן - טרם בוצע" in text and "שם פנימי: `kitchenFloorType`" in text, "the manual-entry spec"
    assert "מה כל תשובה מציגה" in text, "the spec shows what each answer of a touched question opens"

    sysform = json.load(open(form, encoding="utf-8"))
    sysform["isSystem"] = True
    spath = os.path.join(work, "system-form.json")
    json.dump(sysform, open(spath, "w", encoding="utf-8"), ensure_ascii=False)
    out = run(os.path.join(S, "check_ops.py"), spath, gpath, ok=(1,))
    assert "SYSTEM form" in out

    # checklists
    cl = json.load(open(os.path.join(S, "..", "assets", "checklists.json"), encoding="utf-8"))
    assert "base" in cl["types"]
    for t, spec_t in cl["types"].items():
        ids = set()
        for it in spec_t["items"]:
            assert it["id"] not in ids, f"{t}: duplicate id {it['id']}"
            ids.add(it["id"])
            assert it["level"] in ("required", "conditional", "recommended"), it
            assert it["basis"] and it["match"], it
            sug = it.get("suggest") or {}
            assert NAME_RE.match(sug.get("name", "")), f"{t}.{it['id']}: bad suggested name {sug.get('name')}"
            assert sug.get("type") in TYPES, f"{t}.{it['id']}: bad type {sug.get('type')}"
            if sug.get("type") in ("select", "radio", "checkboxList"):
                assert sug.get("values"), f"{t}.{it['id']}: a choice suggestion needs values"
            for det in sug.get("details") or []:
                assert NAME_RE.match(det["name"]) and det["type"] in TYPES and det.get("label"), f"{t}.{it['id']}: {det}"
                assert sug.get("opensOn") in sug.get("values", []), f"{t}.{it['id']}: opensOn is one of the values"
            if sug.get("details"):
                assert any(classify(v) == "unknown" for v in sug["values"]), f"{t}.{it['id']}: a check needs 'לא נבדק'"

    # display logic: evaluator, audit, suggested fixes
    assert condition_value("project.additionalDetails.a != 'לא'", {}) is True, "a negated condition opens on empty"
    assert condition_value("['x', 'y'].includes(project.additionalDetails.a)", {"a": "y"}) is True
    assert condition_value("project.additionalDetails.l.includes('b')", {}) is False, "a member of empty is empty"
    assert condition_value("project.additionalDetails.l", {"l": []}) is True, "[] is truthy, as in JavaScript"
    assert condition_value("project.additionalDetails.n == 7", {"n": "7"}) is True, "loose equality"
    assert condition_value("project.additionalDetails.a == 'x' && project.additionalDetails.b == 'y'",
                           UDict(a="x")) is UNKNOWN, "a field not under test is unknown"
    assert condition_value({"logic": "or", "conditions": [{"field": "a", "operator": "contains", "value": "ב"}]},
                           {"a": ["א", "ב"]}) is True, "structured contains works on a list (client semantics)"
    assert [classify(o) for o in ("לא נבדק", "אין צו מבנה מסוכן", "הנכס אינו בתחום", "הוכרז")] == \
        ["unknown", "negative", "negative", "positive"]
    # the same mistakes in other shapes - not only antiquities (an in-memory form)
    from formlogic import audit, _topic_match  # noqa: E402
    assert classify("הנכס אינו מוגדר כמבנה מסוכן, אך מבנה סמוך מוגדר כמסוכן") == "positive", "a qualified 'no' is a finding"
    assert _topic_match("מסוכנ", "המסוכנימ"), "prefix + plural"
    rows = [{"fields": [
        {"name": "riskNotes", "type": "textarea", "label": "פירוט מבנים מסוכנים"},
        {"name": "loanKind", "type": "radio", "label": "סוג ההלוואה", "values": ["מכוונת", "לא מכוונת"]},
        {"name": "loanFile", "type": "text", "label": "מספר תיק ההלוואה"},
        {"name": "dangerous", "type": "radio", "label": "מבנה מסוכן",
         "values": ["הוכרז מבנה מסוכן", "אין צו", "לא נבדק"]},
        {"name": "dangerousCheckDate", "type": "date", "label": "תאריך בדיקת רשימת המבנים המסוכנים"},
        {"name": "oldCheck", "type": "checkbox", "label": "בדיקה ישנה", "hidden": True},
        {"name": "oldCheckPhoto", "type": "image", "label": "צילום הבדיקה הישנה"},
        {"name": "plansNearby", "type": "radio", "label": "תוכניות בהפקדה בסביבה", "values": ["קיימות", "אין"]},
        {"name": "antennasMap", "type": "image", "label": "צילום אנטנות סלולריות (GovMap)"}]}]
    mem = {"schema": {"s": rows}, "metadata": {"sections": {"s": {"title": "בדיקות"}}}}
    got = {(f["kind"], f["path"]): f for f in audit(mem)}
    assert ("ungated", "dangerousCheckDate") in got and "לא נבדק" not in got[("ungated", "dangerousCheckDate")]["suggest"] \
        and "אין צו" in got[("ungated", "dangerousCheckDate")]["suggest"], "a check date opens on every checked answer"
    assert ("ungated", "riskNotes") in got, "a detail placed before its question is found"
    assert ("ungated", "loanFile") not in got, "the other fields of a 'סוג ...' question are not its details"
    assert not any(p == "oldCheckPhoto" for _, p in got), "a hidden question opens nothing"
    assert ("no-unchecked-answer", "plansNearby") in got, "a planning check without 'לא נבדק'"
    assert ("check-without-question", "antennasMap") in got, "evidence of a check with no question"

    run(os.path.join(S, "audit_form.py"), form, work, "--ops-out", os.path.join(work, "fix_ops.json"))
    findings = json.load(open(os.path.join(work, "audit.json"), encoding="utf-8"))
    kinds = {(f["kind"], f["path"]) for f in findings}
    assert ("ungated", "antiquitiesMap") in kinds, "the map shown for every answer is found"
    assert ("opens-unanswered", "dangerousDetails") in kinds, "a negated condition is found"
    amap = next(f for f in findings if f["path"] == "antiquitiesMap")
    assert amap["suggest"] == "project.additionalDetails.antiquitiesSite == 'הנכס בתחום אתר עתיקות'", amap
    report = open(os.path.join(work, "audit.md"), encoding="utf-8").read()
    assert "מפת התנאים" in report and "| לא נבדק |" in report
    out = run(os.path.join(S, "check_ops.py"), form, os.path.join(work, "fix_ops.json"))
    assert "0 errors" in out and "FIX " not in out, "the suggested fixes pass and leave nothing to fix\n" + out

    # report_inventory + gap_check on the fixture report
    outline = os.path.join(work, "outline.json")
    with open(os.path.join(work, "outline.txt"), "w", encoding="utf-8") as fh:
        fh.write(run(os.path.join(S, "docx_outline.py"), docx, "--json", outline))
    run(os.path.join(S, "report_inventory.py"), outline, work, "--form", os.path.join(work, "form_index.json"))
    inv = json.load(open(os.path.join(work, "inventory.json"), encoding="utf-8"))
    assert inv["items"], "the fixture report yields data points"
    assert all("verdict" in it for it in inv["items"])
    out = run(os.path.join(S, "gap_check.py"), os.path.join(work, "form_index.json"), "--type", "mortgage",
              "--inventory", os.path.join(work, "inventory.json"), "--md", os.path.join(work, "gaps.md"))
    assert "base" in out and "mortgage" in out, out
    gaps = open(os.path.join(work, "gaps.md"), encoding="utf-8").read()
    assert "| ✓ | המועד הקובע |" in gaps, "determinesDate found"
    assert "| ✗ | תרשים הנכס |" in gaps, "451 sketch missing in the fixture form"
    print(f"form skill: index {len(n)} nodes, {len(statuses)} ops checked, {len(inv['items'])} report items - OK")


if __name__ == "__main__":
    main()
