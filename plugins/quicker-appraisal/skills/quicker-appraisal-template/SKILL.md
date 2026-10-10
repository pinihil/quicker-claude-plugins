---
name: quicker-appraisal-template
description: Turn Israeli real-estate appraisal Word reports (שומת מקרקעין, חוות דעת שמאי, any standard - bank/mortgage formats, היטל השבחה, מס שבח, ירושה, גירושין, ביטוח, מס רכוש) into Quicker easy-template-x templates. Reads the .docx design and structure, finds where variables belong - including empty slots and instructions the author typed into the document ([[...]], Word comments, highlights) - places tags from the live Quicker form catalog, builds conditions for words, paragraphs, whole sections and table rows, loops for repeating groups, supports angular-expressions filters and the html extension, then lints and test-renders the result. Use this whenever a user uploads or mentions a Word appraisal report or template and wants variables, תבנית, משתנים, תנאים, לולאות, מיפוי, easy-template-x tags, or wants an existing Quicker template checked or fixed - even if they don't say "template". Requires the Quicker connector.
---

# Quicker appraisal template builder

Turn a Word appraisal report into a Quicker template: same design, with `{...}` tags where data
changes per report, conditions around text that only sometimes applies, and loops over repeating
groups. The variables always come from the user's Quicker form (via the connector), never from memory.

Talk to the user in Hebrew. Keep technical detail in the mapping report, not in chat.

## The non-negotiables (and why)

1. **No Quicker connector -> stop.** Variable names differ per organization and per form; a template
   built on guessed names renders empty fields in production and nobody notices until a client does.
   If no Quicker tools are available (look for `get_word_template_variables` / `list_form_templates` /
   `get_form_template`, usually `mcp__Quicker__*`), reply in Hebrew that the template can't be created until Quicker is connected,
   explain how (Settings -> Connectors -> Quicker), and stop. You may still describe what you see in the
   document, but do not produce tags.
2. **Every tag must exist in the chosen form's catalog** (or in the system fields of the data contract).
   If a value has no matching variable, leave the text as-is and list it in the report under
   "ללא משתנה מתאים" - don't invent a field.
3. **Keep the design.** Never retype or rebuild the document. All edits go through `apply_plan.py`,
   which edits the original XML in place, so fonts, RTL, numbering, tables, text boxes, headers and
   footers survive.
4. **Validate before delivering.** `validate.py` must pass: 0 lint errors and every sample dataset
   rendered on both engines (v3 production, v8 branch). A template that fails at generation time is
   worse than none. If the render harness can't be installed (no node/npm, or no network access to the
   npm registry - `validate.py` exits 4), still deliver after a clean lint, but say plainly in Hebrew that
   the test render didn't run and the template must be tried on a real project in Quicker before it is
   used for reports.

## Workflow

### 1. Check the connector, pick the form, build the catalog

