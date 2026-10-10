# Designing appraisal-form fields that appraisers will actually fill

How a Quicker appraisal form works, and how to turn an office's report into good fields. Read before
writing the first op. Rules marked **(server)** are enforced by the Quicker engine - `check_ops.py`
checks them locally first.

## Contents
1. The model in five lines
2. Is it a field at all?
3. Field types - which one, and why
4. Names, labels, help text
5. Where it goes - tabs, sections, order, width
6. Options
7. Repeating data - groups
8. Questions and their details (display conditions)
9. AI Fill prompts
10. Links to the project card (systemPath)
11. Changing what exists without breaking data or templates
12. Limits
13. One form, several report types

## 1. The model in five lines

- A form = **tabs** -> **sections** -> **rows** -> **fields** and **groups** (repeatable rows).
- Everything typed in the form is saved in the project's `additionalDetails` - **one flat object** for
  the whole form (`p.ad` in Word templates). So a top-level name is unique across ALL sections **(server)**.
- A field's internal `name` is the data key and the Word tag (`{p.ad.loanNumber}`): it **never changes**
  after creation **(server)**. Its Hebrew `label` can change any time.
- A group holds a list: `p.ad.borrowers = [{borrowerName, borrowerId}, ...]`. In Word it is a loop
  (`{#p.ad.borrowers}{borrowerName}{/p.ad.borrowers}`), so fields inside a group appear in templates by
  their bare name.
- System forms ("שומת מקרקעין", "מס רכוש", "שומת רכוש") are never edited: the office works on its own
  copy (`create_custom_form_template`), and a project of an appraisal type opens the office's form for
  that type (else the office default, else the system form).

## 2. Is it a field at all?

Every field is something an appraiser fills in on every project - on a phone at the visit, or at the
desk. A form with 40 needless fields is filled badly. Before proposing a field, ask:

