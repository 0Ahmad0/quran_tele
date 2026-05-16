# Quran Tele 🌙

A professional Telegram bot for sending a personalized daily Quran reading plan. Built with **Python**, **aiogram 3.x**, **APScheduler**, and **SQLite**.

The bot helps users keep a consistent Quran habit by sending their daily pages automatically at their preferred time. It can send pages as a Telegram media album or generate a PDF when the daily portion is larger.

---

## ✨ Features

- 📖 Daily Quran pages for every subscriber
- ⏰ Custom sending time per user
- 🔢 Custom daily page goal per user
- 📍 Custom current page / starting page
- 🖼 Sends pages as images when the portion is 10 pages or fewer
- 📄 Generates a PDF automatically for larger portions
- 🎉 Detects Quran completion and starts a new khatma
- 🤲 Sends periodic duas every 8 hours
- 👑 Admin-only statistics and broadcast commands
- 🔐 Secure configuration through environment variables
- 🗃 Lightweight SQLite database

---

## 🧰 Tech Stack

- Python 3.10+
- aiogram 3.x
- APScheduler
- SQLite
- aiohttp
- img2pdf
- python-dotenv

---

## 📁 Project Structure

```text
quran_tele/
├── main.py              # Telegram bot handlers and scheduler
├── database.py          # SQLite database manager
├── utils.py             # Quran page logic, PDF generation, duas
├── requirements.txt     # Python dependencies
├── .env.example         # Example environment variables
├── .gitignore           # Files that must not be pushed
└── README.md            # Project documentation
```

---

## 🔐 Security First

Never hardcode your Telegram bot token in the source code.

This project reads secrets from environment variables:

```text
BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_user_id
TIMEZONE=Africa/Cairo
```

If your bot token was ever shared publicly, regenerate it immediately from [@BotFather](https://t.me/BotFather):

1. Open BotFather
2. Select your bot
3. Use `/revoke` or regenerate the token
4. Update your `.env` file or hosting environment variables

---

## 🚀 Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/0Ahmad0/quran_tele.git
cd quran_tele
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows:**

```bash
.venv\Scripts\activate
```

**Linux / macOS:**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your environment file

Copy the example file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```text
BOT_TOKEN=put_your_new_bot_token_here
ADMIN_ID=123456789
TIMEZONE=Africa/Cairo
```

### 5. Run the bot

```bash
python main.py
```

---

## 🤖 User Commands

| Command | Description |
|---|---|
| `/start` | Subscribe or reactivate the daily Quran plan |
| `/help` | Show available commands |
| `/status` | Show current settings |
| `/goal 5` | Set daily reading goal to 5 pages |
| `/time 08:00` | Set daily sending time |
| `/page 25` | Set current Quran page |
| `/send_now` | Send today's portion immediately |
| `/pause` | Pause daily sending |
| `/resume` | Resume daily sending |

---

## 👑 Admin Commands

Only the Telegram account matching `ADMIN_ID` can use these commands.

| Command | Description |
|---|---|
| `/admin_stats` | Show number of active subscribers |
| `/broadcast message` | Send a message to all active subscribers |
| `/admin_send_dua` | Send one dua immediately to all active subscribers |

---

## 🕒 Scheduling Logic

The bot checks every minute for users whose configured `send_time` matches the current time in `TIMEZONE`.

Example:

```text
TIMEZONE=Africa/Cairo
```

If a user has:

```text
send_time = 08:00
```

The bot sends their daily Quran pages when local time reaches `08:00`.

---

## 📖 Quran Portion Logic

The Quran has 604 pages.

The bot calculates the pages like this:

- Starts from the user's `current_page`
- Sends `daily_goal` pages
- If the remaining pages are less than or equal to `1.5 × daily_goal`, it sends all remaining pages
- After completion, the next khatma starts from page 1

---

## 📄 PDF Logic

- If the daily portion is **10 pages or fewer**, the bot sends a Telegram media album.
- If the daily portion is **more than 10 pages**, the bot downloads the images and generates a PDF.

Temporary files are stored in `tmp/` and cleaned up after sending.

---

## ☁️ Deployment Notes

For a full step-by-step deployment guide, read [`DEPLOYMENT.md`](DEPLOYMENT.md).

This repository also includes:

- `render.yaml` for Render Background Worker configuration
- `runtime.txt` to request Python 3.11 on supported hosting platforms

You can deploy this bot on platforms such as:

- Render
- Koyeb
- Railway
- VPS

For hosting platforms, set these as environment variables in the dashboard:

```text
BOT_TOKEN
ADMIN_ID
TIMEZONE
```

Do **not** upload your real `.env` file.

### Important SQLite Note

Some free hosting platforms use temporary storage. This means `quran_bot.db` may be deleted after restart or redeploy.

For production use, consider replacing SQLite with a persistent database such as:

- PostgreSQL
- Supabase
- Railway PostgreSQL
- Neon

---

## 🧪 Useful Git Commands

Initial push:

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/0Ahmad0/quran_tele.git
git push -u origin main
```

If you already added the remote:

```bash
git add .
git commit -m "update quran telegram bot"
git push
```

---

## 🛡 Files That Must Stay Private

These files should never be committed:

```text
.env
quran_bot.db
tmp/
__pycache__/
*.pyc
```

They are already covered by `.gitignore`.

---

## 📜 License

This project is open-source. You can use and modify it for personal or educational purposes.

---

## 🤲 Final Note

May Allah make this bot a source of ongoing reward and help people stay connected with the Quran.
