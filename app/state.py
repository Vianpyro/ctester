import json
import os
import threading
from datetime import timezone

try:
    import psycopg
except ImportError:
    psycopg = None

DSN = os.environ.get("CTESTER_DB_DSN", "")

# A single connection behind a global lock: endpoints are sync and share it.
# Move to psycopg_pool if requests ever start queueing here.
_lock = threading.Lock()
_conn = None

STATUSES = ("attempted", "solved")
THEMES = ("light", "dark")
SCRATCH_MAX = 65536


def enabled():
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
    """None means the database is unavailable, never an empty result."""
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
                _close()
                if last_try:
                    return None
    return None


def _sources(rows):
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
    rows = _query(
        "SELECT exercise_id, status FROM exercise_state WHERE account = %s",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercise_id": exercise, "status": status} for exercise, status in rows]


def write_practice_attempt(user, job_id, exercise_id, result):
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
    # The (account, event_id) key makes a replayed poll or a second solve grant nothing.
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
    total = _query(
        "SELECT COALESCE(sum(amount), 0) FROM xp_transaction"
        " WHERE account = %s", (user,), read=True)
    unlocked = _query(
        "SELECT achievement_id, unlocked_at, policy FROM achievement_unlocked"
        " WHERE account = %s ORDER BY unlocked_at, achievement_id",
        (user,), read=True)
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
    holders = _query(
        "SELECT achievement_id, count(DISTINCT account)"
        "  FROM achievement_unlocked GROUP BY achievement_id", (), read=True)
    cohort = _query(
        "SELECT count(DISTINCT account) FROM practice_attempt", (), read=True)
    if holders is None or cohort is None:
        return None
    return ({row[0]: int(row[1]) for row in holders},
            int(cohort[0][0]) if cohort else 0)


def leaderboard_rows(group_number, days, staff=()):
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
    try:
        return value.date().isoformat()
    except AttributeError:
        return str(value)[:10]


def read_theme(user):
    rows = _query("SELECT theme FROM display_preference WHERE account = %s",
                  (user,), read=True)
    if rows is None:
        return None
    return rows[0][0] if rows else ""


def write_theme(user, theme):
    if theme not in THEMES:
        return False
    return _query(
        "INSERT INTO display_preference (account, theme, updated_at)"
        " VALUES (%s, %s, now())"
        " ON CONFLICT (account)"
        " DO UPDATE SET theme = EXCLUDED.theme, updated_at = now()",
        (user, theme),
    ) is not None


def read_scratch(user):
    rows = _query("SELECT code, header_name, header FROM scratch_draft WHERE account = %s",
                  (user,), read=True)
    if rows is None:
        return None
    code, header_name, header = rows[0] if rows else ("", "", "")
    return {"code": code, "header_name": header_name, "header": header}


def write_scratch(user, code, header_name="", header=""):
    texts = (code, header_name, header)
    if (any(not isinstance(text, str) for text in texts)
            or any(len(text.encode("utf-8")) > SCRATCH_MAX for text in texts)):
        return False
    return _query(
        "INSERT INTO scratch_draft (account, code, header_name, header, updated_at)"
        " VALUES (%s, %s, %s, %s, now())"
        " ON CONFLICT (account)"
        " DO UPDATE SET code = EXCLUDED.code, header_name = EXCLUDED.header_name,"
        "               header = EXCLUDED.header, updated_at = now()",
        (user, code, header_name, header),
    ) is not None


def forum_thread(exercise_id, limit, reader=None):
    rows = _query(
        "WITH roots AS ("
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
        "   AND (m.message_id IN (SELECT message_id FROM roots)"
        "        OR m.reply_to IN (SELECT message_id FROM roots))"
        " ORDER BY m.created_at, m.message_id",
        {"ex": exercise_id, "limit": max(int(limit), 0), "who": reader or ""},
        read=True)
    return _messages(rows)


def forum_activity(reader, moderator, days):
    """The last message per thread, for the unread dots. Full precision on purpose:
    the client stores the value back as its 'seen' marker and never displays it."""
    rows = _query(
        "SELECT exercise_id, max(created_at) FROM forum_message"
        "  WHERE NOT hidden"
        "    AND created_at > now() - make_interval(days => %(days)s)"
        "    AND (%(mod)s OR visibility = 'thread' OR account = %(me)s)"
        "  GROUP BY exercise_id",
        {"days": max(int(days), 1), "mod": bool(moderator), "me": reader or ""},
        read=True)
    if rows is None:
        return None
    return {row[0]: row[1].isoformat() for row in rows}


def _messages(rows):
    if rows is None:
        return None
    return [{"id": row[0], "account": row[1], "text": row[2],
             "hidden": bool(row[3]), "created_at": _minute(row[4]),
             "step": row[5], "blocked_kind": row[6], "visibility": row[7],
             "reply_to": row[8], "retained": bool(row[9]),
             "upvotes": int(row[10]), "downvotes": int(row[11]),
             "my_vote": int(row[12])} for row in rows]


def forum_conversation(message_id, reader=None):
    rows = _query(
        "WITH target AS ("
        "   SELECT COALESCE(reply_to, message_id) AS root, exercise_id"
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
        "  JOIN target c ON m.message_id = c.root OR m.reply_to = c.root"
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


def forum_post(message_id, exercise_id, user, text, step=None,
               blocked_kind=None, visibility="thread"):
    return _query(
        "INSERT INTO forum_message"
        "  (message_id, exercise_id, account, text, step, blocked_kind, visibility)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (message_id, exercise_id, user, text, step, blocked_kind, visibility),
    ) is not None


def forum_reply(message_id, exercise_id, user, text, target):
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
    return _query(
        "UPDATE forum_message SET visibility = 'group'"
        " WHERE message_id = %s AND account = %s AND visibility = 'private'"
        " RETURNING message_id", (message_id, user), read=True)


def forum_vote(message_id, user, value):
    value = 1 if int(value) >= 0 else -1
    # Downvotes only apply to replies: a question can't be buried.
    return _query(
        "INSERT INTO forum_helpful (message_id, account, value)"
        " SELECT m.message_id, %(who)s, %(value)s FROM forum_message m"
        "  WHERE m.message_id = %(id)s AND m.account <> %(who)s"
        "    AND (%(value)s = 1 OR m.reply_to IS NOT NULL)"
        " ON CONFLICT (message_id, account) DO UPDATE SET value = EXCLUDED.value"
        " RETURNING forum_helpful.message_id",
        {"who": user, "id": message_id, "value": value}, read=True)


def forum_unvote(message_id, user):
    return _query(
        "DELETE FROM forum_helpful WHERE message_id = %s AND account = %s"
        " RETURNING message_id", (message_id, user), read=True)


def forum_delete(message_id, user):
    return _query(
        "DELETE FROM forum_message WHERE message_id = %s AND account = %s"
        " RETURNING message_id", (message_id, user), read=True)


def forum_thread_of(message_id):
    rows = _query("SELECT exercise_id FROM forum_message WHERE message_id = %s",
                  (message_id,), read=True)
    return rows[0][0] if rows else ""


def forum_report(message_id, user):
    return _query(
        "INSERT INTO forum_report (message_id, account)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, account) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_reports(limit):
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


def forum_moderate(action_id, message_id, moderator, action):
    if action in ("retain", "unretain"):
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


_PROFILE_COLUMNS = ("display_name", "group_number", "display_name_public",
                    "group_number_public", "alias", "plate_frame",
                    "badges_public", "leaderboard_opt_in")

EMPTY_PROFILE = {"display_name": None, "group_number": None,
               "display_name_public": False, "group_number_public": False,
               "alias": None, "plate_frame": None,
               "badges_public": False, "leaderboard_opt_in": False}


def _profile(row):
    return {"display_name": row[1], "group_number": None if row[2] is None else int(row[2]),
            "display_name_public": bool(row[3]), "group_number_public": bool(row[4]),
            "alias": row[5], "plate_frame": row[6],
            "badges_public": bool(row[7]), "leaderboard_opt_in": bool(row[8])}


def forum_profiles(users):
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
    return {row[0]: _profile(row) for row in rows}


def forum_profile(user):
    profiles = forum_profiles([user])
    if profiles is None:
        return None
    return profiles.get(user, dict(EMPTY_PROFILE))


def forum_write_profile(profile_id, user, display_name, group_number, display_name_public,
                        group_number_public, set_by_moderator=False, alias=None,
                        plate_frame=None, badges_public=False,
                        leaderboard_opt_in=False):
    # Profiles are append-only and the latest row wins, so callers pass every field.
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
    rows = _query(
        "SELECT DISTINCT ON (account) alias FROM forum_profile"
        " ORDER BY account, created_at DESC, profile_id DESC", (), read=True)
    if rows is None:
        return None
    return {row[0] for row in rows if row[0]}


def forum_report_name(message_id, user):
    return _query(
        "INSERT INTO forum_reported_name (message_id, account)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, account) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_reported_names(limit):
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


def forum_author(message_id):
    rows = _query("SELECT account FROM forum_message WHERE message_id = %s",
                  (message_id,), read=True)
    if not rows:
        return None
    return rows[0][0]


def _minute(value):
    try:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except AttributeError:
        return str(value)[:16]


def team_join(user, assignment_id, team_id, group_number, number, label,
              max_size):
    # The seat count is part of the INSERT so two joins can't both take the last seat.
    rows = _query(
        "WITH created_team AS ("
        "  INSERT INTO team"
        "    (team_id, assignment_id, group_number, number, label)"
        "  VALUES (%(t)s, %(a)s, %(g)s, %(n)s, %(l)s)"
        "  ON CONFLICT DO NOTHING)"
        " INSERT INTO team_member (team_id, assignment_id, account)"
        " SELECT %(t)s, %(a)s, %(u)s"
        "  WHERE (SELECT count(*) FROM team_member m"
        "          WHERE m.assignment_id = %(a)s AND m.team_id = %(t)s)"
        "        < %(max)s"
        " ON CONFLICT DO NOTHING"
        " RETURNING team_id",
        {"t": team_id, "a": assignment_id, "g": group_number, "n": number,
         "l": label, "u": user, "max": max_size}, read=True)
    return rows[0][0] if rows else None


def team_leave(user, assignment_id):
    return _query(
        "DELETE FROM team_member WHERE assignment_id = %s AND account = %s",
        (assignment_id, user)) is not None


def team_counts(assignment_id, group_number):
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
             "members": int(members)}
            for number, team_id, label, members in rows]


def team_of(user, assignment_id):
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
    rows = _query(
        "SELECT account FROM team_member"
        " WHERE assignment_id = %s AND team_id = %s"
        " ORDER BY joined_at, account",
        (assignment_id, team_id), read=True)
    if rows is None:
        return None
    return [account for (account,) in rows]


def read_team_document(team_id, exercise_id):
    rows = _query(
        "SELECT sources FROM team_document WHERE team_id = %s AND exercise_id = %s",
        (team_id, exercise_id), read=True)
    if rows is None:
        return None
    return _sources(rows) or {} if rows else {}


def write_team_document(team_id, exercise_id, user, sources, revision_id,
                        window):
    # At most one revision per author per window, and only when the text changed.
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
    rows = _query(
        "SELECT sources FROM team_revision"
        " WHERE revision_id = %s AND team_id = %s",
        (revision_id, team_id), read=True)
    if rows is None:
        return None
    return _sources(rows) or {} if rows else {}


def write_team_submission(assignment_id, team_id, user, files):
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


# --- The judge's run journal, read and written by the admin app only. -----------------
# judge_run holds no account: it is the history of the service, not of a student, so
# forget() leaves it alone.

RUN_COLUMNS = ("job_id", "exercise_id", "account", "status", "kind", "duration_s",
               "queue_wait_s", "worker_id", "cache_hit", "reprises", "finished_at")


def journal_offsets():
    rows = _query("SELECT filename, byte_offset FROM judge_journal_cursor", (), read=True)
    return None if rows is None else {name: int(offset) for name, offset in rows}


def write_runs(records, filename, offset):
    """One statement per drain: a reconnect between the rows and the cursor must not
    double-insert, hence ON CONFLICT DO NOTHING on the job id."""
    values = [tuple(record[column] for column in RUN_COLUMNS) for record in records]
    sql = ""
    params = []
    if values:
        placeholders = ", ".join(["(" + ", ".join(["%s"] * len(RUN_COLUMNS)) + ")"] * len(values))
        sql += ("WITH inserted AS (INSERT INTO judge_run (" + ", ".join(RUN_COLUMNS) + ")"
                " VALUES " + placeholders + " ON CONFLICT (job_id) DO NOTHING) ")
        params += [field for value in values for field in value]
    sql += ("INSERT INTO judge_journal_cursor (filename, byte_offset) VALUES (%s, %s)"
            " ON CONFLICT (filename) DO UPDATE SET byte_offset = EXCLUDED.byte_offset")
    params += [filename, offset]
    return _query(sql, tuple(params))


def forget_journal_files(seen):
    """Cursors of files the judge has removed would otherwise be stat'd forever."""
    return _query("DELETE FROM judge_journal_cursor WHERE filename <> ALL(%s::text[])",
                  (list(seen),))


def read_runs(limit, status=None, exercise_id=None, worker_id=None, reveal=False):
    """`account` is only ever selected when asked for: the masking is the query, not a
    filter afterwards, so the default path never touches that column -- and still works
    against a database whose schema predates it."""
    where, params = [], []
    for column, value in (("status", status), ("exercise_id", exercise_id),
                          ("worker_id", worker_id)):
        if value:
            where.append("%s = %%s" % column)
            params.append(value)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(int(limit), 500)))
    colonnes = RUN_COLUMNS if reveal else tuple(
        c for c in RUN_COLUMNS if c != "account")
    rows = _query(
        "SELECT " + ", ".join(colonnes) + " FROM judge_run" + clause +
        " ORDER BY finished_at DESC LIMIT %s", tuple(params), read=True)
    if rows is None:
        return None
    return [dict(zip(colonnes, _run_row(row))) for row in rows]