1. **Pick the form.** `list_form_templates` (system + custom) and, when available,
   `list_custom_form_templates` (the office's own forms, the appraisal types each serves, the default).
   Forms are system (`isSystem: true`, e.g. "שומת מקרקעין", "מס רכוש", "שומת רכוש") or org-custom; each
   has different fields. If the user didn't say which form, **ask** (AskUserQuestion), listing enabled
   forms with title and description, system vs custom, and recommend the one that fits the report type
   you see. A project id or an appraisal type the user mentions also identifies the form. Unattended:
   use the default form (`isDefault`) and say so in the report.
2. **Variables - `get_word_template_variables`** (`formTemplateId`, or `projectId` / `appraisalType`). It
   is the source of truth for tags: every variable's exact tag, label, type, syntax, choice options,
   loops, the system variables (`general`), the filter list and the engine rules. A large form comes in
   parts: call again with `sections` = the reply's `omittedSections` and `reference: false` until
   nothing is omitted. **Read every reply** - it is your reference while mapping. Don't retype the
   replies into files: the script already knows the system variables and filters as the tool listed
   them (October 2026). Replies that came back inline: after building the catalog, compare by eye the
   reply's `general` paths and `filters` names with the catalog's "System fields" and "Filters" lists;
   only if the reply has something the catalog lacks, write just those entries to `work/extra.json`
   (`[{"path","label","kind","tag"}]`) and rebuild with `--extra-system work/extra.json`. Replies the
   harness saved to files: pass them with `--vars` - then the tool's lists replace the built-in ones and
   its form variables are cross-checked against the form.
3. **Structure - `get_form_template(id)`.** It is large and is usually saved to a file (a `.txt` that holds
   the JSON) - copy that file to `form.json` (otherwise write the JSON to `form.json`). It adds what the variables tool doesn't carry:
   display conditions (the best source for section conditions), units (מ"ר vs ₪ - the tool types areas
   as `currency`) and the linked-field map. Prefer it over `get_form_template_schema`.

```bash
S="${CLAUDE_SKILL_DIR}/scripts"      # this skill's scripts folder
cd <work folder>                     # all paths below are relative to it
python3 $S/build_catalog.py form.json work/ [--vars reply1.json ...] [--extra-system work/extra.json]
# -> work/catalog.md + work/catalog.json
```

No form JSON at all (rare): `build_catalog.py --vars reply1.json reply2.json ... work/` - the replies must
then be saved with their `formVariables`, and the catalog has no display conditions or units.

Known gaps of `get_word_template_variables` (October 2026), all covered by the catalog:
`planDataStatus` is typed `html` but is a loop; areas are typed `currency`
without the מ"ר unit; display conditions and linked fields are missing. Where the reply and the catalog
disagree on these, follow the catalog.

Read `work/catalog.md` completely - first its **Notes** (a linked `p.*` field that points at a missing
form field, fields or option lists where the variables tool and the form disagree, sections still
omitted). It lists every variable as a ready-to-paste tag, grouped by form section, with options, loops (and what is in scope inside them), linked fields (`LINKED - use p.x`:
the house rule is to print linked values through `p.*`) and each field's display condition already
translated to template syntax: `shown-if` = the field's own display condition, `block-if` = the
condition of the form block the field sits in, `group condition` = the condition of a repeatable group.
Those conditions are the best source for section conditions - reuse them. Check them against the
report: a field whose condition excludes the report's case (e.g. hidden when `p.ad.referrer` is the bank
this report is for) is never filled for such reports - say so under decisions instead of mapping it
silently.

### 2. Read the document

```bash
python3 $S/docx_outline.py report.docx > work/outline.txt
```

Read the whole outline. Each paragraph has an ID (`P0042`, header `H1-003`, footer `F2-001`), its
location (`T3:r2c1`, `textbox`), style flags and text with markers (see the header of
`docx_outline.py`). Also look at the actual page if layout matters (tables of values, side-by-side
labels): `soffice --headless --convert-to pdf report.docx` and view a page or two.

Work out:
- **Header / footer** - does the document carry its own letterhead graphics? Keep them. If an existing
  header/footer is empty, ask whether to put the organisation's images there. Never create header or
  footer parts that don't exist (`references/quicker-contract.md` §5).
- **Report type and standard** (bank format? which bank? היטל השבחה? ...) - drives which form, which
  conditions, and what is boilerplate vs data. See `references/appraisal-domain.md`.
- **Author instructions** - `[[...]]` text, Word comments (`💬`), highlighted spans (`⟦hl:`). These are
  the user telling you exactly what they want; they override your own inference. Syntax and meaning:
  `references/author-markup.md`.
- **Existing tags** - keep valid ones; fix broken ones (the linter will find them); don't duplicate.
- **Data that changes per report** - concrete values (names, ID numbers, dates, amounts, areas, gush/helka,
  addresses, bank names, chosen options) and **empty slots** (a label followed by nothing, a tab, `____`,
  `XXX`, `..`, or an empty table cell next to/under a label). Both get a tag.
- **Text that only sometimes applies** - sections tied to a form option (שומה מורחבת, נכס בבנייה,
  חוזה שכירות, חריגות בנייה...), optional lines (`label: value` where the value may be empty),
  yes/no wording ("קיים/אין"), bank-specific paragraphs. These get conditions.
- **Repeating structures** - borrowers, owners, permits, plans, mortgages, notes, comparables, linkages:
  a table row or paragraph per item -> a loop. In a filled report the list appears N times: keep the
  first row/paragraph, delete the other samples (`delete_rows` / `delete_paragraph`) and loop the one
  that is left. Don't build "first item + additional items" constructions.
