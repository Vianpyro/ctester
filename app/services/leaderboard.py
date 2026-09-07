"""The optional leaderboard: a cohort, a rank, and nobody named last.

THREE RULES HOLD THIS SCREEN UP, and all three are here rather than in the
router, so `test_ctester.py` can exercise them by direct call:

  * OPT-IN. An account that did not check the box produces no row at all --
    `state.leaderboard_rows()` filters in SQL, so there is nothing to forget
    to hide afterward.
  * A MINIMUM COHORT. Under `policy.minimum_cohort()`, a ranking of three
    people names all three, including the last. Below it, only one's own line
    comes back, with no table at all.
  * NOBODY IS NAMED LAST. Only the top `policy.visible_rows()` are listed;
    everyone else gets their own row and the step to the one above it. That is
    the difference between "here is where you stand" and "here is who is
    behind you".

NO `sub` EVER CROSSES THE BOUNDARY, exactly as in `services/forum.py`: the
`account` column is used to spot the caller's own row and is dropped here.

COUNTED ON FIRST SOLVES. `xp_transaction` already carries one row per
`solved:<exercise>`, made unique by its primary key: redoing a lab adds
nothing, and the daily XP cap -- which zeroes an amount, never a row -- has no
effect on this count.
"""

import policy

# THE WEEK, and it is a rolling seven days rather than a calendar week. A
# calendar week resets at midnight Sunday, which is when nobody is working and
# everybody's number drops to zero at once; a rolling window is always
# comparable to the one before it.
WINDOW_DAYS = 7

# What the instructor's own account does in a student ranking: nothing.
# Moderators are excluded so a teacher testing an exercise cannot appear at
# the top of a group they are not part of.


def _ranked(rows):
    """Rows ordered by weekly first solves, ties broken by lifetime then alias.

    DETERMINISTIC, because a rank that reshuffles between two refreshes reads
    as a bug. The alias breaks the last tie: it is the only stable value here
    that is not the `sub`.
    """
    return sorted(rows, key=lambda r: (-r["recent"], -r["lifetime"],
                                       r["alias"] or ""))


def _row(entry, rank, mine):
    """One public row. THE `account` KEY IS DROPPED HERE, and only here."""
    return {"rank": rank, "alias": entry["alias"] or "Participant",
            "solved": entry["recent"], "mine": mine}


def leaderboard_view(rows, sub, group_number):
    """The payload of GET /leaderboard, or a refusal shaped like a payload.

    `rows` is what `state.leaderboard_rows()` returned; `sub` the caller.

    A CALLER WHO OPTED OUT IS NOT AN ERROR: they get `participating: false`
    and no table. The screen then offers the checkbox rather than an empty
    ranking, which is the state most accounts are in and must not look broken.
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
        return payload
    mine_row = ordered[mine]
    payload["me"] = _row(mine_row, mine + 1, True)
    payload["division"] = policy.division(mine_row["lifetime"])
    payload["lifetime"] = mine_row["lifetime"]
    # UNDER THE THRESHOLD, NO TABLE. Not a truncated one: five rows of which
    # three are strangers in a cohort of four is the same disclosure.
    if cohort < minimum:
        return payload
    visible = policy.visible_rows()
    payload["rows"] = [_row(r, i + 1, r["account"] == sub)
                       for i, r in enumerate(ordered[:visible])]
    # ONE'S OWN ROW IS ALWAYS THERE, appended when it falls past the visible
    # top. The rows in between are NOT sent: they are other people's ranks,
    # and knowing one is 14th does not require knowing who is 13th.
    if mine >= visible:
        payload["rows"].append(payload["me"])
    # THE STEP UP, NEVER THE STEP DOWN. "Two more and you pass 3rd" is
    # actionable; "one behind you is catching up" is pressure with nothing to
    # do about it.
    if mine > 0:
        ahead = ordered[mine - 1]
        payload["gap"] = {"rank": mine, "solved": ahead["recent"] - mine_row["recent"]}
    return payload


def divisions_view(rows):
    """[{id, title, threshold, accounts}] -- how the cohort spreads over divisions.

    Counts only, never who: a division is a band on a page, and the band is
    the whole information.
    """
    counts = {}
    for row in rows or ():
        key = policy.division(row["lifetime"])["id"]
        counts[key] = counts.get(key, 0) + 1
    return [dict(d, accounts=counts.get(d["id"], 0)) for d in policy.divisions()]


def draw_alias(taken, seed):
    """A drawn alias not already in use, or None if the vocabulary ran out.

    DRAWN FROM A CLOSED LIST (`policy.possible_aliases()`), so nothing a
    student typed can ever land in a leaderboard -- which is what makes the
    ranking safe to show without moderating it.

    `seed` is any integer; the caller passes randomness. Deterministic given
    the seed, so a test can pin it: at 324 combinations for thirty accounts,
    walking forward from the seed finds a free one on the first try nearly
    always, and always finds one if there is one.
    """
    pool = policy.possible_aliases()
    taken = set(taken or ())
    start = int(seed) % len(pool)
    for step in range(len(pool)):
        candidate = pool[(start + step) % len(pool)]
        if candidate not in taken:
            return candidate
    return None
