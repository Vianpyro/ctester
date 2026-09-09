#!/usr/bin/env python3
"""ctester -- persistence for students who sign in. See schema.sql.

THIS WHOLE MODULE IS OPTIONAL, and that is what gives it its shape. Without
CTESTER_DB_DSN, `enabled()` is false and the API behaves exactly as before: the
anonymous path never needs this layer. A database that is down must not stop a
student from testing their code the evening before a deadline -- so nothing here
raises. Functions return None or False, and the caller says so honestly on screen.

`account` is ALWAYS the opaque `sub` validated by `security.current_user()`, never
a value taken from a request body: that is the one thing keeping a student out
of another student's state.

Table and column names stay as the schema declares them (see schema.sql); the
Python around them does not.
"""

import json
import os
import threading
from datetime import timezone

try:
    import psycopg          # the only optional import
except ImportError:         # image built without it: persistence is simply absent
    psycopg = None

DSN = os.environ.get("CTESTER_DB_DSN", "")

# ponytail: ONE connection behind a global lock, not a pool. The most frequent
# write is a draft every 1.5 s per signed-in student; at 27 of them the queue
# behind this lock is permanently empty. Move to psycopg_pool the day it is not.
_lock = threading.Lock()
_conn = None

STATUSES = ("attempted", "solved")
# The page's only two themes. Same list as the CHECK in `schema.sql` and the
# `<head>` script: three places, one rule to keep in sync.
THEMES = ("light", "dark")
# La borne du bloc-notes de la Console, en octets. ÉCRITE ICI ET PAS PRISE DANS
# `config` : ce module n'importe pas `config`, exprès -- il est éprouvé par
# appel direct contre un vrai Postgres, sans le reste de l'application. Elle
# vaut `config.MAX_CODE` et le CHECK de `scratch_draft` dans schema.sql ; les
# trois valeurs sont les mêmes 64 Ko, et c'est le CHECK qui a le dernier mot
# pour tout chemin d'écriture.
SCRATCH_MAX = 65536


def enabled():
    """True when persistence is both configured and usable."""
    return bool(DSN) and psycopg is not None


def _close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


def _query(sql, params, read=False):
    """One statement, under the lock. Rows, [] for a write, or None on failure.

    None means "the database did not answer", never "there is nothing": that is
    what lets the caller tell a fault apart from an empty dashboard. Confusing
    the two would make a student believe everything was lost.

    The broad `except Exception` is deliberate. What psycopg can raise -- dead
    connection, Postgres restarted, DNS, encoding -- has exactly one correct
    response here: degrade. Letting it propagate would return 500 on a page whose
    "Tester" button was still working perfectly well.
    """
    global _conn
    if not enabled():
        return None
    with _lock:
        for last_try in (False, True):
            try:
                if _conn is None or _conn.closed:
                    _conn = psycopg.connect(DSN, autocommit=True, connect_timeout=5)
                with _conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall() if read else []
            except Exception:
                # A stale connection is the common case (Postgres restarted
                # overnight): drop it and retry ONCE. Two failures in a row are
                # an outage, and an outage gets reported.
                _close()
                if last_try:
                    return None
    return None


def _sources(rows):
    """The `sources` column of a single row, decoded. None if nothing usable.

    The contents come from the database, but a student put them there: check
    again that it is an object before handing it back to a browser.
    """
    if not rows:
        return None
    try:
        value = json.loads(rows[0][0])
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    return {str(k): str(v) for k, v in value.items()}


def read_resume(user, exercise_id):
    """What goes back into the editor: the draft, else the last submission.

    One round trip for both tables. A student who submitted and then closed the
    tab must find what they sent, not a blank template.
    """
    rows = _query(
        "SELECT sources FROM ("
        "  SELECT sources, 0 AS rank FROM exercise_draft"
        "   WHERE account = %s AND exercise_id = %s"
        "  UNION ALL"
        "  SELECT sources, 1 AS rank FROM exercise_state"
        "   WHERE account = %s AND exercise_id = %s"
        ") AS both_tables ORDER BY rank LIMIT 1",
        (user, exercise_id, user, exercise_id), read=True)
    return _sources(rows)


def write_draft(user, exercise_id, sources):
    return _query(
        "INSERT INTO exercise_draft (account, exercise_id, sources, updated_at)"
        " VALUES (%s, %s, %s, now())"
        " ON CONFLICT (account, exercise_id)"
        " DO UPDATE SET sources = EXCLUDED.sources, updated_at = now()",
        (user, exercise_id, json.dumps(sources)),
    ) is not None


def write_state(user, exercise_id, status, sources):
    """Write the state, WITHOUT EVER LETTING IT GO BACKWARDS.

    The CASE exists for a precise reason: after solving an exercise, people keep
    poking at it. Without it, the first failed experiment would turn the green
    dot back to amber, and the dashboard would say the opposite of what happened.
    """
    if status not in STATUSES:
        return False
    return _query(
        "INSERT INTO exercise_state (account, exercise_id, status, sources, updated_at)"
        " VALUES (%s, %s, %s, %s, now())"
        " ON CONFLICT (account, exercise_id) DO UPDATE SET"
        "   status = CASE WHEN exercise_state.status = 'solved' THEN 'solved'"
        "                 ELSE EXCLUDED.status END,"
        "   sources = EXCLUDED.sources, updated_at = now()",
        (user, exercise_id, status, json.dumps(sources)),
    ) is not None


