# Template syntax as Quicker uses it

easy-template-x + angular expressions + Quicker's own image and html plugins. Production runs engine
**v3.2.1**; the **v8** branch is about to be deployed (see quicker-contract.md §0). Every behaviour
below was verified by rendering with `scripts/render_check.mjs` on both engines; where they differ it
says so. Write templates that are correct on both.

## Contents
1. Tags
2. Expressions
3. Conditions inside a sentence
4. Conditional paragraphs and sections
5. Table rows and cells
6. Loops over paragraphs
7. If / else
8. Pitfalls (what the linter catches)
9. Style conventions
10. v3 vs v8 differences

## 1. Tags

| tag | meaning |
|---|---|
| `{p.ad.x}` | print a value (keeps the formatting of the tag's run) |
| `{#expr}` ... `{/expr}` | block: a **loop** when `expr` is an array (repeatable group), otherwise a **condition** (truthy -> shown) |
| `{p.ad.x \| filter:arg}` | value through a filter |
| `{^x}...{/x}` | inverted block - v8 branch only; `{#!x}...{/!x}` does the same on both engines |
| `{#x [% loopOver: 'row' %]}` | tag options - v8 branch only |

- Single braces only. A tag must sit inside one paragraph (it may span several runs - the engine joins
  them - but `apply_plan.py` always writes each new tag as one run).
- The closing tag repeats the opening expression exactly - house convention, and the only way to read
  a nested template. (`{/}` also works; old templates use it; don't write new ones.)

## 2. Expressions

Angular expressions: `== != > < >= <= && || ! ( )`, string literals in straight single quotes, numbers,
`x.length`, `arr[0].field`, ternary `a ? 'x' : 'y'`, literals `{'אין'}`, filters with `|`.

```
{#p.ad.buildingType == 'בנייה רוויה'}...{/p.ad.buildingType == 'בנייה רוויה'}
{#p.ad.buildingType != 'בנייה רוויה'}...{/p.ad.buildingType != 'בנייה רוויה'}
{#p.ad.numberOfEntries > 1}...{/p.ad.numberOfEntries > 1}
{#p.ad.referrer == 'בנק לאומי' || p.ad.referrer == 'בנק הפועלים'}...{/p.ad.referrer == 'בנק לאומי' || p.ad.referrer == 'בנק הפועלים'}
{#p.ad.propertyIdentification | includes:'נסח רישום מקרקעין'}...{/p.ad.propertyIdentification | includes:'נסח רישום מקרקעין'}
{#!(p.ad.propertyIdentification | includes:'חוזה חכירה')}...{/!(p.ad.propertyIdentification | includes:'חוזה חכירה')}
{#p.ad.permits.length}...{/p.ad.permits.length}
{#!p.ad.elevators}אין{/!p.ad.elevators}
{p.ad.elevators ? p.ad.elevators + ' מעליות' : 'אין'}
{p.ad.d ? (p.ad.d | date) : 'לא ידוע'}          (a filter inside a ternary branch needs parentheses)
```

Truthiness: empty string, `0`, `null`, `false`, missing -> false. An **empty array is truthy**: "group has
rows" is `.length`, not the bare group name (as a loop, an empty array simply renders nothing). Image
fields are the exception - never `.length` on them (quicker-contract.md §5).

## 3. Conditions inside a sentence

Wrap just the words that depend on the value, both tags in the same paragraph:
```
המחזיק בנכס: {p.ad.propertyHolderName}{#p.ad.propertyHolder} - {p.ad.propertyHolder}{/p.ad.propertyHolder}.
מס' קומות: {p.ad.numberOfFloors}{#p.ad.floorOn}, מעל קומת {p.ad.floorOn}{/p.ad.floorOn}
```
In a **numbered** paragraph (`num` in the outline) or a **table cell**, use a ternary value tag instead
(§10): `זהות מזמין השומה: {p.ad.appraisalOrdererName}{p.ad.appraisalOrderer ? ' - ' + p.ad.appraisalOrderer : ''}`.

## 4. Conditional paragraphs and sections

Measured on v3 and v8 (identical results) for a block of two paragraphs X1 X2 between "before" and
"after" - ∅ is an empty paragraph left in the generated report:

| placement | true | false |
|---|---|---|
| **anchor**: `before{#c}` / `X1` / `X2{/c}` | before X1 X2 after | before after |
| own lines: `{#c}` / `X1` / `X2` / `{/c}` | before ∅ X1 X2 ∅ after | before ∅ after |
| `{#c}X1` / `X2{/c}` | before X1 X2 after | before ∅ after |
| `before{#c}` / `X1` / `X2` / `{/c}` | before X1 X2 ∅ after | before after |
| `{#c}X1{/c}` (one paragraph) | before X1 after | before ∅ after |
| old templates: `{#c}X1` / `{/c}after` | after merges into X1's paragraph (its style leaks) | |

So the only placement that never leaves an empty line is **anchor**: opener at the end of the
paragraph before the block, closer at the end of the block's last paragraph. A tag-only line ("own
line") is kept by the engine as an empty paragraph - unless production strips such paragraphs
(open question, quicker-contract.md §8).

`wrap_block` does this for you. All block tags meet at *boundaries* between sibling elements; tags
that meet at one boundary are written together (closers inner->outer, then openers outer->inner), so
nesting is always right. At each boundary it uses the paragraph on the left (anchor). Fallbacks, with a
warning in the report: nothing usable on the left (start of a cell/text box, right after a table, or
a numbered paragraph when a block opens there) -> opener at the start of the first paragraph, or a
tag-only line; a block ending with a table -> closer on its own line after the table. Verified: 32
true/false combinations of five nested/adjacent blocks, with headings, numbered paragraphs and a table,
always produce the right text on both engines. `"block_style": "own"` in the plan forces tag-only
lines everywhere (the team's previous convention) - use it only if production strips empty paragraphs.

Two placements that cost an empty line, and how to avoid them:
- **A block that ends right after a table** gets its closer on a line of its own (nothing to anchor on).
  If the document has an empty paragraph after the table, include it in the block (`"to"` = that
  paragraph) - the closer anchors there and no extra line appears.
- **A loop whose first paragraph has nothing usable before it** (start of a cell, after a table, after a
  numbered heading) needs a tag-only line: prepending the opener to the first paragraph glues the items
  together (the empty end of item 1 merges into item 2 - verified on both engines). A *condition* can be
  prepended instead (clean when true, one empty line when false). Pass `--catalog` to `apply_plan.py` so
  it knows which openers are loops; `"loop": false/true` on the op overrides.

An optional "label: value" line = a one-paragraph `wrap_block` on the value field:
```json
{"op": "wrap_block", "from": "P0071", "to": "P0071", "open": "{#p.ad.propertyNotes}", "close": "{/p.ad.propertyNotes}", "note": "שורה רק כשיש הערות"}
```
A whole chapter under a form option (heading + text + table):
```json
{"op": "wrap_block", "from": "P0130", "to": "T5", "open": "{#p.ad.extanded == 'שומה מורחבת'}", "close": "{/p.ad.extanded == 'שומה מורחבת'}"}
```
`from`/`to` can be paragraph IDs or table IDs, but both must be in the same container (body, the same
table cell, the same text box).

## 5. Table rows and cells

**Rows** - opener at the start of the row's first cell, closer at the end of the row's **last** cell
(`wrap_rows`). Same on both engines for **one or two rows**: they are repeated (loop) or removed
(condition). A block over **3+ rows breaks on v3** (the middle rows stay, or are duplicated) -
`wrap_rows` refuses it; wrap rows one or two at a time, or wrap the whole table with `wrap_block`.
```
| {#p.ad.permits}{permitNumber} | {permitDate | date} | {permitDescription}{/p.ad.permits} |
```
Keep header rows outside the loop. **A table whose every row is inside a loop/condition ends up with no
rows when the group is empty, and Word treats such a file as damaged** - wrap the table (and its caption)
with `wrap_block` on `p.ad.x.length` (the render check flags row-less tables). Opener and closer in the
same grid column (single-column table, or a merged last row) makes the engine repeat the COLUMN -
`wrap_rows` refuses that; on v8 `{#x [% loopOver: 'row' %]}` forces rows.

**An item that spans two rows** (row 1 = the fields, row 2 = one merged full-width cell with notes, as in
lease and mortgage tables of bank reports): `wrap_rows` refuses it (opener and closer in the same grid
column). Loop the whole table instead - `wrap_block` from the table to the table (one copy of the table
per item, header row included) - and wrap table + caption in a `.length` block. Identical on v3 and v8.

**A list nested inside a cell** (all the lessees of one lease, in its cell): there is no loop inside a cell
and no filter that joins one field of a list of objects. Print the first item (`{LeaseBName[0].LeaseContractBuyer}`)
and list it under decisions as **חשוב**; the alternative is a separate table/paragraph loop outside the cell.

**Inside one cell** the engines differ: on v3 any block inside a table works on whole rows, so
`{#x}text{/x}` in a cell removes the entire row when false; on v8 it removes only that text. Don't put
blocks inside cells - for optional text in a cell use a ternary (§3), for an optional row use
`wrap_rows`. Then both engines agree.

## 6. Loops over paragraphs

```
{#p.ad.AdditionalGroup}על פי {AdditionalTitle} מתאריך {AdditionalDate | date}:
{AdditionalDetailsAgreement}{/p.ad.AdditionalGroup}
```
`wrap_block` with the group as the expression. For an inline list use `wrap_inline` and `_isLast` for
separators: `{#p.ad.linkagesGroup}{linkages}{#!_isLast}, {/!_isLast}{/p.ad.linkagesGroup}`.

## 7. If / else

No else: two blocks with opposite conditions.
```
{#p.ad.constructionEHarigot}{p.ad.constructionEHarigot}{/p.ad.constructionEHarigot}{#!p.ad.constructionEHarigot}לא נמצאו חריגות בנייה{/!p.ad.constructionEHarigot}
```
For a select with several options, one block per option value.

## 8. Pitfalls (the linter catches these)

| problem | why it breaks | fix |
|---|---|---|
| `{#!p.ad.x == 'v'}` | `!` applies to `p.ad.x` first -> `false == 'v'` -> never shown | `p.ad.x != 'v'` or `!(p.ad.x == 'v')` |
| bare `{fieldName}` outside its loop | prints empty | full `p.ad.` path, or move it into the loop |
| unknown filter `{x \| upper}` | prints empty | the filter list |
| `{#group}` used as a condition / `{#!group}` | an empty array is truthy | `.length` / `!x.length` |
| `[n]` / `.length` / a loop on an image field | one image = an object | `{p.ad.photos \| maxSize:w:h}`, condition `!(p.ad.photos \| isEmpty)` |
| printing a checkbox / multi-select raw | prints `true` / `a,b` | condition / `\| list:', '` |
| block opened in a numbered paragraph | v3 list strategy deletes/scrambles whole paragraphs | `wrap_block`, or a ternary |
| block inside a table cell | v3: whole row; v8: only the text | ternary, or `wrap_rows` |
| `{x \| html}` sharing a paragraph | block HTML replaces the whole paragraph | alone in its paragraph |
| open/close in the same table column | column loop | `wrap_rows` (2+ cells per row) |
| a block over 3+ table rows | v3 keeps/duplicates middle rows | one or two rows per block |
| every row of a table inside a loop/condition | empty group -> table with no rows -> Word reports damage | wrap the table in `.length` |
| expression over ~200 characters | unmaintainable; some angular-expressions builds cap at 250 | simplify / ask for a field |
| `{/}` anonymous closer | works but unreadable | repeat the opener |
| `{{x}}` double braces | other engine's syntax | single braces |

## 9. Style conventions

- One space around operators and pipes is fine: `{p.ad.x | currency}`; no spaces inside the path.
- Labels and punctuation stay static text outside the tag: `גוש: {p.gush}`.
- Units outside the tag: `{p.ad.squareMeterMeasured | currency} מ"ר`.
- Prefer conditions the form already uses for showing/hiding fields (`shown-if` / `block-if` / `group
  condition` in the catalog) - the report then shows exactly the sections the appraiser filled.

## 10. v3 vs v8 differences (verified)

| situation | v3.2.1 (production) | v8 (branch) |
|---|---|---|
| block opened in a numbered paragraph (`w:numPr`) | list strategy: whole paragraphs repeated/removed, multi-paragraph blocks scrambled | content only |
| block inside one table cell | whole row(s) | that text only |
| picture placeholder (tag in alt text) | ignored - the template's picture prints | swapped / deleted when empty |
| `{^x}`, `[% options %]` | not supported (`[% %]` breaks the tag) | supported |
| anchor blocks, `wrap_rows`, inline conditions in plain paragraphs, ternaries, images via `maxSize`/`grid` | same | same |

To compare engines on a template: `setup_render.sh v3` and `setup_render.sh v8`, render the same data
with both, then `diff_renders.py`.