- **Before declaring "no variable"**: search the whole catalog, including linked `p.*` fields and
  fields inside repeatable groups (a single value that lives in a group is `p.ad.group[0].field`, or its
  linked `p.*` twin). If there really is none, keep the text (rule 2) - but a case value that stays
  hard-coded prints the wrong data in every future report, so list it under `unmatched` and mark it
  **חשוב** for the user to decide (static text, or a new form field).
- **Photo frames** - pictures (`[🖼 picture WxH]`) and text boxes holding pictures. A set of sample
  photos for one field becomes one image tag (`{p.ad.x | maxSize:w:h}`, `| grid:N` for a table) and the
  sample frames are removed (`delete_drawings`); one designed frame can become a v8 placeholder
  (`set_alt`). Never leave a client's photo in the template.

### 3. Write the plan

Write `work/plan.json`. Every change is one op, addressed by outline IDs, each with a short Hebrew
`note` explaining the mapping. Plan-level fields go straight into the Hebrew mapping report - use them
instead of writing the report by hand: `summary`, `decisions` (list), `unmatched` (list of
`{where, text, note}`), `v8_only` (list).

| op | use for |
|---|---|
| `replace` `{p, find, with, nth?/all?}` | a concrete value -> tag; `[[...]]` markup -> tag |
| `insert` `{p, text, after?/before?/at?}` | an empty slot after a label |
| `set_text` `{p, text}` | an empty table cell / a paragraph whose whole text becomes a tag (not for a paragraph holding pictures or text boxes - `insert` + `delete_drawings` there) |
| `delete` `{p, find, nth?/all?}` | sample-only text that must go |
| `wrap_inline` `{p, open, close, from_find?, to_find?}` | condition around part of one paragraph: from the start of `from_find` to the end of `to_find` (searched after it; may cross a line break `\n`); either one missing = paragraph start / end |
| `wrap_block` `{from, to, open, close}` | condition/loop around whole paragraphs and tables (same container); plan-level `"block_style": "own"` forces tag-only lines |
| `wrap_rows` `{table, from_row, to_row, open, close}` | conditional rows / one row per group item (1-2 rows per block; refuses 3+ rows and same-column cells) |
| `insert_paragraph` `{after/before, text, like?, id?}` | an alternative sentence (e.g. the "אין" branch); give it an `id` to target it in later ops |
| `delete_paragraph` `{p}` | instruction-only / marker paragraphs, sample paragraphs 2..N of a list |
| `delete_rows` `{table, rows}` | sample rows 2..N of a list table (then loop the remaining row) |
| `set_alt` `{p, nth, alt, neutral?}` | picture placeholder (v8): the image tag becomes the alt text of the nth picture of a paragraph; the sample picture becomes a grey box unless `"neutral": false` |
| `delete_drawings` `{p, nth?}` | remove sample pictures / photo text boxes from a paragraph |
| `strip_markup` `{markup, comments, highlight_on_tags}` | remove Word comments once their instructions are applied (and, if asked, leftover `[[...]]`) |

`wrap_block` accepts `"loop": false` / `true` to override loop detection (see step 4: pass `--catalog` and
you rarely need it). `replace`, `insert` and `set_text` accept `"format": {"bold": false}` (also `italic`, `underline`). Use it
when a value slot follows a bold label but values are regular weight elsewhere in the document - the new
tag otherwise inherits the formatting of the text before it.

Full examples are in the docstring of `scripts/apply_plan.py`. `find` is exact text within that one
paragraph as the outline shows it without the markers - except tabs and line breaks, which the outline
shows as ⇥ / ⏎ and which you write as `\t` / `\n` in the JSON. For exact spacing (several spaces in a row)
read `docx_outline.py report.docx --json out.json`. Ops run in phases (insert_paragraph -> text ->
delete_paragraph -> rows -> blocks -> delete_rows -> cleanup); IDs always refer to the original outline,
text ops on one paragraph run in plan order and each `find` sees the text as earlier ops left it, and
nested blocks are ordered automatically. A large document (hundreds of ops) is easier to plan with a
short Python script that writes `plan.json` than by hand.