def read_states(user):
    """[{exercise_id, status}] for the list view, or None if the database is mute."""
    rows = _query(
        "SELECT exercise_id, status FROM exercise_state WHERE account = %s",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercise_id": exercise, "status": status} for exercise, status in rows]


def write_practice_attempt(user, job_id, exercise_id, result):
    """Persist one completed practice attempt, once per worker job.

    The API, not JavaScript, reads `result.json` and calls this function.  A
    verdict is practice evidence only; it must never be reused as verified
    mastery while the self-service judge remains intentionally non-secure.
    """
    status = str(result.get("status", "error"))[:64]
    total = result.get("total", 0)
    passed = result.get("passed", 0)
    if not isinstance(total, int) or not isinstance(passed, int):
        total, passed = 0, 0
    total, passed = max(total, 0), max(min(passed, total), 0)
    return _query(
        "INSERT INTO practice_attempt "
        "(job_id, account, exercise_id, status, total, passed) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (job_id) DO NOTHING",
        (job_id, user, exercise_id, status, total, passed),
    ) is not None


def read_practice_summary(user):
    """Per-exercise practice counts; derived mastery is intentionally absent."""
    rows = _query(
        "SELECT exercise_id, count(*), "
        "count(*) FILTER (WHERE total > 0 AND passed = total) "
        "FROM practice_attempt WHERE account = %s "
        "GROUP BY exercise_id",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercise_id": ex, "attempts": attempts, "successes": solved}
            for ex, attempts, solved in rows]


def read_practice_days(user, days):
    """[{date, attempts}] for the last `days` days. The calendar of design 1b.

    A `GROUP BY` OVER AN EXISTING TABLE, NOT A NEW ONE. Every attempt is
    already dated in `practice_attempt`; a second table would be a second
    place the truth could diverge, for a strip of squares.

    THE DAY ONLY, never the time: this is the same rule as `read_progress`,
    and "practiced on the 14th" is all the strip draws. At what hour someone
    worked has no business traveling (privacy.md).

    NO STREAK IS COMPUTED HERE OR ANYWHERE ELSE, and that is the point of the
    calendar replacing one: a gap takes nothing away, so there is no counter
    to break and none to defend.
    """
    rows = _query(
        "SELECT date_trunc('day', completed_at)::date AS day, count(*)"
        "  FROM practice_attempt"
        " WHERE account = %s AND completed_at >= now() - make_interval(days => %s)"
        " GROUP BY day ORDER BY day",
        (user, max(int(days), 1)), read=True)
    if rows is None:
        return None
    return [{"date": _day(day), "attempts": int(count)} for day, count in rows]


def grant_first_solve(user, exercise_id, event_id, amount, reason,
                      policy, payload, daily_cap):
    """Record ONE first solve and its XP, in a single statement.

    Returns the amount actually granted (0 if today's cap is already reached),
    or None if the fact already existed -- or the database did not answer. Both
    are handled the same way by the caller: there is nothing new to celebrate.

    IDEMPOTENCE LIVES IN THE KEY, not in a prior read. `event_id` names the fact
    ("reussite:tp2-ex3"), its primary key makes it unique per student, and the
    `ON CONFLICT` means two simultaneous polls of the same verdict, a restarted
    worker or a replayed HTTP request only grant once. A read followed by a
    write would have left the race open.

    The cap is computed WITHIN the same statement: reading it separately would
    make it wrong as soon as two solves happen concurrently.
    """
    rows = _query(
        "WITH remaining AS ("
        "  SELECT GREATEST(%(cap)s - COALESCE(sum(amount), 0), 0) AS balance"
        "    FROM xp_transaction"
        "   WHERE account = %(user)s"
        "     AND granted_at >= date_trunc('day', now())"
        "), new_event AS ("
        "  INSERT INTO progress_event"
        "    (account, event_id, type, exercise_id, policy, payload)"
        "  VALUES (%(user)s, %(event)s, 'ExerciceReussi', %(ex)s,"
        "          %(policy)s, %(payload)s)"
        "  ON CONFLICT (account, event_id) DO NOTHING"
        "  RETURNING event_id"
        ") "
        "INSERT INTO xp_transaction"
        "  (account, event_id, amount, reason, exercise_id, policy) "
        "SELECT %(user)s, new_event.event_id,"
        "       LEAST(%(amount)s, remaining.balance), %(reason)s, %(ex)s, %(policy)s "
        "  FROM new_event, remaining "
        "RETURNING amount",
        {"user": user, "event": event_id, "ex": exercise_id,
         "policy": policy, "payload": json.dumps(payload),
         "amount": max(int(amount), 0), "reason": reason,
         "cap": max(int(daily_cap), 0)},
        read=True)
    return int(rows[0][0]) if rows else None


def record_event(user, event_id, kind, exercise_id, policy, payload):
    """A progression fact WITHOUT XP: a journal row, nothing more.

    This is what a verification (phase 2) writes. No CTE, no cap, no read:
    `progress_event` is already the append-only journal, and a piece of mastery
    evidence is nothing more than a dated fact. No new table, so no GRANT to
    add and nothing more to remove in `forget()` -- the INSERT is already
    granted there.

    IDEMPOTENCE LIVES IN THE KEY, as for `grant_first_solve`: two polls of the
    same verdict carry the same `event_id` and write only once. A NEW attempt
    carries a different job id, so it leaves its own row: retries stay
    historical.

    Returns the id written, or None -- already known, or the database is mute.
    As with `grant_first_solve`, both are handled the same way by the caller:
    there is no new fact, so nothing to recompute. That is what avoids
    replaying three reads on every poll of `/r/<id>`.
    """
    rows = _query(
        "INSERT INTO progress_event"
        "  (account, event_id, type, exercise_id, policy, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (account, event_id) DO NOTHING "
        "RETURNING event_id",
        (user, event_id, kind, exercise_id, policy, json.dumps(payload)),
        read=True)
    return rows[0][0] if rows else None


def read_events(user, kind, limit=500):
    """Facts of one type, newest first. None if the database is mute.

    [{"exercise_id": str|None, "payload": dict}] -- the date is used to order
    and is not returned: mastery is read as bands, not a timestamped history,
    and the exact time of an attempt has no business traveling (privacy.md).

    BOUNDED like `read_progress`: this is a display read. `event_id` breaks
    ties between two facts in the same second, without which "the latest
    attempt" would depend on the order the planner feels like returning.
    """
    rows = _query(
        "SELECT exercise_id, payload FROM progress_event"
        " WHERE account = %s AND type = %s"
        " ORDER BY created_at DESC, event_id DESC LIMIT %s",
        (user, kind, max(int(limit), 1)), read=True)
    if rows is None:
        return None
    facts = []
    for exercise_id, payload in rows:
        try:
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except ValueError:
            payload = None
        facts.append({"exercise_id": exercise_id,
                      "payload": payload if isinstance(payload, dict) else {}})
    return facts


def unlock(user, achievement_ids, event_id, policy):
    """Add the missing achievements. Replaying the same list creates nothing more."""
    if not achievement_ids:
        return True
    return _query(
        "INSERT INTO achievement_unlocked"
        "  (account, achievement_id, event_id, policy) "
        "SELECT %s, which, %s, %s FROM unnest(%s::text[]) AS which "
        "ON CONFLICT (account, achievement_id) DO NOTHING",
        (user, event_id, policy, list(achievement_ids)),
    ) is not None


def read_progress(user):
    """A student's progression facts, or None if the database is mute.

    {"xp": int, "achievements": [{id, unlocked_at, policy}],
     "transactions": [{exercise_id, amount, reason, granted_at}]}

    The balance, level and skills are NOT here: those are projections,
    `services/progression.py` recomputes them from these facts and the public
    catalog. What is stored is what happened, not what is displayed.

    Dates come out at DAY granularity only. That is what the UI shows, and the
    exact time of a submission has no business traveling.
    """
    total = _query(
        "SELECT COALESCE(sum(amount), 0) FROM xp_transaction"
        " WHERE account = %s", (user,), read=True)
    unlocked = _query(
        "SELECT achievement_id, unlocked_at, policy FROM achievement_unlocked"
        " WHERE account = %s ORDER BY unlocked_at, achievement_id",
        (user,), read=True)
    # BOUNDED, and that is the contract: this list is the display/export of
    # grants, not an unlimited journal. One solve per published exercise fits
    # well under it.
    grants = _query(
        "SELECT exercise_id, amount, reason, granted_at FROM xp_transaction"
        " WHERE account = %s ORDER BY granted_at DESC, event_id LIMIT 200",
        (user,), read=True)
    if total is None or unlocked is None or grants is None:
        return None
    return {
        "xp": int(total[0][0]) if total else 0,
        "achievements": [{"id": row[0], "unlocked_at": _day(row[1]),
                    "policy": row[2]} for row in unlocked],
        "transactions": [{"exercise_id": row[0], "amount": int(row[1]),
                          "reason": row[2], "granted_at": _day(row[3])}
                         for row in grants],
    }


def read_unlock_rates():
    """({achievement_id: holders}, cohort) -- the OBSERVED rate of each unlock.

    THE RARITY IS MEASURED, NEVER DECREED. A card that says "18 %" must mean
    "18 % of the people who practised here have it", or the number is
    decoration -- and a decorative rarity is the exact mechanic
    student-motivations.md refuses.

    THE COHORT IS "ACCOUNTS THAT HAVE SUBMITTED SOMETHING", not "accounts that
    exist": an account that never practised cannot hold a card, and counting it
    would drag every rate down for a reason no student could read.

    The caller must refuse to display a rate under `policy.cohorte_minimale()`:
    a percentage over four people describes those four people.
    """
    holders = _query(
        "SELECT achievement_id, count(DISTINCT account)"
        "  FROM achievement_unlocked GROUP BY achievement_id", (), read=True)
    cohort = _query(
        "SELECT count(DISTINCT account) FROM practice_attempt", (), read=True)
    if holders is None or cohort is None:
        return None
    return ({row[0]: int(row[1]) for row in holders},
            int(cohort[0][0]) if cohort else 0)


# --- The leaderboard (design 1c) ---------------------------------------------
# COUNTED ON FIRST SOLVES, WHICH ALREADY EXIST. `xp_transaction` carries one
# row per `solved:<exercise>` and its primary key is what makes that "first"
# -- so the aggregate is a `count(*)`, redoing a lab adds nothing, and the
# daily XP cap (which zeroes `amount`, never the row) has no effect here. That
# is why we count ROWS and not `sum(amount)`.
#
# ponytail: computed on read, no materialized view. It is one indexed scan
# over a few hundred rows for a cohort of thirty; a refreshed projection would
# be a second place the truth can diverge, plus a schedule to keep. The
# threshold is a p95 of `/leaderboard` above a second, which `load_test.py`
# reports -- same rule as `/progres`.


def leaderboard_rows(group_number, days, staff=()):
    """[{account, alias, group_number, recent, lifetime}] for OPTED-IN accounts.

    OPT-IN IS THE `WHERE`, NOT A FILTER APPLIED AFTER: an account that did not
    check the box produces no row at all, so there is nothing to forget to
    hide downstream. `group_number` None means the whole course.

    AND THE INSTRUCTOR IS EXCLUDED BY THE SAME `WHERE`, for the same reason.
    Their XP is test XP -- they wrote the exercises -- so a ranking carrying
    them would be unfair to every student in it, and fairness must not depend
    on remembering not to tick a box. `staff` comes from the caller
    (`config.FORUM_MODERATORS`) rather than from an import here: this module
    stays the SQL layer, and the moderator list is configuration.

    An empty `staff` excludes nobody -- `x <> ALL(ARRAY[]::text[])` is true --
    so a deployment without moderators behaves exactly as before.

    An opted-in account with nothing this week IS returned, at zero. Dropping
    it would make the cohort size depend on the week, and the cohort size is
    what the privacy threshold reads.

    THE `account` COMES BACK because ranking needs to spot the caller's own
    row; `services/leaderboard.py` is what drops it, exactly as `forum_vue()`
    does for a thread. No `sub` crosses HTTP.
    """
    rows = _query(
        "WITH profile AS ("
        "  SELECT DISTINCT ON (account) account, alias, group_number,"
        "         leaderboard_opt_in"
        "    FROM forum_profile"
        "   ORDER BY account, created_at DESC, profile_id DESC"
        ") "
        "SELECT p.account, p.alias, p.group_number,"
        "       count(x.event_id) FILTER ("
        "           WHERE x.granted_at >= now() - make_interval(days => %(days)s)),"
        "       count(x.event_id) "
        "  FROM profile p"
        "  LEFT JOIN xp_transaction x ON x.account = p.account"
        " WHERE p.leaderboard_opt_in"
        "   AND p.account <> ALL(%(staff)s::text[])"
        "   AND (%(group)s::smallint IS NULL OR p.group_number = %(group)s) "
        " GROUP BY p.account, p.alias, p.group_number",
        {"days": max(int(days), 1),
         "staff": sorted(staff or ()),
         "group": None if group_number is None else int(group_number)},
        read=True)
    if rows is None:
        return None
    return [{"account": row[0], "alias": row[1],
             "group_number": None if row[2] is None else int(row[2]),
             "recent": int(row[3]), "lifetime": int(row[4])} for row in rows]


def _day(value):
    """The date of a timestamp, in ISO. The value as a string if it is not one."""
    try:
        return value.date().isoformat()
    except AttributeError:
        return str(value)[:10]


# --- Display preferences ----------------------------------------------------
# The theme, and nothing else for now. It lives here rather than only in
# `localStorage` because local storage is PER DEVICE: a student working at the
# lab then at home started over from the default theme every time. The
# account already carries the draft from one machine to another; the display
# setting takes the same path.
#
# LOCAL STORAGE STAYS, and it is not redundant: it is what the `<head>` script
# reads before the first paint, long before an HTTP response could arrive.
# What is here is the truth of the ACCOUNT; what is there is what avoids the
# dark-to-light flash on every visit.


def read_theme(user):
    """This account's theme: "light", "dark", or "" if nothing was chosen.

    None -- and nothing else -- means "the database did not answer". The empty
    string means "no choice recorded", and the caller then keeps the device's
    own theme: confusing the two would drop someone's setting every time
    Postgres is mute or new.
    """
    rows = _query("SELECT theme FROM display_preference WHERE account = %s",
                  (user,), read=True)
    if rows is None:
        return None
    return rows[0][0] if rows else ""


def write_theme(user, theme):
    """The chosen theme, overwritten in place. False if the value or the DB refuses.

    ALONG WITH THE DRAFT AND THE STATE, THE ONLY WRITE IN THIS FILE THAT
    REPLACES INSTEAD OF APPENDING. Someone's old theme is not a fact to read
    back, and a journal would grow on every click of a button made to be
    clicked.

    The allow-list is repeated here AND in the schema's CHECK: this one saves
    a round trip, that one holds for every write path.
    """
    if theme not in THEMES:
        return False
    return _query(
        "INSERT INTO display_preference (account, theme, updated_at)"
        " VALUES (%s, %s, now())"
        " ON CONFLICT (account)"
        " DO UPDATE SET theme = EXCLUDED.theme, updated_at = now()",
        (user, theme),
    ) is not None


# --- La Console --------------------------------------------------------------


def read_scratch(user):
    """Le bloc-notes de ce compte : son code, ou "" si rien n'a été enregistré.

    `None` -- ET RIEN D'AUTRE -- veut dire « la base n'a pas répondu ». La
    chaîne vide veut dire « aucun bloc-notes », et l'appelant garde alors ce
    qu'il a en local. Confondre les deux effacerait le travail de quelqu'un à
    la première panne, exactement comme pour le thème.
    """
    rows = _query("SELECT code FROM scratch_draft WHERE account = %s",
                  (user,), read=True)
    if rows is None:
        return None
    return rows[0][0] if rows else ""


def write_scratch(user, code):
    """Le bloc-notes, ÉCRASÉ EN PLACE. False si la base refuse.

    Une ligne par compte, `ON CONFLICT DO UPDATE` : le bloc-notes précédent
    n'est pas un fait à relire, et un journal grossirait à chaque frappe.

    La borne est reposée ici ET dans le CHECK du schéma : celle-ci évite un
    aller-retour, celle-là tient pour tout chemin d'écriture.
    """
    if not isinstance(code, str) or len(code.encode("utf-8")) > SCRATCH_MAX:
        return False
    return _query(
        "INSERT INTO scratch_draft (account, code, updated_at)"
        " VALUES (%s, %s, now())"
        " ON CONFLICT (account)"
        " DO UPDATE SET code = EXCLUDED.code, updated_at = now()",
        (user, code),
    ) is not None


# --- Peer help forum (MVP) ---------------------------------------------------
# ONE thread per published exercise, for signed-in accounts only. Nothing here
# touches progression: no XP, no achievement, no exercise status.
#
# `account` IS ALWAYS the `sub` validated by `security.current_user()`, as
# everywhere else in this file -- never a value taken from a request body.
# That is what prevents posting, deleting or reporting in someone else's name.
#
# THIS MODULE RETURNS THE AUTHOR'S `sub` to the caller, and it is
# `forum_vue()` (`services/forum.py`) that translates it into "Vous" /
# "Participant" / "Enseignant" without ever letting it out. Translating it
# here would require knowing the moderator list in the SQL layer, where it has
# no business being.


def forum_fil(exercise_id, limit, reader=None):
    """An exercise's thread, oldest to newest. None if the database is mute.

    Hidden messages ARE returned, with their flag: it is `forum_vue()` that
    strips them for an ordinary student and keeps them for a moderator,
    because it is the one that knows who is calling. PRIVATE messages are
    returned the same way, with their visibility, and `forum_vue()` drops the
    ones the reader has no business seeing.

    THE LIMIT BOUNDS ROOTS, NOT MESSAGES, and that is what an archive of ten
    thousand messages forces. Bounding messages would eventually cut a thread
    between a question and its answer: the reply would come back alone, its
    root gone, unreadable for the very person it was written for. Here a
    question and ALL its replies enter and leave together. No outer LIMIT, on
    purpose -- truncating a root's replies is the exact failure this CTE
    exists to prevent, and one root with thousands of replies is a moderation
    problem, not a query one.

    FOUR THINGS TRAVEL WITH A MESSAGE, all derived, none stored on the row:
    whether a moderator retained it as the answer (the latest
    `retain`/`unretain` in the journal), how many accounts voted it up, how
    many voted it down, and what THIS reader voted. Deriving beats counter
    columns -- no number to drift, no UPDATE grant to widen.

    `reader` only answers "what did I vote"; it never changes which rows come
    back.
    """
    rows = _query(
        "WITH racines AS ("
        "   SELECT message_id FROM forum_message"
        "    WHERE exercise_id = %(ex)s AND reply_to IS NULL"
        "    ORDER BY created_at DESC, message_id DESC"
        "    LIMIT %(limit)s) "
        "SELECT m.message_id, m.account, m.text, m.hidden, m.created_at,"
        "       m.step, m.blocked_kind, m.visibility, m.reply_to,"
        "       COALESCE(r.action = 'retain', false),"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = 1),"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = -1),"
        "       COALESCE((SELECT h.value FROM forum_helpful h"
        "                  WHERE h.message_id = m.message_id"
        "                    AND h.account = %(who)s), 0)"
        "  FROM forum_message m"
        "  LEFT JOIN LATERAL ("
        "       SELECT action FROM forum_moderation"
        "        WHERE message_id = m.message_id"
        "          AND action IN ('retain', 'unretain')"
        "        ORDER BY created_at DESC, action_id DESC LIMIT 1) r ON true"
        " WHERE m.exercise_id = %(ex)s"
        "   AND (m.message_id IN (SELECT message_id FROM racines)"
        "        OR m.reply_to IN (SELECT message_id FROM racines))"
        " ORDER BY m.created_at, m.message_id",
        {"ex": exercise_id, "limit": max(int(limit), 0), "who": reader or ""},
        read=True)
    return _messages(rows)