def _run_row(row):
    return [value.isoformat() if hasattr(value, "isoformat") else value for value in row]


def read_workers(hours=24):
    """A worker is known by the runs it finished; the judge keeps no other identity."""
    rows = _query(
        "SELECT worker_id, count(*),"
        "       avg(duration_s) FILTER (WHERE status <> 'console'), max(finished_at),"
        "       count(*) FILTER (WHERE status NOT IN ('ok', 'console'))"
        "  FROM judge_run WHERE finished_at > now() - make_interval(hours => %s)"
        " GROUP BY worker_id ORDER BY worker_id", (hours,), read=True)
    if rows is None:
        return None
    return [{"worker_id": worker, "runs": int(runs),
             "average_s": round(float(average), 2) if average is not None else None,
             "last_seen": last.isoformat(), "failures": int(failures)}
            for worker, runs, average, last, failures in rows]


def read_run_stats(days=7):
    rows = _query(
        "SELECT count(*), count(*) FILTER (WHERE cache_hit),"
        "       count(*) FILTER (WHERE status = 'ok'),"
        "       coalesce(sum(reprises), 0),"
        "       avg(queue_wait_s) FILTER (WHERE status <> 'console'),"
        "       count(*) FILTER (WHERE status <> 'console')"
        "  FROM judge_run WHERE finished_at > now() - make_interval(days => %s)",
        (days,), read=True)
    if not rows:
        return None
    total, cached, ok, reprises, waited, graded = rows[0]
    # `graded` excludes Console sessions, so a success rate stays a success rate.
    return {"total": int(total), "cache_hits": int(cached), "ok": int(ok),
            "graded": int(graded), "reprises": int(reprises),
            "average_wait_s": round(float(waited), 2) if waited is not None else None}


