# Quicker render data contract

What the Word generator receives at render time, as defined by Quicker
(`document-context.js`, `document-data-loader.js`, `word.js`). Anything not listed here, and not in the
form catalog, renders empty. **The connector's `get_word_template_variables` is the source of truth**
(variables, system fields, filters, rules, sample data); where it and this file disagree, the tool wins
and this file is the fallback for older connectors.

## Contents
0. Engines
1. Namespaces
2. Questionnaire fields (`p.ad`)
3. Repeatable groups (loops)
4. System fields (outside the questionnaire)
5. Images
6. Filters
7. What does not exist
8. Points still to confirm

## 0. Engines

| | production (master) | branch `feat/easy-template-x-v8` (deploying soon) |
|---|---|---|
| engine | easy-template-x 3.2.1 + easy-template-x-angular-expressions 0.1.0 | easy-template-x ^8 + angular-expressions 1.5.2 |
| handler | plugins Loop, ImageGrid, StyledImage, Link, HtmlAwareText, Html; delimiters `{ } # /`; maxXmlDepth 1000 | same + tag options `[% ... %]` |
| v8-only features | - | picture placeholders (tag in alt text), `{^x}...{/}`, tag options `[% loopOver: 'row' %]` |

Everything else (paths, filters, loops, conditions, HTML) is identical. v8-only features may already be
used - the branch is about to be deployed - but say so in the report, because until then production
prints the template's own picture / ignores the options. A tag whose expression fails prints EMPTY
(the report is not aborted) - the linter is the only safety net. Curly quotes are normalised.

## 1. Namespaces

| prefix | meaning | notes |
|---|---|---|
| `p` | the project | alias of `project`; the house convention is `p` |
| `p.ad` | the appraisal questionnaire (שאלון השומה) | alias of `project.additionalDetails`; convention `p.ad` |
| `c` | primary customer | |
| `customers` | all customers (loop) | |
| top level | `today`, `todayISO`, `ownerName`, `ownerManagerName`, org images | |

- `{visitDate}` and `{additionalDetails.visitDate}` render **empty** - always write the full `p.ad.` path
  outside loops.
- The display conditions in the form schema (`project.additionalDetails.x === ...`) belong to the form
  screen, not to Word. `build_catalog.py` translates them to template syntax (`p.ad.x == ...`).
- Hebrew or hyphenated field names work as-is: `{p.ad.הסכם-חכירה}` - Quicker converts them.
- `p.visitDate` is the visit scheduled on the project; `p.ad.visitDate` is the form field the appraiser
  fills in. Different values - pick by meaning (a report's "מועד הביקור" is usually `p.ad.visitDate`).

## 2. Questionnaire fields

Every field of the chosen form, at `p.ad.<name>`. A field the project left empty prints the form's
**default value** when it has one and its display conditions hold (the export applies defaults the way
the edit form does - October 2026), so boilerplate the office keeps as a field default (bank notes,
declarations) prints even in projects nobody opened. Don't hard-code that text next to the tag. The raw
form types and how to print them:

| form type | example tag | notes |
|---|---|---|
| text, textSod, textPom, read | `{p.ad.visitorName}` | |
| textarea | `{p.ad.bankNotes}` | plain text; line breaks are kept |
| richtext | `{p.ad.x \| html}` | HTML from the rich editor - always add `\| html`, alone in its paragraph (§6) |
| select, selectOther, radio | `{p.ad.extanded}` | conditions compare to the option text: `p.ad.extanded == 'שומה מורחבת'` |
| checkboxList | `{p.ad.propertyIdentification \| list:', '}` | an array; test one option with `p.ad.x \| includes:'נסח רישום מקרקעין'`, non-empty with `p.ad.x.length` |
| checkbox | `{#p.ad.lobby}...{/p.ad.lobby}` | boolean - use only as a condition |
| date | `{p.ad.documentDate \| date}` | DD/MM/YYYY; other formats: `date:'DD.MM.YY'` (moment) |
| number | `{p.ad.rooms}` | |
| currency | `{p.ad.currentMarketValue \| currency} ₪` | `currency` adds thousands separators only - write ₪ yourself. If the field's suffix is מ״ר it is an AREA: `{... \| currency} מ"ר` |
| readNumber | `{p.ad.constructionValPolt \| currency} ₪` | computed number shown with ₪ on screen |
| image | `{p.ad.photo \| maxSize:400:300}` | see §5 |
| html (widget) | depends | custom UI widget; `planDataStatus` is a list of plans: `{#p.ad.planDataStatus}{planNumber} {date \| date} {mahut} {status}{/p.ad.planDataStatus}` |

**Linked fields -> `p.*`.** A form's `metadata.projectFieldsMap` links project fields to form fields
(the system form links city, street, house, gush, helka, subHelka, plot, plotByTaba, apartmentNumber -
from the first row of the address / registration groups - plus floor, rooms, referrer, visitDate,
squareMeter, propertyType, propertyDestiny, determinesDate, appraisalPurpose). House rule: print a
linked value through its `p.*` path. `build_catalog.py` reads the map: linked fields show their `p.*`
tag and a `LINKED` note, group fields show "first row also available as p.x". Fields that are not
linked stay `p.ad.*`. It also reports a link that points at a field the form doesn't have (the system
form maps `apartmentNumber` to `address[0].apartmentNumber`, but the apartment number lives in
`addressDetails`) - such a `p.*` value is not filled from the questionnaire; use the group field
(`p.ad.addressDetails[0].apartmentNumber`) until the map is fixed.

