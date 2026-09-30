<p align="center">
  <img src="assets/brand/wordmark.png" width="320" alt="Maple Helper">
</p>

<p align="center"><b>העוזר האישי שלכם ב-MapleStory</b> · Your personal MapleStory assistant</p>

<p align="center"><sub>Unofficial companion for MapleStory Classic · Not affiliated with Nexon</sub></p>

---

<div dir="rtl">

## מה זה

Maple Helper הוא צ'אט שקוף שנפתח **מעל המשחק** בלחיצה על F9. שואלים שאלה (בהקלדה או בדיבור עם F10), והוא עונה לפי מה שרואים על המסך, לפי הלבל והג'וב שלכם, ולפי מאגר המידע המלא של המשחק מ-[NiaMeowDB](https://meowdb.com/msclassic).

- **בתוך המשחק:** בלי Alt+Tab. F9 פותח וסוגר.
- **רואה מה שאתם רואים:** צילום של חלון המשחק, רק ברגע ששואלים.
- **מכיר אתכם:** פרופיל דמות שמתעדכן לבד (לבל, ג'וב, קווסטים) וזיכרון שיחות.
- **כרטיסים עם תמונות** של מפלצות, פריטים, מפות ו-NPCs.
- **עברית ואנגלית מלאות**, כולל טקסט מעורב שמוצג נכון.
- **פסיבי לגמרי:** לא נוגע במשחק, לא קורא זיכרון, לא לוחץ על מקשים. לא בוט.

## דרישות

- Windows 10/11
- מנוי Claude **Pro או Max** (האפליקציה משתמשת ב-Claude Code שמחובר לחשבון שלכם). אפשר גם מפתח Anthropic API.
- המשחק במצב **Borderless / Windowed Fullscreen**

## פרטיות

הכל נשמר על המחשב שלכם (`%APPDATA%\MapleHelper`). השאלה וצילום חלון המשחק נשלחים ל-Claude דרך החשבון שלכם, רק כששואלים. אין שרת שלנו ואין איסוף נתונים.

</div>

## English

Maple Helper is a transparent chat that opens **on top of the game** with F9. Ask by typing or hold F10 to talk. Answers use what's on your screen, your character's level and job, and the full NiaMeowDB MapleStory Classic database.

**Requirements:** Windows 10/11 · a Claude **Pro or Max** plan (runs through Claude Code signed in to your account; an Anthropic API key also works) · the game in Borderless / Windowed Fullscreen.

**Privacy:** everything stays in `%APPDATA%\MapleHelper`. Only your question and a screenshot of the game window go to Claude, through your own account, and only when you ask.

**Safe by design:** the app never touches the game process: no memory reading, no injected input, no hooks. It captures the screen like any screenshot tool and shows its own window.

## Development

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\scrape_meowdb.py      # knowledge base (≈1h, polite rate)
.venv\Scripts\python -m maplehelper              # run
.venv\Scripts\python -m pytest tests -q          # Hebrew/English rendering tests
```

## Credits

- Game data and images: [NiaMeowDB (meowdb.com)](https://meowdb.com), used with permission. Game assets belong to their rights holders.
- Font: [Rubik](https://fonts.google.com/specimen/Rubik) (SIL Open Font License).
- Hebrew speech recognition: [ivrit.ai](https://huggingface.co/ivrit-ai) Whisper models.
- MapleStory is a trademark of Nexon. This project is not affiliated with or endorsed by Nexon.