def read_status_counts(days=7):
    rows = _query(
        "SELECT status, count(*) FROM judge_run"
        " WHERE finished_at > now() - make_interval(days => %s)"
        " GROUP BY status ORDER BY count(*) DESC", (days,), read=True)
    return None if rows is None else [{"status": s, "count": int(n)} for s, n in rows]


def read_exercise_stats(days=7, limit=20):
    rows = _query(
        "SELECT exercise_id, count(*), avg(duration_s),"
        "       percentile_disc(0.95) WITHIN GROUP (ORDER BY duration_s),"
        "       count(*) FILTER (WHERE status NOT IN ('ok', 'console'))"
        "  FROM judge_run WHERE finished_at > now() - make_interval(days => %s)"
        " GROUP BY exercise_id ORDER BY count(*) DESC LIMIT %s",
        (days, max(1, min(int(limit), 100))), read=True)
    if rows is None:
        return None
    return [{"exercise_id": exercise, "runs": int(runs),
             "average_s": round(float(average), 2) if average is not None else None,
             "p95_s": round(float(p95), 2) if p95 is not None else None,
             "failures": int(failures)}
            for exercise, runs, average, p95, failures in rows]


def read_submitted(user, exercise_id):
    """The last code this account actually submitted for this exercise, with its date.

    Deliberately not read_resume(): that one prefers exercise_draft, which is what the
    student is typing right now, not what they sent to the judge.
    """
    rows = _query(
        "SELECT sources, updated_at FROM exercise_state"
        " WHERE account = %s AND exercise_id = %s", (user, exercise_id), read=True)
    if not rows:
        return None
    files = _sources(rows)
    if files is None:
        return None
    return {"files": files, "at": rows[0][1].isoformat()}


