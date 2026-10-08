# Israeli appraisal reports - what is data, what is boilerplate, what is conditional

Use this when mapping a report without author markup. Always confirm a field exists in the chosen
form's catalog; names below are from the system form "שומת מקרקעין" and may differ in custom forms.

## Contents
1. Report families
2. Anatomy of a bank / mortgage report (most common)
3. Recognising values
4. Typical conditional content
5. Typical loops
6. Boilerplate you should NOT tag
7. Other report families - what changes

## 1. Report families

| family | clues in the text | notes |
|---|---|---|
| בנק / משכנתא (בטוחה לאשראי, often "תקן 19") | לכבוד בנק..., סניף, לידי, מס' הלוואה, לווים, שווי למימוש מהיר, ערך כינון, "הערות לתשומת לב הבנק" | each bank has its own layout; the form switches fields by `p.ad.referrer` |
| היטל השבחה / ועדה מקומית | תכנית משביחה, מצב קודם / מצב חדש, מימוש, ועדה מקומית | before/after values, plan tables |
| מס שבח / מיסוי מקרקעין | יום המכירה, יום הרכישה, שווי ליום... | |
| ירושה / גירושין / פירוק שיתוף | עיזבון, יורשים, איזון משאבים, שווי חלקו של | ownership shares, often several properties |
| ביטוח / שומת רכוש, מס רכוש | ערך כינון, נזק, פיצוי | separate system forms exist ("שומת רכוש", "מס רכוש") - pick them |
| שומה מכרעת / ערר | שמאי מכריע, הצדדים, טענות | long legal narrative - mostly static |

Pick the form that matches the family (ask when unsure - see SKILL.md step 1).

## 2. Anatomy of a bank / mortgage report

| section | usual data -> variable (system form) |
|---|---|
| Header block (often a text box at the top) | date `p.ad.documentDate \| date`, appraisal no. `p.number`, loan no. `p.ad.loanNumber`, loan type `p.ad.loanType` |
| Addressee | bank `p.ad.referrer`, branch `p.ad.branch`, attention `p.ad.bankAgentRecipient`, email `p.ad.bankAgentEmail` |
| Title | property type `p.propertyType`, address parts `p.street` `p.house` `p.city` `p.neighborhood`, gush/helka `p.gush` `p.helka` |
| General details | borrowers loop `p.ad.borrowers`, loan purpose `p.ad.loanPurpose`, orderer `p.ad.appraisalOrdererName` + `p.ad.appraisalOrderer`, purpose `p.appraisalPurpose`, short/extended `p.ad.extanded`, determining date `p.determinesDate`, original referral date `p.ad.documentRefDate`, fee paid by `p.ad.wagePaidBy` |
| Visit | visit date `p.visitDate` (production templates) / `p.ad.visitDate`, visitor `p.ad.visitorName` + role `p.ad.visitorRole`, presenter `p.ad.propertyViewerName`, ID `p.ad.propertyViewerIdNumber`, holder `p.ad.propertyHolderName` + `p.ad.propertyHolder` |
| Property identification | registration loop `p.ad.addressDetails` (gush, helka, subHelka, plot, plotByTaba), documents checked `p.ad.propertyIdentification \| list:', '`, discrepancy `p.ad.generalDiscrepancy` |
| Environment & building | `p.ad.environmentFeatures`, `p.ad.locationFeatures`, `p.ad.buildingType`, `p.ad.buildingPhysicalCondition`, `p.ad.buildingMaintenanceStatus`, `p.ad.constructionType`, `p.ad.elevators`, `p.ad.exteriorCladding`, `p.ad.numberOfFloors`, `p.ad.floorOn`, `p.ad.entryNumber` |
| The property | floor `p.floor`, direction `p.ad.propertyDirections`, rooms `p.ad.rooms`, air directions `p.ad.airDirections \| list`, layout `p.ad.functionalDivision`, linkages loop `p.ad.linkagesGroup`, condition `p.ad.maintenanceStatus`, areas `p.squareMeter`, `p.ad.squareMeterMeasured`, `p.ad.apartmentAreaGross` (+ source `p.ad.apartmentAreaAuth`) - all `\| currency} מ"ר` |
| Finish table | `p.ad.kitchen`, `p.ad.livingRoomFloorType`, `p.ad.bathroomFloorType`, `p.ad.windows`... (whole table conditional on `p.ad.detailFinish == 'כן'`) |
| Planning | plans loop `p.ad.planDataStatus` (planNumber, date, mahut, status), rights loop `p.ad.planDataRightsValid`, permits loop `p.ad.permits`, completion certificate `p.ad.completionCertificate` (+date), deviations `p.ad.constructionEHarigot` (+area), dangerous structure `p.ad.dangerousStructure` |
| Legal status | per document type: נסח טאבו loop `p.ad.perutNesachTabo` (owners, leases, mortgages, notes, easements as nested loops), רמ"י `p.ad.perutRami`, חברה משכנת `p.ad.confRightsGroup`, חוזה חכירה `p.ad.LeaseContractGroup`, הסכם שיתוף `p.ad.agreeSharGroup`, חוזה מכר `p.ad.agreementGroup`, שכירות `p.ad.rentalGroup`, other agreements `p.ad.AdditionalGroup` |
| Valuation | market value `p.ad.currentMarketValue`, reinstatement `p.ad.reinstatementValue`, land `p.ad.landValue` - money `\| currency} ₪`. Quick sale: the system form stores the **percentage** `p.ad.quickSaleValue` (e.g. "-10%"); the shekel amount may live in the display widget `p.ad.SummeryPer4` (unconfirmed - quicker-contract.md §8). Print the percentage, or the guarded widget value flagged **חשוב** - don't compute it with a long ternary chain |
| Taxes, bank notes | `p.ad.taxesAndLevies`, `p.ad.bankNotes`, `p.ad.disclaimer` |
| Signature | `ownerManagerName`, `appraisalSignatureImage \| maxSize:220:120`; licence number stays static text |
| Appendices | under-construction stages, renovation table, photos and plans (image fields: `{p.ad.x \| maxSize:w:h}` / `\| grid:N`), GovMap (`govMapImage`) |