## 3. Repeatable groups

```
{#p.ad.borrowers}{borrowerName} ת.ז. {borrowerIdNumber}{/p.ad.borrowers}
```
- Inside the loop write field names bare. Nested groups are opened by bare name too:
  `{#p.ad.perutNesachTabo} ... {#nesachTaboOwner}{nesachTaboName}{/nesachTaboOwner} ... {/p.ad.perutNesachTabo}`.
- Available inside every loop: `_idx` (**from 0**), `_isFirst`, `_isLast`. Numbering from 1:
  `{_idx | inc}`. Separators: `{#p.ad.linkagesGroup}{_idx | loopSep:'comma'}{linkages}{/p.ad.linkagesGroup}`
  (no separator before the first item) or `{linkages}{#!_isLast}, {/!_isLast}`.
- Outer-scope values stay reachable inside a loop (`{p.number}` works anywhere).
- "Does the group have rows?": `{#p.ad.permits.length}...{/p.ad.permits.length}`;
  first row only: `{p.ad.perutNesachTabo[0].nesachTaboDate | date}`.
- Groups can carry a display condition (catalog: `group condition`). If the report prints the group
  under a heading, wrap heading + loop in that condition.

## 4. System fields

As listed by `get_word_template_variables` (`general`), October 2026:

Project (`p`): `p.number` (מספר שומה), `p.name`, `p.address` (כתובת מלאה), `p.city`, `p.street`,
`p.house`, `p.neighborhood`, `p.gush`, `p.helka`, `p.subHelka`, `p.plot`, `p.plotByTaba`,
`p.apartmentNumber`, `p.floor`, `p.rooms`, `p.squareMeter`, `p.appraisalType`, `p.appraisalPurpose`,
`p.propertyType`, `p.propertyDestiny`, `p.status`, `p.referrer`, `p.referrerReference` (מספר הפניה אצל
המזמין), `p.referrerCase` (מספר תיק אצל המזמין), `p.apartmentOwner`, `p.dueDate`, `p.determinesDate`,
`p.visitDate`, `p.visitContactName`, `p.visitContactPhone`, `p.agentName` (the appraiser; the visitor
filled in the form overrides the assigned appraiser).

Customer: `c.name`, `c.phone`, `c.email`, `c.address`, `c.city`, `c.personalIdentity` (ת.ז / ח.פ);
all customers: `{#customers}{name}{#isPrimary} (לקוח ראשי){/isPrimary}{/customers}` - each with name,
phone, email, address, city, personalIdentity, isPrimary.