def _messages(rows):
    """The row shape every thread read shares. None stays None."""
    if rows is None:
        return None
    return [{"id": row[0], "account": row[1], "text": row[2],
             "hidden": bool(row[3]), "created_at": _minute(row[4]),
             "step": row[5], "blocked_kind": row[6], "visibility": row[7],
             "reply_to": row[8], "retained": bool(row[9]),
             "upvotes": int(row[10]), "downvotes": int(row[11]),
             "my_vote": int(row[12])} for row in rows]


def forum_conversation(message_id, reader=None):
    """(thread key, [messages]) -- the root of `message_id` and all its replies.

    THE PERMALINK, and it exists because a search result is worth nothing
    without somewhere to land: a message three thousand posts back is inside
    no thread window, so `forum_fil` would never return it.

    IT RENDERS THROUGH THE SAME `forum_vue()`/`can_see()` as a thread -- same
    columns, same order, same identity translation. A second rendering path
    would be a second place for a visibility rule to drift.

    (None, None) when the database is mute, (None, []) when there is no such
    message -- the caller answers the same 404 either way.
    """
    rows = _query(
        "WITH cible AS ("
        "   SELECT COALESCE(reply_to, message_id) AS racine, exercise_id"
        "     FROM forum_message WHERE message_id = %(id)s) "
        "SELECT m.message_id, m.account, m.text, m.hidden, m.created_at,"
        "       m.step, m.blocked_kind, m.visibility, m.reply_to,"
        "       COALESCE(r.action = 'retain', false),"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = 1),"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = -1),"
        "       COALESCE((SELECT h.value FROM forum_helpful h"
        "                  WHERE h.message_id = m.message_id"
        "                    AND h.account = %(who)s), 0),"
        "       c.exercise_id"
        "  FROM forum_message m"
        "  JOIN cible c ON m.message_id = c.racine OR m.reply_to = c.racine"
        "  LEFT JOIN LATERAL ("
        "       SELECT action FROM forum_moderation"
        "        WHERE message_id = m.message_id"
        "          AND action IN ('retain', 'unretain')"
        "        ORDER BY created_at DESC, action_id DESC LIMIT 1) r ON true"
        " ORDER BY m.created_at, m.message_id",
        {"id": message_id, "who": reader or ""}, read=True)
    if rows is None:
        return None, None
    if not rows:
        return None, []
    return rows[0][13], _messages(rows)


