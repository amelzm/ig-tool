"""Minimal Instagram private-API client for hiding followers/following.

    POST https://i.instagram.com/api/v1/settings/set_bool/
    GET  https://i.instagram.com/api/v1/settings/get_bool/
    body: setting_id=hide_followers_following_list&value=true|false
"""
import re
import secrets
import string
import uuid

import requests

API = "https://i.instagram.com/api/v1/"
SET_BOOL = API + "settings/set_bool/"
GET_BOOL = API + "settings/get_bool/"
CURRENT_USER = API + "accounts/current_user/?edit=true"
WEB_SET_VISIBILITY = "https://www.instagram.com/api/v1/accounts/set_visibility_settings/"

SETTING = "hide_followers_following_list"

ANDROID_APP_ID = "567067343352427"
UA = ("Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-S911B; "
      "dm3q; qcom; en_US; 458229237)")
TIMEOUT = (8, 25)

SESSION_RE = re.compile(r"sessionid\s*=\s*\"?([^;\"\s]+)")
CSRF_RE = re.compile(r"csrftoken\s*=\s*\"?([^;\"\s]+)")
VALID_SESSION = re.compile(r"^\d{3,}(?:%3A|:)[\w%.~+/=-]+$")


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
    uid = text.split("%3A")[0].split(":")[0]
    return f"{uid}:…{text[-6:]} ({len(text)} chars)"


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
        sessionid = text.strip("\"'").split(";")[0].strip()

    sessionid = sessionid.strip().strip("\"'")
    if not VALID_SESSION.match(sessionid):
        raise InvalidSession("That does not look like an Instagram sessionid.")
    if len(sessionid) < 25:
        raise InvalidSession("That sessionid looks truncated. Copy the whole value.")

    csrf = CSRF_RE.search(text)
    return {"sessionid": sessionid, "csrftoken": csrf.group(1) if csrf else ""}


class Instagram:
    def __init__(self, sessionid, csrftoken=""):
        self.csrftoken = csrftoken or ""
        self._csrf_tried = False
        self.uid = sessionid.split("%3A")[0].split(":")[0]
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": UA,
            "X-IG-App-ID": ANDROID_APP_ID,
            "X-IG-Capabilities": "3brTvw==",
            "X-IG-Connection-Type": "WIFI",
            "X-IG-Bandwidth-TotalBytes-B": "5000000",
            "X-IG-Bandwidth-TotalTime-MS": "2000",
            "X-IG-Bandwidth-Peak-B": "5000000",
            "X-IG-Bandwidth-Peak-Time-MS": "2000",
            "X-ASBD-ID": "198387",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
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
            self._apply_csrf()

    def close(self):
        self.http.close()

    def _apply_csrf(self):
        if self.csrftoken:
            self.http.headers["X-CSRFToken"] = self.csrftoken

    def _capture_csrf(self):
        token = self.http.cookies.get("csrftoken")
        if token and token != self.csrftoken:
            self.csrftoken = token
            self._apply_csrf()

    def _ensure_csrf(self):
        if self.csrftoken or self._csrf_tried:
            return
        self._csrf_tried = True
        try:
            self.http.get("https://www.instagram.com/", timeout=TIMEOUT)
        except requests.RequestException:
            pass
        self._capture_csrf()

    def _send(self, method, url, **kwargs):
        self._ensure_csrf()
        kwargs.setdefault("timeout", TIMEOUT)
        try:
            response = self.http.request(method, url, **kwargs)
        except requests.Timeout:
            raise InstagramError("Instagram timed out. Try again in a moment.")
        except requests.RequestException:
            raise InstagramError("Could not reach Instagram. Try again in a moment.")
        self._capture_csrf()
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
        return payload

    def me(self):
        payload = self._payload(self._send("GET", CURRENT_USER))
        user = payload.get("user") or {}
        if not user.get("pk"):
            raise InvalidSession()
        return {"uid": str(user["pk"]), "username": user.get("username") or ""}

    def read(self):
        payload = self._payload(self._send("GET", GET_BOOL, params={"setting_id": SETTING}))
        value = payload.get("value")
        return value if isinstance(value, bool) else None

    def write(self, value):
        flag = "true" if value else "false"
        payload = self._payload(self._send("POST", SET_BOOL,
                                           data={"setting_id": SETTING, "value": flag}))
        if payload.get("status") == "ok":
            return True
        try:
            fallback = self._payload(self._send(
                "POST", WEB_SET_VISIBILITY,
                data={"is_hide_followers_and_following": flag}))
            if fallback.get("status") == "ok":
                return True
        except InstagramError:
            pass
        raise InstagramError(str(payload.get("message") or ""))


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
        client.write(hide)
        confirmed = client.read()
        return {"status": status, "username": user["username"], "uid": user["uid"],
                "already": False, "confirmed": confirmed is hide, "value": hide,
                "session": mask(cookies["sessionid"])}
    finally:
        client.close()