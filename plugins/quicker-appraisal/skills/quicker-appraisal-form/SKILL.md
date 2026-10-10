---
name: quicker-appraisal-form
description: Design, create and update an appraisal office's own form (טופס שומה מותאם) in Quicker through the connector - built from the office's own report formats and checked against Israeli appraisal standards (תקני שמאות 1.1, 2.1, 3.1, 4.2-8.1, 9.1, 17.1, 19, 20, 21.1, 22), the ethics regulations, bank practice (הוראה 451) and authority procedures (היטל השבחה, 197, הפקעות, רמ"י). Adds fields, options, sections, repeating groups, display conditions and AI Fill prompts; hides fields; copies a system form for the office; rolls a form back to an earlier version - always as a plan the user approves before anything changes. Use whenever a user wants to add or change fields in a Quicker form, build a form for a report type or a bank, align a form with a standard, asks "what is missing in our form", or after quicker-appraisal-template found report values with no matching field - even if they don't say "form". Requires the Quicker connector.
---

# Quicker appraisal form builder

Turn an appraisal office's own report formats into the form its appraisers fill in Quicker: the
fields its reports print, in the order its reports print them, with the options, conditions and AI
Fill prompts that make the form fast to fill - and checked against what the law, the standards and
the ordering body require. Changes go through Quicker's plan -> approve -> apply tools, so nothing
changes until the user agrees, and every change can be rolled back.

Talk to the user in Hebrew, in appraisers' language. Keep JSON, paths and engine detail out of chat
unless asked; show tables.

## Principles (and why)

1. **The office's formats are the source of truth.** The form exists to produce *this office's*
   reports. Build it from the office's own reports and templates (attached Word files, the template the
   user just mapped, the report types they describe). The standards are a completeness check and a
   source of good suggestions - not a generic form to impose. If the user asks for form work and no
   report format is in sight, ask once for one or two representative reports; build from standards
   alone only if they say they have none or want that.
2. **Nothing changes without an approved plan.** `plan_form_template_changes` changes nothing; show
   the user the plan (its `summaryHe` exactly as written + the impact + your reasons) and call
   `apply_form_template_changes` only after an explicit "yes" in this conversation. Unattended: plan,
   write the report, stop.