def forum_search(terms, reader, limit):
    """[{id, exercise_id, extrait, created_at, upvotes, replies}]. None if mute.

    ONE QUERY FOR TWO USES: typed into the compose box it proposes duplicates,
    typed into the search bar it reaches the archive. Two queries would be two
    places for the clause below to drift, and the one that drifted would be
    the one that stopped protecting.

    THE PRIVACY RULE IS THE `WHERE`, NOT A FILTER AFTER: a private forum
    question can never surface as "someone already asked this" to anyone but
    its author. Everything in a chat is public, so the clause is always true
    there -- it stays anyway, because this table also holds the forum's
    private questions, and a clause dropped because "it cannot happen here"
    is the one that fires later.

    A MODERATOR GETS NO EXCEPTION. They read threads already; widening this
    `WHERE` for them would be one more branch to get wrong, for nothing.

    `left(text, 240)` RATHER THAN `ts_headline`: the page shows the excerpt
    through `textContent`, and a highlight is not worth a formatting-option
    string. ponytail: ts_headline the day the excerpt is worth it.
    """
    terms = str(terms or "").strip()
    if not terms:
        return []
    rows = _query(
        "SELECT m.message_id, m.exercise_id, left(m.text, 240), m.created_at,"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = 1),"
        "       (SELECT count(*) FROM forum_message rp"
        "         WHERE rp.reply_to = COALESCE(m.reply_to, m.message_id))"
        "  FROM forum_message m, websearch_to_tsquery('french', %(q)s) AS q(tsq)"
        " WHERE m.search @@ q.tsq"
        "   AND m.hidden = false"
        "   AND (m.visibility = 'thread' OR m.account = %(me)s)"
        " ORDER BY ts_rank(m.search, q.tsq) DESC, m.created_at DESC"
        " LIMIT %(limit)s",
        {"q": terms, "me": reader or "", "limit": max(int(limit), 1)},
        read=True)
    if rows is None:
        return None
    return [{"id": r[0], "exercise_id": r[1], "extrait": r[2],
             "created_at": _minute(r[3]), "upvotes": int(r[4]),
             "replies": int(r[5])} for r in rows]


def forum_top(hours, limit):
    """The most upvoted ROOTS of the last `hours`. Moderator-only, see the router.

    ROOTS ONLY: "what is being asked" is a question, and ranking replies in
    the same table would put answers above the questions they answer.
    """
    rows = _query(
        "SELECT m.message_id, m.exercise_id, m.text, m.created_at, m.visibility,"
        "       m.step, m.blocked_kind,"
        "       (SELECT count(*) FROM forum_helpful h"
        "         WHERE h.message_id = m.message_id AND h.value = 1) AS votes,"
        "       (SELECT count(*) FROM forum_message rp"
        "         WHERE rp.reply_to = m.message_id)"
        "  FROM forum_message m"
        " WHERE m.reply_to IS NULL AND m.hidden = false"
        "   AND m.created_at >= now() - make_interval(hours => %(hours)s)"
        " ORDER BY votes DESC, m.created_at DESC"
        " LIMIT %(limit)s",
        {"hours": max(int(hours), 1), "limit": max(int(limit), 1)}, read=True)
    if rows is None:
        return None
    return [{"id": r[0], "exercise_id": r[1], "text": r[2],
             "created_at": _minute(r[3]), "visibility": r[4], "step": r[5],
             "blocked_kind": r[6], "upvotes": int(r[7]), "replies": int(r[8])}
            for r in rows]


def forum_publier(message_id, exercise_id, user, text, step=None,
                  blocked_kind=None, visibility="thread"):
    """Add a message. The id is generated by the caller (uuid4).

    `step`, `blocked_kind` and `visibility` come from CLOSED lists validated in
    `services/forum.py`; the CHECK on `visibility` is the same defense as
    everywhere else -- it holds for a psql session opened at midnight too.
    """
    return _query(
        "INSERT INTO forum_message"
        "  (message_id, exercise_id, account, text, step, blocked_kind, visibility)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (message_id, exercise_id, user, text, step, blocked_kind, visibility),
    ) is not None


