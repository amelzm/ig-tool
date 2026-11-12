"""Instagram private-API client for hiding followers/following.

    POST https://i.instagram.com/graphql/query
    fb_api_req_friendly_name=IGSettingsBooleanMutation
    variables={"setting_id":"hide_followers_following_list","value":true,...}

Auth is `Bearer IGT:2:<base64 json>` plus the session cookie. The older REST
route (api/v1/settings/set_bool/) now answers `login_required` for most
sessions, so GraphQL is the only path used here.

Standard library only.
"""
import base64
import json
import re
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://i.instagram.com/api/v1/"
GRAPHQL = "https://i.instagram.com/graphql/query"
CURRENT_USER = API + "accounts/current_user/?edit=true"
GET_BOOL = API + "settings/get_bool/"

SETTING = "hide_followers_following_list"
MUTATION = "IGSettingsBooleanMutation"
CLIENT_DOC_ID = "2669261950526978627082629536"
RESULT_KEY = "xdt_api__v1__settings__set_bool"

APP_ID = "124024574287414"
UA = "Instagram 453.0.0"
TIMEOUT = 15
MAX_BODY = 1024 * 1024

SESSION_RE = re.compile(r"sessionid\s*=\s*\"?([^;\"\s]+)")
CSRF_RE = re.compile(r"csrftoken\s*=\s*\"?([^;\"\s]+)")
VALID_SESSION = re.compile(r"^[1-9][0-9]*(?::|%3[aA]).+$")
UID_RE = re.compile(r"%3[aA]|:")
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


class ValidationError(InvalidSession):
    """Bad input, as opposed to a session Instagram rejected."""


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise InstagramError("Instagram redirected the request; credentials were not forwarded.")


def mask(session):
    """Short, log-safe fingerprint of a sessionid."""
    text = str(session or "").strip()
    if not text:
        return "(empty)"
    return f"{UID_RE.split(text, maxsplit=1)[0]}:…{text[-6:]} ({len(text)} chars)"


def _clean(sessionid):
    """Validate the bare sessionid value, without `sessionid=`."""
    if not sessionid:
        raise ValidationError("Paste your sessionid first.")
    for char in sessionid:
        if ord(char) <= 32 or ord(char) >= 127 or char in BAD_CHARS:
            raise ValidationError(
                "Enter only the sessionid value, without 'sessionid=' or semicolons.")
    if not VALID_SESSION.match(sessionid):
        raise ValidationError(
            "Invalid sessionid format: expected a numeric user ID followed by ':' or '%3A'.")
    if len(sessionid) < 25:
        raise ValidationError("That sessionid looks truncated. Copy the whole value.")
    return sessionid


def parse_session(raw):
    """Accept a bare sessionid, a full cookie string, or a `Cookie:` header."""
    text = " ".join(str(raw).split())
    if not text:
        raise ValidationError("Paste your sessionid first.")
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()

    match = SESSION_RE.search(text)
    if match:
        sessionid = match.group(1)
    elif "=" in text and not VALID_SESSION.match(text.split(";")[0].strip()):
        raise ValidationError("Could not find a sessionid in that value.")
    else:
        sessionid = text.split(";")[0].strip()

    sessionid = _clean(sessionid.strip().strip("\"'"))
    csrf = CSRF_RE.search(text)
    return {"sessionid": sessionid, "csrftoken": csrf.group(1) if csrf else ""}


