# Veil — hide Instagram followers & following

Flips Instagram's `hide_followers_following_list` setting using the visitor's own
`sessionid` cookie. No password, no OAuth app, no database. The change is stored on
Instagram's side, so it applies everywhere.

Two front ends over one client:

- a web tool (`server.py`) that takes the sessionid in a form
- a CLI (`main.py`) that prompts for it

## Requirements

- Python 3.10 or newer
- An Instagram account
- A valid `sessionid` cookie value
- Internet connection

No third-party packages. Standard library only.

## CLI

```sh
python main.py          # hide
python main.py --show   # make the lists visible again
python main.py --check  # offline sanity check, no network
```

The sessionid is read with hidden terminal input, so it does not land in your shell
history. Paste only the cookie value — not `sessionid=`.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Operation successful |
| 1 | Instagram, network, or request error |
| 2 | Sessionid failed validation |
| 130 | Interrupted |

## Web

```sh
python server.py
```

Open http://localhost:8080. `PORT` overrides the port.

| Route | Method | Notes |
| --- | --- | --- |
| `/` | GET | The page |
| `/health`, `/api/health` | GET | Health check |
| `/api/hide` | POST | `{"session": "...", "hide": true\|false}` |
| `/api/visit` | POST | Page-open beacon |

Rate limit 12 runs per IP per 10 minutes. Request bodies cap at 16 KB.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `PORT` | no | Listen port, default `8080` |

## How it works

1. The sessionid is validated and the numeric user id extracted from it.
2. An `Authorization: Bearer IGT:2:<base64 json>` header is built from the session.
3. An authenticated GraphQL POST is sent to Instagram with the
   `IGSettingsBooleanMutation`.
4. The response is parsed and the run only counts as successful when Instagram
   echoes back the expected `value`.
5. The setting is read back to confirm.

## API details

| Parameter | Value |
| --- | --- |
| Endpoint | `https://i.instagram.com/graphql/query` |
| HTTP method | POST |
| Mutation | `IGSettingsBooleanMutation` |
| Setting id | `hide_followers_following_list` |
| Callsite | `account_privacy` |
| Authentication | `Bearer IGT:2` |
| App id | `124024574287414` |
| Timeout | 15 seconds |

## Structure

| File | Responsibility |
| --- | --- |
| `instagram.py` | Session validation, request building, execution, response checks |
| `server.py` | HTTP server, routing, rate limiting, media |
| `main.py` | CLI entry point |
| `index.html` | The page |

Errors derive from `InstagramError`; `ValidationError` marks bad input rather than a
rejected session. Session values are redacted out of error text before it is shown
or logged.

## Deploy

```sh
docker build -t veil .
docker run --rm -p 8080:8080 veil
```

`railway.json` selects the Dockerfile. Keep replicas at 1 — the rate limiter is
in-process.

## Security notes

- The sessionid is a bearer credential. It is held only for the duration of a
  request — anyone who obtains it can act as the account until the session is
  revoked.
- `X-Forwarded-For` is trusted for rate limiting. Correct behind Railway's proxy,
  spoofable if the port is exposed directly.
- Every response carries CSP, `nosniff`, `no-referrer`, and `DENY` framing.

Independent project. Not affiliated with Instagram or Meta.
