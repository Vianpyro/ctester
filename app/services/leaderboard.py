import policy

WINDOW_DAYS = 7


def _ranked(rows):
    return sorted(rows, key=lambda r: (-r["recent"], -r["lifetime"],
                                       r["alias"] or ""))


def _row(entry, rank, mine):
    return {"rank": rank, "alias": entry["alias"] or "Participant",
            "solved": entry["recent"], "mine": mine}


def leaderboard_view(rows, sub, group_number, reader=False):
    """Top rows plus the caller's own row, and nothing below the minimum cohort.

    Only upward gaps are reported, so nobody is ever shown as last.
    """
    rows = list(rows or ())
    ordered = _ranked(rows)
    mine = next((i for i, r in enumerate(ordered) if r["account"] == sub), None)
    cohort = len(ordered)
    minimum = policy.minimum_cohort()
    payload = {
        "group": group_number,
        "window_days": WINDOW_DAYS,
        "cohort": cohort,
        "minimum": minimum,
        "participating": mine is not None,
        "rows": [],
        "me": None,
        "gap": None,
    }
    if mine is None:
        if reader and cohort >= minimum:
            payload["rows"] = [_row(r, i + 1, False)
                               for i, r in enumerate(ordered[:policy.visible_rows()])]
        return payload
    mine_row = ordered[mine]
    payload["me"] = _row(mine_row, mine + 1, True)
    payload["division"] = policy.division(mine_row["lifetime"])
    payload["lifetime"] = mine_row["lifetime"]
    if cohort < minimum:
        return payload
    visible = policy.visible_rows()
    payload["rows"] = [_row(r, i + 1, r["account"] == sub)
                       for i, r in enumerate(ordered[:visible])]
    if mine >= visible:
        payload["rows"].append(payload["me"])
    if mine > 0:
        ahead = ordered[mine - 1]
        payload["gap"] = {"rank": mine, "solved": ahead["recent"] - mine_row["recent"]}
    return payload


def divisions_view(rows):
    counts = {}
    for row in rows or ():
        key = policy.division(row["lifetime"])["id"]
        counts[key] = counts.get(key, 0) + 1
    return [dict(d, accounts=counts.get(d["id"], 0)) for d in policy.divisions()]


def draw_alias(taken, seed):
    pool = policy.possible_aliases()
    taken = set(taken or ())
    start = int(seed) % len(pool)
    for step in range(len(pool)):
        candidate = pool[(start + step) % len(pool)]
        if candidate not in taken:
            return candidate
    return None
