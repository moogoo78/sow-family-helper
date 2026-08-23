#!/usr/bin/env python3
"""Stdlib-only backend for the SOW family contact app.

Serves the static frontend and a small password-gated JSON API backed by
north7.sqlite. No third-party dependencies -- `python3 server.py` is the
whole deploy story.

Env vars:
    HOST            bind address (default 0.0.0.0, i.e. reachable on the LAN)
    PORT            bind port (default 8000)
    COOKIE_SECURE   set to "1" to mark the session cookie Secure (only do
                    this if the app is actually served over HTTPS)
    SOW_ENV         set to "production" for the real deployment (see
                    compose.traefik.yml); anything else counts as a local
                    dev instance and gets a "dev | " page-title prefix
"""
import hashlib
import hmac
import html
import http.cookies
import json
import mimetypes
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dataset

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_COOKIE = "sow_session"
SESSION_MAX_AGE = 400 * 24 * 3600  # ~400 days: "remember this device"
LOGIN_RATE_LIMIT = 8
LOGIN_RATE_WINDOW = 600  # seconds
PBKDF2_ITERATIONS = 310_000  # must match scripts/set_password.py

COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"
IS_DEV = os.environ.get("SOW_ENV") != "production"
DEV_TITLE_PREFIX = "dev | "

_login_attempts = {}
_login_lock = threading.Lock()


def rate_limit_ok(ip):
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_RATE_WINDOW]
        if len(attempts) >= LOGIN_RATE_LIMIT:
            _login_attempts[ip] = attempts
            return False
        attempts.append(now)
        _login_attempts[ip] = attempts
        return True


def get_setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def check_password(con, password):
    salt_hex = get_setting(con, "password_salt")
    stored_hash = get_setting(con, "password_hash")
    if not salt_hex or not stored_hash:
        return False
    salt = bytes.fromhex(salt_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()
    return hmac.compare_digest(candidate, stored_hash)


def make_session_token(secret, now):
    expiry = int(now) + SESSION_MAX_AGE
    payload = str(expiry)
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(secret, token, now):
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        expiry = int(payload)
    except ValueError:
        return False
    return now < expiry


class Handler(BaseHTTPRequestHandler):
    server_version = "SOWFamily/1.0"

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _session_cookie_value(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        jar = http.cookies.SimpleCookie()
        jar.load(cookie_header)
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _is_authenticated(self, con):
        secret = get_setting(con, "session_secret")
        if not secret:
            return False
        token = self._session_cookie_value()
        return verify_session_token(secret, token, time.time())

    def _set_session_cookie(self, value, max_age):
        parts = [f"{SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if COOKIE_SECURE:
            parts.append("Secure")
        return ("Set-Cookie", "; ".join(parts))

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _brand_index(self, body):
        """Stamp the 團 name from `settings` into the login page and title.

        The login screen renders before the API is reachable, so this cannot
        come down with /api/members. With no group_label set the page keeps
        its generic wording.
        """
        con = dataset.connect()
        try:
            label = dataset.get_group_label(con)
        finally:
            con.close()
        if not label:
            return body
        safe = html.escape(label).encode("utf-8")
        body = body.replace(b"<title>\xe8\x8d\x92\xe9\x87\x8e\xe8\xa6\xaa\xe5\xad\x90\xe5\x9c\x98\xe9\x80\x9a\xe8\xa8\x8a\xe9\x8c\x84</title>",
                            b"<title>" + safe + "通訊錄</title>".encode("utf-8"), 1)
        body = body.replace(b'<p class="group-label"></p>',
                            b'<p class="group-label">' + safe + b"</p>", 1)
        return body

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path.startswith("/static/"):
            path = path[len("/static/"):]
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send_json(404, {"error": "not found"})
            return
        content_type, _ = mimetypes.guess_type(full)
        with open(full, "rb") as f:
            body = f.read()
        if rel == "index.html":
            body = self._brand_index(body)
        if IS_DEV and rel == "index.html":
            body = body.replace(b"<title>", b"<title>" + DEV_TITLE_PREFIX.encode("utf-8"), 1)
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            try:
                con = dataset.connect()
                try:
                    con.execute("SELECT 1")
                finally:
                    con.close()
            except sqlite3.Error:
                self._send_json(500, {"status": "error"})
                return
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/api/members":
            con = dataset.connect()
            try:
                if not self._is_authenticated(con):
                    self._send_json(401, {"error": "unauthorized"})
                    return
                people = dataset.build_members(con)
                leaders = dataset.build_leaders(con)
                current_th_year = dataset.get_current_th_year(con)
                group_label = dataset.get_group_label(con)
            finally:
                con.close()
            self._send_json(200, {
                "ok": True,
                "people": people,
                "leaders": leaders,
                "groups": dataset.group_list(),
                "current_th_year": current_th_year,
                "group_label": group_label,
            })
            return
        self._serve_static(self.path)

    def do_POST(self):
        if self.path == "/api/login":
            client_ip = self.client_address[0]
            if not rate_limit_ok(client_ip):
                self._send_json(429, {"error": "too many attempts, try again later"})
                return
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "bad request"})
                return
            password = body.get("password", "")
            con = dataset.connect()
            try:
                if not password or not check_password(con, password):
                    self._send_json(401, {"error": "invalid password"})
                    return
                secret = get_setting(con, "session_secret")
            finally:
                con.close()
            token = make_session_token(secret, time.time())
            self._send_json(200, {"ok": True}, extra_headers=[self._set_session_cookie(token, SESSION_MAX_AGE)])
            return
        if self.path == "/api/logout":
            self._send_json(200, {"ok": True}, extra_headers=[self._set_session_cookie("", 0)])
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    if not os.path.exists(dataset.DB_PATH):
        raise SystemExit(f"database not found at {dataset.DB_PATH}")
    con = dataset.connect()
    try:
        has_settings = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        if not has_settings or get_setting(con, "password_hash") is None:
            raise SystemExit(
                "no password set yet -- run: python3 scripts/set_password.py"
            )
    finally:
        con.close()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SOW family app listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