def forum_repondre(message_id, exercise_id, user, text, target):
    """Reply to `target`. [] if the target is unknown or in another thread.

    THE FLATTENING IS `COALESCE(t.reply_to, t.message_id)`, AND IT IS THE
    WHOLE TRICK: replying to a reply stores the ROOT's id, so a thread stays
    flat to draw, `can_see` needs one dictionary lookup rather than a walk,
    and there is no depth to bound. One expression, in SQL, so it cannot be
    forgotten by a caller.

    THE `WHERE` IS THE RULE, as everywhere in this file: the root must exist
    AND live in the same thread. A made-up id inserts nothing -- there is no
    prior read to race, and no `if` in a router to get wrong. This is
    INTEGRITY, not privacy: a chat is public, so a reply is visible exactly
    like anything else, and it carries no visibility of its own.

    Separate from `forum_publier` rather than a parameter on it, because the
    two return different things: a root is a plain INSERT that only fails when
    the database is mute, a reply can be legitimately REFUSED. Folding them
    would mean one function whose False means two different HTTP answers.
    """
    return _query(
        "INSERT INTO forum_message"
        "  (message_id, exercise_id, account, text, visibility, reply_to)"
        " SELECT %(id)s, %(ex)s, %(who)s, %(text)s, 'thread',"
        "        COALESCE(t.reply_to, t.message_id)"
        "   FROM forum_message t"
        "  WHERE t.message_id = %(target)s AND t.exercise_id = %(ex)s"
        " RETURNING message_id",
        {"id": message_id, "ex": exercise_id, "who": user, "text": text,
         "target": target}, read=True)


def forum_open_to_group(message_id, user):
    """Open one's OWN private message to one's group. The only transition.

    [] when the message is not theirs, is not private, or does not exist --
    the same answer for all three, as everywhere else in this file. None when
    the database did not answer.

    THE `WHERE` IS THE WHOLE RULE, and it is one-way: `visibility = 'private'`
    means group -> private cannot be expressed, so nobody can hide what others
    have already read. That is the immutability social.md sets out, held by
    Postgres rather than by whoever writes the next query.
    """
    return _query(
        "UPDATE forum_message SET visibility = 'group'"
        " WHERE message_id = %s AND account = %s AND visibility = 'private'"
        " RETURNING message_id", (message_id, user), read=True)


def forum_voter(message_id, user, value):
    """Vote on someone ELSE's message. [] if refused, None if the base is mute.

    FOUR PROTECTIONS IN ONE STATEMENT, and that is the point of writing it as
    an `INSERT ... SELECT` rather than a read then a write:

      * the SELECT forbids a made-up id;
      * `m.account <> %(who)s` forbids voting on one's own message;
      * `m.reply_to IS NOT NULL` FORBIDS -1 ON A QUESTION -- a question cannot
        be buried by a vote, which is the whole promise of a place built for
        people who are afraid to ask. It is held by the statement, not by the
        page choosing not to draw a button;
      * the primary key holds "once per account", and `DO UPDATE` turns the
        second vote into a change of mind rather than a duplicate.

    `DO UPDATE` IS WHY THE SCHEMA GRANTS `UPDATE (value)` -- a column grant,
    so `message_id` and `account` stay unwritable and nobody's vote can be
    moved onto another message.

    IT STILL GRANTS NOTHING. No XP, no achievement, no card: a message written
    to be upvoted is a message written for the counter. On a question the +1
    reads as "moi aussi", which is what tells the instructor what is being
    asked -- without counting anybody.
    """
    value = 1 if int(value) >= 0 else -1
    return _query(
        "INSERT INTO forum_helpful (message_id, account, value)"
        " SELECT m.message_id, %(who)s, %(value)s FROM forum_message m"
        "  WHERE m.message_id = %(id)s AND m.account <> %(who)s"
        "    AND (%(value)s = 1 OR m.reply_to IS NOT NULL)"
        " ON CONFLICT (message_id, account) DO UPDATE SET value = EXCLUDED.value"
        " RETURNING forum_helpful.message_id",
        {"who": user, "id": message_id, "value": value}, read=True)


def forum_devoter(message_id, user):
    """Take one's own vote back. [] if there was none -- the same 404 as the rest."""
    return _query(
        "DELETE FROM forum_helpful WHERE message_id = %s AND account = %s"
        " RETURNING message_id", (message_id, user), read=True)


def forum_supprimer(message_id, user):
    """Delete THEIR OWN message. [] if it is not theirs (or already gone).

    The `account = %s` clause IS the access control: there is no prior read to
    make lie, and deleting a neighbor's message would require being the
    neighbor.
    """
    return _query(
        "DELETE FROM forum_message WHERE message_id = %s AND account = %s"
        " RETURNING message_id", (message_id, user), read=True)


def forum_fil_de(message_id):
    """The thread key a message lives in, or "" -- for ringing the room.

    A separate one-row read rather than a wider `RETURNING` on the delete and
    the moderation statements: those two are the file's most carefully written
    SQL (an access-control `WHERE`, a two-write CTE), and widening them to
    carry a value only a notification needs would put a bell in the way of a
    rule. Both actions are rare; this costs a primary-key lookup.
    """
    rows = _query("SELECT exercise_id FROM forum_message WHERE message_id = %s",
                  (message_id,), read=True)
    return rows[0][0] if rows else ""


def forum_signaler(message_id, user):
    """Report a message. [] if it does not exist OR is already reported by them.

    TWO PROTECTIONS IN ONE STATEMENT: the `SELECT ... FROM forum_message`
    forbids reporting a made-up id -- so no orphan row carrying a `sub` for
    nothing -- and the primary key forbids the duplicate. A read followed by a
    write would have left both races open.
    """
    return _query(
        "INSERT INTO forum_report (message_id, account)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, account) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_signalements(limit):
    """Reported messages, most-reported first. The moderator's view.

    THE MINIMUM USEFUL FOR MODERATION, and nothing more: the text, the
    exercise, the date, the state and the COUNT of reports. Never who
    reported, never who wrote, never submitted code, a detailed verdict or
    progression data.
    """
    rows = _query(
        "SELECT m.message_id, m.exercise_id, m.text, m.hidden, m.created_at,"
        "       count(*) AS how_many"
        "  FROM forum_message m"
        "  JOIN forum_report s ON s.message_id = m.message_id"
        " GROUP BY m.message_id, m.exercise_id, m.text, m.hidden, m.created_at"
        " ORDER BY how_many DESC, m.created_at LIMIT %s",
        (max(int(limit), 0),), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "exercise_id": row[1], "text": row[2],
             "hidden": bool(row[3]), "created_at": _minute(row[4]),
             "report_count": int(row[5])} for row in rows]


def forum_moderer(action_id, message_id, moderator, action):
    """Hide or restore a message AND journal the action, in ONE statement.

    [] when the message does not exist; None when the database did not answer.

    THE JOURNAL IS APPEND-ONLY and the current state is a column: the two
    writes must therefore fall together. Split into two autocommit `_query`
    calls, a connection dropped in the middle would leave a message hidden
    that nothing explains -- or the reverse, a journal that lies.
    """
    if action in ("retain", "unretain"):
        # NO COLUMN IS TOUCHED, and that is the point: the journal's latest
        # row IS the retained answer (see `forum_fil`). A `retained` column
        # would need one more UPDATE grant on a table whose whole design is
        # that a message cannot be rewritten.
        return _query(
            "INSERT INTO forum_moderation (action_id, message_id, account, action)"
            " SELECT %s, m.message_id, %s, %s FROM forum_message m"
            "  WHERE m.message_id = %s RETURNING message_id",
            (action_id, moderator, action, message_id), read=True)
    if action not in ("hide", "restore"):
        return []
    return _query(
        "WITH acted AS ("
        "  INSERT INTO forum_moderation"
        "    (action_id, message_id, account, action)"
        "  SELECT %(aid)s, m.message_id, %(who)s, %(which)s"
        "    FROM forum_message m WHERE m.message_id = %(id)s"
        "  RETURNING message_id"
        ") UPDATE forum_message SET hidden = %(hidden)s"
        "  WHERE message_id = (SELECT message_id FROM acted)"
        "  RETURNING message_id",
        {"aid": action_id, "id": message_id, "who": moderator,
         "which": action, "hidden": action == "hide"}, read=True)


# --- The chosen name and group number ---------------------------------------
# APPEND-ONLY, THE LAST ROW IS AUTHORITATIVE. No UPDATE, so no UPDATE GRANT:
# ownership is held by Postgres, not by the discipline of whoever writes the
# next query. `DISTINCT ON` reads it in one pass over the index
# (account, created_at DESC).