| the data point in the report is... | it belongs in |
|---|---|
| different in every report (a value, a choice, a date, a list) | **a form field** |
| the same in every report (legal wording, standard declarations, the office's methodology text) | fixed text in the Word template - or a field with a `defaultValue` when appraisers adjust it per report (bank notes, limiting conditions): the default fills empty fields and the Word export |
| the appraiser's own details (name, licence number, signature, phone) | the user / office settings and the template's system variables (`p.agentName`, `appraisalSignatureImage`...), not the form |
| already a project or customer column (address, gush/helka, dates, customer name and ID, appraisal type, referrer) | **use the existing column** - `p.*` / `c.*` - or a field bound to it (§10); never a second copy |
| computed from other values (VAT, totals, percentages of a value) | the template (`| currency`, expressions) or a `readNumber` field - agents cannot create `read`/`readNumber`/`html` fields; suggest the form builder for those |
| a document (extract, permit, contract) | Quicker's project files; at most an `image` field when the report embeds a picture of it |
| a long narrative the appraiser writes per report (environment, planning status, principles, reservations) | `richtext` - paragraphs, bold and lists, the way the report shows them (§3) |

Two more tests from appraisal practice:
- **Who knows the value and when?** Visit facts (condition, finish, who presented the property) are
  filled at the visit; registration and planning data come from documents at the desk. That decides
  the tab (§5) and the AI Fill prompt (§9).
- **Does a choice drive text?** If the report prints different paragraphs by a value (bank, extended
  vs short, property under construction), make it a choice field (`select`/`radio`) - templates and
  form conditions branch on exact option values. If it's descriptive only, `selectOther` or text is fine.

## 3. Field types

Agents may create: `text`, `textarea`, `richtext`, `number`, `currency`, `date`, `select`,
`selectOther`, `radio`, `checkbox`, `checkboxList`, `image`, `textPom`, `textSod` **(server)**.

| type | use for | notes |
|---|---|---|
| `text` | short free text: names, file numbers, plan numbers, ID numbers | IDs/file numbers are text, not number (leading zeros, dashes) |
| `textarea` | a few plain lines (a remark, an address note, a short explanation) | line breaks print as line breaks; no formatting |
| `richtext` | **detailed text** - descriptions, analysis, planning / legal status, reservations, explanations, anything the report shows as paragraphs or lists | the editor keeps paragraphs, bold and lists; the Word template prints it with `{p.ad.x \| html}` alone in its paragraph. AI Fill: see below |
| `number` | counts and years: rooms, floors, units, year built | the input is a whole non-negative number (`min=0`) - not for amounts, areas, percentages, adjustments |
| `currency` | money (shows ₪, thousands separators) **and areas with `suffix: "מ\"ר"`** | `suffix` replaces the ₪ (≤20 chars); an area without suffix shows ₪ - the system form's areas carry `מ״ר` |
| `date` | dates (visit, valuation date, permit date, extract date) | stored as an ISO date; templates format with `| date:'DD/MM/YYYY'` |
| `select` | a closed list of 3-15 options that drive text or conditions | |
| `selectOther` | a list + a free value - **the default for appraisers' descriptive lists** (flooring, condition, building type) | appraisers always meet the case that's not on the list |
| `radio` | 2-4 exclusive options shown as buttons (מקוצרת/מורחבת, קיים/לא קיים, תואם/חורג) | faster than a dropdown on a phone |
| `checkbox` | a yes/no flag used to show other fields or text | prints as true/false - only as a condition in templates |
| `checkboxList` | several options at once (air directions, documents checked, components of the extract) | an array: templates use `| list:', '` and `| includes:'x'` |
| `image` | photos, plans, maps, scanned excerpts the report shows | `limit` 1-30; full width |
| `textPom` | a value typed with quick % / מ"ר buttons | for percentages and adjustments ("-10%") and mixed area text |
| `textSod` | a value typed with quick "source of data" buttons | for "מקור הנתון" next to a key fact (area source, rights source) - the standards now ask for sources (6.1, 7.1, 9.1) |

**Rich text in practice.**
- AI Fill, agents and the API write plain text; Quicker turns it into rich-text paragraphs (a blank line
  starts a paragraph, a line break stays a line break) **(server)**. So the prompt asks for paragraphs -
  "פסקה לכל נושא, שורה ריקה בין פסקאות" - not for HTML.
- Changing an existing `textarea` to `richtext` is allowed **(server)**, with a cost: every Word
  template that prints it must change to `| html` (without it the markup prints as text - the plan's
  impact lists those templates for a type change), and old values' line breaks merge at the next edit.
  Convert only when the user wants formatting in that field, and fix the templates (template skill) in
  the same session. New detailed-text fields start as `richtext`.

## 4. Names, labels, help text

- **name** **(server)**: English camelCase, starts lowercase, `^[a-z][a-zA-Z0-9]*$`, ≤60 characters,
  not reserved (`true false null undefined this constructor prototype project toString valueOf
  hasOwnProperty isPrototypeOf length x y z i`), unique at the top level of the whole form and within
  its group.
  - Meaningful English the next person understands: `bankFileNumber`, `collateralValue`,
    `forcedSaleDiscount`, `extractDate`, `kitchenFloorType` - not `field1`, not transliterated Hebrew.
  - **Follow the form's own families.** Next to `livingRoomFloorType` / `roomsFloorType` the kitchen is
    `kitchenFloorType`; inside `perutNesachTabo` the prefix is `nesachTabo...`. `form_index.py --find`
    shows the neighbours. Older forms have names that start with a capital (`LeaseContractCapacity`);
    keep the family but start lowercase (`leaseContractPurpose`) - the server refuses the capital.
  - Inside a group prefer names that are distinctive on their own (`tenantName`, not `name`): Word
    loops print them bare.
  - A name is forever. Never reuse a name that once meant something else (old projects hold its data).
- **label** (≤120, Hebrew, **(server)** no `{{ }}`): the words **the office's report uses** for the
  value - that is what appraisers recognise and what the template mapping looks for. Drop trailing
  colons. Add the unit only if the field has no suffix ("שטח (מ"ר)").
- **explan** (≤500): the tooltip "?" - when to fill, which document, a rule ("לפי תקן 9.1 - בלי
  מרפסות"). Use it for anything an intern would ask. A field that exists because a standard or the
  regulations require it says so, with the clause: "נדרש לפי תקן 19 §4.15(ב) - מס שבח במימוש, בלי
  פטורים אישיים". The appraiser learns the rule where it applies, and a reviewer sees why the field is
  there. Cite only clauses you verified in `standards.md` / `checklists.json`.
- **placeholder** (≤120): a format example ("לדוגמה: 12/2024").
- **required**: only for what a report can't go out without; required fields block nothing in Quicker
  but mark the form - overuse makes them noise.

## 5. Where it goes

- **Tabs**: the system form has `visit` (ביקור בנכס - filled on site, often on a phone) and
  `appraisal` (פרטי שומה - at the desk). Put a field where it is filled: physical facts and who was
  there -> visit; documents, planning, rights, values -> appraisal.
- **Sections** mirror the report's chapters and the order of standard 1.1: general/orderer -> visit ->
  identification -> description -> planning -> rights -> principles -> calculation -> value. Add a new
  section only for a real chapter of the office's report that the form lacks (and give it its fields
  in the same plan - an empty section is a warning). Keys are camelCase like field names.
- **Order**: use `after` to place a field next to its neighbour in the report (`after: "loanNumber"`).
  Without `after` it goes last in the section/group: it joins the last row when that row is plain (no
  title, no condition), otherwise it gets a new row at the end. `after` a field joins that field's row
  - **including a card's title and condition** (`check_ops.py` warns, and its preview names the card);
  a group always gets its own row. There is no "before" / "first": the first place you can reach is
  after the section's first field.
- **Cards**: a card is a plain row with a heading. `update_row {field, set: {title, subHeader, explan,
  if, aiConfig, icon}}` changes the card that holds `field` **(server)** - its condition hides every
  field in it. To make a **new card**, add its first field where it starts a row of its own (without
  `after` at the end of a section whose last row is a card or a group, or `after` a group), give that
  row a title (and a condition) with `update_row` on the field, then add the other fields `after` it -
  they join the card. Sections take `update_section {key, set: {title, icon, aiConfig}}`.
- **Width**: leave `class` out - the engine copies the neighbour's width (`col-md-4 col-sm-6
  col-xs-12` by default); `textarea`/`richtext`/`image` go full width (`col-md-12 col-xs-12`).
- `move_field` moves a top-level field or group to another section (data untouched). Fields inside a
  group cannot leave it **(server)**.

## 6. Options

- Take options from **the office's reports** (every variant you see across reports), in the office's
  wording. Templates and conditions compare against the exact text (`{#p.ad.loanType == 'מכוונת'}`), so
  an option's text is part of the contract - fix spelling before the first project uses it.
- Prefer `selectOther` over adding an "אחר" option.
- `add_options` appends; `remove_options` is refused for an option any project saved **(server)** -
  removing options is rarely worth it.
- **Organization lists**: `referrer` (גורם מפנה), `appraisalPurpose`, `propertyType`, `propertyDestiny`,
  `appraisalType` - and any field bound to those columns or with `valuesSource` - show the office's
  lists, for all forms. The form's options for them are refused **(server)**: tell the user to change
  them in הגדרות ← אפשרויות בחירה ← אפשרויות בחירה בפרטי פרויקט (managers). There the office ticks
  which values to show **from Quicker's built-in list** - a value the list doesn't offer needs Quicker
  support. `get_option_list({field})` returns the office's active values with their exact text - use
  it before writing a condition on a referrer.
- ≤300 options, each ≤200 characters **(server)**.

## 7. Repeating data - groups

- Use a group for anything the report lists a varying number of times: borrowers, owners and their
  shares, lessees, mortgages, warning notes, plans, permits, comparables, tenants, units, attachments,
  court questions.
- A group needs `groupName` (name rules), a `title` (the heading above its rows) and ≥1 field (≤80).
  Add `aiConfig.prompt` on the group to tell AI Fill which document holds the rows.
- To add a column to an existing group: `add_field` with `group: "<group path>"` - never a parallel
  group.
- **Depth**: groups may nest (a lessee's rights inside a lease inside the extract), up to 3 levels from
  a section **(server)**. All levels reach Word templates as nested loops. Still prefer the shallowest
  shape that fits: every level is another "add row" click for the appraiser and another loop in the
  template, so a list of owners with a share column is one group, not owners -> shares.
- A single value that happens to live in a group (the first owner) is `p.ad.group[0].field` in
  templates - no need for a duplicate top-level field.

## 8. Questions and their details (`if`)

Much of an appraisal form is **a question and the details it opens**: "אתר עתיקות" opens the map and
the declaration only when the property is in a site; "חוזה שכירות: קיים" opens the lease table;
"מבנה מסוכן: הוכרז" opens the order's details. A form that shows the details for every answer looks
careless (a map upload under "לא נבדק"), invites wrong data, and prints leftovers. The rules:

1. **Details open only on the answers they describe.** A finding's details (פירוט, מפה / צילום,
   תאריך, מסמך, סכום, השפעה על השווי) open on the answer that reports the finding. Nothing opens on
   "לא נבדק", "לא ידוע", "אין", "לא קיים". Give each detail its own `if` with the same expression - or,
   for a block of details, put them in one card and give the card the condition (`update_row`, §5); a
   group takes it once, on the group. Two refinements:
   - a detail **about the check itself** (תאריך הבדיקה, מקור המידע) opens on every *checked* answer -
     "כן" and "לא" alike - and only "לא נבדק" closes it;
   - a qualified "no" is a finding ("הנכס אינו מוגדר כמבנה מסוכן, אך מבנה סמוך במתחם מוגדר") - its
     details open on it too.
   A "סוג ..." / "מהות ..." question picks a kind; the record's other fields (the loan's file number
   under "סוג ההלוואה") are not its details - only fields that exist for one kind are ("פרטי ההיוון"
   under "סוג החכירה = מהוונת").
2. **Match the answers that open, not the ones that close.** `== 'הוכרז מבנה מסוכן'` or
   `['א', 'ב'].includes(...)` - not `!= 'אין צו'`. A negated condition shows the details before anyone
   answered, and opens them for every answer added later (add "לא נבדק" next year and the details open
   on it).
3. **Copy the option text exactly.** A condition compares strings; `'קיים'` never matches the option
   `'קיים חשש'`. The plan now rejects such a condition **(server)** ("... שאינו אחת מהאפשרויות שלו"),
   and a checkbox compared with `'כן'` instead of `true` - `check_ops.py` catches both first; conditions
   already in the form are not re-checked (`audit_form.py` finds those). When you add, fix or rename an option, re-check the
   conditions that name it (`form_index.md` "Conditions that name option values").
4. **A detail of a detail carries the whole chain.** A hidden field keeps its value. If "פירוט ההשפעה"
   opens on "השפעה על השווי = יש", and that question opens only on "זיהום = קיים חשש", the detail's
   condition is `contamination == 'קיים חשש' && contaminationImpact == 'יש'` - otherwise changing the
   first answer leaves the detail open with stale text.
5. **Every check from an outside source has a "לא נבדק" answer** (registry, municipality, Israel
   Antiquities Authority, GovMap, the planning file). Without it an appraiser who didn't check must
   pick "no", and the report states a fact nobody verified. In the Word template "לא נבדק" prints the
   office's assumption sentence ("לא נערכה בדיקה ...; השומה מניחה כי ...").
6. **A question's AI Fill prompt says silence is not "no"**: "בחר רק לפי מסמך או בדיקה שקובעים זאת;
   אם אין - השאר ריק". AI Fill sees each detail's condition and fills the question and its details
   together, so a wrong answer drags wrong details with it.
7. **Evidence goes with its finding.** A map or screenshot that documents the finding opens with that
   answer only - the antiquities map on "הנכס בתחום אתר עתיקות", not on "אינו בתחום" and never on
   "לא נבדק". Open it on both checked answers (`['בתחום', 'אינו בתחום'].includes(...)`) only when the
   office's own report attaches the map to prove a negative too - and say so to the user. "We write
   it in every report" means the *question* is in every report, not its evidence. Context images every
   report carries (the location map) need no question.
8. **Details sit right after their question** - not before it (a "פירוט" above its question reads as
   always relevant), in the report's order (`after` the question, then each
   detail after the previous one). Don't anchor on a field with an empty label (the plan summary would
   show its internal name) - give it a label first (`update_field` `set.label`) when the right place is
   next to it.
