# Quicker - תבניות שומה וטופס שומה

שני סקילים לשמאי מקרקעין שעובדים ב-Quicker:

- **תבניות מסמכים** - הופך דוח שמאות בוורד (שומת מקרקעין, חוות דעת לבנק, היטל השבחה, מס שבח, ירושה
  ועוד) לתבנית מסמך של Quicker. העיצוב נשאר בדיוק כמו שהוא. במקומות שבהם הנתונים משתנים מדוח לדוח
  מוכנסים משתנים. מתווספים תנאים לקטעים שמופיעים רק לפעמים, לולאות לטבלאות חוזרות ותמונות.
- **טופס השומה של המשרד** - בונה ומעדכן את טופס השומה המותאם של המשרד. הבסיס הוא הדוחות שהמשרד כבר
  כותב, והטופס נבדק מול תקני השמאות, תקנות האתיקה ודרישות הבנקים והרשויות. כל שינוי מוצג לך לפני
  שהוא מתבצע, ואפשר להחזיר כל גרסה קודמת.

## מה צריך

- **חשבון Quicker פעיל והקונקטור של Quicker מחובר** (בלשונית **Connectors** של התוסף). בלי הקונקטור
  אין תבניות ואין שינויי טופס, כי שמות השדות נלקחים תמיד מהטופס החי של המשרד.
- **לשינוי טפסים בלבד:** הרשאה לעריכת הגדרות המשרד ב-Quicker. בנוסף, מנהל המשרד צריך להפעיל בהגדרות
  ה-MCP של Quicker את שני הכלים שכבויים כברירת מחדל: "יצירת טופס שומה לארגון" ו"ביצוע תוכנית שינויים
  בטופס שומה". בלי ההפעלה, Claude מכין את רשימת השינויים, ואפשר לבצע אותה ידנית בבונה הטפסים.
- הרצת קוד ויצירת קבצים מופעלות בחשבון Claude. בחשבון ארגוני זה תלוי בהגדרת המנהל.

## איך משתמשים

**תבנית:** מעלים לשיחה את קובץ הוורד וכותבים, למשל, "תהפוך את הדוח הזה לתבנית ל-Quicker". Claude
ישאל לאיזה טופס שומה התבנית מיועדת. בסוף מקבלים שני קבצים:
- קובץ `..._template.docx`, מוכן להעלאה ב-Quicker (הגדרות ← טפסי שומה מותאמים ← תבניות מסמכים).
- דוח מיפוי בעברית.

**טופס:** מעלים דוח או שניים של המשרד וכותבים, למשל, "תבנה לנו טופס לשומות לבנק לפי הדוח הזה" או
"מה חסר בטופס שלנו לתקן 19". Claude:
1. משווה את הדוח לטופס הקיים.
2. מציע שדות במקום הנכון, עם אפשרויות בחירה, תנאי תצוגה והנחיות ל-AI Fill.
3. מראה טבלת שינויים עם הסיבה לכל שינוי, ואת ההשפעה על פרויקטים ותבניות קיימים.
4. מבצע רק אחרי אישור שלך.

## מידע ופרטיות

- הקבצים שהעלית נשארים בסביבת העבודה של Claude. התוסף לא שולח אותם לשום מקום.
- התוסף עובד מול Quicker דרך הקונקטור, בהרשאות המשתמש שלך:
  - **קורא** את מבנה טופסי השומה.
  - **כותב** רק לטופסי השומה של המשרד, ורק אחרי אישור מפורש שלך בשיחה.
  - הגרסה הקודמת של הטופס נשמרת, ואפשר לשחזר אותה.
  - נתוני הפרויקטים לא נמחקים. שדה שמוציאים מהטופס מוסתר, והנתונים שבו נשמרים.
- לבדיקת תבנית, הסקיל מתקין בסביבת הקוד מ-npm את מנוע התבניות ש-Quicker משתמש בו (`easy-template-x`,
  `angular-expressions`, `jszip`, בגרסאות נעולות), ומרנדר את התבנית על נתוני דמה. אם אין גישה ל-npm,
  הבדיקה חלקית, והסקיל אומר זאת במפורש.

---

## English

Two skills for Israeli real-estate appraisers on Quicker:

- **Document templates:** turns appraisal Word reports into Quicker document templates. The original
  design is kept; tags go where the data changes, with conditions, loops and images. Every template is
  linted and test-rendered.
- **The office's appraisal form:** designs and updates the office's own Quicker appraisal form from the
  office's report formats. It is checked against the Israeli appraisal standards (1.1-22), the ethics
  regulations and bank and authority practice. Every change is a plan the user reviews and approves
  before Quicker applies it, and earlier versions can be restored.

**Requirements:** the Quicker connector. Changing forms also requires the permission to edit the
office's settings, and the office must enable the form-editing tools in Quicker's MCP settings.

**Data:** the plugin works through the connector with your own permissions:
- It reads form structures.
- It writes only to the office's own forms, and only after your explicit approval.
- It never deletes project data, and the previous version of a form is always kept.

Your files stay in Claude's code execution environment. To test-render templates, the skill installs
pinned npm packages (`easy-template-x`, `angular-expressions`, `jszip`) in that environment. When npm
is not reachable it falls back to static checks and says so.
