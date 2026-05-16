# Quran Tele Deployment Guide

This guide shows you exactly what to do from zero until the bot is running online.

---

## 1. Create a new secure Telegram bot token

Because an old token was exposed before, create a fresh token before deployment.

1. Open Telegram.
2. Go to [@BotFather](https://t.me/BotFather).
3. Select your bot.
4. Revoke the old token or generate a new token.
5. Keep the new token private.

Never commit the real token to GitHub.

---

## 2. Get your Telegram admin ID

1. Open [@userinfobot](https://t.me/userinfobot).
2. Copy your numeric Telegram user ID.
3. This value will be used as `ADMIN_ID`.

---

## 3. Run locally first

From the project folder:

```bash
python -m pip install -r requirements.txt
```

Create a local `.env` file:

```text
BOT_TOKEN=your_real_new_bot_token
ADMIN_ID=your_numeric_telegram_id
TIMEZONE=Africa/Cairo
```

Run the bot:

```bash
python main.py
```

Then open your bot in Telegram and test:

```text
/start
/status
/send_now
```

---

## 4. Push updates to GitHub

Make sure `.env` is not committed.

```bash
git status
git add .
git commit -m "prepare deployment"
git push origin main
```

---

## 5. Deploy on Render

The bot uses polling, so deploy it as a **Background Worker**, not a Web Service.

### Option A: Manual Render setup

1. Open [Render](https://render.com).
2. Click **New +**.
3. Choose **Background Worker**.
4. Connect GitHub.
5. Select the repository: `0Ahmad0/quran_tele`.
6. Use these settings:

| Setting | Value |
|---|---|
| Environment | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python main.py` |

7. Add environment variables:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Your new token from BotFather |
| `ADMIN_ID` | Your numeric Telegram user ID |
| `TIMEZONE` | `Africa/Cairo` or your timezone |

8. Click **Create Background Worker**.
9. Open logs and wait for: `Quran bot started`.

### Option B: Render Blueprint

This repository includes `render.yaml`, so Render can detect the worker configuration automatically.

You still must add the real secret values in Render environment variables.

---

## 6. Deploy on Koyeb

1. Open [Koyeb](https://www.koyeb.com).
2. Create a new app.
3. Choose GitHub deployment.
4. Select `0Ahmad0/quran_tele`.
5. Build command:

```bash
pip install -r requirements.txt
```

6. Run command:

```bash
python main.py
```

7. Add environment variables:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Your new token from BotFather |
| `ADMIN_ID` | Your numeric Telegram user ID |
| `TIMEZONE` | `Africa/Cairo` or your timezone |

8. Deploy and check logs.

---

## 7. Important SQLite note

The current database is SQLite and stored in `quran_bot.db`.

On free hosting, this file may be deleted after restart or redeploy if the platform does not provide persistent disk storage.

For production, move the database to PostgreSQL using one of these:

- Supabase
- Neon
- Railway PostgreSQL
- Render PostgreSQL

---

## 8. Deployment checklist

Before going live:

- [ ] Old Telegram token revoked.
- [ ] New token added only to `.env` locally or hosting environment variables.
- [ ] `.env` is not on GitHub.
- [ ] `ADMIN_ID` is correct.
- [ ] Bot works locally.
- [ ] GitHub repo is updated.
- [ ] Hosting service is a worker/background service.
- [ ] Logs show `Quran bot started`.
- [ ] You tested `/start`, `/status`, and `/send_now` in Telegram.

---

## 9. Common errors

### `ModuleNotFoundError: No module named 'aiogram'`

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

### `Missing BOT_TOKEN`

Create `.env` locally or set `BOT_TOKEN` in hosting environment variables.

### Bot does not answer

Check:

- The token is correct.
- Only one copy of the bot is running.
- Hosting logs do not show errors.
- The bot is started using `python main.py`.

### Admin commands do not work

Check that `ADMIN_ID` is your numeric Telegram ID, not your username.