9. **An existing free-text field that becomes a question's detail** ("חריגות בנייה" text box under a
   new question "חריגות בנייה: קיימות / לא נמצאו / לא נבדק"): old projects have text but no answer, so
   a plain `== 'קיימות'` hides their text. Use a transition condition -
   `project.additionalDetails.q == 'קיימות' || (!project.additionalDetails.q && project.additionalDetails.detail)`
   - the text stays visible until someone answers. (`!q` here tests "not answered yet"; rule 2 is about
   not opening details on a *negated answer*.) Adding a condition to an existing field also changes
   what Word templates should print: the plan lists the templates that print it
   (`wordTemplatesStillPrinting`) - wrap those lines in the same condition (template skill).
10. **No default answer on a question.** A default records an answer nobody gave - "אין" or "לא קיים"
   by default is a false statement in every report nobody checked, and even "לא נבדק" by default hides
   that nobody looked. Defaults are for boilerplate text (notes, declarations, limiting conditions) and
   for values that really are the same for the office.
11. **A question above an existing field**: there is no "before" - add the question after the field
   that precedes it, or add it after the field and `move_field` the field (same section) `after` the
   question.
12. **Check what each answer shows.** `check_ops.py` prints the display logic of the fields the plan
   touches, and its preview has a "מפת התנאים": per question, what each answer shows, and what shows
   for every answer though it looks like a detail. Read it before showing the plan. For a form that
   already exists, `audit_form.py` does the same for the whole form (and writes ready
   `update_field` ops for the fixes).

