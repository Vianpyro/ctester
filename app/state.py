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

# ponytail: kept as the French values the schema and the API/JS/tests already
# agree on ('essaye', 'valide'); the column is now `status` (see schema.sql),
# but the values themselves are a wire-format contract shared with the JSON
# response, the frontend and the test suites. Translate all of those together
# in one pass, not this module alone.
STATUSES = ("essaye", "valide")
# The page's only two themes. Same list as the CHECK in `schema.sql` and the
# `<head>` script: three places, one rule to keep in sync.
THEMES = ("light", "dark")


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
        "   status = CASE WHEN exercise_state.status = 'valide' THEN 'valide'"
        "                 ELSE EXCLUDED.status END,"
        "   sources = EXCLUDED.sources, updated_at = now()",
        (user, exercise_id, status, json.dumps(sources)),
    ) is not None


def read_states(user):
    """[{exercice_id, statut}] for the list view, or None if the database is mute."""
    rows = _query(
        "SELECT exercise_id, status FROM exercise_state WHERE account = %s",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercice_id": exercise, "statut": status} for exercise, status in rows]


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
    return [{"exercice_id": ex, "tentatives": attempts, "reussites": solved}
            for ex, attempts, solved in rows]


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

    [{"exercice_id": str|None, "charge": dict}] -- the date is used to order
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
        facts.append({"exercice_id": exercise_id,
                      "charge": payload if isinstance(payload, dict) else {}})
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

    {"xp": int, "succes": [{id, obtenu_le, politique}],
     "transactions": [{exercice_id, montant, motif, accorde_le}]}

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
        "succes": [{"id": row[0], "obtenu_le": _day(row[1]),
                    "politique": row[2]} for row in unlocked],
        "transactions": [{"exercice_id": row[0], "montant": int(row[1]),
                          "motif": row[2], "accorde_le": _day(row[3])}
                         for row in grants],
    }


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


def forum_fil(exercise_id, limit):
    """An exercise's thread, oldest to newest. None if the database is mute.

    Hidden messages ARE returned, with their flag: it is `forum_vue()` that
    strips them for an ordinary student and keeps them for a moderator,
    because it is the one that knows who is calling.
    """
    rows = _query(
        "SELECT message_id, account, text, hidden, created_at"
        " FROM forum_message WHERE exercise_id = %s"
        " ORDER BY created_at, message_id LIMIT %s",
        (exercise_id, max(int(limit), 0)), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "utilisateur": row[1], "texte": row[2],
             "masque": bool(row[3]), "cree_le": _minute(row[4])} for row in rows]


def forum_publier(message_id, exercise_id, user, text):
    """Add a message. The id is generated by the caller (uuid4)."""
    return _query(
        "INSERT INTO forum_message (message_id, exercise_id, account, text)"
        " VALUES (%s, %s, %s, %s)",
        (message_id, exercise_id, user, text),
    ) is not None


def forum_supprimer(message_id, user):
    """Delete THEIR OWN message. [] if it is not theirs (or already gone).

    The `account = %s` clause IS the access control: there is no prior read to
    make lie, and deleting a neighbor's message would require being the
    neighbor.
    """
    return _query(
        "DELETE FROM forum_message WHERE message_id = %s AND account = %s"
        " RETURNING message_id", (message_id, user), read=True)


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
    return [{"id": row[0], "exercice_id": row[1], "texte": row[2],
             "masque": bool(row[3]), "cree_le": _minute(row[4]),
             "signalements": int(row[5])} for row in rows]


def forum_moderer(action_id, message_id, moderator, action):
    """Hide or restore a message AND journal the action, in ONE statement.

    [] when the message does not exist; None when the database did not answer.

    THE JOURNAL IS APPEND-ONLY and the current state is a column: the two
    writes must therefore fall together. Split into two autocommit `_query`
    calls, a connection dropped in the middle would leave a message hidden
    that nothing explains -- or the reverse, a journal that lies.
    """
    if action not in ("masquer", "retablir"):
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
         "which": action, "hidden": action == "masquer"}, read=True)


# --- The chosen name and group number ---------------------------------------
# APPEND-ONLY, THE LAST ROW IS AUTHORITATIVE. No UPDATE, so no UPDATE GRANT:
# ownership is held by Postgres, not by the discipline of whoever writes the
# next query. `DISTINCT ON` reads it in one pass over the index
# (account, created_at DESC).

_PROFILE_COLUMNS = ("pseudo", "groupe", "pseudo_public", "groupe_public")


def _profil(row):
    return {"pseudo": row[1], "groupe": None if row[2] is None else int(row[2]),
            "pseudo_public": bool(row[3]), "groupe_public": bool(row[4])}


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
        "SELECT DISTINCT ON (account)"
        "       account, display_name, group_number, display_name_public, group_number_public"
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
    return profiles.get(user, {"pseudo": None, "groupe": None,
                              "pseudo_public": False, "groupe_public": False})


def forum_profil_ecrire(profile_id, user, display_name, group_number, display_name_public,
                        group_number_public, set_by_moderator=False):
    """Add a profile row. Older ones stay, and that is intentional."""
    return _query(
        "INSERT INTO forum_profile (profile_id, account, display_name, group_number,"
        "                          display_name_public, group_number_public, set_by_moderator)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (profile_id, user, display_name, group_number, bool(display_name_public),
         bool(group_number_public), bool(set_by_moderator)),
    ) is not None


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
    return [{"id": row[0], "utilisateur": row[1], "pseudo": row[2],
             "groupe": None if row[3] is None else int(row[3]),
             "cree_le": _minute(row[4]), "signalements": int(row[5])}
            for row in rows]


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


def forget(user):
    """Erase everything stored for this user, in ONE statement.

    The consent sentence shown before redirecting to Rauthy promises this exists,
    so it exists -- not "later".

    TWELVE DELETEs, ONE ROUND TRIP, and that is the point: with one autocommit
    statement per table, a connection dropped in the middle would leave half a
    student erased and half not -- and the half that stays is the half nobody
    can see any more to ask for again. Data-modifying CTEs run exactly once each
    and commit together.

    EVERY TABLE CARRIES `account`, AND IT IS THE SAME CLAUSE EVERYWHERE: what
    leaves is what THIS person wrote -- their messages, their reports, and the
    moderation actions they themselves took if they are a moderator. Nothing
    another wrote is touched. A report left on a deleted message shows up
    nowhere any more -- every read starts from `forum_message` -- and stays
    erasable by whoever filed it.
    """
    return _query(
        "WITH b AS (DELETE FROM exercise_draft     WHERE account = %(u)s),"
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
        "     p AS (DELETE FROM display_preference  WHERE account = %(u)s)"
        " SELECT 1",
        {"u": user},
    ) is not None
