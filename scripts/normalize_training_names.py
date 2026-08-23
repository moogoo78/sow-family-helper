#!/usr/bin/env python3
"""Canonicalise 訓練紀錄 course names.

The same course is written several ways depending on who typed it:
蜂十七基 / 蜂17基 / 北蜂17基, 育三基 / 育3基, 三珠六 / 山豬6. This rewrites
every training_log row to one spelling and drops the duplicates that fall
out.

Rules:
  * 三珠 / 三株 -> 山豬 (the DB already spells it 山豬7, 山豬8, 山豬13)
  * Chinese numerals -> Arabic: 十七 -> 17, 二十 -> 20, 十 -> 10
  * a 基訓 with no 區域 prefix is a 北 one: 蜂17基 -> 北蜂17基
  * 期別 written before the 團: 北23蜂基 -> 北蜂23基
  * spaces dropped (29 進) and one-off names mapped (雙珠（25進） -> 25進)

`canonical_training()` is also what scripts/import_n7_10.py uses, so a
re-import cannot bring the old spellings back.

Dry run by default; pass --apply to write.

    python3 scripts/normalize_training_names.py [--apply]
"""
import collections
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "north7.sqlite")

# Misspellings of a course name. Applied before the numerals, so the 三 in
# 三珠 is never mistaken for a number.
NAME_ALIASES = {"三珠": "山豬", "三株": "山豬"}

# Whole names that are only recognisable one at a time.
FULL_NAME_ALIASES = {"雙珠（25進）": "25進"}

# 北23蜂基 is 北蜂23基 written with the 期別 before the 團.
SWAPPED_BASE = re.compile(r"^([" + "北桃宜花竹" + r"])(\d+)([蟻蜂鹿鷹育])基$")

# 基訓 is named 區域＋團＋期別: 北蟻15基, 桃蜂2基, 宜育1基. A name with no
# region is a 北 course -- 北 is simply left off when everyone means 北.
# Only 基訓 gets the prefix: 進訓 (31進), 山豬 and 解說員訓 take no region.
REGIONS = "北桃宜花竹"
BASE_COURSE = re.compile(r"^[蟻蜂鹿鷹育]\d+基$")
DEFAULT_REGION = "北"

DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}
NUMERAL_RUN = re.compile("[" + "".join(DIGITS) + "十]+")


def cn_to_int(run):
    """一 -> 1, 十 -> 10, 十六 -> 16, 二十 -> 20, 二十一 -> 21."""
    if "十" not in run:
        return sum(DIGITS[c] for c in run) if len(run) == 1 else None
    head, _, tail = run.partition("十")
    if any(c == "十" for c in tail):
        return None
    tens = DIGITS.get(head, 1) if head else 1
    ones = DIGITS.get(tail, 0) if tail else 0
    if head and head not in DIGITS:
        return None
    return tens * 10 + ones


def canonical_training(name):
    out = re.sub(r"\s+", "", name or "")  # 「29 進」
    out = FULL_NAME_ALIASES.get(out, out)
    for wrong, right in NAME_ALIASES.items():
        out = out.replace(wrong, right)

    def sub(m):
        value = cn_to_int(m.group(0))
        return m.group(0) if value is None else str(value)

    out = NUMERAL_RUN.sub(sub, out)

    out = SWAPPED_BASE.sub(r"\1\3\2基", out)
    if BASE_COURSE.match(out):
        out = DEFAULT_REGION + out
    return out


def main():
    apply = "--apply" in sys.argv[1:]
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT rowid, name, person_id FROM training_log")]

    renames = [(r, canonical_training(r["name"])) for r in rows]
    renames = [(r, new) for r, new in renames if new != r["name"]]

    # After renaming, a person can end up holding the same course twice.
    seen = collections.defaultdict(set)
    for r in rows:
        seen[r["person_id"]].add(canonical_training(r["name"]))
    drop = []
    kept = collections.defaultdict(set)
    for r in rows:
        canon = canonical_training(r["name"])
        if canon in kept[r["person_id"]]:
            drop.append((r, canon))
        else:
            kept[r["person_id"]].add(canon)

    by_change = collections.Counter((r["name"], new) for r, new in renames)
    print(f"{len(renames)} rows to rename ({len(by_change)} distinct names), {len(drop)} duplicate rows to delete\n")
    for (old, new), n in sorted(by_change.items()):
        print(f"   {old} -> {new}   x{n}")
    for r, canon in drop:
        who = con.execute("SELECT name, nickname FROM person WHERE id = ?", (r["person_id"],)).fetchone()
        print(f"   delete duplicate: {who['nickname']}({who['name']}) 「{r['name']}」 == 「{canon}」")

    if not apply:
        print("\ndry run -- pass --apply to write")
        return

    cur = con.cursor()
    for r, _ in drop:
        cur.execute("DELETE FROM training_log WHERE rowid = ?", (r["rowid"],))
    dropped = {r["rowid"] for r, _ in drop}
    for r, new in renames:
        if r["rowid"] not in dropped:
            cur.execute("UPDATE training_log SET name = ? WHERE rowid = ?", (new, r["rowid"]))
    con.commit()
    print(f"\napplied: {len(renames) - len(dropped & {r['rowid'] for r, _ in renames})} renamed, {len(drop)} deleted")


if __name__ == "__main__":
    main()