Common questions in Israeli appraisal reports - shape them like this:

| question | answers | opens (on) |
|---|---|---|
| אתר עתיקות | הנכס בתחום אתר עתיקות / הנכס אינו בתחום אתר עתיקות / לא נבדק | מפת רשות העתיקות, פירוט ההכרזה, השפעה (בתחום) |
| מבנה מסוכן | הוכרז מבנה מסוכן / אין צו / לא נבדק | פירוט הצו, תאריך, מסמך (הוכרז) |
| חריגות בנייה ושימוש בניגוד להיתר | קיימות חריגות / לא נמצאו חריגות / לא נבדק | פירוט החריגות והשפעתן (richtext), צילומים (קיימות) |
| זיהום קרקע | קיים חשש / לא נמצא חשש / לא נבדק | מקור החשש ופירוט, השפעה (קיים חשש) |
| הפקעות / הערות לפי סעיף 126 | קיימות / אין / לא נבדק | שטח מופקע, תכנית, סטטוס מימוש (קיימות) |
| מתע"ן / תשתית תחבורה בקרבת הנכס | קיים / לא קיים / לא נבדק | מרחק הליכה, שלב (מתוכנן / בביצוע / פעיל) (קיים) |
| אנטנה סלולרית / קו מתח גבוה בקרבה | קיים בקרבת הנכס / לא קיים / לא נבדק | מרחק, צילום (קיים) |
| התחדשות עירונית (תמ"א 38 / פינוי בינוי) | קיים הליך / אין / לא נבדק | שלב, יזם, תמורות (קיים הליך) |
| חוזה שכירות | קיים / לא קיים | טבלת השכירות - group (קיים) |
| הערות אזהרה / שעבודים / עיקולים בנסח | רשומים / אין | טבלת הרישומים - group (רשומים) |
| סוג הזכות (checkboxList) | בעלות / חכירה / חכירה מהוונת ... | פרטי החכירה (`.includes('חכירה')`) |
| בית משותף | רשום / לא רשום | תת-חלקה, הצמדות, תשריט (רשום) |
| היטל השבחה | חל / לא חל / לא נבדק | תכנית משביחה, אומדן (חל) |

Syntax **(server)** - an expression over the form's own fields:
```
project.additionalDetails.dangerousBuilding == 'הוכרז מבנה מסוכן'
['הנכס בתחום אתר עתיקות', 'הנכס אינו בתחום אתר עתיקות'].includes(project.additionalDetails.antiquitiesSite)
project.additionalDetails.typeZchut.includes('חכירה')                      (checkboxList)
project.additionalDetails.reducedPriceProgram === true                     (checkbox)
project.additionalDetails.contamination == 'קיים חשש' && project.additionalDetails.contaminationImpact == 'יש'
project.additionalDetails.borrowers[x].borrowerType === 'חברה'             (inside a group row: x, y, z)
```
or structured: `{"logic": "and", "conditions": [{"field": "extanded", "operator": "equals", "value": "שומה מורחבת"}]}`
(operators: equals, notEquals, greaterThan, lessThan, greaterOrEqual, lessOrEqual, contains,
notContains, isEmpty, isNotEmpty, isTrue, isFalse).
Allowed: reads of the form's fields, literals, comparisons, `&& || !`, `?:`, `.includes()` /
`.indexOf()`, `.length`. Refused: any other call, assignment, `constructor`/`__proto__`..., any root
other than `project.additionalDetails`, fields the form doesn't have (a field added earlier in the same
plan counts). A member of an empty field is empty, not an error, so `x.includes('a')` is safe.

