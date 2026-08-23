#!/usr/bin/env python3
"""Set or change the shared login password for the SOW family app.

Usage:
    python3 scripts/set_password.py

Stores a salted PBKDF2 hash (never the plaintext) in the `settings` table
of north7.sqlite, alongside a fresh session-signing secret. Rotating the
secret here invalidates every previously "remembered" login on other
devices, which is the right behavior whenever the password changes.
"""
import getpass
import hashlib
import os
import secrets
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "north7.sqlite")

PBKDF2_ITERATIONS = 310_000


def ensure_settings_table(con):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def set_setting(con, key, value):
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("New shared password: ")
    if not password:
        print("error: password cannot be empty", file=sys.stderr)
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("error: passwords did not match", file=sys.stderr)
        sys.exit(1)

    salt = secrets.token_bytes(16)
    password_hash = hash_password(password, salt)
    session_secret = secrets.token_hex(32)

    con = sqlite3.connect(DB_PATH)
    try:
        ensure_settings_table(con)
        set_setting(con, "password_salt", salt.hex())
        set_setting(con, "password_hash", password_hash)
        set_setting(con, "session_secret", session_secret)
        con.commit()
    finally:
        con.close()

    print("Password updated. Any devices that were previously remembered are now logged out.")


if __name__ == "__main__":
    main()
