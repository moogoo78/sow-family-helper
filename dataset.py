"""Reads north7.sqlite and builds the member bundle served by the API.

Stdlib only. Queries the DB fresh on every call -- the dataset is tiny
(low hundreds of rows) so there's no need for caching or a build step.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "north7.sqlite")

# Verified against actual role_log text (role names like "蟻導"/"蜂團長"/
# "育成"/"鹿攝影"/"鷹指導" only ever appear under one group_name each) --
# NOT the "A/B/C/D/E = 蟻蜂鹿育鷹" order schema.private.md suggests, which is wrong.
GROUP_LABELS = {"A": "蟻", "B": "蜂", "C": "育成", "D": "鹿", "E": "鷹"}
GROUP_ORDER = ["A", "B", "D", "C", "E"]  # display order: 蟻蜂鹿育鷹

# role_log rows for a person's grade within their group (e.g. "蟻二", "鷹三").
# Everything else at th_year level is a staff/committee role (團長/副團長/
# 導引員/攝影/育成 committee seats, etc.) -- there's no fixed vocabulary for
# those (100+ distinct historical strings), but the kid-grade set is closed.
KID_ROLES = {
    f"{group}{grade}"
    for group in ("蟻", "蜂", "鹿", "鷹")
    for grade in ("一", "二", "三")
}

# 育成 (group C) has no grade levels like the other groups -- a plain "育成"
# role just means an active member, not staff, and so does "育成"+a group
# character ("育成蟻" is a pre-school child who comes along to 蟻團, one step
# below 小小蟻). Only the more specific roles (育導/會長/副會長/組長/... --
# 50+ historical strings) count as 工作人員.
NON_STAFF_ROLES_BY_GROUP = {
    "C": {"育成"} | {f"育成{group}" for group in ("蟻", "蜂", "鹿", "鷹")}
}


def group_for_role(group_name, role):
    """The group a role_log row really belongs to.

    育成 members who help out a kids' group are recorded under that group
    (e.g. "育成蟻"/"育副會-蟻" under A) even though they are 育成 people --
    and the same kind of role is filed under C for other groups
    (育副會-鹿/育副會-鷹). Any 育-prefixed role counts as 育成 (C).
    """
    if role and role.startswith("育"):
        return "C"
    return group_name

# Optional contact columns that may be added to `person` later (see schema.private.md).
# Auto-detected via PRAGMA table_info so no code change is needed after
# `ALTER TABLE person ADD COLUMN ...` -- just restart the server.
# `email` is deliberately absent: the column is populated in the DB but the
# address book does not show it, so it stays out of the API payload too.
CONTACT_COLUMNS = {
    "mobile": "tel",
    "phone": "tel",
    "line_id": None,
    "address": None,
}


# A stored 地址 may be a full street address; the app only ever shows the
# 縣市＋區 part of it, so the rest is dropped here rather than in the
# frontend -- it never reaches the browser at all.
STREET_MARKERS = "路街巷弄號段樓室F"
DISTRICT_SUFFIXES = "區鄉鎮"


def mask_address(value):
    """新北市三重區仁愛街298之2號4樓 -> 新北市三重區.

    Values that carry no street part (新北市三重區, 基隆八斗子, 竹北市 --
    most of them, since the roster's 地區 column lands here) are already
    coarse enough and are left alone.
    """
    text = (value or "").strip()
    if not text or not any(c in text for c in STREET_MARKERS):
        return text or None
    for i, ch in enumerate(text):
        if ch in DISTRICT_SUFFIXES:
            return text[: i + 1]
    # No 區/鄉/鎮 (e.g. 新竹縣竹北市...): cut at the last 縣/市 before the
    # street part instead.
    head = text[: min(i for i, c in enumerate(text) if c in STREET_MARKERS)]
    cut = max(head.rfind("市"), head.rfind("縣"))
    return text[: cut + 1] if cut >= 0 else head or text


def get_group_label(con):
    """The 團 this instance serves (e.g. 北七團), from the settings table.

    Nothing in the data identifies the group as a whole -- role_log only
    knows the 分團 within it -- so it is configured, not derived. Absent
    means "unset"; the frontend just leaves it out.
    """
    row = con.execute("SELECT value FROM settings WHERE key = 'group_label'").fetchone()
    return (row[0] or "").strip() or None if row else None


def group_list():
    return [{"code": code, "label": GROUP_LABELS[code]} for code in GROUP_ORDER]


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def detect_contact_columns(con):
    cols = {row["name"] for row in con.execute("PRAGMA table_info(person)")}
    return [c for c in CONTACT_COLUMNS if c in cols]


def relation_label(sex, is_child):
    if is_child:
        return {"M": "兒子", "F": "女兒"}.get(sex, "小孩")
    return {"M": "爸爸", "F": "媽媽"}.get(sex, "家長")


def get_current_th_year(con):
    """Latest known th_year across the DB -- advances on its own as new
    family/role_log rows are added, no code change needed each year."""
    rows = [
        con.execute("SELECT MAX(join_th_year) FROM family").fetchone()[0],
        con.execute("SELECT MAX(th_year) FROM role_log").fetchone()[0],
    ]
    return max(y for y in rows if y is not None)


def family_active_in_year(fam_row, year):
    join_year = fam_row["join_th_year"]
    leave_year = fam_row["leave_th_year"]
    if join_year is not None and join_year > year:
        return False
    if leave_year is not None and leave_year < year:
        return False
    return True


def build_members(con):
    current_th_year = get_current_th_year(con)
    contact_cols = detect_contact_columns(con)
    contact_select = "".join(f", p.{c}" for c in contact_cols)

    people = {
        row["id"]: dict(row)
        for row in con.execute(
            f"""
            SELECT p.id, p.name, p.nickname, p.old_nickname, p.sex, p.is_child,
                   p.family_name, p.sow_number{contact_select}
            FROM person p
            """
        )
    }

    # family_id -> family row
    families = {row["id"]: dict(row) for row in con.execute("SELECT id, name, join_th_year, leave_th_year FROM family")}

    # person_id -> list of family_person rows (each carries its family)
    memberships = {}
    for row in con.execute("SELECT family_id, person_id FROM family_person"):
        memberships.setdefault(row["person_id"], []).append(families[row["family_id"]])

    roles = {}
    for row in con.execute(
        "SELECT th_year, group_name, person_id, role, role_remark, remark FROM role_log ORDER BY th_year DESC"
    ):
        group_name = group_for_role(row["group_name"], row["role"])
        roles.setdefault(row["person_id"], []).append(
            {
                "th_year": row["th_year"],
                "group_label": GROUP_LABELS.get(group_name, group_name or None),
                "role": row["role"],
                "role_remark": row["role_remark"] or None,
                "remark": row["remark"] or None,
            }
        )

    trainings = {}
    for row in con.execute("SELECT name, person_id FROM training_log"):
        trainings.setdefault(row["person_id"], []).append({"name": row["name"]})

    # 入團年: the first year the person appears in role_log at all. A "無"
    # row still means they were on that year's roster, just without a post,
    # so those count here even though 職務紀錄 hides them. The last year is
    # what the training lists show next to someone who has left.
    first_th_year = {}
    last_th_year = {}
    for row in con.execute(
        "SELECT person_id, MIN(th_year) AS first, MAX(th_year) AS last FROM role_log GROUP BY person_id"
    ):
        first_th_year[row["person_id"]] = row["first"]
        last_th_year[row["person_id"]] = row["last"]

    current_group_by_person = {}
    for row in con.execute(
        "SELECT person_id, group_name, role FROM role_log WHERE th_year = ?", (current_th_year,)
    ):
        if not row["group_name"]:
            continue
        group_name = group_for_role(row["group_name"], row["role"])
        non_staff = row["role"] in KID_ROLES or row["role"] in NON_STAFF_ROLES_BY_GROUP.get(
            group_name, ()
        )
        current_group_by_person[row["person_id"]] = {
            "code": group_name,
            "label": GROUP_LABELS.get(group_name, group_name),
            "role": row["role"],
            "category": "小孩" if non_staff else "工作人員",
        }

    def pick_current(fam_rows):
        no_leave = [f for f in fam_rows if f["leave_th_year"] is None]
        if no_leave:
            return max(no_leave, key=lambda f: (f["join_th_year"] or 0))
        return max(fam_rows, key=lambda f: (f["join_th_year"] or 0))

    bundle = []
    for pid, p in people.items():
        fam_rows = memberships.get(pid, [])
        # Active this year = the family is active, or the person holds a role
        # this year. The second half covers people with no family row of their
        # own -- e.g. a child split out of a same-nickname merge, whose only
        # record is their role_log entry.
        active = (any(family_active_in_year(f, current_th_year) for f in fam_rows)
                  or pid in current_group_by_person)
        # People who have left are carried too, but only when they have a
        # 培訓紀錄: over half of everyone who has been on a 基訓 has since left,
        # and a 基訓 roster missing half its names is not much of a roster.
        # `active` keeps them out of everything else (搜尋、分團、新家庭).
        if not active and pid not in trainings:
            continue
        current = pick_current(fam_rows) if fam_rows else None
        past = [f for f in fam_rows if current and f["id"] != current["id"]]

        family = None
        family_members = []
        if current is not None:
            family = {
                "id": current["id"],
                "name": current["name"],
                "join_th_year": current["join_th_year"],
            }
            for row in con.execute(
                "SELECT person_id FROM family_person WHERE family_id = ? AND person_id != ?",
                (current["id"], pid),
            ):
                other = people.get(row["person_id"])
                if other is None:
                    continue
                family_members.append(
                    {
                        "id": other["id"],
                        "name": other["name"],
                        "nickname": other["nickname"],
                        "relation": relation_label(other["sex"], other["is_child"]),
                    }
                )
        elif p["family_name"]:
            family = {"id": None, "name": p["family_name"]}

        entry = {
            "id": pid,
            "name": p["name"],
            "nickname": p["nickname"],
            "old_nickname": p["old_nickname"] or None,
            "sex": p["sex"] or None,
            "is_child": bool(p["is_child"]),
            "family": family,
            "family_members": family_members,
            "family_history": [
                {"name": f["name"], "join_th_year": f["join_th_year"], "leave_th_year": f["leave_th_year"]}
                for f in past
            ],
            "roles": roles.get(pid, []),
            "trainings": trainings.get(pid, []),
            "current_group": current_group_by_person.get(pid),
            "first_th_year": first_th_year.get(pid),
            "last_th_year": last_th_year.get(pid),
            "active": active,
            # Shown only after the reader taps 顯示荒野編號 on the profile.
            "sow_number": p["sow_number"] or None,
        }
        for c in contact_cols:
            entry[c] = mask_address(p[c]) if c == "address" else (p[c] or None)
        bundle.append(entry)

    bundle.sort(key=lambda e: (e["nickname"] or ""))
    return bundle