General: `today` (already DD/MM/YYYY - no `| date`), `todayISO` (format with `| date`), `ownerName` (the
office), `ownerManagerName` (signs the report).

Top-level `quickSalePrice` appears in old production templates but is not in the variables tool - use
only if the user confirms (the linter warns).

## 5. Images

An image value is `{_type:'image', source, format, width, height}` - already display-sized (form images
are pre-shrunk to <= 1800 px, EXIF-rotated, then capped at 590x435; organisation images at 680x800;
webp/heic/svg converted). No alt text (pictures are marked decorative). **A field holding one image is an
object; several images are an array; an empty field is `[]`.** Works the same on v3 and v8:

| need | tag |
|---|---|
| all images of a field, flowing (one or many) | `{p.ad.buildingImages \| maxSize:290:220}` |
| as a grid table, N columns | `{p.ad.propertyImages \| maxSize:290:220 \| grid:2}` - alone in its paragraph (the table is inserted before it) |
| styled | `\| frame:'1pt':'#333'`, `\| rounded:10`, `\| gap:12`, `\| align:'center'` (order: maxSize -> frame/rounded/gap/align -> grid) |
| a condition around a caption/heading | `{#!(p.ad.photos \| isEmpty)}...{/!(p.ad.photos \| isEmpty)}` |

One element per image (each photo in its own table row with a caption, say): loop over the field and
use `{image}` inside - `{#p.ad.photos}{image | maxSize:400:300}{/p.ad.photos}`. A single-image field
runs as a one-item list. (This needed Quicker's image-loop fix in word-expressions.js /
word-loop-plugin.js / word-image-plugin.js; before it, these loops printed nothing.)

Never:
- `.length` on an image field - with one image the field is an object, so `.length` is undefined and
  the condition hides the only image;
- `[0]` / `[n]` - empty when the field holds a single image (works only with 2+); prefer the whole field
  or a placeholder;
- a condition just to hide an empty image tag - an empty field prints nothing anyway.

**Picture placeholder (v8 branch only):** put the tag - and nothing else - in the alt text of a picture
that is already in the document (`set_alt` op). The picture is swapped for the data image and keeps its
frame, position and wrapping. A multi-image field gives its first image. An empty field (or an index
beyond the images) deletes the picture. Use `| maxSize:<frame w>:<frame h>` (the outline shows each
picture's size). `set_alt` also swaps the sample picture for a neutral grey box - a client's photo must
never stay inside a template, and until v8 is deployed that box is what production prints.
Choosing: one designed photo frame -> placeholder; a set of photos (several frames, a row, a block) ->
one flow or grid tag that adapts to any number of images (placeholders can't show image 2 of a field
reliably).

Organisation images: `appraisalHeaderImage`, `appraisalFooterImage`, `appraisalSignatureImage`,
`govMapImage` - always with `| maxSize:w:h`. Header/footer: `{appraisalHeaderImage |
maxSize:HEADER_IMAGE_WIDTH:1000}` / `{appraisalFooterImage | maxSize:FOOTER_IMAGE_WIDTH:1000}` pull the
graphics from the organisation settings; `HEADER_IMAGE_WIDTH` / `FOOTER_IMAGE_WIDTH` are constants
Quicker fills in. Per document:
- the document has its own header/footer graphics (logo, letterhead, address line) -> keep them, don't
  add the org image tags;
- an existing header/footer is empty or holds a placeholder -> ask whether to use the organisation
  images (unattended: leave it and mention the option);
- no header/footer at all -> don't create one (new parts need relationships, content types and section
  references - easy to corrupt); mention the option in the report.

Legacy pattern in older templates (top-level `{#buildingImages}{image}{/}`, `{govmapImage}`): don't
create new ones, don't break existing ones.

## 6. Filters (complete list - `word.js`)