class Instagram:
    def __init__(self, sessionid, csrftoken=""):
        self.sessionid = sessionid
        self.uid = UID_RE.split(sessionid, maxsplit=1)[0]
        self.csrftoken = csrftoken or ""
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())

    def close(self):
        pass

    def _headers(self):
        payload = {
            "ds_user_id": self.uid,
            "sessionid": self.sessionid,
            "should_use_header_over_cookies": True,
        }
        encoded = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")
        headers = {
            "Authorization": f"Bearer IGT:2:{encoded}",
            "Cookie": (f"sessionid={self.sessionid}; ds_user_id={self.uid}; "
                       f"ig_did={str(uuid.uuid4()).upper()}; "
                       f"mid={''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(11))}"),
            "IG-INTENDED-USER-ID": self.uid,
            "X-IG-App-ID": APP_ID,
            "X-Auth-Type": "instagram",
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "identity",
            "X-GraphQL-Client-Library": "pando",
            "X-FB-Friendly-Name": MUTATION,
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.csrftoken:
            headers["X-CSRFToken"] = self.csrftoken
        return headers

    def _redact(self, text):
        secrets_ = {self.sessionid, urllib.parse.unquote(self.sessionid),
                    urllib.parse.quote(self.sessionid, safe="")}
        for secret in sorted(secrets_, key=len, reverse=True):
            if secret:
                text = text.replace(secret, "<REDACTED>")
        return text

    def _execute(self, url, data=None):
        request = urllib.request.Request(
            url, data=data, headers=self._headers(),
            method="POST" if data is not None else "GET")
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise Unavailable("Instagram's response was too large.")
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from None
        except urllib.error.URLError as error:
            raise InstagramError(f"Network/TLS failure: {error.reason}.") from None
        except TimeoutError:
            raise InstagramError("Instagram timed out. Try again in a moment.") from None
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Unavailable("Instagram returned an unreadable response.") from None
        if not isinstance(payload, dict):
            raise Unavailable("Instagram returned an unexpected response.")
        return payload

    def _http_error(self, error):
        with error:
            raw = error.read(16385)
        reason, code = "", None
        try:
            body = json.loads(raw)
            if isinstance(body, dict):
                errors = body.get("errors")
                if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                    first = errors[0]
                    reason = str(first.get("description") or first.get("summary")
                                 or first.get("message") or "")
                    code = first.get("code")
                reason = reason or str(body.get("message") or "")
        except (ValueError, UnicodeError):
            pass

        text = self._redact(reason or "no details")[:400]
        if code:
            text += f" (code {code})"
        message = f"HTTP {error.code}: {text}"

        if error.code == 429 or "rate_limit" in text:
            return RateLimited(message)
        if error.code in (401, 403) or "login_required" in text:
            return InvalidSession(message)
        if "checkpoint" in text or "challenge" in text:
            return Challenge(message)
        if error.code >= 500:
            return Unavailable(message)
        return InstagramError(message)

    def _payload(self, payload):
        message = str(payload.get("message") or "")
        if message == "login_required" or payload.get("authenticated") is False:
            raise InvalidSession()
        if "checkpoint" in message or payload.get("checkpoint_url"):
            raise Challenge()
        if "challenge" in message:
            raise Challenge()
        if "rate_limit" in message or "wait a few minutes" in message:
            raise RateLimited()
        return payload

    @staticmethod
    def _reason(payload):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first = errors[0]
            return str(first.get("description") or first.get("summary")
                       or first.get("message") or "")
        return str(payload.get("message") or "")

    @staticmethod
    def _incorrect_query(payload):
        errors = payload.get("errors")
        if not isinstance(errors, list):
            return False
        return any(isinstance(e, dict) and e.get("code") == 1675002 for e in errors)

    @staticmethod
    def _result(payload):
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        matches = [value for key, value in data.items()
                   if (key == RESULT_KEY or key.startswith(RESULT_KEY + "("))
                   and isinstance(value, dict)]
        return matches[0] if len(matches) == 1 else None

    def me(self):
        """Best effort: the uid always comes from the session itself."""
        try:
            payload = self._payload(self._execute(CURRENT_USER))
        except InstagramError:
            return {"uid": self.uid, "username": ""}
        user = payload.get("user") or {}
        return {"uid": str(user.get("pk") or self.uid),
                "username": user.get("username") or ""}

    def read(self):
        """Best effort read of the current value. None when unknown."""
        try:
            payload = self._payload(
                self._execute(GET_BOOL + "?" + urllib.parse.urlencode({"setting_id": SETTING})))
        except InstagramError:
            return None
        value = payload.get("value")
        return value if isinstance(value, bool) else None

    def write(self, value):
        """Run the mutation. True only when Instagram echoes the new value.

        Instagram has moved between `client_doc_id` and `doc_id` for persisted
        queries, so try the documented one and fall back to the other.
        """
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
        payload, result, failure = {}, None, None
        for param in ("client_doc_id", "doc_id"):
            body = dict(common, **{param: CLIENT_DOC_ID})
            try:
                payload = self._payload(
                    self._execute(GRAPHQL, urllib.parse.urlencode(body).encode()))
            except InstagramError as error:
                failure = error
                continue
            result = self._result(payload)
            if result is not None or not self._incorrect_query(payload):
                failure = None
                break

        if result is None:
            if failure is not None:
                raise failure
            reason = self._reason(payload)
            raise InstagramError(
                "Instagram did not confirm the setting"
                + (f": {reason}." if reason else "."))
        if result.get("value") is not bool(value):
            raise InstagramError(
                f"Instagram returned value={result.get('value')!r} instead of {bool(value)!r}.")
        for key in ("error_name_value", "errorNameValue",
                    "fallback_message", "fallbackMessage"):
            if result.get(key):
                raise InstagramError(str(result[key]))
        return True


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