Tag-writing rules - details and the tested reasons are in `references/template-syntax.md`:
- Questionnaire fields are `{p.ad.<name>}`; system fields are `p.*`, `c.*`, `today`... (`references/quicker-contract.md`).
- Inside a loop write bare field names: `{#p.ad.borrowers}{borrowerName}{/p.ad.borrowers}`.
- Closing tags repeat the opening expression exactly: `{#p.ad.x == 'כן'}...{/p.ad.x == 'כן'}`.
- Negation: `p.ad.x != 'v'` or `!p.ad.flag` - never `!p.ad.x == 'v'` (always false).
- Use only Quicker filters: `date`, `currency`, `fixed`, `list`, `includes`, `isEmpty`, `stripTag`, `html`,
  `lower`, image `maxSize/frame/rounded/align/gap/grid`, loops `inc/loopSep`.
- Format by type (the catalog already shows it): dates `| date`, money `| currency} ₪`, areas
  `| currency} מ"ר`, multi-select `| list:', '`, richtext `| html`, images `| maxSize:w:h`,
  checkboxes only as conditions.
- Whole optional paragraphs, chapters, paragraph loops: `wrap_block` only - never hand-place block tags.
  It puts each tag at the end of the paragraph before the boundary (the only placement that leaves no
  empty line on either engine) and keeps nesting right; when it has to fall back it says so in the
  report. An optional "label: value" line is a one-paragraph `wrap_block` on the value field.
- Table rows: `wrap_rows`. If every row of a table ends up inside loops/conditions, also wrap the table
  (and its caption) in a `.length` block - an empty group would otherwise leave a table with no rows,
  which Word reports as damaged. Inside a table cell or a numbered paragraph (`num` in the outline)
  don't open blocks at all - v3 (production) and v8 behave differently there; use a ternary value tag for
  optional words: `{p.ad.x ? ' - ' + p.ad.x : ''}`.
- Two blocks that are alternatives (שומה מורחבת / מקוצרת): `== 'A'` and `!= 'A'`, so exactly one prints
  even when the field is empty. Keep expressions short - a 200+ character expression is a sign the value
  should come from Quicker, not from the template.
- **Engines.** Production is v3.2.1; the v8 branch is about to deploy. Write templates that are correct
  on both (`references/template-syntax.md` §10). v8-only features - picture placeholders, `{^x}`,
  `[% options %]` - are allowed, but list them in the report ("works after the v8 deployment").
- `{p.ad.x | html}` alone in its paragraph (block HTML replaces the whole paragraph).
- **Images** (`references/quicker-contract.md` §5): `{p.ad.photos | maxSize:w:h}` prints every image of
  the field (one or many), `| grid:N` lays them out as a table; empty prints nothing, so no condition is
  needed. For one element per image (a row per photo with a caption) loop with `{image}` inside:
  `{#p.ad.photos}{image | maxSize:400:300}{/p.ad.photos}`. Never `.length` on an image field and avoid
  `[n]` (a field with one image is an object). A single designed photo frame can become a placeholder
  (`set_alt`, v8 only, alt text = the tag only, `| maxSize` = the frame size from the outline).
- Layouts that need a known pattern (template-syntax.md §5-6): a block that ends right after a table
  (include the empty paragraph after the table, if there is one); an item that spans two table rows with
  a merged second row (loop the whole table, inside a `.length` block); a list nested inside a table cell
  (no loop in cells - print `group[0].field` and flag it); an empty text-box frame meant for a photo
  (`delete` its padding, `insert` the image tag, `delete_drawings` the frame); a heading over an image
  grid (condition on the heading only - the grid tag stays alone in its paragraph).
- Keep conditions minimal and meaningful. A condition on every single line makes the template
  unmaintainable; wrap the lines whose label would otherwise hang empty or whose text is wrong for
  some reports.
- **Details of a form question print under the question's answer.** When the catalog gives a field a
  `shown-if` (the antiquities map opens on "הנכס בתחום אתר עתיקות"), wrap the lines that print it in
  that condition, not only in `{#p.ad.x}`: a hidden field keeps its old value, so a map uploaded before
  the answer changed to "לא נבדק" would still print. Each answer gets its own wording - "לא נבדק"
  prints the office's sentence for an unchecked item (an assumption), never the "no" wording.

### 4. Apply and validate

```bash
python3 $S/apply_plan.py report.docx work/plan.json out/<name>_template.docx \
        --report out/<name>_mapping_report.md --catalog work/catalog.json
python3 $S/validate.py out/<name>_template.docx work/catalog.json work/ --report out/<name>_mapping_report.md
```

