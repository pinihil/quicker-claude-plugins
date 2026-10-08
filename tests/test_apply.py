#!/usr/bin/env python3
"""Regression checks for apply_plan.py on a fictional document (needs python-docx + Pillow).
Usage: python3 tests/test_apply.py <catalog.json>"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from docx import Document
from docx.shared import Inches
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "plugins/quicker-appraisal/skills/quicker-appraisal-template/scripts")
cat = sys.argv[1]
w = tempfile.mkdtemp()
photo = os.path.join(w, "client_photo.png")
Image.new("RGB", (64, 48), (200, 30, 30)).save(photo)

d = Document()
d.add_paragraph("תמונות הנכס:")
d.add_paragraph().add_run().add_picture(photo, width=Inches(1))       # P0002 - sample photo to delete
d.add_paragraph("לבניין יש לובי.")                                     # P0003 - checkbox condition
t = d.add_table(rows=2, cols=2)                                        # T1 - borrowers
t.rows[0].cells[0].text, t.rows[0].cells[1].text = "שם", "ת.ז"
t.rows[1].cells[0].text, t.rows[1].cells[1].text = "ישראל ישראלי", "012345678"
d.add_paragraph("סוף")                                                 # P0006
src = os.path.join(w, "in.docx")
d.save(src)

plan = {"ops": [
    {"op": "delete_drawings", "p": "P0002"},
    {"op": "insert", "p": "P0002", "at": "start", "text": "{p.ad.propertyImages | maxSize:300:200 | grid:2}"},
    {"op": "wrap_block", "from": "P0003", "to": "P0003", "open": "{#p.ad.lobby}", "close": "{/p.ad.lobby}"},
    {"op": "set_text", "p": "P0004", "text": "{#p.ad.borrowers}{borrowerName}"},
    {"op": "set_text", "p": "P0005", "text": "{borrowerId}{/p.ad.borrowers}"},
]}
# P0004/P0005 are the cells of row 2 in the outline order - look them up instead of guessing
outline = subprocess.run([sys.executable, os.path.join(S, "docx_outline.py"), src], capture_output=True, text=True).stdout
ids = [l.split()[0] for l in outline.splitlines() if l.startswith("P") and "T1:r2" in l]
plan["ops"][3]["p"], plan["ops"][4]["p"] = ids[0], ids[1]
pp = os.path.join(w, "plan.json")
json.dump(plan, open(pp, "w"), ensure_ascii=False)
out = os.path.join(w, "out.docx")
r = subprocess.run([sys.executable, os.path.join(S, "apply_plan.py"), src, pp, out, "--catalog", cat],
                   capture_output=True, text=True)
res = json.loads(r.stdout)
fails = []
if res["errors"]:
    fails.append(f"apply errors: {res['errors']}")
media = [n for n in zipfile.ZipFile(out).namelist() if n.startswith("word/media/")]
if media:
    fails.append(f"deleted sample photo still in the package: {media}")
if res["counts"]["loops"] != 1 or res["counts"]["conditions"] != 1:
    fails.append(f"loop/condition counts wrong: {res['counts']}")
xml = zipfile.ZipFile(out).read("word/document.xml").decode()
grid_para = [l for l in subprocess.run([sys.executable, os.path.join(S, "docx_outline.py"), out], capture_output=True,
                                       text=True).stdout.splitlines() if "| grid" in l]
if not grid_para or "{#" in grid_para[0] or "{/" in grid_para[0]:
    fails.append(f"block tag anchored on the grid paragraph: {grid_para}")
if "<w:highlight" in xml:
    fails.append("a highlight leaked into the template")
for f in fails:
    print("FAIL:", f)
print("apply_plan regression:", "FAILED" if fails else "ok", res["counts"])
sys.exit(1 if fails else 0)