## 3. Recognising values

| looks like | likely |
|---|---|
| `12/03/2026`, `12.3.26`, `12 במרץ 2026` | a date field - which one is decided by the label before it |
| `1,850,000 ₪`, `₪ 1,850,000`, `1,850,000 ש"ח` | money - market value / land value / sale price / rent ... by label |
| `96.5 מ"ר`, `96.5 מ״ר` | area |
| 9 digits after ת.ז / מ.ז | an ID - inside a person loop |
| 4-6 digits after "גוש", 1-4 after "חלקה" / "תת חלקה" | gush / helka / subHelka |
| `2026-0412`, `שומה מס' 123/26` | `p.number` |
| a bank name (לאומי, הפועלים, מזרחי טפחות, דיסקונט, הבינלאומי, אוצר החייל, מרכנתיל, ירושלים, מסד, יהב, פועלי אגודת ישראל) after לכבוד | `p.ad.referrer` |
| a word that is one of a select field's options (e.g. "שומה מורחבת", "בנייה רוויה", "טוב") | that select field |
| a list of options with ✓ | a checkboxList (`\| list`) |
| a person's name after מבקר/מציג/מחזיק/מזמין | the matching visitor/presenter/holder/orderer field |

Labels are the strongest signal: the value next to "מס' חדרים:" is `rooms` whatever it looks like.
When the same value appears twice (date in header and in body), tag each occurrence by its own label.
The appraiser's name in the signature is `ownerManagerName` (or `p.agentName` when the report is signed
by the assigned appraiser - ask if unclear).

## 4. Typical conditional content

- **Line with an optional value** ("מס' כניסה: 2", "סניף: 123", "לידי: ...") -> one-paragraph block on
  that field.
- **Option-driven chapters**: planning & licensing only in `p.ad.extanded == 'שומה מורחבת'` (short
  report shows "בהתאם להנחיות הבנק לא מוצג"); finish table only when `p.ad.detailFinish == 'כן'`;
  "נכס בבנייה" / "נכס בשיפוצים" appendices by `p.ad.propertyConditionStatus`; rental section when
  `p.ad.ifLease == 'קיים'`; additional agreements when `p.ad.ifAdditionalAgreements == 'קיים'`.
- **Legal documents**: each document-type section only when `p.ad.propertyIdentification` includes it
  (`| includes:'נסח רישום מקרקעין'` ...); inside a נסח, sub-sections by `nesachTabosubIF | includes:'משכנתאות'`.
- **Bank-specific paragraphs**: by `p.ad.referrer` (the catalog's `group condition` lists the banks).
- **Yes/No wording**: "קיימת מעלית" / "אין מעלית", "לא נמצאו חריגות בנייה" -> two opposite blocks.
- **Optional suffixes in a sentence**: " - {role}", ", מעל קומת {floorOn}" -> inline condition (not in a
  numbered paragraph or a table cell - there use a ternary, see template-syntax.md §10).

Reuse the form's own conditions (catalog `shown-if` / `block-if` / `group condition`) - they are what
the appraiser sees, so the report shows exactly the sections that were filled.

## 5. Typical loops

borrowers, owners (per legal document), mortgages, warning notes, leases, easements, permits, plans,
building rights, linkages, renovation items, comparable deals. In tables: one row per item
(`wrap_rows`). In text: one paragraph or line per item (`wrap_block` / `wrap_inline`). In a filled
report the list appears N times - keep one sample, delete the rest, loop the one left.
Images are NOT loops: `{p.ad.photos | maxSize:w:h}` (or `| grid:N`) prints all of them.

## 6. Boilerplate you should NOT tag

Declarations ("הריני מצהיר..."), methodology text, legal disclaimers, section titles, the appraiser's
licence number and contact details (no variable exists), page numbers (Word fields), bank instructions
quoted verbatim. When in doubt whether a sentence is boilerplate or data, compare with what the form
can supply - if no field could have produced it, it's boilerplate.

## 7. Other report families - what changes

- **היטל השבחה**: "מצב קודם" / "מצב חדש" pairs, plan numbers, planning dates, sum of the betterment -
  usually a custom form; expect loops over plans and comparables.
- **ירושה / גירושין / פירוק שיתוף**: several properties and owner shares - look for a repeatable
  properties group in the form; static legal narrative around it.
- **ביטוח / מס רכוש**: reinstatement value, damage items (loops), photos - use the matching system form.
- **Custom org forms**: names and groups differ - rely on the catalog labels, not on this file.
