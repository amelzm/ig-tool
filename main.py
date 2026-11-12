"""CLI entry point.

    python main.py           prompts for the sessionid, hides the lists
    python main.py --check   offline sanity check, no network

Exit codes: 0 success, 1 Instagram/network error, 2 bad sessionid input,
130 interrupted.
"""
import getpass
import json
import logging
import sys

import instagram
import telegram

logger = logging.getLogger("instagram.hide_lists")


def check():
    """Offline sanity check; no external service is contacted."""
    return {
        "mode": "check",
        "parse": instagram.mask("1234567890%3Aabcdefghijklmnopqrstuvwxyz"),
        "telegram_configured": telegram.configured(),
        "message": "Local check only. No external service was contacted.",
    }


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s",
                        stream=sys.stderr)

    if argv is None:
        argv = sys.argv[1:]
    if "--check" in argv:
        print(json.dumps(check(), indent=2))
        return 0

    hide = "--show" not in argv
    try:
        sessionid = getpass.getpass("Your Instagram sessionid value: ").strip()
        result = instagram.run(sessionid, hide)
    except instagram.ValidationError as error:
        logger.error("%s", error.message)
        return 2
    except instagram.InstagramError as error:
        logger.error("%s", error.message)
        return 1
    except KeyboardInterrupt:
        logger.error("Interrupted. The update may have been applied; check before retrying.")
        return 130

    verb = "hidden" if result["value"] else "visible"
    logger.info("Instagram confirmed the setting (value=%s).",
                "true" if result["value"] else "false")
    account = f"@{result['username']}" if result["username"] else result["uid"]
    print(f"Done: followers and following are {verb} for {account}.")
    if not result["confirmed"]:
        print("Not read back — open the app to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
