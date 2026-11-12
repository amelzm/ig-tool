"""Instagram private-API client for hiding followers/following.

Uses the GraphQL `IGSettingsBooleanMutation` with `Bearer IGT:2:` auth, which is
what the current web client calls:

    POST https://i.instagram.com/graphql/query
    fb_api_req_friendly_name=IGSettingsBooleanMutation
    variables={"setting_id":"hide_followers_following_list","value":true,...}

The older REST route (api/v1/settings/set_bool/) now answers `login_required`
for many sessions, so it is no longer the primary path.
"""
import base64
import json
import re
import secrets
import string
import uuid

import requests

API = "https://i.instagram.com/api/v1/"
GRAPHQL = "https://i.instagram.com/graphql/query"
CURRENT_USER = API + "accounts/current_user/?edit=true"
GET_BOOL = API + "settings/get_bool/"
SET_BOOL = API + "settings/set_bool/"
WEB_SET_VISIBILITY = "https://www.instagram.com/api/v1/accounts/set_visibility_settings/"

SETTING = "hide_followers_following_list"
MUTATION = "IGSettingsBooleanMutation"
CLIENT_DOC_ID = "2669261950526978627082629536"
RESULT_KEY = "xdt_api__v1__settings__set_bool"

WEB_APP_ID = "124024574287414"
ANDROID_APP_ID = "567067343352427"
UA = "Instagram 453.0.0"
TIMEOUT = (8, 25)

SESSION_RE = re.compile(r"sessionid\s*=\s*\"?([^;\"\s]+)")
CSRF_RE = re.compile(r"csrftoken\s*=\s*\"?([^;\"\s]+)")
VALID_SESSION = re.compile(r"^[1-9][0-9]*(?::|%3[aA]).+$")
BAD_CHARS = set(';,"\\')


class InstagramError(Exception):
    code, status = "error", 502
    default = "Instagram rejected the request."

    def __init__(self, message=""):
        self.message = message or self.default
        super().__init__(self.message)


class InvalidSession(InstagramError):
    code, status = "invalid_session", 401
    default = "That session is not valid or has expired. Log in again and copy a fresh sessionid."


class Challenge(InstagramError):
    code, status = "challenge", 403
    default = "Instagram wants a security check. Approve it in the app, then retry."


class RateLimited(InstagramError):
    code, status = "rate_limited", 429
    default = "Instagram is rate limiting. Wait a minute and try again."


class Unavailable(InstagramError):
    code, status = "unavailable", 502
    default = "Instagram did not respond properly. Try again in a moment."


RunError = InstagramError


def mask(session):
    """Short, log-safe fingerprint of a sessionid."""
    text = str(session or "").strip()
    if not text:
        return "(empty)"
    uid = re.split(r"%3[aA]|:", text, maxsplit=1)[0]
    return f"{uid}:…{text[-6:]} ({len(text)} chars)"


def _clean(sessionid):
    """Validate the bare sessionid value."""
    if not sessionid:
        raise InvalidSession("Paste your sessionid first.")
    for char in sessionid:
        if ord(char) <= 32 or ord(char) >= 127 or char in BAD_CHARS:
            raise InvalidSession(
                "Enter only the sessionid value, without 'sessionid=' or semicolons.")
    if not VALID_SESSION.match(sessionid):
        raise InvalidSession(
            "That does not look like an Instagram sessionid: it must start with "
            "your numeric id followed by ':' or '%3A'.")
    if len(sessionid) < 25:
        raise InvalidSession("That sessionid looks truncated. Copy the whole value.")
    return sessionid


def parse_session(raw):
    """Accept a bare sessionid, a full cookie string, or a `Cookie:` header."""
    text = " ".join(str(raw).split())
    if not text:
        raise InvalidSession("Paste your sessionid first.")
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()

    match = SESSION_RE.search(text)
    if match:
        sessionid = match.group(1)
    elif "=" in text and not VALID_SESSION.match(text.split(";")[0].strip()):
        raise InvalidSession("Could not find a sessionid in that value.")
    else:
        sessionid = text.split(";")[0].strip()

    sessionid = _clean(sessionid.strip().strip("\"'"))
    csrf = CSRF_RE.search(text)
    return {"sessionid": sessionid, "csrftoken": csrf.group(1) if csrf else ""}


