#!/usr/bin/env python3
"""ctester -- persistence for students who sign in. See schema.sql.

THIS WHOLE MODULE IS OPTIONAL, and that is what gives it its shape. Without
CTESTER_DB_DSN, `enabled()` is false and the API behaves exactly as before: the
anonymous path never needs this layer. A database that is down must not stop a
student from testing their code the evening before a deadline -- so nothing here
raises. Functions return None or False, and the caller says so honestly on screen.

`utilisateur` is ALWAYS the opaque `sub` validated by app.current_user(), never a value
taken from a request body: that is the one thing keeping a student out of
another student's state.

Table and column names stay as the schema declares them (see schema.sql); the
Python around them does not.
"""

import json
import os
import threading

try:
    import psycopg          # the exposed container's only external dependency
except ImportError:         # image built without it: persistence is simply absent
    psycopg = None

DSN = os.environ.get("CTESTER_DB_DSN", "")

# ponytail: ONE connection behind a global lock, not a pool. The most frequent
# write is a draft every 1.5 s per signed-in student; at 27 of them the queue
# behind this lock is permanently empty. Move to psycopg_pool the day it is not.
_lock = threading.Lock()
_conn = None

STATUSES = ("essaye", "valide")


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
        "  SELECT sources, 0 AS rank FROM brouillon_exercice"
        "   WHERE utilisateur = %s AND exercice_id = %s"
        "  UNION ALL"
        "  SELECT sources, 1 AS rank FROM etat_exercice"
        "   WHERE utilisateur = %s AND exercice_id = %s"
        ") AS both_tables ORDER BY rank LIMIT 1",
        (user, exercise_id, user, exercise_id), read=True)
    return _sources(rows)


def write_draft(user, exercise_id, sources):
    return _query(
        "INSERT INTO brouillon_exercice (utilisateur, exercice_id, sources, maj)"
        " VALUES (%s, %s, %s, now())"
        " ON CONFLICT (utilisateur, exercice_id)"
        " DO UPDATE SET sources = EXCLUDED.sources, maj = now()",
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
        "INSERT INTO etat_exercice (utilisateur, exercice_id, statut, sources, maj)"
        " VALUES (%s, %s, %s, %s, now())"
        " ON CONFLICT (utilisateur, exercice_id) DO UPDATE SET"
        "   statut = CASE WHEN etat_exercice.statut = 'valide' THEN 'valide'"
        "                 ELSE EXCLUDED.statut END,"
        "   sources = EXCLUDED.sources, maj = now()",
        (user, exercise_id, status, json.dumps(sources)),
    ) is not None


def read_states(user):
    """[{exercice_id, statut}] for the list view, or None if the database is mute."""
    rows = _query(
        "SELECT exercice_id, statut FROM etat_exercice WHERE utilisateur = %s",
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
        "INSERT INTO tentative_pratique "
        "(job_id, utilisateur, exercice_id, statut, total, reussis) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (job_id) DO NOTHING",
        (job_id, user, exercise_id, status, total, passed),
    ) is not None


def read_practice_summary(user):
    """Per-exercise practice counts; derived mastery is intentionally absent."""
    rows = _query(
        "SELECT exercice_id, count(*), "
        "count(*) FILTER (WHERE total > 0 AND reussis = total) "
        "FROM tentative_pratique WHERE utilisateur = %s "
        "GROUP BY exercice_id",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercice_id": ex, "tentatives": attempts, "reussites": solved}
            for ex, attempts, solved in rows]


def forget(user):
    """Erase everything stored for this user.

    The consent sentence shown before redirecting to Rauthy promises this exists,
    so it exists -- not "later".
    """
    drafts = _query(
        "DELETE FROM brouillon_exercice WHERE utilisateur = %s", (user,))
    states = _query(
        "DELETE FROM etat_exercice WHERE utilisateur = %s", (user,))
    attempts = _query(
        "DELETE FROM tentative_pratique WHERE utilisateur = %s", (user,))
    return drafts is not None and states is not None and attempts is not None