3. **Project data is sacred.** A field's internal name is its data key and its Word tag - it never
   changes. Retire fields by hiding, not removing. Never create a second field for a value the form or
   the project card already holds (`p.gush`, `p.determinesDate`, the customer's ID...).
4. **Fewer, better fields.** Every field is typed by an appraiser on every project, often on a phone at
   the visit. Boilerplate stays in the template, the appraiser's own details in the settings,
   calculations in the template. A form that mirrors the report's order and uses choice fields where
   the report branches is filled twice as fast.
5. **Be exact about the rules.** Say which standard and version a requirement comes from, separate law
   (תקנות האתיקה) from standards (a professional norm, binding only where legislation says so, e.g.
   22) from practice (a bank's format). `references/standards.md` marks what couldn't be verified -
   don't present those as certain.
6. **No connector, no form work.** Without the Quicker tools (`list_custom_form_templates`,
   `get_form_template`, `plan_form_template_changes`, usually `mcp__Quicker__*`) say in Hebrew that
   Quicker must be connected (Settings -> Connectors -> Quicker) and stop. Read tools present but no
   editing tools: the user lacks the permission to edit the office's settings, or their Quicker
   version doesn't have form editing yet - you can still analyse and write the change list for a
   manager or the form builder; say so.
7. **Know up front whether you can apply.** Apply is off when `apply_form_template_changes` is not
   among your tools, or when a plan reply says `applyAvailable: false` (Quicker's default for an
   office). Then say so *before* asking for approval, so the user isn't asked to approve something
   that won't happen.
8. **Show only what applies.** Much of a form is a question and the details it opens (אתר עתיקות ->
   the map; מבנה מסוכן -> the order). Details open only on the answer they describe - the antiquities
   map on "בתחום", not on "אינו בתחום" or "לא נבדק" - and checks from an outside source always offer
   "לא נבדק". A map upload under "לא נבדק" is the kind of thing that makes appraisers stop trusting a
   form.

**Quicker paths** (write Hebrew paths with ←):
- the office's option lists (גורם מפנה, מטרת השומה, סוג נכס...): הגדרות ← אפשרויות בחירה ← אפשרויות
  בחירה בפרטי פרויקט. The office ticks values from Quicker's built-in list; a value it doesn't offer
  needs Quicker support. `get_option_list({field})` gives the active values' exact text.
- enabling the editing tools: הגדרות ← בינה מלאכותית ← הגדרות MCP ← "כלים מורשים לסוכני AI" (managers).
- the form builder and Word templates: הגדרות ← טפסי שומה מותאמים.

## Workflow

```bash
S="${CLAUDE_SKILL_DIR}/scripts"      # this skill's scripts
cd <work folder>                     # paths below are relative to it
```

### 1. Pin down the target

- **Which form.** `list_custom_form_templates` (the office's forms, their appraisal types, the default)
  and, if needed, `list_form_templates`. Infer from the request (bank, appraisal type, form name); ask
  (AskUserQuestion) only when it's really ambiguous. A system form is never edited - if the office has
  no form of its own for this work, the plan starts with a copy (see "Creating a form").
- **Which formats.** The office's reports/templates for this form: attached files, the file the
  template skill just mapped, or ask for them. Several banks or report types on one form -> one report
  of each.
- **Which appraisal type and standards** (`gap_check.py --list` shows the types): mortgage for a bank,
  `collateral19`, `betterment`, `rmi`, `urbanRenewal21`, `court`... Usually obvious from the report;
  `scripts/docx_outline.py` prints report-type hints at the top.

### 2. Load and index the form

`get_form_template(id)` is ~100KB and usually saved to a file - copy that file to `form.json`.
```bash
python3 $S/form_index.py form.json work/          # -> work/form_index.md (+ .json)
python3 $S/form_index.py form.json --find "ריצוף"   # fields whose label/name looks like it
```
Read `work/form_index.md`: tabs, sections, every field with its path, type, options, condition,
`-> p.x` links, `[org list]` (options owned by the office settings), `[hidden]`, `[AI]`, and groups
three levels deep (the deepest level). Note the form's `version` - the plan is checked against it.

```bash
python3 $S/audit_form.py form.json work/ [--section <key>]   # -> work/audit.md: display logic as appraisers see it
```
It lists details shown for every answer of their question, conditions that compare to options that
don't exist, negated conditions, broken chains, checks with no "לא נבדק", and a "מפת התנאים" (what
each answer shows). Read it for the sections you'll touch: your new fields must not repeat those
patterns, and existing problems go to the findings (Scope, step 5).

### 3. Read the office's formats

```bash
python3 $S/docx_outline.py report.docx --json work/outline.json > work/outline.txt
python3 $S/report_inventory.py work/outline.json work/ --form work/form_index.json   # -> work/inventory.md
```
Read `outline.txt` and `inventory.md` together. The inventory lists every label/value pair, empty slot,
table row and repeating table it could find, under its heading, with a value kind and the closest
existing fields (`exists` / `maybe` / `new`). It is heuristic: confirm each verdict yourself, and look at
the page (`soffice --headless --convert-to pdf`) when tables carry the data.

For each data point decide - and keep the decision, it goes into the report:
- **exists** -> nothing to add (the template maps to it). Check `form_index.py --find` before
  believing "new": appraisers word the same thing differently ("שטח רשום" / "שטח לפי נסח").
- **new field** -> design it (step 5).
- **not a field** -> fixed text / settings / a project column / a calculation (`references/form-design.md` §2).
- **existing field, wrong shape** -> `update_field` (label, options, condition, prompt) or a new field
  + `hide_field` when the type can't convert.

Coming from **quicker-appraisal-template** with values left over: start from its `work/plan.json` -
`unmatched` (values left as fixed text, marked חשוב) are the candidates, and `decisions` may flag
mapped values that print empty because a form condition hides their field for this bank or case;
fixing those conditions serves the same goal, so they belong in the plan (labelled). That is the whole
scope - the inventory and gap check are optional here; raise only required gaps that touch the same
values or are date-driven (9.1). Check which form the template was mapped against:
```bash
python3 $S/form_index.py form.json --check-tags work/plan.json   # every p.ad tag exists here? same form?
```
If it was mapped against the system form while the office works on its own form, the new fields go into
the office's form, the template must be used with that form, and the follow-up
`get_word_template_variables` uses the office form's id. After apply, hand back: the template skill
re-reads the variables and maps the values.

### 4. Check against the standards and practice

```bash
python3 $S/gap_check.py work/form_index.json --type mortgage [--type collateral19] \
        --inventory work/inventory.json --md work/gaps.md
```
`base` (ethics regulations + standard 1.1 + section standards) is always included. Each item shows
whether the form has it (✓; ~ = only partly - hidden, something close, or a free-text box where a table
or an amount is needed; ✗ = nothing), whether the office's report shows it, its level (חובה /
כשרלוונטי / מומלץ) and source, and a suggested field. Matching is by words - confirm every ✓ and ✗
against `form_index.md` before you report it.
Read `references/standards.md` for the items you raise.

How to use the gaps:
- **In the report, not in the form** -> strong candidate: the office prints it, appraisers retype it.
- **Required, in neither** -> raise it with the user as a finding with its source ("תקן 19 §4.15 מחייב
  שיעור הנחת מכירה כפויה - לא מופיע בדוח ולא בטופס"). Many offices keep such items as fixed text or
  outside Quicker; add a field only if they want it filled per project.
- **Recommended, in neither** -> mention briefly; don't pad the form.
- Date-driven: from 1.1.2027 standard 9.1 changes the apartment area (balconies outside it) - offer the
  fields when the form serves residential reports signed from then.

### 5. Design the changes

Write `work/ops.json`:
```json
{ "templateId": "<form id>", "note": "שדות מהדוח לבנק מזרחי טפחות + תקן 19",
  "ops": [
    {"op": "add_field", "section": "propertyFields", "after": "bathroomFloorSize",
     "field": {"name": "kitchenFloorType", "label": "סוג ריצוף במטבח", "type": "selectOther",
               "values": ["קרמיקה", "טארצו", "פרקט", "אריחי שיש", "גרניט פורצלן"],
               "aiConfig": {"prompt": "מהביקור בנכס - סוג הריצוף במטבח. אם לא צוין - השאר ריק."}},
     "why": "טבלת מרכיבי הגמר בדוח מציגה ריצוף מטבח; בטופס יש סלון, חדרים ורחצה בלבד"}
  ]}
```
**Scope.** The plan holds what the user asked for and what it needs to work (a condition that would
hide the new field, a sibling option list, the conditions a template's `decisions` flag). Other
improvements you notice go to the findings with an
offer of a separate plan - the user should be able to approve the request without approving extras.

Rules of thumb (details and every server rule in `references/form-design.md`, op shapes in
`references/form-tools.md`):
- **Reuse the form's patterns**: same section, same naming family, same options as the sibling fields
  (`kitchenFloorType` next to `livingRoomFloorType`, with its options), `after` the sibling.
- **Labels in the office's words**, names in English camelCase (lowercase first letter, even when the
  family is `LeaseContract...`), `why` on every op - the report location in the report's words or the
  standard, no outline ids or internal names: it becomes the user's review table.
- **Types by the value**: money -> `currency`; areas -> `currency` + `suffix: "מ\"ר"`; counts/years ->
  `number`; percentages/adjustments -> `textPom`; dates -> `date`; "source of the figure" -> `textSod`;
  descriptive lists -> `selectOther`; text-driving choices -> `select`/`radio`; lists -> a group;
  **detailed text (descriptions, analysis, planning / legal status, reservations) -> `richtext`**, with
  a prompt that asks for paragraphs ("פסקה לכל נושא, שורה ריקה בין פסקאות" - Quicker turns them into
  rich-text paragraphs); `textarea` only for a few plain lines.
- **Questions and their details** (`references/form-design.md` §8): each detail gets an `if` that
  matches the answers it describes (`== 'X'`, `[...].includes(...)`) - never `!=` - with the option
  text copied exactly; a detail of a detail carries its whole chain; checks from an outside source get
  "לא נבדק"; the question's prompt says silence is not "no"; no default answer on a question. A block
  of details can be one card with one condition (`update_row`). Conditions also where the report has
  them (bank-specific, extended only, under construction), consistent with the template's sections.
- **explan cites the source** for fields a standard requires ("נדרש לפי תקן 19 §4.15(ב)").
- **AI Fill prompt on every new field and group**: the source document, what exactly, format, "if
  missing leave empty". Professional judgements (value, discounts, adjustments): tell AI Fill not to
  fill them.
- Groups nest up to 3 levels, but keep the shallowest shape that fits (form-design.md §7). Org option lists (`referrer`,
  `appraisalPurpose`, `propertyType`, `propertyDestiny`, `appraisalType`) are changed in the settings,
  not by ops.
- **A new report type on a form that serves other work** (the office has one form for everything):
  prefer a separate office form for that appraisal type (projects of the type open it automatically);
  when that's not possible, add one switch field (e.g. a checkbox "שומה לבטוחה לפי תקן 19") and put
  a condition on every new field. Recipe in `references/form-design.md` §13.
- **Pre-filled text** (`default:` in the index): `defaultValue` on `add_field` / `update_field` - it
  fills empty fields only (new projects, unfilled ones, and the Word export); saved text stays. When
  adding a report type, read the defaults of notes / declaration fields - they may contradict it
  (`references/form-design.md` §13, item 6).
- **Cards and sections**: `update_row` (a card's heading, guidance, condition, AI prompt - named by a
  field in it) and `update_section` (title, icon, AI prompt). A field placed `after` a field inside a
  conditional card joins that card and its condition (`check_ops.py` warns; the plan summary says so) -
  right when the card serves the same case (kitchen floor in the "מטבח" card).
- Don't anchor `after` on a field with an empty label - the plan summary would show its internal name;
  give it a label first (`update_field` `set.label`) when that is the right place.
- An existing text box that becomes a question's detail gets a transition condition so old projects
  keep their text (`references/form-design.md` §8, rule 9).
- ≤ 60 ops per plan; a large redesign is several plans, each reviewed (by section is natural).

### 6. Check locally, then plan

```bash
python3 $S/check_ops.py form.json work/ops.json --md work/preview.md --payload work/payload.json
```
It replays the ops on a copy of the form the way the server does - including the check that every
condition compares a field with a value it can hold (an option, `true`/`false` for a checkbox, a number
for a number field). Fix every **ERR** (the server would reject the whole plan); read every **WARN** (missing prompt, a likely unit, a label very close to an
existing field, depth 3, long text not in `richtext`...). Then it audits the display logic of what the
plan touches on the resulting form ("Display logic after the plan"): a **FIX** on a field you add or
change is your mistake - fix it before planning (each comes with a ready condition); `[כבר בטופס]`
marks what the form already had. It writes `preview.md` (the Hebrew review table, with your `why`) and
`payload.json` (`why` stripped) - pass the payload's `templateId`, `ops`, `note` to
`plan_form_template_changes`.

Read the plan reply (`references/form-tools.md` §5): any `rejected` op -> fix and plan again.
`nothingToApply` -> tell the user the form already has it all.

### 7. Show and ask

Show the user, in Hebrew:
1. Your review table (`preview.md` - trimmed to what matters) - what each field is, where it goes and
   why (the report line or the standard). When the plan adds or changes questions and details, include
   the preview's "מפת התנאים" (what each answer shows) - it is how the user checks the logic.
2. The plan's `summaryHe` **exactly as returned** - that is what will be applied. Where a line could
   mislead (conditions, a field inside a conditional group or card), add a plain line under it -
   `references/form-tools.md` §5. It says when each field is shown ("מוצג רק כאשר ...") and which Word
   templates will print a hidden or newly conditioned field empty. When summaryHe already lists every
   field, keep your review table per section, not per field - the message is for an office manager.
3. The impact in plain words: how many projects use the form, data or Word templates touched by a
   change, projects that move between forms, fields without an AI prompt.
4. Findings you did *not* turn into changes (required items missing, decisions for them).
Then ask (AskUserQuestion when available, otherwise a plain question): apply / change something /
cancel. If apply is off (principle 7), say it first and ask instead: approve (applied once a manager
enables the tool, or entered by hand in the form builder) / change / cancel. Give the plan's expiry
in Israel time. Changes -> edit `ops.json`, check, plan again (the old plan just expires).
When you stop here (waiting, apply off, unattended), this message is the chat message; step 9's file
goes with it.

### 8. Apply

Only after an explicit approval of this plan: `apply_form_template_changes({planId})`.
- Apply off (principle 7): a manager turns on "ביצוע תוכנית שינויים בטופס שומה"
  (`apply_form_template_changes`) under הגדרות ← בינה מלאכותית ← הגדרות MCP, then you apply - the
  plan lives 24 hours, after that plan again. Or the user enters the changes by hand in the form
  builder: give them the exact internal names (templates find fields by name), types, options,
  conditions and prompts. Don't retry.
- `superseded` (the form changed since) -> re-read the form, re-run check_ops, plan and show again.
- Success -> note `previousVersion` -> `version`; call `get_word_template_variables({formTemplateId})`;
  if the work came from a Word template, continue there (quicker-appraisal-template) to map the new
  fields.

### 9. Deliver

Write `out/<form title>_form_changes.md` in the work folder (Hebrew) when apply is off or nobody is
there to approve (it is then the manual-entry spec, marked "מתוכנן - טרם בוצע"), after applying more
than a couple of ops, or when the user asks; a one- or two-op change applied in the chat needs no file.
```bash
python3 $S/change_report.py form.json work/ops.json --reply work/plan_reply.json \
        --findings work/findings.md --out "out/<form title>_form_changes.md"   # [--applied <version>]
```
It writes everything but the findings (write those in `work/findings.md`, Hebrew), with the plan's
expiry in Israel time. Contents:
- the form and its version (before -> after, or planned);
- the changes table with reasons;
- for manual entry, every field's exact internal name, type, options, condition and prompt;
- findings left open (standards gaps, organization lists to change in the settings, default texts,
  card conditions for the form builder, fields the user declined);
- how to undo ("restore_form_template_version לגרסה N" - or ask Claude to restore).

In chat after apply: one short paragraph - what changed, the version, what's left to decide.

## Creating a form

When the office has no form of its own for this work, or asks for a separate one (e.g. per bank):
1. Base: usually the system "שומת מקרקעין" (`list_form_templates`), or one of the office's forms when
   it is closer. Title in Hebrew as the office names its report ("שומה לבנק - מזרחי טפחות").
2. Appraisal types: an office form takes over the projects of its types - and **two office forms can't
   share a type**. If another form holds the type, create with `appraisalTypes: []` and settle it with
   the user (a `set_form_props` op later shows how many projects move).
3. Ask before creating (it's visible to the whole office), then `create_custom_form_template` with a
   fresh `idempotencyKey` (`python3 -c "import uuid; print(uuid.uuid4())"`); keep the key for retries.
   `create` absent from the tools -> it's not enabled for the office (manager: MCP tool settings).
4. Continue from step 2 on the new form's id.

## Other requests

- **Small change** ("תוסיף אפשרות 'בנק ירושלים'", "תשנה את התווית"): index -> ops -> check -> plan ->
  show -> apply. No report needed. `referrer` and the other org lists -> the settings (Quicker paths above). A new
  referrer (bank) also gets none of the bank-specific fields: `form_index.md` "Conditions that name
  option values" lists the fields and cards each bank turns on - offer to add the new bank where its
  reports need them (exact text from `get_option_list({field: "referrer"})`, or
  `.includes('מזרחי')`-style conditions - the plan checks the value against the office's list).
  Entries marked `card:` / `row in` are card conditions: `update_row` on a field of the card.
- **"מה חסר לנו בטופס" / "האם הטופס מתאים לתקן 19"**: steps 2-4 and a findings report; plan only if
  asked.
- **"תבדוק את הטופס" / "למה השדה הזה מופיע" / fixing conditions**: `audit_form.py ... --ops-out
  work/fix_ops.json` writes `update_field` ops for the fixes it can express; review each (the
  heuristics read labels), add "לא נבדק" options and question prompts where advised, then step 6.
- **Undo / "תחזיר את הטופס למצב של אתמול"**: `list_form_template_versions` -> pick the version with the
  user (who/when/summary) -> `restore_form_template_version` -> show `summaryHe` and
  `fieldsWithDataNotInRestoredVersion` -> approval -> apply.
- **Hide a field**: say what happens - data kept, AI Fill skips it, templates print it empty for new
  projects; the plan names those templates. `show_field` brings it back.
- **A new standard version** (e.g. 9.1 in 2027): gap_check with the relevant type, propose the new
  fields next to the old ones (old projects keep their data), and conditions or labels that say which
  applies.

## Reference files

- `references/form-design.md` - the form model, field types, names, placement, options, groups,
  conditions, AI Fill prompts, links to project columns, safe changes, limits. Read before writing ops.
- `references/form-tools.md` - the exact tool contract: who sees what, op shapes, the plan reply,
  apply, versions/restore, error messages and what to do.
- `references/standards.md` - the standards and regulations: what binds, the official list with
  versions, what each requires the report to hold, purposes without a standard, the item -> standard
  table. Read the parts behind any finding you raise.
- `assets/checklists.json` - the per-type checklists `gap_check.py` uses (with sources).