class Instagram:
    def __init__(self, sessionid, csrftoken=""):
        self.sessionid = sessionid
        self.uid = re.split(r"%3[aA]|:", sessionid, maxsplit=1)[0]
        self.csrftoken = csrftoken or ""
        self.http = requests.Session()
        self.http.headers.update({
            "Authorization": self._authorization(),
            "User-Agent": UA,
            "X-IG-App-ID": WEB_APP_ID,
            "X-Auth-Type": "instagram",
            "IG-INTENDED-USER-ID": self.uid,
            "X-GraphQL-Client-Library": "pando",
            "X-FB-Friendly-Name": MUTATION,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        jar = self.http.cookies
        jar.set("sessionid", sessionid, domain=".instagram.com")
        jar.set("ds_user_id", self.uid, domain=".instagram.com")
        jar.set("ig_did", str(uuid.uuid4()).upper(), domain=".instagram.com")
        jar.set("mid", "".join(secrets.choice(string.ascii_letters + string.digits)
                               for _ in range(11)), domain=".instagram.com")
        if self.csrftoken:
            self.http.headers["X-CSRFToken"] = self.csrftoken

    def _authorization(self):
        payload = {
            "ds_user_id": self.uid,
            "sessionid": self.sessionid,
            "should_use_header_over_cookies": True,
        }
        encoded = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")
        return f"Bearer IGT:2:{encoded}"

    def close(self):
        self.http.close()

    def _send(self, method, url, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        try:
            response = self.http.request(method, url, **kwargs)
        except requests.Timeout:
            raise InstagramError("Instagram timed out. Try again in a moment.")
        except requests.RequestException:
            raise InstagramError("Could not reach Instagram. Try again in a moment.")
        if response.status_code == 429:
            raise RateLimited()
        return response

    @staticmethod
    def _payload(response):
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        message = str(payload.get("message") or "")
        errors = payload.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else errors
            if isinstance(first, dict):
                message = message or str(first.get("message") or "")
                if first.get("code") in (464, 400) and "login" in message.lower():
                    raise InvalidSession()
        if message == "login_required" or payload.get("authenticated") is False:
            raise InvalidSession()
        if "checkpoint" in message or payload.get("checkpoint_url"):
            raise Challenge()
        if "challenge" in message:
            raise Challenge()
        if "rate_limit" in message or "wait a few minutes" in message:
            raise RateLimited()
        if response.status_code >= 500:
            raise Unavailable()
        if response.status_code in (401, 403) and not payload.get("data"):
            raise InvalidSession()
        return payload

    @staticmethod
    def _result(payload):
        """Pull the mutation result node out of the GraphQL envelope."""
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        for key, value in data.items():
            if (key == RESULT_KEY or key.startswith(RESULT_KEY + "(")) \
                    and isinstance(value, dict):
                return value
        return None

    def me(self):
        """Best effort: the uid always comes from the session itself."""
        try:
            payload = self._payload(self._send("GET", CURRENT_USER))
        except InstagramError:
            return {"uid": self.uid, "username": ""}
        user = payload.get("user") or {}
        return {"uid": str(user.get("pk") or self.uid),
                "username": user.get("username") or ""}

    def read(self):
        """Best effort read of the current value. None when unknown."""
        try:
            payload = self._payload(self._send("GET", GET_BOOL,
                                               params={"setting_id": SETTING}))
        except InstagramError:
            return None
        value = payload.get("value")
        return value if isinstance(value, bool) else None

    @staticmethod
    def _incorrect_query(payload):
        errors = payload.get("errors")
        if not isinstance(errors, list):
            return False
        return any(isinstance(e, dict) and e.get("code") == 1675002 for e in errors)

    @staticmethod
    def _reason(payload):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first = errors[0]
            return str(first.get("description") or first.get("summary")
                       or first.get("message") or "")
        return str(payload.get("message") or "")

    @staticmethod
    def _verify(result, value):
        if result.get("value") is not bool(value):
            raise InstagramError(
                f"Instagram returned value={result.get('value')!r} instead of {bool(value)!r}.")
        for key in ("error_name_value", "errorNameValue",
                    "fallback_message", "fallbackMessage"):
            if result.get(key):
                raise InstagramError(str(result[key]))

    def _graphql(self, value):
        """Run the mutation, trying both persisted-query parameter names."""
        common = {
            "method": "post",
            "format": "json",
            "server_timestamps": "true",
            "locale": "user",
            "fb_api_req_friendly_name": MUTATION,
            "variables": json.dumps({
                "setting_id": SETTING,
                "allow_error_codes": True,
                "callsite": "account_privacy",
                "value": bool(value),
            }),
        }
        payload, result = {}, None
        for param in ("client_doc_id", "doc_id"):
            payload = self._payload(
                self._send("POST", GRAPHQL, data=dict(common, **{param: CLIENT_DOC_ID})))
            result = self._result(payload)
            if result is not None or not self._incorrect_query(payload):
                break
        return payload, result

    def write(self, value):
        """Apply the setting. True when a route reports success.

        GraphQL first (what the web client uses), then the REST route, then the
        web visibility route. Instagram retires these shapes without notice, so
        a stale one must not take the whole run down.
        """
        flag = "true" if value else "false"
        reasons = []

        try:
            payload, result = self._graphql(value)
            if result is not None:
                self._verify(result, value)
                return True
            reasons.append("graphql: " + (self._reason(payload) or "no setting node"))
        except InvalidSession:
            raise
        except InstagramError as error:
            reasons.append("graphql: " + error.message)

        for label, url, data, extra in (
            ("rest", SET_BOOL, {"setting_id": SETTING, "value": flag},
             {"X-IG-App-ID": ANDROID_APP_ID}),
            ("web", WEB_SET_VISIBILITY, {"is_hide_followers_and_following": flag}, {}),
        ):
            try:
                payload = self._payload(self._send("POST", url, data=data,
                                                   headers=extra or None))
                if payload.get("status") == "ok":
                    return True
                reasons.append(f"{label}: " + str(payload.get("message") or "rejected"))
            except InvalidSession:
                raise
            except InstagramError as error:
                reasons.append(f"{label}: " + error.message)

        raise InstagramError("; ".join(reasons)[:280] or "Instagram rejected the request.")


def run(raw, hide=True):
    """Validate the session, apply the setting, and read it back."""
    cookies = parse_session(raw)
    client = Instagram(cookies["sessionid"], cookies["csrftoken"])
    try:
        user = client.me()
        current = client.read()
        status = "already" if current is hide else ("hidden" if hide else "shown")
        if current is hide:
            return {"status": status, "username": user["username"], "uid": user["uid"],
                    "already": True, "confirmed": True, "value": hide,
                    "session": mask(cookies["sessionid"])}
        try:
            client.write(hide)
        except InstagramError as error:
            if not user["username"] and "session" not in error.message.lower():
                raise type(error)(
                    f"{error.message} The session may also be expired.") from None
            raise
        confirmed = client.read()
        return {"status": status, "username": user["username"], "uid": user["uid"],
                "already": False, "confirmed": confirmed is hide, "value": hide,
                "session": mask(cookies["sessionid"])}
    finally:
        client.close()
