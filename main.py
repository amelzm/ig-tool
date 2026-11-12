"""Offline check. Run python main.py; no input or network required."""
import json
import instagram
import telegram


def run_demo():
    return {"mode": "demo", "parse": instagram.mask("1234567890%3Aabcdefghijklmnopqrstuvwxyz"),
            "telegram_configured": telegram.configured(),
            "message": "Local check only. No external service was contacted."}


if __name__ == '__main__':
    print(json.dumps(run_demo(), indent=2))