Keep conditions consistent with the office's templates: the Word template wraps what it prints from a
detail in the same condition as the form (hidden fields keep their values). Don't hide a field that a
template prints unconditionally - tell the user which template to change.

## 9. AI Fill prompts (`aiConfig.prompt`)

Quicker's AI Fill reads the project's documents and fills the form. Without a prompt it guesses from
the label. A good prompt (≤4000 chars) says:
1. **Where** - which document or source: "מנסח רישום המקרקעין (טאבו)", "מהיתר הבנייה האחרון",
   "מחוזה החכירה מול רמ"י", "מתשריט הבית המשותף", "מהפניית הבנק", "מהביקור - לא ממסמכים".
2. **What exactly** - which value when there are several ("השטח הרשום של תת-החלקה, לא שטח החלקה").
3. **Format and unit** - "מספר בלבד, במ"ר", "התאריך כפי שמופיע", "בדיוק אחת מהאפשרויות".
4. **When to leave it empty** - "אם המסמך לא צורף - השאר ריק. אל תסיק ואל תעריך".

Examples:
- `extractDate`: "תאריך הפקת נסח רישום המקרקעין (מופיע בראש הנסח). אם לא צורף נסח - השאר ריק."
- `forcedSaleDiscount`: "אל תמלא - שיקול דעת של השמאי." (a prompt can also tell AI Fill to stay away)
- group `tenantsTable`: "שורה לכל שוכר מתוך חוזי השכירות או רשימת השוכרים שצורפה: שם, שטח במ"ר,
  דמי שכירות חודשיים, תאריך סיום. אל תכלול שוכרים שלא מופיעים במסמכים."
