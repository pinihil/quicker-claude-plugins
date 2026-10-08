# Quicker - תבניות שומה

הופך דוח שמאות בוורד (שומת מקרקעין, חוות דעת לבנק, היטל השבחה, מס שבח, ירושה ועוד) לתבנית מסמך של Quicker:
אותו עיצוב בדיוק, עם משתנים במקומות שבהם הנתונים משתנים מדוח לדוח, תנאים לקטעים שמופיעים רק לפעמים,
לולאות לטבלאות חוזרות (לווים, היתרים, משכנתאות) ותמונות.

## מה צריך

- חשבון Quicker פעיל, והקונקטור של Quicker מחובר (בלשונית **Connectors** של התוסף). בלי הקונקטור
  הסקיל לא ייצור תבנית - שמות המשתנים נלקחים תמיד מטופס השומה של המשרד שלך.
- הרצת קוד ויצירת קבצים מופעלות בחשבון Claude (בארגון - לפי הגדרת המנהל).

## איך משתמשים

מעלים לשיחה את קובץ הוורד וכותבים, למשל: "תהפוך את הדוח הזה לתבנית ל-Quicker".
Claude ישאל לאיזה טופס שומה התבנית מיועדת, ימפה את הערכים למשתנים, יבדוק את התבנית וימסור:

- קובץ `..._template.docx` מוכן להעלאה ב-Quicker (הגדרות > טפסי שומה מותאמים > תבניות מסמכים)
- דוח מיפוי בעברית: מה מופה לאיזה משתנה, אילו תנאים נוספו, ומה נשאר ללא משתנה מתאים

אפשר גם לסמן הוראות בתוך הוורד עצמו - `[[גוש]]`, `[[אם: שומה מורחבת]] ... [[סוף]]`, `[[לכל: לווים]]`,
הערות Word או הדגשה בצהוב - וגם לבקש "תבדוק לי את התבנית הקיימת".

## מידע ופרטיות

- הקובץ שהעלית נשאר בסביבת העבודה של Claude. התוסף לא שולח אותו לשום מקום.
- התוסף קורא מ-Quicker, דרך הקונקטור ובהרשאות המשתמש שלך, את מבנה טופס השומה (שדות, אפשרויות, קבוצות).
  הוא לא כותב ל-Quicker ולא משנה נתונים.
- לבדיקת התבנית הסקיל מתקין בסביבת הקוד, מ-npm, את מנוע התבניות שבו Quicker משתמש
  (`easy-template-x`, `angular-expressions`, `jszip`, בגרסאות נעולות) ומרנדר את התבנית על נתוני דמה.
  אם אין גישה ל-npm, הבדיקה מתבצעת חלקית (בדיקת תחביר ומשתנים בלבד) והסקיל אומר זאת במפורש.

---

## English

Turns Israeli real-estate appraisal Word reports into Quicker document templates. Claude keeps the
original design and places easy-template-x tags where the data changes, adds conditions for optional
paragraphs, sections and table rows, loops for repeating groups and image tags. Variable names always
come from your organization's live Quicker form through the Quicker connector, so the plugin needs
that connector connected; without it no template is produced.

**Usage:** attach a .docx report and ask Claude to turn it into a Quicker template, or to check an
existing template. You get the template file and a Hebrew mapping report.

**Data:** the plugin reads your appraisal form structure from Quicker through the connector with your
own permissions and never writes to Quicker. Your document stays in Claude's code execution
environment. To test-render the template, the skill installs pinned versions of `easy-template-x`,
`angular-expressions` and `jszip` from the public npm registry into that environment; when npm is not
reachable it falls back to static checks and says so.
