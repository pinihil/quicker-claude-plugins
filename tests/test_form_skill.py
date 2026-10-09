#!/usr/bin/env python3
"""
Regression test for the quicker-appraisal-form scripts on a fictional office form.

    python3 tests/test_form_skill.py <work dir> <fixture.docx>

- form_index: indexes the form (groups, nested groups, hidden, links, org lists), --find works
- check_ops: every op of tests/fixtures/form-ops.json gets the status in its "expect" list (the
  statuses were checked against the Quicker engine), the payload drops "why", a system form is refused
- checklists.json: every item is well-formed and its suggested name passes the server's name rule
- report_inventory + gap_check: run on the fixture report and produce findings
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
    assert len(idx["topLevelNames"]) == 16, idx["topLevelNames"]
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
    assert "ownerReps" in out and "get_word_template_variables" in out, "depth-3 group warns about the variables tool"
    assert "השדה ייכנס לכרטיס" in out, "placing after a field of a conditional card warns (the engine joins the card)"
    preview = open(os.path.join(work, "preview.md"), encoding="utf-8").read()
    assert "טבלת הגמר בדוח" in preview, "the op's why reaches the review table"

    good = {"templateId": spec["templateId"], "ops": [op for op, want in zip(spec["ops"], spec["expect"]) if want != "ERR"]}
    gpath = os.path.join(work, "good-ops.json")
    json.dump(good, open(gpath, "w", encoding="utf-8"), ensure_ascii=False)
    run(os.path.join(S, "check_ops.py"), form, gpath, "--payload", payload)
    sent = json.load(open(payload, encoding="utf-8"))
    assert all("why" not in op for op in sent["ops"]), "why is stripped (the server rejects unknown keys)"
    assert sent["templateId"] == spec["templateId"]

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
