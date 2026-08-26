#!/usr/bin/env python3
"""Fill blank `姓名`/`電子郵件` on `person` from a roster CSV.

Usage:
    python3 scripts/backfill_from_roster.py source/csv/n7-11.csv 11
    python3 scripts/backfill_from_roster.py source/csv/n7-11.csv 11 --apply

Only ever writes into a column that is currently empty -- an existing name
or email is never overwritten, so the script is safe to re-run and safe to
run against an older roster. Dry run unless --apply, which takes a
`north7.sqlite.bak-pre-backfill` copy first.

Matching is deliberately timid, because 自然名 repeat across people (see
groups.private.md) and a wrong match writes one family's contact details
onto another's:

  * A person who already has a 姓名 is matched on that, and only when the
    roster holds exactly one row with it.
  * A person with no 姓名 at all is matched on 自然名, and only when that
    自然名 is unique on both sides -- one roster row, and one `person` row
    that appears in role_log for the roster's year. Counting only that
    year's people is what separates a current member from someone who used
    the same 自然名 years ago and has long since left.
  * A 姓名 that some other `person` row already carries is left alone: that
    is a duplicate-person problem (merge_duplicate_people.py), not a
    missing-field one.

Everything skipped is listed with the reason, so the leftovers can be
chased by hand.
"""
import argparse
import csv
import os
import shutil
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "north7.sqlite")
BACKUP_SUFFIX = ".bak-pre-backfill"

NAME_COLUMN = "姓名"
NICKNAME_COLUMN = "自然名"
EMAIL_COLUMN = "電子郵件"
# person column -> roster column
FIELDS = {"name": NAME_COLUMN, "email": EMAIL_COLUMN}


def read_roster(path):
    """Roster rows, keyed by 姓名 and by 自然名.

    The older exports put a BOM-only line (and sometimes a title line)
    above the real header, so the header row is found rather than assumed.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header_index = next((i for i, row in enumerate(rows) if NICKNAME_COLUMN in row), None)
    if header_index is None:
        raise SystemExit(f"error: no '{NICKNAME_COLUMN}' column found in {path}")
    header = rows[header_index]
    missing = [c for c in (NAME_COLUMN, EMAIL_COLUMN) if c not in header]
    if missing:
        raise SystemExit(f"error: {path} has no {'/'.join(missing)} column")
    entries = [
        {key: (row[header.index(key)] or "").strip() for key in (NAME_COLUMN, NICKNAME_COLUMN, EMAIL_COLUMN)}
        for row in rows[header_index + 1:]
        if len(row) >= len(header)
    ]
    by_name, by_nickname = {}, {}
    for entry in entries:
        if entry[NAME_COLUMN]:
            by_name.setdefault(entry[NAME_COLUMN], []).append(entry)
        if entry[NICKNAME_COLUMN]:
            by_nickname.setdefault(entry[NICKNAME_COLUMN], []).append(entry)
    return by_name, by_nickname


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_path", help="roster export, e.g. source/csv/n7-11.csv")
    parser.add_argument("th_year", type=int, help="the 第N年 that roster is for")
    parser.add_argument("--apply", action="store_true", help="write to the DB (default: dry run)")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"error: database not found at {DB_PATH}")
    by_name, by_nickname = read_roster(args.csv_path)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        people = [dict(r) for r in con.execute("SELECT id, name, nickname, email FROM person")]
        in_year = {r[0] for r in con.execute(
            "SELECT DISTINCT person_id FROM role_log WHERE th_year = ?", (args.th_year,))}

        taken_names = {}
        nickname_counts = {}
        for p in people:
            if (p["name"] or "").strip():
                taken_names.setdefault(p["name"].strip(), []).append(p["id"])
            if (p["nickname"] or "").strip() and p["id"] in in_year:
                nickname_counts[p["nickname"].strip()] = nickname_counts.get(p["nickname"].strip(), 0) + 1

        updates, skips = [], []
        for p in people:
            blanks = [col for col in FIELDS if not (p[col] or "").strip()]
            if not blanks:
                continue
            name = (p["name"] or "").strip()
            nickname = (p["nickname"] or "").strip()
            label = f"id={p['id']} {nickname or '?'} {name}".rstrip()

            if name:
                matches = by_name.get(name, [])
                how = NAME_COLUMN
            elif p["id"] not in in_year:
                continue  # not on this year's roster; nothing to match against
            elif nickname_counts.get(nickname, 0) > 1:
                skips.append(f"{label}: 自然名 belongs to {nickname_counts[nickname]} people on 第{args.th_year}年's roster")
                continue
            else:
                matches = by_nickname.get(nickname, [])
                how = NICKNAME_COLUMN
            if not matches:
                continue  # simply not on this roster
            if len(matches) > 1:
                skips.append(f"{label}: {len(matches)} roster rows share that {how}")
                continue
            row = matches[0]

            fill = {}
            for col in blanks:
                value = row[FIELDS[col]]
                if not value:
                    continue
                if col == "name" and value in taken_names:
                    skips.append(f"{label}: 姓名 {value} already on person id={taken_names[value][0]} (duplicate?)")
                    continue
                fill[col] = value
            if fill:
                updates.append((p["id"], label, how, fill))

        for pid, label, how, fill in updates:
            shown = ", ".join(f"{col}={value}" for col, value in fill.items())
            print(f"  {label}  <-  {shown}   (matched on {how})")
        for line in skips:
            print(f"  SKIP {line}")
        filled = {col: sum(1 for _, _, _, f in updates if col in f) for col in FIELDS}
        print(f"\n{len(updates)} people to update ("
              + ", ".join(f"{col}: {n}" for col, n in filled.items())
              + f"), {len(skips)} skipped")

        if not args.apply:
            print("dry run -- re-run with --apply to write")
            return
        if not updates:
            print("nothing to do")
            return
        backup = DB_PATH + BACKUP_SUFFIX
        shutil.copyfile(DB_PATH, backup)
        print(f"backup: {backup}")
        for pid, _, _, fill in updates:
            assignments = ", ".join(f"{col} = ?" for col in fill)
            con.execute(f"UPDATE person SET {assignments} WHERE id = ?", (*fill.values(), pid))
        con.commit()
        print(f"updated {len(updates)} people")
    finally:
        con.close()


if __name__ == "__main__":
    main()