- `apply_plan.py` exits non-zero if any op failed (text not found, bad ID); fix the plan and rerun from
  the original report - never apply a plan on top of an already-tagged output. It also removes from
  the package every image that no longer appears in the document (deleted sample photos), and prints
  the counts (value tags, conditions, loops) for the summary.
- `validate.py` runs everything: lint, five sample datasets (`full` = first option of every select,
  `alt` = last option, `empty`, `mixed`, `off` = last option with every checkbox, group and image empty),
  test renders on v3 (production) and v8, and a v3-vs-v8 content diff; it writes `work/validation.json`
  and the "בדיקות" section of the mapping report (re-running replaces it). Exit 0 = clean; 1 = lint
  errors or a failed render (the console names them); 4 = the render harness couldn't be installed ->
  deliver after a clean lint with the caveat (non-negotiable 4).
- Fix every lint **error**. Review warnings: `anonymous-close`, `legacy-name` and `undocumented-field`
  are acceptable in tags you didn't write (existing templates) but not in new ones.
- A failed render names the cause: an engine error (the template is broken), tags that survived (a typo -
  or, on v3 only, a v8 placeholder, which is expected), a table that lost all its rows, or a value that
  printed as `[object Object]` / `undefined` / `NaN` (a list or object printed as text, or a wrong
  filter). The harness is stricter than production, which silently prints a failing tag empty.
- A combination the five datasets miss (e.g. one specific checkbox off): copy `work/data/data_alt.json`,
  change the field, and pass it with `--data`.
- Read the renders, not only the verdicts: `python3 $S/diff_renders.py work/render/v3_full.docx
  work/render/v3_empty.docx` (conditional sections appear/disappear as intended, nothing reads oddly like
  "גוש: , חלקה:"), or convert one to PDF. Any v3-vs-v8 difference that is not a v8-only feature is a
  construct the engines treat differently - fix it.

### 5. Deliver

- Save the template next to the source (or in the outputs folder) as `<original name>_template.docx`,
  plus the mapping report.
- Empty lines that `apply_plan` warned about (a closer after a table, a loop after a numbered heading)
  are the engine's cost - mention them in one line, don't hide them.
- In chat (Hebrew, short): which form was used; how many variables, conditions and loops (take them
  from apply_plan's `counts`, not from memory); the validation result; anything that needs a decision
  (values with no matching field, ambiguous choices, conditions you inferred rather than were told);
  bugs found in pre-existing tags.
- Next step for the user: upload in Quicker (הגדרות ← טפסי שומה מותאמים ← תבניות מסמכים) or open in
  Word with the Quicker add-in and run "זיהוי ביטויים".
- **Values with no field** (`unmatched` marked חשוב): offer, in one line, to add them to the office's
  form with the **quicker-appraisal-form** skill (it plans the fields from this report, the user approves,
  Quicker applies). Keep `work/plan.json` and the outline - that skill starts from them. After the form
  changes, rebuild the catalog (`get_word_template_variables` + `get_form_template` again), map the
  values in a follow-up plan on the original report, and validate again. Only for an office form: a
  system form is copied for the office first, and the template must then be uploaded to that copy.

## Other entry points

- **"Check / fix my template"** (the document already has tags): build the catalog for its form, run
  `validate.py`, explain findings in Hebrew, and fix errors with a plan
  (`replace` on the broken tag text). Don't rewrite `{/}` closers or legacy names in a working
  template unless asked - report them.
- **Partially tagged documents**: map only what is missing; keep existing tags unless they are wrong.
- **Several documents**: build the catalog once, then outline -> plan -> apply -> validate per file.

## Reference files

- `references/quicker-contract.md` - the render data model: `p` / `p.ad` / `c` / loops / images /
  filters, what does not exist, open points to confirm. Read before writing the first tag.
- `references/template-syntax.md` - easy-template-x + angular expressions as Quicker uses them, the
  tested block/row patterns and the pitfalls the linter catches. Read before writing conditions/loops.
- `references/author-markup.md` - the `[[...]]` / comment / highlight instruction language users can
  type into Word (Hebrew). Read whenever the outline shows markup, comments or highlights.
- `references/appraisal-domain.md` - anatomy of Israeli appraisal reports, how values look, which
  variable usually fits, which sections are conditional. Read when mapping a report without markup.