Valuation figures and professional judgements (value, adjustments, discounts, approaches) should say
explicitly not to fill - AI Fill must not invent an appraiser's conclusion.

A group's prompt often describes its columns ("fill the apartment number only for תב"ע"). When you
change a column's condition or prompt, read the group's prompt too and update it in the same plan
(`update_field` on the group with `set.aiConfig`) - otherwise the two contradict each other.

## 10. Links to the project card (`systemPath`)

A top-level field can be bound to a project or customer column, so the form and the project card show
one value (and lists, search and automations see it). Allowed **(server)**: `p.name p.city p.street
p.house p.apartmentNumber p.neighborhood p.gush p.helka p.subHelka p.plot p.plotByTaba p.floor p.rooms
p.squareMeter p.appraisalType p.appraisalPurpose p.propertyType p.propertyDestiny p.referrer
p.referrerCase p.referrerReference p.apartmentOwner p.dueDate p.determinesDate p.visitDate`, customer
`c.name c.phone c.email c.address c.city c.personalIdentity` (read to pre-fill), `p.agentName`,
`today`. Not inside groups. Before adding such a field, check the form doesn't already have one bound
to that column (`form_index.md` shows `-> p.x`).

## 11. Changing what exists

| want | do | not |
|---|---|---|
| better wording | `update_field` `set.label` | a new field |
| another type | only: text -> textarea/textSod/textPom; textSod <-> text/textPom; textarea -> richtext; select -> selectOther/radio; radio -> select/selectOther; number -> currency **(server)** | anything else: add a new field and hide the old |
| retire a field | `hide_field` (data kept, AI Fill skips it, `show_field` reverses) | `remove_field` - refused if any project holds data, a Word template reads it, a condition reads it, it's linked to a project column or a computed field uses it **(server)** |
| tidy option text | add the corrected option; leave the old (projects hold it) | rename an option in place |
| another section | `move_field` (top-level only) | remove + add (loses the data link) |
| pre-filled text | `update_field` `set.defaultValue` - fills empty fields only (new projects, unfilled ones, the Word export); the plan says how many projects keep their own text | expecting saved projects to change |
| a card's heading, guidance, condition, AI prompt | `update_row` on a field of the card | a form-builder task (no longer needed) |
| a section's title, icon, AI prompt | `update_section` | |