_PROFILE_COLUMNS = ("display_name", "group_number", "display_name_public",
                    "group_number_public", "alias", "plate_frame",
                    "badges_public", "leaderboard_opt_in")

# What an account with no profile row reads as. NOT `{}`: every caller reads
# these keys, and a missing one would be an outage's None in disguise.
EMPTY_PROFILE = {"display_name": None, "group_number": None,
               "display_name_public": False, "group_number_public": False,
               "alias": None, "plate_frame": None,
               "badges_public": False, "leaderboard_opt_in": False}


def _profil(row):
    return {"display_name": row[1], "group_number": None if row[2] is None else int(row[2]),
            "display_name_public": bool(row[3]), "group_number_public": bool(row[4]),
            "alias": row[5], "plate_frame": row[6],
            "badges_public": bool(row[7]), "leaderboard_opt_in": bool(row[8])}


def forum_profils(users):
    """{sub: profile} for these accounts. {} for those who never set one.

    ONE QUERY FOR AN ENTIRE THREAD: a thread of twenty messages must not cost
    twenty round trips behind the global lock. `= ANY(%s)` takes the list as
    it is -- same shape as progression's `unnest`.
    """
    people = sorted({u for u in users if u})
    if not people:
        return {}
    rows = _query(
        "SELECT DISTINCT ON (account) account, " + ", ".join(_PROFILE_COLUMNS) +
        "  FROM forum_profile WHERE account = ANY(%s)"
        " ORDER BY account, created_at DESC, profile_id DESC",
        (people,), read=True)
    if rows is None:
        return None
    return {row[0]: _profil(row) for row in rows}


def forum_profil(user):
    """This account's profile, {} if it never set one. None if the database is mute."""
    profiles = forum_profils([user])
    if profiles is None:
        return None
    return profiles.get(user, dict(EMPTY_PROFILE))


def forum_profil_ecrire(profile_id, user, display_name, group_number, display_name_public,
                        group_number_public, set_by_moderator=False, alias=None,
                        plate_frame=None, badges_public=False,
                        leaderboard_opt_in=False):
    """Add a profile row. Older ones stay, and that is intentional.

    EVERY FIELD IS WRITTEN EVERY TIME, because the latest row is the whole
    profile: a partial write would silently reset the fields it left out. The
    caller therefore reads the current profile first and passes it back --
    which is also what makes "clear a reported name" able to keep the group
    number.
    """
    return _query(
        "INSERT INTO forum_profile (profile_id, account, display_name, group_number,"
        "                          display_name_public, group_number_public,"
        "                          set_by_moderator, alias, plate_frame,"
        "                          badges_public, leaderboard_opt_in)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (profile_id, user, display_name, group_number, bool(display_name_public),
         bool(group_number_public), bool(set_by_moderator), alias, plate_frame,
         bool(badges_public), bool(leaderboard_opt_in)),
    ) is not None


def forum_taken_aliases():
    """Every alias currently in use. `alias_libre()` draws around this set.

    THE WHOLE COLUMN, not a per-candidate lookup: at thirty accounts this is
    one small scan, where a "is this one free?" query per attempt would be one
    round trip per attempt behind the global lock.
    """
    rows = _query(
        "SELECT DISTINCT ON (account) alias FROM forum_profile"
        " ORDER BY account, created_at DESC, profile_id DESC", (), read=True)
    if rows is None:
        return None
    return {row[0] for row in rows if row[0]}


def forum_nom_signaler(message_id, user):
    """Report the NAME of a message's author. Same two protections as
    `forum_signaler`: the SELECT forbids a made-up id, the primary key
    forbids the duplicate."""
    return _query(
        "INSERT INTO forum_reported_name (message_id, account)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, account) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_noms_signales(limit):
    """Reported NAMES, for a moderator. The name, the group, the message as a
    handle -- never the `sub`: `routers/forum.py` only copies what is shown.

    The same account can be reported from several of their messages; one row
    per carrying message is returned, most-reported first, with the author's
    current profile.
    """
    rows = _query(
        "SELECT m.message_id, m.account, p.display_name, p.group_number, m.created_at,"
        "       count(*) AS how_many"
        "  FROM forum_reported_name s"
        "  JOIN forum_message m ON m.message_id = s.message_id"
        "  LEFT JOIN LATERAL ("
        "       SELECT display_name, group_number FROM forum_profile"
        "        WHERE account = m.account"
        "        ORDER BY created_at DESC, profile_id DESC LIMIT 1) p ON true"
        " GROUP BY m.message_id, m.account, p.display_name, p.group_number, m.created_at"
        " ORDER BY how_many DESC, m.created_at LIMIT %s",
        (max(int(limit), 0),), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "account": row[1], "display_name": row[2],
             "group_number": None if row[3] is None else int(row[3]),
             "created_at": _minute(row[4]), "report_count": int(row[5])}
            for row in rows]


def forum_help_rows(limit, hours):
    """"Who needs help", aggregated. The instructor's view (design 1h).

    COUNTS AND STEPS, NEVER PEOPLE. One row per (exercise, step): how many
    accounts are stuck there, how many of those opened their question to their
    group, and how long the oldest has been waiting. No `sub`, no name, no
    text, no code -- a count is what says where to walk in the room, and
    nothing more is needed for that.

    PRIVATE QUESTIONS ARE COUNTED, NOT REVEALED. They stay unreadable (only
    their author can open them to a group); this row says a number exists, so
    six people stuck on the same conversion read as one explanation at the
    board rather than six unanswered messages.

    Only messages carrying a `step` are aggregated: an ordinary thread post is
    a discussion, not a call for help, and mixing them would bury the signal.
    """
    rows = _query(
        "SELECT exercise_id, step, blocked_kind,"
        "       count(DISTINCT account),"
        "       count(*) FILTER (WHERE visibility = 'group'),"
        "       min(created_at)"
        "  FROM forum_message"
        " WHERE step IS NOT NULL AND NOT hidden"
        "   AND created_at >= now() - make_interval(hours => %s)"
        " GROUP BY exercise_id, step, blocked_kind"
        " ORDER BY count(DISTINCT account) DESC, min(created_at) LIMIT %s",
        (max(int(hours), 1), max(int(limit), 0)), read=True)
    if rows is None:
        return None
    return [{"exercise_id": row[0], "step": row[1], "blocked_kind": row[2],
             "people": int(row[3]), "opened": int(row[4]),
             "since": _minute(row[5])} for row in rows]


def forum_auteur(message_id):
    """The `sub` of a message's author, or None. Reserved for name moderation:
    the page only ever has a message as a handle, never an account id."""
    rows = _query("SELECT account FROM forum_message WHERE message_id = %s",
                  (message_id,), read=True)
    if not rows:
        return None
    return rows[0][0]


def _minute(value):
    """A timestamp at MINUTE precision, in explicit UTC. The value as a string otherwise.

    At the minute, not the day, unlike progression: a thread is read in order,
    and "today" on ten messages helps no one. At the minute, not the second:
    nobody needs to time who answered first.

    WITH THE TIMEZONE, AND THAT IS THE WHOLE POINT. The column is TIMESTAMPTZ,
    so the stored instant was always correct; it was the string sent that said
    nothing about it, and the page displayed it as if it were local -- a
    message written in Montreal came out four hours in the future. The "Z" is
    enough for the page to translate it back into the reader's timezone.
    Nothing to migrate.
    """
    try:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except AttributeError:
        return str(value)[:16]


# --------------------------------------------------------------------------
# Team assignments. See the block comment in `schema.sql`: a GROUP is the
# section a student declares, a TEAM is who they hand in with, and only the
# second one is authoritative here.
#
# THE APPLICATION ROLE CANNOT WRITE THE ROSTER. It has `SELECT` on `team` and
# `SELECT, DELETE` on `team_member` -- no INSERT, no UPDATE (see the GRANT in
# VHome). There is therefore no code path, distracted or otherwise, by which a
# request can put an account on a team: `import_teams.py` does it through the
# admin DSN, and the DELETE exists only so "Supprimer mes données" can keep
# its promise.


