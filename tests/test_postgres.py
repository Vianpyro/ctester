#!/usr/bin/env python3

import os
import re
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "worker"), os.path.join(ROOT, "app")]

DSN = os.environ.get("CTESTER_DB_DSN", "")
ADMIN_DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or DSN
if not DSN:
    print("CTESTER_DB_DSN empty: nothing to exercise here (see the header).")
    raise SystemExit(0)

import state       # noqa: E402 -- it reads CTESTER_DB_DSN at import

if not state.enabled():
    raise SystemExit("psycopg is missing: pip install 'psycopg[binary]'")

TABLES = ("exercise_draft", "exercise_state", "practice_attempt",
          "progress_event", "xp_transaction", "achievement_unlocked",
          "forum_message", "forum_report", "forum_moderation",
          "forum_profile", "forum_reported_name", "forum_helpful",
          "team_member", "team_revision",
          "display_preference")

ALICE, BOB = "sub-alice", "sub-bob"


def count(table, user):
    rows = state._query(
        "SELECT count(*) FROM %s WHERE account = %%s" % table,
        (user,), read=True)
    assert rows is not None, "the database did not answer on " + table
    return rows[0][0]


def upgrade_from_an_older_database():
    """A database that already holds the tables must still gain the columns added since.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that exists, so a column added
    only inside the CREATE block reaches a fresh database and never an old one. Every
    other check here starts from an empty database, which is exactly why that slipped
    through until the dashboard stopped ingesting in production.
    """
    import psycopg
    with open(os.path.join(ROOT, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        cx.execute(sql)
        # judge_run comme une base d'avant la colonne, puis on rejoue le schema.
        cx.execute("ALTER TABLE judge_run DROP COLUMN IF EXISTS account")
        cx.execute(sql)
        presentes = {row[0] for row in cx.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'judge_run'")}
    manquantes = set(state.RUN_COLUMNS) - presentes
    assert not manquantes, (
        "judge_run: %s manque(nt) apres une mise a niveau. Une colonne ajoutee au"
        " CREATE doit avoir son ALTER TABLE ... ADD COLUMN IF NOT EXISTS."
        % ", ".join(sorted(manquantes)))
    print("ok   schema.sql upgrades a database that already exists, not just a fresh one")


def apply_schema():
    import psycopg
    with open(os.path.join(ROOT, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        for _ in range(2):
            cx.execute(sql)
        found = {row[0] for row in cx.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    missing = set(TABLES) - found
    assert not missing, "missing tables: " + ", ".join(sorted(missing))
    print("ok   schema.sql applies, and replays without breaking anything")


def schema_repairs_an_older_database():
    import psycopg
    added = {
        "forum_message": ("step", "blocked_kind", "visibility"),
        "forum_profile": ("alias", "plate_frame", "badges_public",
                          "leaderboard_opt_in"),
        "scratch_draft": ("header_name", "header"),
    }
    with open(os.path.join(ROOT, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()

    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        def columns(table):
            return {row[0]: (row[1], row[2]) for row in cx.execute(
                "SELECT column_name, is_nullable, column_default"
                "  FROM information_schema.columns WHERE table_name = %s",
                (table,))}

        before = {table: columns(table) for table in added}
        privileges = list(cx.execute(
            "SELECT grantee, table_name, column_name, privilege_type"
            "  FROM information_schema.column_privileges"
            " WHERE table_name = ANY(%s) AND column_name = ANY(%s)"
            "   AND grantee <> current_user",
            (list(added), [n for names in added.values() for n in names])))

        for table, names in added.items():
            for name in names:
                cx.execute("ALTER TABLE %s DROP COLUMN IF EXISTS %s"
                           % (table, name))
        cx.execute("ALTER TABLE forum_moderation"
                   " DROP CONSTRAINT IF EXISTS forum_moderation_action_check")
        cx.execute("ALTER TABLE forum_moderation ADD CONSTRAINT"
                   " forum_moderation_action_check"
                   " CHECK (action IN ('hide', 'restore'))")

        cx.execute(sql)

        for table, names in added.items():
            now = columns(table)
            for name in names:
                assert name in now, \
                    "%s.%s was not restored by replaying schema.sql" % (table, name)
                assert now[name] == before[table][name], \
                    "%s.%s came back different: %r then %r" % (
                        table, name, before[table][name], now[name])

        action_check = cx.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            "  WHERE conrelid = 'forum_moderation'::regclass"
            "    AND conname = 'forum_moderation_action_check'").fetchone()[0]
        for verb in ("hide", "restore", "retain", "unretain"):
            assert verb in action_check, (verb, action_check)

        cx.execute(sql)
        for table, names in added.items():
            assert columns(table) == before[table], table

        for grantee, table, column, privilege in privileges:
            cx.execute('GRANT %s (%s) ON %s TO "%s"'
                       % (privilege, column, table, grantee))
        restored = {(row[0], row[1], row[2], row[3]) for row in cx.execute(
            "SELECT grantee, table_name, column_name, privilege_type"
            "  FROM information_schema.column_privileges"
            " WHERE table_name = ANY(%s) AND column_name = ANY(%s)"
            "   AND grantee <> current_user",
            (list(added), [n for names in added.values() for n in names]))}
        assert restored == {tuple(row) for row in privileges}, \
            "column grants were not restored: %r" % (restored,)
    print("ok   schema.sql repairs an older database, and stays idempotent")


def schema_renames_legacy_solve_events():
    import psycopg
    with open(os.path.join(ROOT, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    legacy, doubled = "legacy-a", "legacy-b"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        def add_solve(account, event_id):
            cx.execute("INSERT INTO progress_event (account, event_id, type, exercise_id,"
                       " policy) VALUES (%s, %s, 'ExerciceReussi', 'tp9-ex1', 'p')",
                       (account, event_id))
            cx.execute("INSERT INTO xp_transaction (account, event_id, amount, reason,"
                       " exercise_id, policy) VALUES (%s, %s, 10, 'r', 'tp9-ex1', 'p')",
                       (account, event_id))

        add_solve(legacy, "reussite:tp9-ex1")
        cx.execute("INSERT INTO achievement_unlocked (account, achievement_id, event_id,"
                   " policy) VALUES (%s, 'premiere-reussite', 'reussite:tp9-ex1', 'p')",
                   (legacy,))
        add_solve(doubled, "reussite:tp9-ex1")
        add_solve(doubled, "solved:tp9-ex1")
        cx.execute(sql)

        def ids(table, account):
            return sorted(row[0] for row in cx.execute(
                "SELECT event_id FROM %s WHERE account = %%s" % table, (account,)))

        for table in ("progress_event", "xp_transaction", "achievement_unlocked"):
            assert ids(table, legacy) == ["solved:tp9-ex1"], (table, ids(table, legacy))
        for table in ("progress_event", "xp_transaction"):
            assert ids(table, doubled) == ["reussite:tp9-ex1", "solved:tp9-ex1"], table
        assert state.grant_first_solve(legacy, "tp9-ex1", "solved:tp9-ex1", 10, "r",
                                       "p", {}, 100) is None
        assert ids("xp_transaction", legacy) == ["solved:tp9-ex1"]
        for table in ("progress_event", "xp_transaction", "achievement_unlocked"):
            cx.execute("DELETE FROM %s WHERE account IN (%%s, %%s)" % table,
                       (legacy, doubled))
    print("ok   legacy 'reussite:' events are renamed, never duplicated")


def schema_migrates_a_roster_shaped_team_table():
    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        cx.execute("DROP TABLE IF EXISTS team_revision, team_submission,"
                   " team_document, team_member, team CASCADE")
        cx.execute("CREATE TABLE team ("
                   " team_id TEXT NOT NULL, assignment_id TEXT NOT NULL,"
                   " group_number SMALLINT NOT NULL"
                   "   CHECK (group_number BETWEEN 1 AND 99),"
                   " label TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                   " PRIMARY KEY (team_id, assignment_id))")
        cx.execute("CREATE TABLE team_member ("
                   " team_id TEXT NOT NULL, assignment_id TEXT NOT NULL,"
                   " account TEXT NOT NULL,"
                   " joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                   " PRIMARY KEY (assignment_id, account),"
                   " FOREIGN KEY (team_id, assignment_id)"
                   "   REFERENCES team (team_id, assignment_id) ON DELETE CASCADE)")
        cx.execute("INSERT INTO team VALUES"
                   " ('g04-e01', 'devoir', 4, 'Équipe 1', now())")
        cx.execute("INSERT INTO team_member VALUES"
                   " ('g04-e01', 'devoir', 'sub-hier', now())")

    apply_schema()
    upgrade_from_an_older_database()

    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        ligne = cx.execute(
            "SELECT group_number, number, label FROM team"
            " WHERE team_id = 'g04-e01'").fetchone()
        assert ligne == (4, 1, "Équipe 1"), ligne
        assert cx.execute("SELECT count(*) FROM team_member").fetchone()[0] == 1
        assert cx.execute(
            "SELECT count(*) FROM pg_indexes"
            " WHERE indexname = 'team_number_idx'").fetchone()[0] == 1
    _reset_teams()
    print("ok   schema.sql migre la table `team` d'hier sans perdre de ligne")


def append_only():
    if ADMIN_DSN == DSN:
        print("--   append-only: NOT PLAYED (no distinct CTESTER_DB_ADMIN_DSN)")
        return
    import psycopg
    refused = []
    for table in ("progress_event", "xp_transaction", "achievement_unlocked"):
        with psycopg.connect(DSN, autocommit=True) as cx:
            try:
                cx.execute("UPDATE %s SET policy = 'cheat'" % table)
            except psycopg.errors.InsufficientPrivilege:
                refused.append(table)
    assert len(refused) == 3, "UPDATE accepted somewhere: " + str(refused)
    print("ok   Postgres refuses UPDATE on the three progression tables")


def drafts_and_states():
    assert state.write_draft(ALICE, "tp2-ex3", {"submission.c": "int main(void){}"})
    assert state.read_resume(ALICE, "tp2-ex3") == {"submission.c": "int main(void){}"}
    assert state.write_state(ALICE, "tp2-ex3", "solved", {"submission.c": "sent"})
    assert state.read_resume(ALICE, "tp2-ex3")["submission.c"] == "int main(void){}"
    assert state.write_state(ALICE, "tp2-ex3", "attempted", {"submission.c": "broken"})
    assert state.read_states(ALICE) == [{"exercise_id": "tp2-ex3", "status": "solved"}]
    assert state.write_state(ALICE, "tp2-ex3", "perfect", {}) is False
    print("ok   draft, state, and \"solved\" does not go backwards")


def practice_attempts():
    verdict = {"status": "ok", "total": 3, "passed": 3}
    assert state.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert state.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert state.write_practice_attempt(ALICE, "job-2", "tp2-ex3",
                                       {"status": "ok", "total": 3, "passed": 1})
    assert state.read_practice_summary(ALICE) == [
        {"exercise_id": "tp2-ex3", "attempts": 2, "successes": 1}]
    assert state.write_practice_attempt(ALICE, "job-3", "tp2-ex3",
                                       {"status": "ok", "total": 1, "passed": 9})
    print("ok   practice attempt: idempotent per job, bounded by the schema")


def grants():
    granted = state.grant_first_solve(
        ALICE, "tp2-ex3", "solved:tp2-ex3", 15, "first solve",
        "policy-1", {"job": "job-1", "difficulte": "foundation"}, 100)
    assert granted == 15, granted
    for _ in range(3):
        assert state.grant_first_solve(
            ALICE, "tp2-ex3", "solved:tp2-ex3", 15, "first solve",
            "policy-1", {"job": "job-9"}, 100) is None
    assert count("xp_transaction", ALICE) == 1
    assert count("progress_event", ALICE) == 1

    assert state.grant_first_solve(
        ALICE, "tp2-ex0", "solved:tp2-ex0", 30, "first solve",
        "policy-1", {"job": "job-4"}, 20) == 5
    assert state.grant_first_solve(
        ALICE, "tp7-ex1", "solved:tp7-ex1", 30, "first solve",
        "policy-1", {"job": "job-5"}, 20) == 0
    assert count("xp_transaction", ALICE) == 3
    print("ok   grant: once per fact, cap applied within the same statement")


def achievements_and_reading():
    assert state.unlock(ALICE, ["premiere-reussite", "premiere-competence"],
                       "solved:tp2-ex3", "policy-1")
    assert state.unlock(ALICE, ["premiere-reussite", "cinq-reussites"],
                       "solved:tp2-ex0", "policy-1")
    assert count("achievement_unlocked", ALICE) == 3
    assert state.unlock(ALICE, [], "solved:tp2-ex3", "policy-1")

    view = state.read_progress(ALICE)
    assert view["xp"] == 20, view
    assert [s["id"] for s in view["achievements"]] == [
        "premiere-competence", "premiere-reussite", "cinq-reussites"], view["achievements"]
    assert all(len(s["unlocked_at"]) == 10 for s in view["achievements"]), view["achievements"]
    assert len(view["transactions"]) == 3
    assert view["transactions"][0]["reason"] == "first solve"
    print("ok   achievements without duplicates, and reading the facts (day-level dates)")


def mastery_evidence():
    written = state.record_event(ALICE, "verification:verif-tp2:job-v1",
                              "VerificationEvaluated", "verif-tp2", "policy-1",
                              {"job": "job-v1", "passed": False})
    assert written == "verification:verif-tp2:job-v1", written
    assert state.record_event(ALICE, "verification:verif-tp2:job-v1",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v1", "passed": True}) is None
    assert state.record_event(ALICE, "verification:verif-tp2:job-v2",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v2", "passed": True})

    facts = state.read_events(ALICE, "VerificationEvaluated")
    assert [f["payload"]["job"] for f in facts] == ["job-v2", "job-v1"], facts
    assert facts[0]["payload"]["passed"] is True
    assert facts[0]["exercise_id"] == "verif-tp2"
    assert count("progress_event", ALICE) > len(facts)
    assert state.read_events(ALICE, "ExerciceReussi")
    assert state.read_progress(ALICE)["xp"] == 20

    import psycopg
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute(
            "INSERT INTO progress_event"
            " (account, event_id, type, exercise_id, policy, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (ALICE, "verification:verif-tp2:corrupted", "VerificationEvaluated",
             "verif-tp2", "policy-1", "{ this is not JSON"))
    facts = state.read_events(ALICE, "VerificationEvaluated")
    corrupted = [f for f in facts if f["payload"] == {}]
    assert len(corrupted) == 1, facts
    print("ok   mastery evidence: same journal, no XP, no extra GRANT")


def account_isolation():
    assert state.write_draft(BOB, "tp2-ex3", {"submission.c": "// bob"})
    assert state.grant_first_solve(
        BOB, "tp2-ex3", "solved:tp2-ex3", 15, "first solve",
        "policy-1", {"job": "job-b"}, 100) == 15
    assert state.unlock(BOB, ["premiere-reussite"], "solved:tp2-ex3", "policy-1")
    assert state.read_progress(BOB)["xp"] == 15
    assert state.read_progress(ALICE)["xp"] == 20
    print("ok   two accounts, the same fact, no mixing")


def forum():
    m1, m2 = "a" * 32, "b" * 32
    assert state.forum_post(m1, "tp2-ex3", ALICE, "Why does my loop spin?")
    assert state.forum_post(m2, "tp2-ex3", BOB, "same problem here")
    assert state.forum_post("c" * 32, "tp2-ex0", BOB, "another exercise")
    thread = state.forum_thread("tp2-ex3", 200)
    assert [m["id"] for m in thread] == [m1, m2], thread
    assert thread[0]["account"] == ALICE and thread[0]["hidden"] is False
    assert len(thread[0]["created_at"]) == 17 and thread[0]["created_at"].endswith("Z"), \
        thread[0]["created_at"]
    assert len(state.forum_thread("tp2-ex0", 200)) == 1
    assert state.forum_thread("tp2-ex3", 1) == thread[-1:]

    assert state.forum_report(m2, ALICE) == [(m2,)]
    assert state.forum_report(m2, ALICE) == []
    assert state.forum_report("f" * 32, ALICE) == []
    assert count("forum_report", ALICE) == 1
    assert state.forum_report(m2, BOB) == [(m2,)]
    queue = state.forum_reports(200)
    assert len(queue) == 1, queue
    assert queue[0]["id"] == m2 and queue[0]["report_count"] == 2
    assert queue[0]["text"] == "same problem here"
    assert queue[0]["exercise_id"] == "tp2-ex3"

    assert state.forum_moderate("d" * 32, m2, ALICE, "hide") == [(m2,)]
    assert state.forum_thread("tp2-ex3", 200)[1]["hidden"] is True
    assert state.forum_moderate("e" * 32, m2, ALICE, "restore") == [(m2,)]
    assert state.forum_thread("tp2-ex3", 200)[1]["hidden"] is False
    assert count("forum_moderation", ALICE) == 2
    assert state.forum_moderate("9" * 32, "f" * 32, ALICE, "hide") == []
    assert state._query(
        "INSERT INTO forum_moderation"
        " (action_id, message_id, account, action)"
        " VALUES (%s, %s, %s, 'supprimer')",
        ("7" * 32, m2, ALICE)) is None

    assert state.forum_delete(m2, ALICE) == []
    assert state.forum_delete(m1, ALICE) == [(m1,)]
    assert state.forum_delete(m1, ALICE) == []
    assert [m["id"] for m in state.forum_thread("tp2-ex3", 200)] == [m2]
    assert state.forum_post("1" * 32, "tp2-ex3", ALICE, "I'm back")
    print("ok   forum: thread per exercise, unique report, journaled moderation")


def identity():
    assert state.forum_profiles([ALICE, BOB]) == {}
    assert state.forum_profile(ALICE) == state.EMPTY_PROFILE
    assert state.forum_write_profile("p" * 32, ALICE, "Alice", 3, True, False)
    assert state.forum_write_profile("q" * 32, BOB, "Bob", 7, False, True)
    assert state.forum_write_profile("r" * 32, ALICE, "Alice B", 3, True, True)
    assert count("forum_profile", ALICE) == 2
    profiles = state.forum_profiles([ALICE, BOB, "sub-personne"])
    assert profiles[ALICE] == dict(state.EMPTY_PROFILE, display_name="Alice B",
                                   group_number=3, display_name_public=True,
                                   group_number_public=True)
    assert profiles[BOB]["display_name"] == "Bob" and profiles[BOB]["group_number"] == 7
    assert "sub-personne" not in profiles
    assert state.forum_write_profile("s" * 32, ALICE, "Alice", 0, False, False) \
        is False
    assert state.forum_write_profile("t" * 32, ALICE, "Alice", 100, False, False) \
        is False

    message = state.forum_thread("tp2-ex3", 200, ALICE)[0]["id"]
    assert state.forum_author(message) in (ALICE, BOB)
    assert state.forum_author("f" * 32) is None
    assert state.forum_report_name(message, BOB) == [(message,)]
    assert state.forum_report_name(message, BOB) == []
    assert state.forum_report_name("f" * 32, BOB) == []
    reported = state.forum_reported_names(200)
    assert len(reported) == 1 and reported[0]["id"] == message, reported
    author = state.forum_author(message)
    assert reported[0]["display_name"] == \
        state.forum_profiles([author])[author]["display_name"]
    assert reported[0]["report_count"] == 1
    assert state.forum_report_name("b" * 32, ALICE) == [("b" * 32,)]
    print("ok   identity: journal, last row wins, schema bounds, reported name")


def stuck_and_helpful():
    BLOQUE = "8" * 32
    thread = state.forum_thread("tp2-ex3", 200, ALICE)
    assert thread, "the forum() step should have left a message behind"

    assert state.forum_post(BLOQUE, "tp2-ex3", ALICE, "stuck",
                            "compilation", "unclear-error", "private")
    stuck = [m for m in state.forum_thread("tp2-ex3", 200, ALICE)
             if m["id"] == BLOQUE][0]
    assert stuck["visibility"] == "private" and stuck["step"] == "compilation"

    assert state.forum_open_to_group(BLOQUE, BOB) == []
    assert state.forum_open_to_group(BLOQUE, ALICE) != []
    assert state.forum_open_to_group(BLOQUE, ALICE) == []
    assert [m for m in state.forum_thread("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["visibility"] == "group"

    assert state.forum_vote(BLOQUE, ALICE, 1) == []
    assert state.forum_vote("0" * 32, BOB, 1) == []
    assert state.forum_vote(BLOQUE, BOB, 1) != []
    assert state.forum_vote(BLOQUE, BOB, 1) != []
    assert state.forum_vote(BLOQUE, BOB, -1) == []
    seen = [m for m in state.forum_thread("tp2-ex3", 200, BOB)
           if m["id"] == BLOQUE][0]
    assert seen["upvotes"] == 1 and seen["downvotes"] == 0
    assert seen["my_vote"] == 1
    assert [m for m in state.forum_thread("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["my_vote"] == 0
    assert state.forum_vote("c" * 32, ALICE, 1) != []

    REPONSE = "7" * 32
    assert state.forum_reply(REPONSE, "tp2-ex3", BOB, "essaie ça", BLOQUE) != []
    ENCORE = "6" * 32
    assert state.forum_reply(ENCORE, "tp2-ex3", ALICE, "merci", REPONSE) != []
    par_id = {m["id"]: m for m in state.forum_thread("tp2-ex3", 200, ALICE)}
    assert par_id[REPONSE]["reply_to"] == BLOQUE
    assert par_id[ENCORE]["reply_to"] == BLOQUE, "une réponse vise la RACINE"
    assert state.forum_reply("5" * 32, "tp2-ex0", BOB, "x", BLOQUE) == []
    assert state.forum_reply("5" * 32, "tp2-ex3", BOB, "x", "0" * 32) == []
    assert state.forum_vote(REPONSE, ALICE, -1) != []
    assert state.forum_vote(REPONSE, ALICE, 1) != []
    apres = {m["id"]: m for m in state.forum_thread("tp2-ex3", 200, ALICE)}
    assert apres[REPONSE]["upvotes"] == 1 and apres[REPONSE]["downvotes"] == 0
    assert state.forum_unvote(REPONSE, ALICE) != []
    assert state.forum_unvote(REPONSE, ALICE) == []
    assert {m["id"]: m for m in state.forum_thread("tp2-ex3", 200, ALICE)}[
        REPONSE]["upvotes"] == 0

    court = state.forum_thread("tp2-ex3", 1, ALICE)
    racines = [m for m in court if not m["reply_to"]]
    assert len(racines) == 1, court
    assert all(m["reply_to"] == racines[0]["id"]
               for m in court if m["reply_to"]), court

    fil_cle, conv = state.forum_conversation(ENCORE, ALICE)
    assert fil_cle == "tp2-ex3"
    assert {m["id"] for m in conv} == {BLOQUE, REPONSE, ENCORE}
    assert state.forum_conversation("0" * 32, ALICE) == (None, [])

    PRIVEE = "4" * 32
    assert state.forum_post(PRIVEE, "tp2-ex3", ALICE,
                            "mon segfault mysterieux", "execution",
                            "wrong-result", "private")
    a_elle = [r["id"] for r in state.forum_search("segfault", ALICE, 5)]
    a_lui = [r["id"] for r in state.forum_search("segfault", BOB, 5)]
    assert PRIVEE in a_elle, a_elle
    assert PRIVEE not in a_lui, a_lui
    assert state.forum_search("", ALICE, 5) == []
    for hostile in ("&& ||", '"', "a:*!", "'; DROP TABLE forum_message; --"):
        assert state.forum_search(hostile, ALICE, 5) is not None, hostile

    top = state.forum_top(24, 50)
    assert top is not None and all(r["id"] != REPONSE for r in top), top
    assert any(r["id"] == BLOQUE for r in top)

    before = seen["text"]
    assert state.forum_moderate("m" * 32, BLOQUE, BOB, "retain") != []
    retained = [m for m in state.forum_thread("tp2-ex3", 200, ALICE)
                if m["id"] == BLOQUE][0]
    assert retained["retained"] is True and retained["text"] == before
    assert state.forum_moderate("n" * 32, BLOQUE, BOB, "unretain") != []
    assert [m for m in state.forum_thread("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["retained"] is False

    rows = state.forum_help_rows(50, 24)
    line = [r for r in rows if r["step"] == "compilation"][0]
    assert line["people"] == 1 and line["opened"] == 1, line
    assert "account" not in line and "text" not in line, line

    days = state.read_practice_days(ALICE, 91)
    assert isinstance(days, list)
    assert all(set(d) == {"date", "attempts"} for d in days), days
    print("ok   stuck/helpful: one-way transition, three refusals, "
          "derived retention")


def leaderboard_rows():
    assert state.forum_write_profile("u" * 32, ALICE, "Alice", 3, True, True,
                                     alias="Rotor cuivre", leaderboard_opt_in=True)
    assert state.forum_write_profile("v" * 32, BOB, "Bob", 3, False, True,
                                     alias="Palier lisse", leaderboard_opt_in=False)
    rows = state.leaderboard_rows(3, 7)
    assert [r["account"] for r in rows] == [ALICE], rows
    assert rows[0]["recent"] >= 0 and rows[0]["lifetime"] >= rows[0]["recent"]
    assert [r["account"] for r in state.leaderboard_rows(None, 7)] == [ALICE]
    assert state.leaderboard_rows(99, 7) == []
    assert state.forum_write_profile("w" * 32, BOB, "Bob", 3, False, True,
                                     alias="Palier lisse", leaderboard_opt_in=True)
    assert {r["account"] for r in state.leaderboard_rows(3, 7)} == {ALICE, BOB}
    assert state.forum_taken_aliases() == {"Rotor cuivre", "Palier lisse"}
    rates, cohort = state.read_unlock_rates()
    assert isinstance(rates, dict) and cohort >= 1, (rates, cohort)
    print("ok   leaderboard: opt-in is the WHERE, a quiet week still counts")


def forum_privileges():
    if ADMIN_DSN == DSN:
        print("--   forum privileges: NOT PLAYED (no distinct CTESTER_DB_ADMIN_DSN)")
        return
    import psycopg
    attempts = (
        ("forum_message.text", "UPDATE forum_message SET text = 'rewritten'"),
        ("forum_message.account",
         "UPDATE forum_message SET account = 'sub-x'"),
        ("forum_report",
         "UPDATE forum_report SET account = 'sub-x'"),
        ("forum_moderation",
         "UPDATE forum_moderation SET action = 'restore'"),
        ("forum_profile.display_name", "UPDATE forum_profile SET display_name = 'other'"),
        ("forum_profile.display_name_public",
         "UPDATE forum_profile SET display_name_public = true"),
        ("forum_reported_name",
         "UPDATE forum_reported_name SET account = 'sub-x'"),
        ("forum_helpful", "UPDATE forum_helpful SET account = 'sub-x'"),
    )
    refused = []
    for name, sql in attempts:
        with psycopg.connect(DSN, autocommit=True) as cx:
            try:
                cx.execute(sql)
            except psycopg.errors.InsufficientPrivilege:
                refused.append(name)
    assert len(refused) == len(attempts), "UPDATE accepted somewhere: " \
                                       + str(refused)
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("UPDATE forum_message SET hidden = hidden")
        cx.execute("UPDATE forum_message SET visibility = visibility")
        cx.execute("UPDATE forum_helpful SET value = value")
    print("ok   forum: only `hidden` and `visibility` are writable, "
          "the rest is append-only")


def preferences():
    assert state.read_theme(ALICE) == "", "a fresh account has no theme"
    assert state.write_theme(ALICE, "light")
    assert state.read_theme(ALICE) == "light"
    assert state.write_theme(ALICE, "dark")
    assert state.read_theme(ALICE) == "dark"
    assert count("display_preference", ALICE) == 1
    assert state.write_theme(ALICE, "neon") is False
    assert state.read_theme(ALICE) == "dark"
    assert state.write_theme(BOB, "light")
    assert state.read_theme(ALICE) == "dark" and state.read_theme(BOB) == "light"
    print("ok   the theme writes, overwrites, and stays this account's own")


def deletion():
    before = {t: count(t, ALICE) for t in TABLES}
    assert all(before.values()), "useless test: nothing to erase " + str(before)
    assert state.forget(ALICE)
    after = {t: count(t, ALICE) for t in TABLES}
    assert not any(after.values()), after
    assert count("exercise_draft", BOB) == 1, "erased from the neighbor!"
    assert state.read_progress(BOB)["xp"] == 15
    assert count("forum_message", BOB) == 3, "message erased from the neighbor!"
    assert count("forum_report", BOB) == 1
    assert state.forget(ALICE)
    assert _rows("SELECT count(*) FROM team_document WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team_submission WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team_member"
                 " WHERE team_id = 'g04-e01' AND account = %s", (CLEO,)) == 1
    print("ok   \"Delete my data\" empties the fifteen account tables, leaves "
          "the team's work, and touches nobody else's")


def _inscrire(assignment_id, groupe, numero, comptes):
    import psycopg
    team_id = "g%02d-e%02d" % (groupe, numero)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        cx.execute("INSERT INTO team"
                   "   (team_id, assignment_id, group_number, number, label)"
                   " VALUES (%s, %s, %s, %s, %s)"
                   " ON CONFLICT (team_id, assignment_id) DO NOTHING",
                   (team_id, assignment_id, groupe, numero,
                    "Équipe %d" % numero))
        for compte in comptes:
            cx.execute("INSERT INTO team_member (team_id, assignment_id, account)"
                       " VALUES (%s, %s, %s)"
                       " ON CONFLICT (assignment_id, account) DO UPDATE SET"
                       "   team_id = EXCLUDED.team_id",
                       (team_id, assignment_id, compte))
    return team_id


CLEO = "sub-cleo"


def _reset_teams():
    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        cx.execute("DELETE FROM team_submission")
        cx.execute("DELETE FROM team_revision")
        cx.execute("DELETE FROM team_document")
        cx.execute("DELETE FROM team_member")
        cx.execute("DELETE FROM team")


def teams():
    _reset_teams()
    assert state.team_join(ALICE, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           4) == "g04-e01"
    assert state.team_join(CLEO, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           4) == "g04-e01"
    assert state.team_join(ALICE, "devoir", "g04-e02", 4, 2, "Équipe 2",
                           4) is None

    equipe = state.team_of(ALICE, "devoir")
    assert equipe["team_id"] == "g04-e01" and equipe["number"] == 1
    assert equipe["group_number"] == 4 and equipe["label"] == "Équipe 1"
    assert state.team_of("sub-personne", "devoir") is None
    assert state.team_of(ALICE, "autre-devoir") is None
    assert sorted(state.team_roster("devoir", "g04-e01")) == sorted([ALICE, CLEO])

    assert state.team_join(BOB, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           2) is None
    assert state.team_join(BOB, "devoir", "g06-e01", 6, 1, "Équipe 1",
                           4) == "g06-e01"
    assert state.team_of(BOB, "devoir")["team_id"] == "g06-e01"
    assert state.team_roster("devoir", "g04-e01") != state.team_roster(
        "devoir", "g06-e01")

    liste = state.team_counts("devoir", 4)
    assert liste[0] == {"number": 1, "team_id": "g04-e01", "label": "Équipe 1",
                        "members": 2}, liste
    assert [e["members"] for e in liste] == [2, 0], liste
    assert state.team_counts("devoir", 6)[0]["members"] == 1

    assert state.team_leave(CLEO, "devoir")
    assert state.team_of(CLEO, "devoir") is None
    assert state.team_counts("devoir", 4)[0]["members"] == 1

    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        try:
            cx.execute("INSERT INTO team_member (team_id, assignment_id, account)"
                       " VALUES ('g09-e09', 'devoir', 'sub-x')")
            raise AssertionError("une équipe inexistante a été acceptée")
        except psycopg.errors.ForeignKeyViolation:
            pass

    _inscrire("autre-devoir", 6, 2, [ALICE])
    miennes = state.team_memberships(ALICE)
    assert {m["assignment_id"]: m["team_id"] for m in miennes} == {
        "devoir": "g04-e01", "autre-devoir": "g06-e02"}, miennes
    assert sorted(m["number"] for m in miennes) == [1, 2]
    assert state.team_memberships("sub-personne") == []
    print("ok   teams: on prend une place libre, la place est comptée dans le "
          "WHERE, et deux groupes ont chacun leur « Équipe 1 »")


def team_documents():
    fenetre = 120
    _reset_teams()
    _inscrire("devoir", 4, 1, [ALICE, CLEO])
    _inscrire("devoir", 6, 1, [BOB])

    def ecrire(compte, texte, window=fenetre):
        return state.write_team_document("g04-e01", "dev-a", compte,
                                         {"main.c": texte}, uuid.uuid4().hex,
                                         window)

    assert state.read_team_document("g04-e01", "dev-a") == {}
    assert ecrire(ALICE, "un\n")
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "un\n"}
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 1

    assert ecrire(ALICE, "deux\n") and ecrire(ALICE, "trois\n")
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 1
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "trois\n"}

    assert ecrire(CLEO, "quatre\n")
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 2

    assert ecrire(CLEO, "quatre\n", window=0)
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 2
    assert ecrire(CLEO, "cinq\n", window=0)
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 3

    lignes = state.read_team_revisions("g04-e01", "dev-a", 10)
    assert [r["account"] for r in lignes] == [CLEO, CLEO, ALICE], lignes
    assert all(r["bytes"] > 0 for r in lignes)

    identifiant = lignes[0]["revision_id"]
    assert state.read_team_revision("g04-e01", identifiant) == {"main.c": "cinq\n"}
    assert state.read_team_revision("g06-e01", identifiant) == {}

    assert state.write_team_document("g06-e01", "dev-a", BOB, {"main.c": "bob\n"},
                                     uuid.uuid4().hex, fenetre)
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "cinq\n"}
    assert state.read_team_document("g06-e01", "dev-a") == {"main.c": "bob\n"}
    print("ok   team_document: un UPSERT et une révision coalescée en UNE "
          "instruction, isolés par équipe")


def team_submissions():
    assert state.read_team_submission("devoir", "g04-e01") == {}
    assert state.write_team_submission("devoir", "g04-e01", ALICE,
                                       {"Devoir/main.c": "x\n"})
    assert state.read_team_submission("devoir", "g04-e01")["submitted_by"] == ALICE
    assert state.write_team_submission("devoir", "g04-e01", CLEO,
                                       {"Devoir/main.c": "y\n"})
    assert _rows("SELECT count(*) FROM team_submission WHERE team_id = 'g04-e01'") == 1
    assert state.read_team_submission("devoir", "g04-e01")["submitted_by"] == CLEO
    assert state.write_team_submission("devoir", "g06-e01", BOB, {"Devoir/main.c": "b\n"})
    assert state.read_team_submission("devoir", "g06-e01")["submitted_by"] == BOB
    equipes = {e["team_id"]: e for e in state.read_teams("devoir")}
    assert equipes["g04-e01"]["members"] == 2 and equipes["g04-e01"]["group_number"] == 4
    assert equipes["g06-e01"]["members"] == 1
    print("ok   team_submission: une seule remise par équipe, remplaçable")


def team_privileges():
    if ADMIN_DSN == DSN:
        print("--   team privileges: NOT PLAYED (no distinct CTESTER_DB_ADMIN_DSN)")
        return
    import psycopg
    refuses = (
        ("team DELETE", "DELETE FROM team WHERE team_id = 'g04-e01'"),
        ("team.number", "UPDATE team SET number = 9"),
        ("team.group_number", "UPDATE team SET group_number = 9"),
        ("team.label", "UPDATE team SET label = 'Pirate'"),
        ("team_member.team_id", "UPDATE team_member SET team_id = 'g04-e01'"),
        ("team_member.account", "UPDATE team_member SET account = 'sub-x'"),
        ("team_revision UPDATE", "UPDATE team_revision SET account = 'sub-x'"),
    )
    manques = []
    for nom, sql in refuses:
        with psycopg.connect(DSN, autocommit=True) as cx:
            try:
                cx.execute(sql)
                manques.append(nom)
            except psycopg.errors.InsufficientPrivilege:
                pass
    assert not manques, "écriture acceptée sur : " + ", ".join(manques)
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("SELECT count(*) FROM team")
        cx.execute("UPDATE team_document SET sources = sources")
        cx.execute("UPDATE team_submission SET files = files")
        cx.execute("DELETE FROM team_member WHERE account = 'sub-absent'")
    print("ok   team: on entre et on sort, mais rien ne se modifie -- ni une "
          "équipe, ni une appartenance")


def _rows(sql, params=()):
    lignes = state._query(sql, params, read=True)
    assert lignes is not None, sql
    return lignes[0][0]


def main():
    apply_schema()
    schema_repairs_an_older_database()
    schema_renames_legacy_solve_events()
    schema_migrates_a_roster_shaped_team_table()
    append_only()
    for user in (ALICE, BOB, CLEO):
        state.forget(user)
    drafts_and_states()
    practice_attempts()
    grants()
    achievements_and_reading()
    mastery_evidence()
    account_isolation()
    forum()
    identity()
    stuck_and_helpful()
    leaderboard_rows()
    teams()
    team_documents()
    team_submissions()
    team_privileges()
    forum_privileges()
    preferences()
    deletion()
    state.forget(BOB)
    print("\nthe SQL holds up on a real PostgreSQL.")


if __name__ == "__main__":
    main()