A hidden field still prints in old templates for old projects and prints empty for new ones; the same
holds for a field behind a new condition. The plan lists those templates
(`impact.wordTemplatesStillPrinting`, also in `summaryHe`) - wrap the lines there in the same condition,
or keep the field.

## 12. Limits (server)

60 ops per plan; label/title ≤120; section title ≤80; explan ≤500; placeholder ≤120; suffix ≤20;
aiConfig.prompt ≤4000; options ≤300 × ≤200 chars; group ≤80 fields; condition ≤1000 chars; form
schema ≤2 MB; image `limit` 1-30; class tokens `col-(xs|sm|md|lg)-1..12`, ≤4 tokens; section icon a
Font Awesome 4 name (`fa-bank`).

## 13. One form, several report types

Many offices keep one form for all their work. Adding a report type (a standard-19 collateral report,
an extended report, a court opinion) to such a form must not clutter every other project.

**First choice - a separate office form for the type.** Quicker opens the form whose `appraisalTypes`
holds the project's appraisal type, so projects of that type get it automatically and the others don't
see it. `create_custom_form_template` with `basedOnTemplateId` = the office's current form keeps
everything the office already has (names stay the same, so Word templates keep working); then plan only
the additions on the copy. Pass `appraisalTypes` explicitly - omitted, the copy keeps the source's types
and the create fails on the clash rule (one office form per appraisal type). If the source form already
lists the new type, create with `[]`, remove the type from the source (`set_form_props`), then give it
to the copy - two plans, both shown to the user.