# --- Rejoindre une équipe -------------------------------------------------------
# LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE DE COURS, et un étudiant prend
# une place libre dans celle qu'il veut. C'est exactement le geste qu'il fait
# déjà sur Moodle -- et il DOIT correspondre : « Équipe 7 » ici est « Équipe 7 »
# là-bas, sinon l'enseignant corrige deux listes qui divergent.
#
# LE LISTAGE DE L'ENSEIGNANT ÉTAIT INÉCRIVABLE (CTester ne lui montre jamais un
# `sub`), et un code d'invitation avec confirmation unanime a été essayé puis
# retiré : il ne correspondait à rien de ce que les étudiants font déjà, et il
# n'était pas nécessaire.
#
# CE QUI TIENT À LA PLACE, ET C'EST UNE DATE QUE LE CONTENU PORTE DÉJÀ : on ne
# rejoint et on ne quitte que TANT QUE LE DEVOIR EST FERMÉ. Pendant la
# formation il n'y a rien à voler -- le devoir n'ouvre pas -- et une fois
# ouvert, plus personne ne bouge. Cette condition-là est dans le SERVICE
# (`teams.joinable`), parce qu'elle se lit dans le catalogue publié, pas en
# base : `access()` reste la seule lecture d'une release.


def team_join(user, assignment_id, team_id, group_number, number, label,
              taille_max):
    """Prendre une place. L'ÉQUIPE EST CRÉÉE SI ELLE N'EXISTE PAS ENCORE.

    Une équipe est une ligne le jour où quelqu'un y entre, pas le jour où le
    devoir est publié : peupler douze équipes vides par groupe à la
    publication, ce serait douze lignes par groupe que personne ne lira. Son
    numéro et son groupe viennent du CONTENU, pas de la requête -- le service
    les a bornés contre `team.count` avant d'arriver ici.

    TROIS REFUS DANS UNE INSTRUCTION, là où trois `if` en laisseraient chacun
    un ouvert : l'équipe ne doit pas être pleine, et ce compte ne doit pas être
    déjà sur une équipe de ce devoir (la clé primaire s'en charge). Rend le
    `team_id` rejoint, ou None.
    """
    lignes = _query(
        "WITH equipe AS ("
        "  INSERT INTO team"
        "    (team_id, assignment_id, group_number, number, label)"
        "  VALUES (%(t)s, %(a)s, %(g)s, %(n)s, %(l)s)"
        "  ON CONFLICT DO NOTHING)"
        " INSERT INTO team_member (team_id, assignment_id, account)"
        " SELECT %(t)s, %(a)s, %(u)s"
        # LA PLACE EST COMPTÉE DANS LE `WHERE`, pas relue avant : deux
        # étudiants qui cliquent sur la dernière place au même instant
        # passeraient tous les deux un `if`.
        "  WHERE (SELECT count(*) FROM team_member m"
        "          WHERE m.assignment_id = %(a)s AND m.team_id = %(t)s)"
        "        < %(max)s"
        " ON CONFLICT DO NOTHING"
        " RETURNING team_id",
        {"t": team_id, "a": assignment_id, "g": group_number, "n": number,
         "l": label, "u": user, "max": taille_max}, read=True)
    return lignes[0][0] if lignes else None


def team_leave(user, assignment_id):
    """Quitter. La CONDITION DE DATE est au-dessus, dans le service.

    Elle ne peut pas être ici : « le devoir est-il ouvert ? » se lit dans le
    catalogue publié (`access()`), pas en base -- et dupliquer une date de
    release dans Postgres serait un second endroit où la vérité peut diverger.

    L'ÉQUIPE VIDÉE RESTE, et c'est voulu : elle porte peut-être déjà un
    document, et son numéro est celui de Moodle. Une équipe vide se remplit à
    nouveau ; une équipe supprimée renumérote tout.
    """
    return _query(
        "DELETE FROM team_member WHERE assignment_id = %s AND account = %s",
        (assignment_id, user)) is not None


def team_counts(assignment_id, group_number):
    """[{number, team_id, label, members}] -- les équipes de CE groupe.

    LA LISTE QUE L'ÉTUDIANT PARCOURT, et elle ne montre que les équipes qui
    existent : les autres sont des places libres que le service ajoute depuis
    `team.count`. Compter en SQL plutôt que de rendre les membres évite de
    faire traverser des `sub` pour afficher « 3/4 ».
    """
    rows = _query(
        "SELECT t.number, t.team_id, t.label,"
        "       (SELECT count(*) FROM team_member m"
        "         WHERE m.assignment_id = t.assignment_id"
        "           AND m.team_id = t.team_id)"
        "  FROM team t"
        " WHERE t.assignment_id = %s AND t.group_number = %s"
        " ORDER BY t.number",
        (assignment_id, group_number), read=True)
    if rows is None:
        return None
    return [{"number": int(number), "team_id": team_id, "label": label,
             "members": int(membres)}
            for number, team_id, label, membres in rows]


def team_of(user, assignment_id):
    """This account's team for this assignment, or None. THE ONLY GATE.

    Everything a team route does starts here: the document, the history, the
    hand-in and the live socket all resolve their team from the AUTHENTICATED
    account and the assignment, never from an id in a body, a URL or a
    WebSocket frame. A student who edits the team id in a payload is asking
    for a team this query will simply not return.

    None means "no team", and it also means "the database did not answer" --
    the two are the same answer here on purpose: without a proven membership,
    nothing opens.
    """
    rows = _query(
        "SELECT m.team_id, t.group_number, t.number, t.label"
        "  FROM team_member m"
        "  JOIN team t ON t.team_id = m.team_id"
        "             AND t.assignment_id = m.assignment_id"
        " WHERE m.assignment_id = %s AND m.account = %s",
        (assignment_id, user), read=True)
    if not rows:
        return None
    team_id, group_number, number, label = rows[0]
    return {"team_id": team_id, "assignment_id": assignment_id,
            "group_number": group_number, "number": number, "label": label}


def team_roster(assignment_id, team_id):
    """The team's accounts, oldest membership first. None if the base is mute.

    IT RETURNS `sub`s, and it is the caller (`services/teams.py`) that turns
    them into the labels teammates see -- exactly the split `forum_vue()`
    makes. No `sub` leaves this application through a team route either.
    """
    rows = _query(
        "SELECT account FROM team_member"
        " WHERE assignment_id = %s AND team_id = %s"
        " ORDER BY joined_at, account",
        (assignment_id, team_id), read=True)
    if rows is None:
        return None
    return [account for (account,) in rows]


def read_team_document(team_id, exercise_id):
    """The shared sources, `{}` when nothing has been written yet, None on failure.

    THE THREE ANSWERS ARE DISTINCT, unlike `read_resume`'s two: an empty
    workspace and a database that did not answer look identical on screen and
    call for opposite reactions -- start typing, or do not touch anything.
    """
    rows = _query(
        "SELECT sources FROM team_document WHERE team_id = %s AND exercise_id = %s",
        (team_id, exercise_id), read=True)
    if rows is None:
        return None
    return _sources(rows) or {} if rows else {}


def write_team_document(team_id, exercise_id, user, sources, revision_id,
                        window):
    """Save the shared document AND, when it is worth one, a revision. ONE statement.

    TWO WRITES THAT MUST NOT COME APART. With two round trips, a connection
    dropped in between would leave a document with no history, or history for
    a document that was never saved -- and the second is the one an instructor
    would later read as evidence.

    THE COALESCING RULE IS THE `WHERE`, NOT AN `if` IN PYTHON. A revision is
    written only when this account has not written one for this document in
    the last `window` seconds AND the newest revision does not already hold
    exactly these bytes. Four members typing at once therefore produce one
    revision each per window -- which is what "who changed this" needs -- and
    a member who only watches produces none. A read followed by a write would
    have been the same rule with a race in the middle.

    ponytail: two members saving in the same instant both see an empty window
    (the statement's snapshot is taken at its start) and both write a
    revision. The cost is one extra row in a history nobody grades; a lock
    would cost more than the duplicate it prevents.
    """
    return _query(
        "WITH saved AS ("
        "  INSERT INTO team_document"
        "    (team_id, exercise_id, sources, updated_by, updated_at)"
        "  VALUES (%(t)s, %(e)s, %(s)s, %(a)s, now())"
        "  ON CONFLICT (team_id, exercise_id) DO UPDATE SET"
        "    sources = EXCLUDED.sources, updated_by = EXCLUDED.updated_by,"
        "    updated_at = now()"
        "  RETURNING team_id)"
        " INSERT INTO team_revision"
        "   (revision_id, team_id, exercise_id, account, sources)"
        " SELECT %(r)s, %(t)s, %(e)s, %(a)s, %(s)s"
        "  WHERE NOT EXISTS ("
        "    SELECT 1 FROM team_revision"
        "     WHERE team_id = %(t)s AND exercise_id = %(e)s AND account = %(a)s"
        "       AND created_at > now() - make_interval(secs => %(w)s))"
        "    AND %(s)s IS DISTINCT FROM ("
        "    SELECT sources FROM team_revision"
        "     WHERE team_id = %(t)s AND exercise_id = %(e)s"
        "     ORDER BY created_at DESC, revision_id DESC LIMIT 1)",
        {"t": team_id, "e": exercise_id, "a": user, "r": revision_id,
         "s": json.dumps(sources), "w": window},
    ) is not None


