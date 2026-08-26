#!/usr/bin/env python3
"""Set or change the login passwords for the SOW family app.

Usage:
    python3 scripts/set_password.py            # the shared password
    python3 scripts/set_password.py --admin    # the admin password

Two passwords, one login field. The shared one is what the whole 團 gets;
the admin one additionally unlocks the contact details the address book
keeps out of everyone else's payload (email). The admin password is
optional -- with none set, nobody can log in as admin.

Stores a salted PBKDF2 hash (never the plaintext) in the `settings` table
of north7.sqlite. Setting the shared password also rotates the
session-signing secret, which invalidates every previously "remembered"
login on other devices -- the right behavior whenever that password
changes. Setting the admin password deliberately does NOT rotate it, so
the 團 is not logged out over an admin-side change; admin sessions expire
on their own after 30 days (ADMIN_SESSION_MAX_AGE in server.py).
"""
import argparse
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


def get_setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(con, key, value):
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


def matches(con, password, prefix):
    """Whether `password` is already the one stored under `prefix`."""
    salt_hex = get_setting(con, f"{prefix}password_salt")
    stored_hash = get_setting(con, f"{prefix}password_hash")
    if not salt_hex or not stored_hash:
        return False
    return hash_password(password, bytes.fromhex(salt_hex)) == stored_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--admin",
        action="store_true",
        help="set the admin password (unlocks email) instead of the shared one",
    )
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"error: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    prefix = "admin_" if args.admin else ""
    which = "admin" if args.admin else "shared"
    password = getpass.getpass(f"New {which} password: ")
    if not password:
        print("error: password cannot be empty", file=sys.stderr)
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("error: passwords did not match", file=sys.stderr)
        sys.exit(1)

    salt = secrets.token_bytes(16)
    password_hash = hash_password(password, salt)

    con = sqlite3.connect(DB_PATH)
    try:
        ensure_settings_table(con)
        # The login tries the admin password first, so letting the two be the
        # same would silently hand every member an admin session.
        if matches(con, password, "admin_" if not args.admin else ""):
            other = "admin" if not args.admin else "shared"
            print(
                f"error: that is already the {other} password -- the two must differ",
                file=sys.stderr,
            )
            sys.exit(1)
        set_setting(con, f"{prefix}password_salt", salt.hex())
        set_setting(con, f"{prefix}password_hash", password_hash)
        if not args.admin:
            set_setting(con, "session_secret", secrets.token_hex(32))
        con.commit()
    finally:
        con.close()

    if args.admin:
        print("Admin password updated. Member logins are unaffected; "
              "existing admin sessions last until they expire (30 days).")
    else:
        print("Password updated. Any devices that were previously remembered are now logged out.")


if __name__ == "__main__":
    main()
