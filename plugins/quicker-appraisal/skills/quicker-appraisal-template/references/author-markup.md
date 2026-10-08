# Author markup - instructions typed into the Word document

Users can tell the skill exactly what they want by writing in the document itself. Part A is the
user-facing guide (Hebrew - share it when a user asks how to mark a document). Part B is how to
interpret it.

---

## Part A - מדריך למשתמש: איך מסמנים בוורד

כותבים הוראות בתוך סוגריים מרובעים כפולים `[[ ... ]]`, בדיוק במקום שבו הן חלות. אפשר לכתוב בעברית
חופשית - שם השדה כפי שמופיע בטופס השומה מספיק.

| מה כותבים | מה קורה |
|---|---|
| `[[גוש]]`, `[[תאריך הביקור]]`, `[[שווי שוק]]` | כאן ייכנס הערך של השדה |
| `[[p.ad.rooms]]` | אפשר גם מזהה מדויק של שדה |
| `[[אם: שומה מורחבת]]` ... `[[סוף]]` | הקטע שבין הסימונים יוצג רק כשהתנאי מתקיים. יכול להיות כמה מילים בתוך משפט, או כמה פסקאות וטבלאות |
| `[[אם: ...]]` ... `[[אחרת]]` ... `[[סוף]]` | הקטע הראשון כשהתנאי מתקיים, השני כשלא |
| `[[פסקה אם: יש מעלית]]` בתחילת פסקה | כל הפסקה מותנית |
| `[[לכל: בעלים]]` ... `[[סוף]]` | הקטע חוזר לכל פריט בקבוצה. בתוכו `[[שם]]`, `[[ת.ז]]` מתייחסים לפריט |
| `[[שורה לכל: היתרים]]` בתוך שורת טבלה | השורה תשוכפל לכל פריט |
| `[[שורה אם: נכס בבנייה]]` בתוך שורת טבלה | השורה תוצג רק כשהתנאי מתקיים |
| `[[תמונה: תמונות הבניין, 2 בשורה]]` | תמונה או גלריה |
| `[[קבוע]]` בתחילת פסקה | הפסקה נשארת טקסט קבוע, גם אם נראה שיש בה נתונים |
| `[[הערה: הפסקה הזו רק לבנק לאומי]]` | הוראה חופשית לסקיל. לא נכנסת לתבנית |

דרכים נוספות:
- **הערת Word** (סקירה ← הערה חדשה) על טקסט מסומן: כותבים בה את אותה הוראה בלי סוגריים -
  `משתנה: מספר חדרים`, `אם: יש חריגות בנייה`, `לכל: משכנתאות`, `קבוע`. ההוראה חלה על הטקסט שסומן.
- **הדגשה בצהוב** על ערך לדוגמה (למשל "6938"): הסימן אומר "זה נתון שמשתנה - תמפה אותו".
- **תגיות מוכנות** כמו `{p.ad.rooms}` שכבר נכתבו במסמך נשמרות ונבדקות.

תנאים נכתבים בשפה רגילה: `אם: הבנק הוא לאומי`, `אם: אין חריגות`, `אם: מספר כניסות גדול מ-1`,
`אם: מסמכי הזכויות כוללים נסח טאבו`. הסקיל מתרגם לשדה ולערך המדויקים בטופס.

---

## Part B - interpreting markup (for the model)

### Precedence
Author instructions beat inference. If the author marked a value, map it even if you would not have;
if a paragraph is marked `[[קבוע]]`, do not tag it even if it contains numbers.

### Resolving a description to a field
1. Exact path (`p.ad.x`, `p.gush`) -> use it (lint verifies it exists).
2. Match the Hebrew against catalog labels: exact label > label contains the words > section context
   (the same words can exist in several sections - e.g. "תאריך" in five groups; pick by where the
   markup sits and which section it belongs to).
