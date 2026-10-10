# תחזוקה ושחרור גרסאות (לצוות Quicker)

ה-repo הזה הוא **marketplace** של תוספים (plugins) ל-Claude. כרגע יש בו תוסף אחד, `quicker-appraisal`,
שמכיל שני סקילים - `quicker-appraisal-template` (תבניות Word) ו-`quicker-appraisal-form` (טופס השומה
של המשרד) - ואת ההפניה לקונקטור של Quicker.
לקוח מוסיף את ה-repo פעם אחת, ומאותו רגע כל גרסה שממוזגת ל-`main` מגיעה אליו.

```
quicker-claude-plugins/
├── .claude-plugin/
│   └── marketplace.json              קטלוג התוספים (שם ה-marketplace: quicker)
├── plugins/
│   └── quicker-appraisal/            התוסף - רק התיקייה הזו מגיעה ללקוחות
│       ├── .claude-plugin/
│       │   └── plugin.json           שם (קבוע לתמיד), version, תיאור
│       ├── .mcp.json                 כתובת שרת ה-MCP של Quicker
│       ├── README.md                 מה שהלקוח רואה לפני ההתקנה (גם תיאור הרישום ב-directory)
│       ├── LICENSE
│       ├── CHANGELOG.md              סעיף לכל גרסה
│       └── skills/
│           ├── quicker-appraisal-template/
│           │   ├── SKILL.md
│           │   ├── references/       חוזה הנתונים, תחביר, סימוני [[...]], תחום השמאות
│           │   ├── scripts/          בניית קטלוג, outline, apply, lint, render
│           │   └── assets/
│           └── quicker-appraisal-form/
│               ├── SKILL.md
│               ├── references/       מודל הטופס, חוזה כלי העריכה, תקני השמאות
│               ├── scripts/          אינדקס טופס, מלאי דוח, בדיקת פעולות, בדיקת פערים מול התקנים
│               └── assets/           checklists.json - רשימות התיוג לפי סוג שומה (עם מקורות)
├── README.md                         לעמוד ה-repo - ללקוחות: מה התוסף עושה ואיך מתקינים
├── MAINTAINING.md                    הקובץ הזה
├── tests/                            בדיקת עשן על טפסים ותבנית פיקטיביים (רצה ב-CI)
├── evals/                            הגדרות ה-evals (קבצי הקלט נשמרים מחוץ ל-repo)
├── tools/
│   ├── check_plugin.py               בדיקות לפני שחרור + חובת העלאת גרסה
│   └── build_zip.sh                  zip להעלאה ידנית (פיילוט / ארגון)
├── .github/workflows/validate.yml     CI לכל PR ולכל push ל-main
└── .github/workflows/release.yml      תג vX.Y.Z -> zip ב-GitHub Releases
```

## הקמה ראשונה

1. בעל זכויות היוצרים ב-`LICENSE` - לעדכן לשם הישות המשפטית אם צריך.
2. ליצור ב-GitHub repo **ציבורי** בשם `quicker-il/quicker-claude-plugins` ולדחוף אליו.
   repo פרטי עובד רק ללקוח שקיבל גישה אליו ב-GitHub.
3. לבדוק מקומית:
   ```bash
   python3 tools/check_plugin.py
   claude plugin validate ./plugins/quicker-appraisal && claude plugin validate .
   bash tests/smoke_test.sh
   ```
4. להתקין אצלך כמו לקוח, ולנסות על דוח אמיתי (ראו "איך לקוח מתקין").

## איך לקוח מתקין