def read_team_revisions(team_id, exercise_id, limit):
    """The document's history, newest first: who, when, and how big.

    THE SOURCES ARE NOT IN HERE. A history list is read to choose a moment,
    and shipping every revision's full text would send the whole term's
    keystrokes to a page that displays a date. `read_team_revision` fetches
    the one that was chosen.
    """
    rows = _query(
        "SELECT revision_id, account, created_at, length(sources)"
        "  FROM team_revision WHERE team_id = %s AND exercise_id = %s"
        " ORDER BY created_at DESC, revision_id DESC LIMIT %s",
        (team_id, exercise_id, limit), read=True)
    if rows is None:
        return None
    return [{"revision_id": revision_id, "account": account,
             "created_at": _minute(created_at), "bytes": int(size)}
            for revision_id, account, created_at, size in rows]


def read_team_revision(team_id, revision_id):
    """One revision's sources, `{}` if it is not this team's. None on failure.

    THE TEAM IS IN THE `WHERE`, not checked afterwards in Python: a revision
    id copied from somewhere else does not resolve, so there is nothing to
    filter out and nothing to forget to filter.
    """
    rows = _query(
        "SELECT sources FROM team_revision"
        " WHERE revision_id = %s AND team_id = %s",
        (revision_id, team_id), read=True)
    if rows is None:
        return None
    return _sources(rows) or {} if rows else {}


def write_team_submission(assignment_id, team_id, user, files):
    """The hand-in. ONE PER TEAM -- the primary key holds that, not a check.

    Handing in again replaces it: a team that finds a bug at 22:00 must be
    able to fix it, and what was there before is still readable in
    `team_revision`. `submitted_by` says who pressed the button last.
    """
    return _query(
        "INSERT INTO team_submission"
        "  (assignment_id, team_id, submitted_by, files, submitted_at)"
        " VALUES (%s, %s, %s, %s, now())"
        " ON CONFLICT (assignment_id, team_id) DO UPDATE SET"
        "   submitted_by = EXCLUDED.submitted_by, files = EXCLUDED.files,"
        "   submitted_at = now()",
        (assignment_id, team_id, user, json.dumps(files)),
    ) is not None


def read_team_submission(assignment_id, team_id):
    """`{}` when the team has not handed in, None when the base is mute."""
    rows = _query(
        "SELECT submitted_by, submitted_at FROM team_submission"
        " WHERE assignment_id = %s AND team_id = %s",
        (assignment_id, team_id), read=True)
    if rows is None:
        return None
    if not rows:
        return {}
    submitted_by, submitted_at = rows[0]
    return {"submitted_by": submitted_by, "submitted_at": _minute(submitted_at)}


def team_memberships(user):
    """Every team this account is on, across assignments. None on failure.

    READ WITHOUT AN ASSIGNMENT, unlike `team_of()`, and that is the point: it
    answers "which teams am I on" for a student who wants to check their
    roster BEFORE the assignment opens. It grants nothing -- `workspace()` is
    still the gate for every document, revision, room and hand-in.
    """
    rows = _query(
        "SELECT m.assignment_id, m.team_id, t.group_number, t.number, t.label"
        "  FROM team_member m"
        "  JOIN team t ON t.team_id = m.team_id"
        "             AND t.assignment_id = m.assignment_id"
        " WHERE m.account = %s"
        " ORDER BY m.assignment_id",
        (user,), read=True)
    if rows is None:
        return None
    return [{"assignment_id": assignment_id, "team_id": team_id,
             "group_number": group_number, "number": number, "label": label}
            for assignment_id, team_id, group_number, number, label in rows]


def read_teams(assignment_id):
    """Every team of one assignment, for the instructor's view. None on failure."""
    rows = _query(
        "SELECT t.team_id, t.group_number, t.label, count(m.account)"
        "  FROM team t LEFT JOIN team_member m"
        "    ON m.team_id = t.team_id AND m.assignment_id = t.assignment_id"
        " WHERE t.assignment_id = %s"
        " GROUP BY t.team_id, t.group_number, t.label"
        " ORDER BY t.group_number, t.team_id",
        (assignment_id,), read=True)
    if rows is None:
        return None
    return [{"team_id": team_id, "group_number": group_number, "label": label,
             "members": int(members)}
            for team_id, group_number, label, members in rows]


def forget(user):
    """Erase everything stored for this user, in ONE statement.

    The consent sentence shown before redirecting to Rauthy promises this exists,
    so it exists -- not "later".

    FIFTEEN DELETEs, ONE ROUND TRIP, and that is the point: with one autocommit
    statement per table, a connection dropped in the middle would leave half a
    student erased and half not -- and the half that stays is the half nobody
    can see any more to ask for again. Data-modifying CTEs run exactly once each
    and commit together.

    EVERY TABLE THAT CARRIES AN `account` COLUMN IS IN HERE, AND IT IS THE SAME
    CLAUSE EVERYWHERE: what leaves is what THIS person wrote -- their messages,
    their reports, and the moderation actions they themselves took if they are
    a moderator. Nothing another wrote is touched. A report left on a deleted
    message shows up nowhere any more -- every read starts from
    `forum_message` -- and stays erasable by whoever filed it.

    THE THREE TEAM-OWNED TABLES ARE DELIBERATELY ABSENT, and they are the ones
    with no `account` column: `team` is the instructor's roster, and
    `team_document` and `team_submission` are FOUR people's graded work.
    Erasing one member must not take three others' assignment with it -- that
    is not erasure, that is deletion of somebody else's data. What does leave
    is this account's membership row and the revisions it authored: the
    account stops being on the team, and stops being named in its history.
    An instructor who needs the roster back re-runs `import_teams.py`.
    """
    return _query(
        "WITH b AS (DELETE FROM exercise_draft     WHERE account = %(u)s),"
        "     bn AS (DELETE FROM scratch_draft     WHERE account = %(u)s),"
        "     e AS (DELETE FROM exercise_state      WHERE account = %(u)s),"
        "     t AS (DELETE FROM practice_attempt    WHERE account = %(u)s),"
        "     j AS (DELETE FROM progress_event      WHERE account = %(u)s),"
        "     x AS (DELETE FROM xp_transaction      WHERE account = %(u)s),"
        "     s AS (DELETE FROM achievement_unlocked WHERE account = %(u)s),"
        "     f AS (DELETE FROM forum_message       WHERE account = %(u)s),"
        "     g AS (DELETE FROM forum_report        WHERE account = %(u)s),"
        "     h AS (DELETE FROM forum_moderation    WHERE account = %(u)s),"
        "     i AS (DELETE FROM forum_profile       WHERE account = %(u)s),"
        "     k AS (DELETE FROM forum_reported_name WHERE account = %(u)s),"
        "     l AS (DELETE FROM forum_helpful       WHERE account = %(u)s),"
        "     m AS (DELETE FROM team_member         WHERE account = %(u)s),"
        "     n AS (DELETE FROM team_revision       WHERE account = %(u)s),"
        "     p AS (DELETE FROM display_preference  WHERE account = %(u)s)"
        " SELECT 1",
        {"u": user},
    ) is not None