3. Inside `[[לכל: ...]]` resolve against the loop group's fields first.
4. Still ambiguous between 2+ fields -> pick the most plausible, and list the alternatives in the report.
5. No field matches -> do not invent. Leave the `[[...]]` text in place (the linter reports it as
   `leftover-markup`) and list it under "ללא משתנה מתאים". Exception: things Quicker is known not to hold
   (quicker-contract.md §7 - licence number, appraiser phone/email): replace the marker with a fill-in
   line `______` (so generated reports don't print `[[...]]`), and list it under "ללא משתנה מתאים" as
   **חשוב** - the office writes its fixed text there once.

### Turning markup into ops
- Variable markup: `replace` the exact `[[...]]` text with the tag (the tag inherits the markup's
  formatting; highlight is removed automatically).
- `[[אם: X]] ... [[סוף]]` around **part** of a paragraph: two `replace` ops - the markers become `{#expr}`
  and `{/expr}` (an inline condition; in a numbered paragraph or a table cell use a ternary instead).
  When the markers wrap the **whole** paragraph, `delete` both markers and `wrap_block` that paragraph -
  an inline block around a whole paragraph leaves an empty line when false.
- Markers that **stand alone in their own paragraphs** (or open/close a multi-paragraph region): delete
  the marker text (`delete`, or `delete_paragraph` if the paragraph holds only the marker), then
  `wrap_block` from the first to the last content paragraph/table. Don't turn standalone marker
  paragraphs into tag paragraphs - that pattern leaves empty lines (see template-syntax.md §4).
- `[[אחרת]]`: split into two blocks - `{#expr}`...`{/expr}` and `{#!(expr)}`...`{/!(expr)}` (or the
  natural negation: `!=` for `==`, `!x` for a boolean, `!x.length` for a group).
- Two markups that are alternatives of one field (`[[אם: שומה מורחבת]]` ... and `[[אם: שומה מקוצרת]]` ...):
  write them as `== 'A'` and `!= 'A'` so exactly one of them always prints, even when the field is
  empty. Say so in the decisions list.
- `[[פסקה אם: X]]`: delete the marker, `wrap_block` that single paragraph.
- `[[לכל: G]]`: like a condition, with the group path as the expression; inner markup resolves to bare
  field names of G.
- `[[שורה לכל: G]]` / `[[שורה אם: X]]`: delete the marker, `wrap_rows` on that row.
- `[[תמונה: ...]]`: `replace` with the image tag alone in its paragraph - `{p.ad.x | maxSize:w:h}`, plus
  `| grid:N` when the author asks for N per row (see quicker-contract.md §5).
- `[[הערה: ...]]`: follow it, then `delete` it (or `delete_paragraph`).
- `[[קבוע]]`: `delete` the marker; tag nothing in that paragraph.
- Comments: apply the instruction to the commented range (the outline shows `⟦cN│...⟧` and the comment
  text). After all comment instructions are applied, run `{"op": "strip_markup", "markup": false,
  "comments": true}` to remove the comments from the template.
- Highlight on empty runs (`⟦hl:yellow│⟧` with nothing inside) is formatting debris, not an instruction -
  ignore it.
- Highlighted sample values: map them like any value (`replace`). `replace` removes the highlight from the
  new tag run. If the document uses highlight as a colour code for existing tags (like production
  templates do), leave it alone.

### Translating natural-language conditions
Map the words to a field and an operator using the catalog's options:
- "שומה מורחבת" -> `p.ad.extanded == 'שומה מורחבת'` (value must be one of the field's options, verbatim)
- "יש חריגות" -> `p.ad.constructionEHarigot` (truthy); "אין חריגות" -> `!p.ad.constructionEHarigot`
- "הבנק הוא לאומי או הפועלים" -> `p.ad.referrer == 'בנק לאומי' || p.ad.referrer == 'בנק הפועלים'`
- "מסמכי הזכויות כוללים נסח" -> `p.ad.propertyIdentification | includes:'נסח רישום מקרקעין'`
- "יש היתרים" -> `p.ad.permits.length`
- "יותר מכניסה אחת" -> `p.ad.numberOfEntries > 1`
If the value the author wrote is not an exact option, use the closest option and note it in the report.