| איפה | מה עושים |
|---|---|
| Claude (צ'אט / Cowork / אפליקציה) | Customize > Plugins > Add > Add marketplace, מזינים `quicker-il/quicker-claude-plugins`, ואז Install על **quicker-appraisal**. בלשונית Connectors של התוסף - Connect ל-Quicker |
| משרד ב-Team / Enterprise | סנכרון ארגוני מ-GitHub עובד רק על repo **פרטי** של הארגון עצמו, ולכן לא על ה-repo הזה. שתי דרכים: (1) ה-Owner משאיר את **User-created skills** פעיל וכל עובד מוסיף את ה-marketplace לבד; (2) ה-Owner מעלה את ה-zip מ-Releases (**Upload a plugin**) ומעלה כל גרסה חדשה ידנית. את הקונקטור מוסיפים בהגדרות הארגון > Connectors |
| Claude Code | `claude plugin marketplace add quicker-il/quicker-claude-plugins` ואז `claude plugin install quicker-appraisal@quicker` |
| פיילוט בלי GitHub | `bash tools/build_zip.sh` ושולחים את ה-zip. אין עדכונים אוטומטיים - כל גרסה מעלים מחדש |

לקוח שהוסיף את ה-marketplace בעצמו מקבל עדכונים כשהוא מפעיל **Sync automatically** על ה-marketplace,
או כשהוא לוחץ **Check for updates**. כדאי לכתוב את זה במדריך ההתקנה ללקוחות.

## שחרור גרסה

1. עובדים ב-branch ופותחים PR.
2. משנים את הסקיל. אם השינוי נוגע במיפוי, בתנאים או בכלים - מריצים את ה-evals (`evals/README.md`).
3. מעלים את `version` ב-`plugin.json` (תיקון: 1.0.1, יכולת חדשה: 1.1.0, שינוי שובר: 2.0.0)
   ומוסיפים סעיף `## <גרסה>` ב-`CHANGELOG.md`.
4. ה-CI בודק שהגרסה עלתה. **בלי העלאת גרסה הלקוחות לא מקבלים את השינוי** - Claude מזהה עדכון לפי
   מספר הגרסה, לא לפי ה-commit.
5. מיזוג ל-`main` = שחרור למי שהוסיף את ה-marketplace.
6. תג גרסה (`git tag v1.0.1 && git push --tags`) - ה-workflow `release` בונה את ה-zip ומפרסם אותו ב-Releases,
   בשביל משרדים ארגוניים שמעלים את התוסף ידנית. התג חייב להיות זהה ל-`version`.

## כללים

- **אסור** להכניס ל-repo את קוד השרת של Quicker (`word-image-plugin`, `word-loop-plugin`,
  `word-expressions`). ה-repo ציבורי. לבדיקת גרידים ומסגרות תמונה אפשר לשים עותק מקומי ב-
  `scripts/quicker/word-image-plugin.cjs` - התיקייה ב-`.gitignore`, ו-`check_plugin.py` עוצר אם הקובץ נכנס.
- אין סודות, מפתחות או טוקנים באף קובץ. ההתחברות ל-Quicker היא OAuth של כל משתמש.
- את `name` של התוסף ושל ה-marketplace לא משנים לעולם. את `displayName` אפשר לשנות.
- קבצי הקלט של ה-evals (דוחות אמיתיים) לא נכנסים ל-repo.
- **סקריפטים משותפים** (`docx_outline.py`, `docxlib.py`): לכל סקיל עותק משלו, כדי שכל סקיל יעבוד גם
  לבד. משנים באחד ומעתיקים לשני - `check_plugin.py` נכשל אם העותקים שונים.
- **כללי השרת בסקיל הטפסים** (`check_ops.py`, `formlib.py`) מחקים את מנוע העריכה של Quicker
  (`form-template-ops.js`, `form-sync-fields.js`, `form-option-lists.js`), ומאוקטובר 2026 גם את בדיקת ערכי
  התנאים (`validateConditionInForm`) ואת בדיקת ערך ברירת המחדל (`checkDefaultValue`) ב-`form-template-ops.js`
  וב-`form-template-plans.js`. שינוי בכללים בשרת = עדכון שם, ועדכון הסטטוסים ב-`tests/fixtures/form-ops.json`
  (שנבדקו מול המנוע). את קוד המנוע עצמו לא מעתיקים לכאן.
- **לוגיקת התצוגה** (`formlogic.py`) קוראת תנאים כמו הדפדפן: מחרוזת היא ביטוי של AngularJS `$eval`, ותנאי
  מובנה עובד לפי `client/app/common/condition-evaluator.js`. שינוי באחד מהם = עדכון `formlogic.py`
  והבדיקות ב-`test_form_skill.py`. לתשומת לב: הספרייה `angular-expressions` ב-npm חוסמת קריאה ל-`.includes()`,
  והדפדפן לא. לכן בתבניות Word משתמשים ב-`| includes:`, ובטופס ב-`.includes()`.
- **בסיס הידע של התקנים** (`references/standards.md`, `assets/checklists.json`) מתוארך לאוקטובר 2026.
  הוועדה לתקינה שמאית מחדשת תקנים כל כמה חודשים (תוכנית 2027: 10.1, 14.1, 15.1, 19.1) - לעבור על
  הרשימה ב-gov.il פעם ברבעון ולעדכן.

## הגשה ל-directory של Anthropic (שלב ב')

1. [claude.ai/directory/manage](https://claude.ai/directory/manage) > Submit new > **MCP connector** -
   שרת ה-MCP של Quicker.
2. Submit new > **Plugin bundle** - ה-repo הזה, תיקייה `plugins/quicker-appraisal`, branch `main`.
3. לחבר בין שני הרישומים (pairing).
4. אחרי האישור: כל מיזוג ל-`main` נסרק ומגיע ללקוחות אוטומטית, והלקוחות מוצאים את התוסף בחיפוש.

## בהמשך: להעביר בדיקות לשרת

הסקיל מחקה כרגע את מנוע התבניות של Quicker (גרסת המנוע, פילטרים, תוסף התמונות) כדי לבדוק תבניות.
כלי `validate_template` בשרת ה-MCP, שירנדר עם המנוע האמיתי, יבטל את התלות ב-npm אצל הלקוח, ישמור
על התאמה מלאה לייצור, ויאפשר לשדרג את המנוע (v3 ל-v8) בלי לשחרר גרסת תוסף.

באותו אופן, `check_ops.py` מחקה את כללי עריכת הטפסים כדי לתפוס שגיאות לפני `plan_form_template_changes`.
התוכנית בשרת היא ממילא הסמכות; אם הכללים בשרת ישתנו לעיתים קרובות, אפשר לוותר על הבדיקה המקומית
ולהסתמך על התשובה של `plan` בלבד.