Default texts (bank notes, declarations, limiting conditions) are shared by every report type on one
form. A separate form gives the new type its own; on one form, see item 6.

When `create_custom_form_template` is off (absent from the tools) and the user named the current form:
plan on the current form with the switch below, and offer the separate form as a recommendation -
what it needs (a new appraisal type in the settings, a manager enabling form creation) and what it
solves.

**When the office wants one form** (or the type isn't an appraisal type of its own - "extended" vs
"short", a bank that wants extra items):

1. **One switch, not many.** Reuse what the form has - a "סוג דוח" / `reportKind` radio, a bank select,
   the org `appraisalType` list - or add one field: a `radio` when the report kinds exclude each other,
   a `checkbox` for "also does X" ("שומה לבטוחה לפי תקן 19"). Put it at the top of the first section,
   with an AI Fill prompt only if the engagement letter states it; otherwise tell AI Fill to leave it.
2. **A condition on every new field and group**, all reading that one switch, written the same way:
   `project.additionalDetails.reportKind == 'שומה מורחבת'`, or for a checkbox
   `project.additionalDetails.collateral19`. Fields inside a group need no condition of their own when
   the group has one.
3. **Scope when there is no report of the type yet** (built from the standard alone): the standard's
   required items plus the "when relevant" items that fit the property the office will typically value
   (offices, retail and rented assets for business credit: lease, tenants, occupancy, income) - all
   behind the switch. The rest go to the findings.
4. **Placement.** Sections can't carry a condition (`add_section` has no `if`); cards can
   (`update_row`). So:
   - a new section for the type shows its title on every project, even when all its fields are hidden.
     Use one only when the type is a real chapter of the report (and say so to the user); otherwise put
     the fields next to their siblings in the existing sections (the bank's loan number beside the
     other bank details, the forced-sale discount beside the value).
   - a block of fields that only the new type has can be **a card with the switch as its condition**
     (`update_row`, §5) - one condition instead of one per field.
   - **a field placed `after` a field that sits in a conditional card joins that card and inherits its
     condition** - the engine does it silently and the plan summary doesn't mention it. Use it on
     purpose when the form already has a card for the type; avoid it otherwise (`check_ops.py` warns).
   - an existing card the type needs that another switch hides: `update_row` can widen its condition
     (`reportKind == 'שומה מורחבת' || collateral19 === true`) - with the user's agreement, since it
     changes what the other reports show.
5. **Sections the new type needs that another switch hides.** `form_index.md` "Conditions that name
   option values" shows them (a planning card shown only for "שומה מורחבת"). Either widen the card's
   condition with `update_row` (item 4 - it changes what other reports show, so ask), or say it in the
   switch's `explan` ("בשומה לפי תקן 19 בוחרים גם 'שומה מורחבת'"). Update that other switch's AI Fill
   prompt in the same plan ("בשומה לפי תקן 19 - תמיד 'שומה מורחבת'"), or AI Fill may pick the answer
   that hides the section.
6. **Existing fields that conflict.** Read the `default:` texts in the index (notes,
   declarations, limiting conditions): their pre-filled text may contradict the new type (a mortgage
   declaration on a court opinion). Either rewrite the default so it fits every type (`update_field`
   `set.defaultValue` - saved projects keep their text), or keep the old field for the other types
   (`if`: the switch is off) and add a twin with the type's text as its default (`if`: the switch is
   on) - a default only fills a field whose conditions hold, so each report gets its own text. The
   Word template then prints the twin under the same condition.
   Never put a condition on an existing field the other report types need.
7. **Tell the user** which projects will see what: "בפרויקט שבו סוג הדוח הוא X יופיעו N שדות חדשים;
   בשאר הפרויקטים הטופס לא משתנה" - and that the Word template for the new type needs its own
   sections (the template skill can wrap them in the same condition).

