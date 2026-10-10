# The Quicker form-editing tools (MCP) - exact contract

As implemented in Quicker (October 2026). Tool names appear with the connector's prefix (e.g.
`mcp__Quicker__plan_form_template_changes`); search for the bare name if unsure.

## Contents
1. Who sees which tool
2. Read tools
3. create_custom_form_template
4. plan_form_template_changes - ops
5. The plan reply
6. apply_form_template_changes
7. Versions and restore
8. Errors and what to do

## 1. Who sees which tool

- The five editing tools exist only for a user allowed to edit the organization's settings (the
  permission the form editor requires). A user without it doesn't see them at all - tell them a
  manager must do the change (or grant the permission). The check repeats on every call.
- Enabled by default: `plan_form_template_changes`, `list_form_template_versions`,
  `restore_form_template_version` (it only plans). **Off by default: `create_custom_form_template`
  and `apply_form_template_changes`** - a manager turns them on in Quicker: הגדרות ← בינה מלאכותית ←
  הגדרות MCP ← "כלים מורשים לסוכני AI". A tool that is off is **absent** from the tool list. Apply is
  off when either `apply_form_template_changes` isn't in the tool list or a plan reply carries
  `applyAvailable: false` (with a `nextStep` saying so) - check before promising anything.
  -> Never promise a change you can't apply. Plan, show, and tell the user exactly what to enable -
  or offer the alternative: the change list for the form builder (הגדרות ← טפסי שומה מותאמים).