def read_activity(days=7):
    """Runs per bucket, so a lab session's shape is visible: hourly over one day,
    daily beyond it."""
    unit = "hour" if days <= 1 else "day"
    rows = _query(
        "SELECT date_trunc(%s, finished_at) AS t, count(*),"
        "       count(*) FILTER (WHERE status NOT IN ('ok', 'console'))"
        "  FROM judge_run WHERE finished_at > now() - make_interval(days => %s)"
        " GROUP BY t ORDER BY t", (unit, days), read=True)
    if rows is None:
        return None
    return {"unit": unit,
            "buckets": [{"t": t.isoformat(), "runs": int(n), "failures": int(f)}
                        for t, n, f in rows]}


def read_usage(days=7):
    rows = _query(
        "SELECT (SELECT count(*) FROM exercise_state WHERE status = 'solved'),"
        "       (SELECT count(DISTINCT account) FROM practice_attempt"
        "         WHERE completed_at > now() - make_interval(days => %s)),"
        "       (SELECT coalesce(sum(amount), 0) FROM xp_transaction"
        "         WHERE granted_at > now() - make_interval(days => %s))",
        (days, days), read=True)
    if not rows:
        return None
    solved, active, xp = rows[0]
    return {"solved": int(solved), "active_accounts": int(active), "xp": int(xp)}


def read_channels(days=7):
    """Where the discussion is, without any message text: the admin app has no sign-in."""
    rows = _query(
        "SELECT exercise_id, count(*),"
        "       count(*) FILTER (WHERE created_at > now() - interval '24 hours'),"
        "       count(DISTINCT account), max(created_at)"
        "  FROM forum_message"
        " WHERE NOT hidden AND created_at > now() - make_interval(days => %s)"
        " GROUP BY exercise_id ORDER BY max(created_at) DESC", (days,), read=True)
    if rows is None:
        return None
    return [{"thread": t, "messages": int(n), "recent": int(r),
             "people": int(p), "last": last.isoformat()}
            for t, n, r, p, last in rows]

def forget(user):
    # One statement, so a dropped connection can't leave half an account behind.
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
        "     p AS (DELETE FROM display_preference  WHERE account = %(u)s),"
        "     q AS (DELETE FROM judge_run            WHERE account = %(u)s)"
        " SELECT 1",
        {"u": user},
    ) is not None