| filter | arguments / behaviour |
|---|---|
| `date:'FORMAT'` | moment tokens, default `DD/MM/YYYY`. Form dates are stored as ISO timestamps (`2026-03-15T08:30:00.000Z`); also reads DD/MM/YYYY, D/M/YYYY, YYYY-MM-DD, DD.MM.YYYY, DD-MM-YYYY (+HH:mm); anything else prints as is |
| `currency` | thousands separators only, up to 3 decimals, no ₪ (write it yourself) |
| `fixed` | 2 decimals |
| `list:', '` | join an array |
| `includes:'v'` | array/string contains - for conditions |
| `isEmpty` | true when empty |
| `stripTag` | remove HTML tags |
| `lower` | lowercase |
| `inc:n` | numeric increment (loop counters): `{_idx \| inc}` numbers items from 1 |
| `loopSep:'comma\|pipe\|dash\|space\|semicolon\|newline'` | on `_idx`: the separator before every item except the first - `{_idx \| loopSep:'comma'}{name}` |
| `html` | rich text (see below) |
| `maxSize:W:H` | pixels, width then height; shrinks only, keeps the ratio; applies to every image of the field |
| `frame:'W':'#RGB'` | W number = points, also `'1.5pt'` / `'2px'`; default 1pt black; colour 3 or 6 hex, with or without # |
| `rounded:P` | percent of the shorter side, 0-50, default 10 |
| `align:'right\|center\|left\|justify'` | also ימין / אמצע / שמאל; aligns the picture's paragraph |
| `gap:N` | space between images: number = px, also `'px'` / `'pt'`; default 8px for several images, 0 for one |
| `grid:C:'W':'#RGB'` | C columns 1-12 (default 3); optional border width in pt + colour (default no lines); column width = widest image + margins |

There is no ₪ filter and no number-to-words filter. An unknown filter prints the tag empty (and the
upload linter flags it as `unknownFilter`) - treat it as an error.

**HTML.** Quicker's own html plugin (v3 and v8; easy-template-x-extension-html is not used). `{x | html}`
converts lists, alignment, direction, colour, font, headings, tables and links. HTML with block
elements replaces the WHOLE paragraph that holds the tag; a single inline paragraph replaces just the
tag. So put `{p.ad.x | html}` alone in its paragraph. Nothing in the data marks a value as HTML - only
the filter does, so every richtext field needs `| html` (without it the markup prints as text).

## 7. What does not exist

Appraiser licence number, per-appraiser signature (the signature is the organisation's), appraiser
phone/email. Keep these as fixed text in the template (or ask the user for the text).

Who signs: `ownerManagerName` (the office manager) is the default signer; `p.agentName` is the appraiser
of this project (the visitor in the form overrides the assigned one). When a report shows one name both
as visitor and signer, use `p.agentName` for the visit line and `ownerManagerName` under the signature,
and list the choice under decisions.

## 8. Points still to confirm

- Quick-sale value in shekels: the system form stores the percentage `p.ad.quickSaleValue` ("-10%").
  Its display widget `p.ad.SummeryPer4` (type html, mislabelled "אחוז מסך עלות הבניה הצפוי") shows
  "שווי הנכס לאחר הפחתה ... ₪" - whether that amount is saved with the project is unconfirmed. Until
  confirmed: print the percentage, or `{p.ad.SummeryPer4 > 0 ? (p.ad.SummeryPer4 | currency) + ' ₪' : ''}`
  flagged **חשוב** (test on a real project). Top-level `quickSalePrice` from old templates: the linter warns.
- Whether production removes the empty paragraph that a tag-only line leaves behind (stock
  easy-template-x keeps it - see template-syntax.md §4). The skill avoids tag-only lines unless the
  plan asks for `"block_style": "own"`.
- Time zone of `| date`: values are UTC timestamps. The render check formats them in Israel time; if the
  server formats in UTC, a date saved as Israeli midnight prints one day earlier.
- `p.ad.planDataStatus`: production templates loop over it (`{#p.ad.planDataStatus}{planNumber}...`), the
  variables tool lists it as an `html` field. The catalog keeps the loop.
- `_idx` / `_isFirst` / `_isLast` inside `{#customers}`: the variables tool documents them for form groups;
  the render check assumes every loop has them.