- Editable by ops since the October 2026 update: a field's `defaultValue`, a card's (row's) title,
  sub-heading, help text, condition and AI prompt (`update_row`), a section's title, icon and AI prompt
  (`update_section`). Still not: a condition on a whole section (sections have none) and `read` /
  `readNumber` / `html` fields - form-builder jobs.

## 2. Read tools

| tool | use |
|---|---|
| `list_custom_form_templates` | the office's own forms: id, title, appraisalTypes, isDefault, basedOn, version, sections with field counts |
| `list_form_templates` | system + office forms (summary) |
| `get_form_template(id)` | the full form: schema, metadata (sections, tabs, projectFieldsMap), computedFields, version. ~100KB - the client usually saves it to a file; copy it to `form.json` and run `form_index.py` |
| `get_word_template_variables(formTemplateId)` | what Word templates can use after the change (refresh after apply) |
| `get_option_list({field})` | the office's active values of an organization list (`referrer`, `appraisalPurpose`, `propertyType`, `propertyDestiny`, `appraisalType`) with their exact text - before a condition on one of them |

## 3. create_custom_form_template

```json
{ "basedOnTemplateId": "<system or office form id>", "title": "שומת מקרקעין - בנקים",
  "description": "...", "appraisalTypes": ["שומה לבנק"], "setAsDefault": false,
  "idempotencyKey": "<a NEW uuid per form>" }
```
- Copies the source exactly (schema, metadata, computed fields). Then change the copy with plans.
- `idempotencyKey` (8-64 chars `[A-Za-z0-9_-]`): the same key returns the form it already created
  (`created: false`) - safe to retry after a timeout. Generate one per intended form and reuse it
  only for retries of that create. A key whose form was deleted -> error, use a new key.
- `appraisalTypes` omitted = keep the source's types; `[]` = none. **Two office forms can't serve the
  same appraisal type**: the call fails naming the other form. Create with `[]` and assign the type
  later (`set_form_props`), after the user decides which form gives it up.
- `setAsDefault: true` makes it the office default (projects whose type has no office form).
- Reply: `{created, templateId, title, version, appraisalTypes, isDefault, basedOn, nextStep}`.
- **Ask the user before creating** - a new form is visible to the whole office.

## 4. plan_form_template_changes

```json
{ "templateId": "<office form id>", "ops": [ ... up to 60 ... ], "note": "למה - נשמר בהיסטוריה" }
```
Nothing changes. Each op is checked on the form as earlier ops left it, in order.

| op | shape |
|---|---|
| `add_field` | `{section: "<sectionKey>" \| group: "<group path>", after?: "<sibling name>", field: {name, label, type, values?, class?, explan?, placeholder?, required?, suffix?, limit?, systemPath?, if?, aiConfig?: {prompt}, defaultValue?}}` - exactly one of `section` / `group` |
| `add_group` | `{section \| group, after?, definition: {groupName, title, subTitle?, explan?, if?, aiConfig?, fields: [field or nested {groupName, ...}]}}` |
| `add_section` | `{key, title, tab: "<tab key>", icon?: "fa-...", after?: "<section key in that tab>", aiConfig?: {prompt}}` |
| `update_field` | `{path, set: {...}}` - field: `label explan aiConfig if class suffix limit placeholder required type defaultValue`; group: `title subTitle explan if aiConfig`. `null` removes an optional property. No `name`/`groupName` |
| `update_row` | `{field: "<a top-level field of the card>", section?, set: {title?, subTitle?, subHeader?, explan?, if?, aiConfig?, icon?}}` - a card (a plain row of fields), named by a field in it. A group row is a group: `update_field` on its path |
| `update_section` | `{key, set: {title?, icon?, aiConfig?}}` |
| `add_options` / `remove_options` | `{path, values: [...]}` - choice fields only, not organization lists |
| `move_field` | `{path, toSection, after?}` - top-level fields/groups only |
| `hide_field` / `show_field` | `{path}` |
| `remove_field` | `{path}` |
| `set_form_props` | `{title?, description?, appraisalTypes?, isDefault?}` |

`defaultValue` - what an **empty** field gets: when the form opens, and in the Word export (only where
the field's display conditions hold - a hidden detail gets no default). Saved values are never replaced;
the plan says how many projects already hold one. Shapes: text (≤4000; rich text ≤8000, plain
paragraphs become `<p>`), an option of a select/radio, a list of options for a checkboxList, a number,
`true`/`false` for a checkbox, `YYYY-MM-DD` for a date. No default on image / html / read fields.

Conditions are checked **against the form they land in**: every field read exists, a checkbox is
compared with `true`/`false`, a number field with a number, a choice field with one of its options
(organization lists: the office's list; or a value projects already saved). Otherwise the field would
never show - the plan is rejected, with "האם התכוונת ל..." when an option is close. `check_ops.py`
checks the same before you plan.

Paths are `additionalDetails` names joined by dots: `squareMeter`, `borrowers.borrowerName`,
`perutNesachTabo.nesachTaboOwner.nesachTaboName`. A name repeated in two sections can't be addressed
(error says so - leave it to the form builder).

Idempotent ops: a field/group that already exists with the same definition, options already there,
a field already hidden -> `no_op` (not an error). A plan where everything is `no_op` returns
`nothingToApply: true` and no planId.

## 5. The plan reply

```json
{ "planId": "...", "status": "pending" | "rejected", "expiresAt": "...", "templateId": "...",
  "templateTitle": "...", "baseVersion": 7, "resultVersion": 8,
  "changes": [ {"i": 0, "op": "add_field", "path": "bankFileNumber", "label": "...", "status": "will_apply" | "no_op" | "rejected",
                "reason": "...", "suggestion": "hide_field", "summary": ["..."]} ],
  "impact": { "projectsOnForm": 143, "byAppraisalType": [{"appraisalType": "...", "count": 90}],
              "byPath": {"oldNotes": {"projectsWithData": 12, "templateRefs": [{"documentId", "name", "title", "tags": ["{p.ad.oldNotes}"]}]}},
              "afterChange": {"projectsOnForm", "movingIn", "movingOut"},      // when appraisalTypes / isDefault change
              "restore": {...},                                                  // restore plans, §7
              "unreadableWordTemplates": ["..."],
              "aiFill": ["bankFileNumber: אין aiConfig.prompt - ..."] },
  "summaryHe": ["יתווסף שדה ... אחרי ...", "...", "הטופס משמש כיום 143 פרויקטים ..."],
  "errors": [], "warnings": [], "nextStep": "...",
  "applyAvailable": false }                                                     // only when apply is off
```
- `rejected` anywhere -> the whole plan is `rejected` and can't be applied. Fix the op (read `reason`,
  follow `suggestion`) and plan again. Don't apply the "good part" separately without telling the user.
- `projectsOnForm` counts projects that open this form by appraisal type and the office default
  (`project.formTemplateId` is not used by the app).
- `byPath` lists data and Word templates for removals, type changes, **hidden fields and new
  conditions** (field or card). `impact.wordTemplatesStillPrinting` turns the last two into lines
  ("... מודפס ב-3 תבניות Word ... - כשתנאי התצוגה לא מתקיים ... יודפס ריק") that `summaryHe` already
  includes: those templates should wrap the field in the same condition (template skill).
- `summaryHe` says when each field is shown ("- מוצג רק כאשר "סוג" הוא "שומה מורחבת" וגם ..."),
  including the condition of the card a field joins and of the groups around it, and names untitled
  groups by where they sit. Show it as is; add a line only where it still could mislead.
- `expiresAt` is UTC - tell the user the time in Israel time (`change_report.py` writes it so).
- **Show the user `summaryHe` exactly as written**, plus the impact lines that matter (projects with
  data in touched fields, Word templates that read them, projects moving between forms), plus your own
  design table (why each field, where it came from). Then ask for explicit approval.
- Plans expire after **24 hours**.

## 6. apply_form_template_changes

`{ "planId": "..." }` - **only after the user explicitly approved this plan in this conversation.**
- Re-checks everything in one transaction: the form must still be at `baseVersion` (otherwise
  `superseded`: someone saved the form in the builder or another plan applied) and data saved since
  can still block a removal. The re-run must give exactly the result that was shown (hash check).
- The replaced version is kept (restorable). Caches refresh at once - AI Fill and the variables tool
  see the new fields immediately.
- Reply: `{applied: true, planId, templateId, version, previousVersion, changesApplied, noOps,
  summaryHe, nextStep}`. Applying the same planId again returns the same reply with `replayed: true`
  and changes nothing - safe to retry after a timeout.
- After apply: call `get_word_template_variables(formTemplateId)` before mapping any Word template.

## 7. Versions and restore

- `list_form_template_versions({templateId, limit?})` -> `currentVersion` and `versions[]`: each entry is
  the form **as it was at that version**, saved when the next version replaced it: `version,
  replacedAt, replacedBy {id, name}, replacedBySource (ui | mcp | ai_generation | restore | migration),
  changeSummary, planId`. History starts with the first change after the feature shipped.
- `restore_form_template_version({templateId, version, note?})` -> a **plan** (kind restore) like any
  other: `summaryHe` ("הטופס יחזור לגרסה N: יחזרו X שדות, יוסרו Y..."), `impact.restore.added /
  removed / changed`, and **`fieldsWithDataNotInRestoredVersion`** - fields that leave the form while
  projects hold data in them (the data stays, the form stops showing it). Show those before asking.
  Then `apply_form_template_changes(planId)`. The restore is a new version, so it can be undone too.

## 8. Errors and what to do

| message (Hebrew from the server) | meaning | do |
|---|---|---|
| "זהו טופס מערכת, ואותו לא משנים..." | planned on a system form | `create_custom_form_template`, plan on the copy |
| "הטופס לא נמצא בארגון" | wrong id / another org | `list_custom_form_templates` |
| "אין הרשאה לערוך את טפסי השומה..." | user lacks the settings permission | tell the user; a manager must act |
| "השם ... כבר בשימוש בטופס" | name taken (anywhere at top level) | `update_field` the existing one, or another name |
| "אי אפשר להסיר את ...: יש בו נתונים ב-N פרויקטים / N תבניות Word / תנאי תצוגה..." | removal blocked | `hide_field` (suggestion) |
| "האפשרויות של ... הן רשימה של הארגון" | org option list | הגדרות ← אפשרויות בחירה ← אפשרויות בחירה בפרטי פרויקט (not ops) |
| "אי אפשר לשנות סוג מ-X ל-Y..." | unsafe type change | new field + hide old |
| "הטופס השתנה מאז התוכנית (גרסה A -> B)" | superseded at apply | re-read the form, plan again, show again |
| "פג תוקף התוכנית (24 שעות)" | expired | plan again |
| "מאז התוכנית השתנו נתונים..." | data now blocks an op | plan again without it (hide instead) |
| "התוצאה שונה ממה שהוצג למשתמש" | engine changed between plan and apply | plan again and show again |
| "כבר יש טופס של הארגון לסוג השומה ..." | appraisal type clash | create with `[]` / remove the type from the other form first |
| "תנאי התצוגה משווה את ... ל"...", שאינו אחת מהאפשרויות שלו ... האם התכוונת ל: ..." | a condition on a value the field can't hold | copy the option text exactly (`form_index.md`); for an organization list `get_option_list` |
| "... אבל זו תיבת סימון ששומרת כן/לא - משווים ל-true או false" | checkbox compared with text | `=== true` / `=== false` |
| "... שדה מספרי, לטקסט ..." | number field compared with text | compare with a number |
| "ברירת המחדל ... אינה אחת מהאפשרויות של השדה" | default not an option | an option, exactly as written |
| "... היא קבוצה חוזרת - את הכותרת, התנאי וההנחיה שלה משנים ב-update_field" | `update_row` on a group | `update_field` with the group's path |
