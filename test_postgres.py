#!/usr/bin/env python3
"""ctester -- exercises `app/schema.sql` and `app/state.py` against a REAL PostgreSQL.

    docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester \
               -p 55432:5432 postgres:16-alpine
    CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
      python3 test_postgres.py

With the application role, which reproduces production exactly -- the schema
laid down by `postgres`, everything else played by `ctester_app` and its only
GRANTs:

    CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
    CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester \
      python3 test_postgres.py

THE ROLE IS ALL THERE IS TO CREATE (`CREATE ROLE ctester_app LOGIN PASSWORD
'y'`, once). Its PRIVILEGES come with `schema.sql`, which this file applies:
they used to live in Ansible and be recopied here to be exercised -- and a
harness that duplicates a rule in order to test it is a harness saying the
rule lives in the wrong repository. Ansible still creates the role, because
its password comes from the vault.

WHY THIS FILE EXISTS. `test_ctester.py` simulates the database: what it
exercises is the HTTP boundary, not the SQL. But the progression and forum
writes are not ordinary SQL -- a data-modifying CTE feeding an INSERT, a
data-modifying CTE feeding an UPDATE, an `unnest` of a parameterized array, an
INSERT ... SELECT whose `WHERE` clause IS the access control, a `DISTINCT ON`
and a LATERAL join for the latest profile, thirteen DELETEs in a single
statement. These shapes compile in your head and fail in production; there is
no middle ground.

WITHOUT `CTESTER_DB_DSN`, IT DOES NOTHING AND EXITS 0. That is deliberate: it
must be runnable everywhere without becoming one more reason not to run the
other checks. It is NOT in the Ansible verification -- it writes, and the only
database the role knows is the students'.
"""

import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

DSN = os.environ.get("CTESTER_DB_DSN", "")
# The schema is laid down by the owner, never by the application role: that is
# what the Ansible role does, and that is exactly what we want to exercise.
# Without an admin DSN, the two are the same and the privilege check below
# reports itself as not played rather than passing while lying.
ADMIN_DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or DSN
if not DSN:
    print("CTESTER_DB_DSN empty: nothing to exercise here (see the header).")
    raise SystemExit(0)

import state       # noqa: E402 -- it reads CTESTER_DB_DSN at import

if not state.enabled():
    raise SystemExit("psycopg is missing: pip install 'psycopg[binary]'")

# LES TABLES QUI PORTENT UN COMPTE, c'est-à-dire exactement celles que
# `forget()` vide. Les trois tables d'équipe qui n'y sont pas
# (`team`, `team_document`, `team_submission`) appartiennent au listage de
# l'enseignant ou au travail noté de trois autres personnes -- voir
# `deletion()` plus bas, qui vérifie qu'elles SURVIVENT.
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


def apply_schema():
    """The schema as Ansible applies it: the whole file, in one block.

    Replaying it must have no effect -- that is what the `IF NOT EXISTS`
    clauses promise, and that is what the role does on every converge.

    AND IT CARRIES THE GRANTS NOW. Applying the schema IS applying the
    privileges, so there is nothing here to keep in sync with another
    repository any more. The `DO` block grants nothing when `ctester_app` does
    not exist, which is what keeps this runnable against a bare database --
    exactly the case where only `CTESTER_DB_DSN` is set.
    """
    import psycopg
    with open(os.path.join(HERE, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    # THROUGH THE ADMIN DSN: `ctester_app` has no right to create a table, and
    # that is intentional. Going through `state._query` here would fail this
    # check for the right reason, in the wrong place.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        for _ in range(2):
            cx.execute(sql)
        found = {row[0] for row in cx.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    missing = set(TABLES) - found
    assert not missing, "missing tables: " + ", ".join(sorted(missing))
    print("ok   schema.sql applies, and replays without breaking anything")


def schema_repairs_an_older_database():
    """THE SCHEMA MUST REPAIR A DATABASE, not only create one from nothing.

    THIS IS THE CHECK THAT WAS MISSING, and its absence cost a failed deploy.
    `schema.sql` guards every table with `CREATE TABLE IF NOT EXISTS`, so
    replaying it on a host that already has its tables is free -- and that is
    exactly the trap: a column ADDED to an existing table is never applied,
    the replay reports success, and the next thing to touch that column is
    what fails. On the Dell it was the GRANT:

        ERROR: column "visibility" of relation "forum_message" does not exist

    So the migration section at the end of `schema.sql` carries an
    `ADD COLUMN IF NOT EXISTS` per added column. What is proven here is that
    those statements DO repair a database missing them: the columns are
    dropped, the schema is replayed, and they must come back -- with their
    type, their NOT NULL and their DEFAULT.

    ANY FUTURE COLUMN ADDED TO AN EXISTING TABLE NEEDS ITS LINE THERE TOO, and
    this test only guards the ones already written. The rule itself is spelled
    out in `schema.sql`; a host that skips it fails the way this one did.
    """
    import psycopg
    # What the migration section is responsible for. The CHECK travels with
    # `visibility` because dropping the column drops the constraint too.
    added = {
        "forum_message": ("step", "blocked_kind", "visibility"),
        "forum_profile": ("alias", "plate_frame", "badges_public",
                          "leaderboard_opt_in"),
    }
    with open(os.path.join(HERE, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()

    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        def columns(table):
            return {row[0]: (row[1], row[2]) for row in cx.execute(
                "SELECT column_name, is_nullable, column_default"
                "  FROM information_schema.columns WHERE table_name = %s",
                (table,))}

        before = {table: columns(table) for table in added}
        # DROPPING A COLUMN DESTROYS ITS GRANTS, and that is not a detail of
        # this test -- it is why the Ansible role applies the schema BEFORE it
        # grants, and why re-granting is safe to replay. Here it has to be
        # undone: every check after this one writes as `ctester_app`, and
        # `forum_open_to_group` would fail on a `visibility` it may no longer
        # update -- which reads as a broken UPDATE rather than a lost GRANT.
        privileges = list(cx.execute(
            "SELECT grantee, table_name, column_name, privilege_type"
            "  FROM information_schema.column_privileges"
            " WHERE table_name = ANY(%s) AND column_name = ANY(%s)"
            "   AND grantee <> current_user",
            (list(added), [n for names in added.values() for n in names])))

        # BACK TO AN OLDER HOST: drop what the redesign added, and widen
        # nothing -- this is the shape the Dell was in when the deploy failed.
        for table, names in added.items():
            for name in names:
                cx.execute("ALTER TABLE %s DROP COLUMN IF EXISTS %s"
                           % (table, name))
        cx.execute("ALTER TABLE forum_moderation"
                   " DROP CONSTRAINT IF EXISTS forum_moderation_action_check")
        cx.execute("ALTER TABLE forum_moderation ADD CONSTRAINT"
                   " forum_moderation_action_check"
                   " CHECK (action IN ('hide', 'restore'))")

        cx.execute(sql)                                   # the role's replay

        for table, names in added.items():
            now = columns(table)
            for name in names:
                assert name in now, \
                    "%s.%s was not restored by replaying schema.sql" % (table, name)
                assert now[name] == before[table][name], \
                    "%s.%s came back different: %r then %r" % (
                        table, name, before[table][name], now[name])

        # AND THE WIDENED CHECK COMES BACK. This is the half that would not
        # have failed the deploy at all: the old constraint still read
        # ('hide', 'restore'), and the first click on "Retenir comme réponse"
        # would have been refused months later with nothing explaining it.
        action_check = cx.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            "  WHERE conrelid = 'forum_moderation'::regclass"
            "    AND conname = 'forum_moderation_action_check'").fetchone()[0]
        for verb in ("hide", "restore", "retain", "unretain"):
            assert verb in action_check, (verb, action_check)

        # REPLAYING AGAIN CHANGES NOTHING: the migrations run on every
        # converge, so one that only worked once would break the next run.
        cx.execute(sql)
        for table, names in added.items():
            assert columns(table) == before[table], table

        # THE GRANTS THE DROP TOOK WITH IT, PUT BACK -- this is exactly what
        # the role's GRANT tasks do after applying the schema, replayed here
        # for the same reason: everything below writes as `ctester_app`.
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


def schema_migrates_a_roster_shaped_team_table():
    """LA FORME QU'AVAIT `team` AVANT QUE LES ÉQUIPES NE SE CHOISISSENT.

    CE CONTRÔLE EXISTE PARCE QUE LA PANNE EST ARRIVÉE DEUX FOIS, à l'identique,
    et les deux fois UNIQUEMENT EN PRODUCTION -- `invite_code`, puis `number` :

        ERROR: column "number" does not exist

    Le mécanisme : sur une base où `team` existe déjà, `CREATE TABLE IF NOT
    EXISTS` ne fait rien, donc une colonne ajoutée dans la DÉCLARATION n'existe
    pas -- c'est l'`ALTER` de la section migration qui la pose. Tout ce qui la
    référence avant cet `ALTER` (un index, une contrainte) fait alors tomber
    toute la convergence sous `ON_ERROR_STOP=1`. Sur une base neuve, rien ne se
    voit.

    `test_ctester.py::test_aucun_index_ne_precede_la_colonne_qu_il_indexe`
    attrape la faute par lecture, sans Postgres, donc il part avec le tick.
    Celui-ci pose la VRAIE table d'hier et la migre : c'est le seul qui prouve
    que les données survivent au passage.
    """
    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        # La forme « listage » : pas de `number`, `group_number` obligatoire,
        # et aucune des colonnes du protocole de confirmation.
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

    apply_schema()          # DEUX FOIS : la réparation doit être rejouable.

    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        ligne = cx.execute(
            "SELECT group_number, number, label FROM team"
            " WHERE team_id = 'g04-e01'").fetchone()
        # LES DONNÉES SURVIVENT, et la colonne neuve arrive remplie : un
        # `SET NOT NULL` sur une colonne vide ferait tomber la convergence
        # aussi sûrement qu'un index prématuré.
        assert ligne == (4, 1, "Équipe 1"), ligne
        assert cx.execute("SELECT count(*) FROM team_member").fetchone()[0] == 1
        # ET L'INDEX EST LÀ, celui qui échouait.
        assert cx.execute(
            "SELECT count(*) FROM pg_indexes"
            " WHERE indexname = 'team_number_idx'").fetchone()[0] == 1
    _reset_teams()
    print("ok   schema.sql migre la table `team` d'hier sans perdre de ligne")


def append_only():
    """THE PROGRESSION TABLES ARE APPEND-ONLY, AND POSTGRES HOLDS IT.

    The application role has no `UPDATE` on them (see the GRANT in VHome).
    Ownership therefore does not depend on `state.py`'s discipline: a
    distracted line of Python cannot rewrite an XP grant after the fact, and
    fixing a mistake requires explicit admin access.

    Not played when both DSNs are the same -- there would be nothing to refuse.
    """
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
    # The draft wins over the submitted state: it is the work in progress.
    assert state.write_state(ALICE, "tp2-ex3", "solved", {"submission.c": "sent"})
    assert state.read_resume(ALICE, "tp2-ex3")["submission.c"] == "int main(void){}"
    # AND "solved" DOES NOT GO BACKWARDS. People keep poking at a solved
    # exercise; without the schema's CASE, the dashboard would say the
    # opposite of what happened.
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
    # A malformed verdict must not violate the CHECK (passed <= total): the
    # bound lives both in Python AND in the schema, and it is the schema being
    # exercised here.
    assert state.write_practice_attempt(ALICE, "job-3", "tp2-ex3",
                                       {"status": "ok", "total": 1, "passed": 9})
    print("ok   practice attempt: idempotent per job, bounded by the schema")


def grants():
    """THE HEART OF THIS FILE: the data-modifying CTE feeding the INSERT."""
    granted = state.grant_first_solve(
        ALICE, "tp2-ex3", "reussite:tp2-ex3", 15, "first solve",
        "policy-1", {"job": "job-1", "difficulte": "foundation"}, 100)
    assert granted == 15, granted
    # REPLAYING THE SAME FACT GRANTS NOTHING. That is the one thing that makes
    # a replayed HTTP poll, a restarted worker and a redone exercise harmless.
    for _ in range(3):
        assert state.grant_first_solve(
            ALICE, "tp2-ex3", "reussite:tp2-ex3", 15, "first solve",
            "policy-1", {"job": "job-9"}, 100) is None
    assert count("xp_transaction", ALICE) == 1
    assert count("progress_event", ALICE) == 1

    # THE CAP IS COMPUTED WITHIN THE STATEMENT. Past it, the fact is recorded
    # at zero rather than disappearing -- and the CHECK (amount >= 0) accepts it.
    assert state.grant_first_solve(
        ALICE, "tp2-ex0", "reussite:tp2-ex0", 30, "first solve",
        "policy-1", {"job": "job-4"}, 20) == 5           # 20 - 15 already granted
    assert state.grant_first_solve(
        ALICE, "tp7-ex1", "reussite:tp7-ex1", 30, "first solve",
        "policy-1", {"job": "job-5"}, 20) == 0           # cap reached
    assert count("xp_transaction", ALICE) == 3
    print("ok   grant: once per fact, cap applied within the same statement")


def achievements_and_reading():
    # `unnest(%s::text[])`: a parameterized array, not a list of VALUES built
    # in Python. This is the shape that only exists in real SQL.
    assert state.unlock(ALICE, ["premiere-reussite", "premiere-competence"],
                       "reussite:tp2-ex3", "policy-1")
    assert state.unlock(ALICE, ["premiere-reussite", "cinq-reussites"],
                       "reussite:tp2-ex0", "policy-1")
    assert count("achievement_unlocked", ALICE) == 3     # not 4: one duplicate
    assert state.unlock(ALICE, [], "reussite:tp2-ex3", "policy-1")

    view = state.read_progress(ALICE)
    assert view["xp"] == 20, view                        # 15 + 5 + 0
    # CHRONOLOGICAL FIRST, alphabetical on a tied timestamp. The first two
    # arrived in the same statement, so at the same microsecond: without
    # `achievement_id` as the second criterion, their order would be whatever
    # Postgres feels like returning, and it would change between calls right
    # in front of the student.
    assert [s["id"] for s in view["achievements"]] == [
        "premiere-competence", "premiere-reussite", "cinq-reussites"], view["achievements"]
    assert all(len(s["unlocked_at"]) == 10 for s in view["achievements"]), view["achievements"]
    assert len(view["transactions"]) == 3
    assert view["transactions"][0]["reason"] == "first solve"
    print("ok   achievements without duplicates, and reading the facts (day-level dates)")


def mastery_evidence():
    """The journal's other write: a fact WITHOUT XP, and reading it back typed.

    No new table -- it is `progress_event` that carries both. This check is
    therefore also proof that the existing GRANT is enough: if phase 2 had
    needed one more privilege, it would fail here.
    """
    written = state.record_event(ALICE, "verification:verif-tp2:job-v1",
                              "VerificationEvaluated", "verif-tp2", "policy-1",
                              {"job": "job-v1", "passed": False})
    assert written == "verification:verif-tp2:job-v1", written
    # Replaying the same poll writes nothing: same key, same refusal.
    assert state.record_event(ALICE, "verification:verif-tp2:job-v1",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v1", "passed": True}) is None
    # A RETRY, though, is a different job and so a different fact: attempts
    # stay historical.
    assert state.record_event(ALICE, "verification:verif-tp2:job-v2",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v2", "passed": True})

    facts = state.read_events(ALICE, "VerificationEvaluated")
    # NEWEST FIRST: it is the latest attempt that makes the band.
    assert [f["payload"]["job"] for f in facts] == ["job-v2", "job-v1"], facts
    assert facts[0]["payload"]["passed"] is True
    assert facts[0]["exercise_id"] == "verif-tp2"
    # THE TYPE FILTER IS REAL: practice solves from the same account live in
    # the same table and must not surface here.
    assert count("progress_event", ALICE) > len(facts)
    assert state.read_events(ALICE, "ExerciceReussi")
    # And none of this touched the balance.
    assert state.read_progress(ALICE)["xp"] == 20

    # `payload` IS PLAIN TEXT (see schema.sql) -- nothing in Postgres enforces
    # it stays valid JSON. A row written outside the app's own INSERT (an old
    # schema version, a manual fix) must not crash the read; it degrades to
    # `{}`, like every other malformed value this module refuses to trust.
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
    """WHAT ACTUALLY MATTERS: nobody sees or erases a neighbor's data."""
    assert state.write_draft(BOB, "tp2-ex3", {"submission.c": "// bob"})
    assert state.grant_first_solve(
        BOB, "tp2-ex3", "reussite:tp2-ex3", 15, "first solve",
        "policy-1", {"job": "job-b"}, 100) == 15
    # THE SAME EVENT ID FOR TWO STUDENTS: the primary key carries `account`, so
    # "reussite:tp2-ex3" belongs to nobody. A primary key on the id alone would
    # have given Bob Alice's XP.
    assert state.unlock(BOB, ["premiere-reussite"], "reussite:tp2-ex3", "policy-1")
    assert state.read_progress(BOB)["xp"] == 15
    assert state.read_progress(ALICE)["xp"] == 20
    print("ok   two accounts, the same fact, no mixing")


def forum():
    """The forum: one thread per exercise, a unique report, a journaled
    moderation action -- and the data-modifying CTE that writes the state AND
    the journal at once.
    """
    m1, m2 = "a" * 32, "b" * 32
    assert state.forum_publier(m1, "tp2-ex3", ALICE, "Why does my loop spin?")
    assert state.forum_publier(m2, "tp2-ex3", BOB, "same problem here")
    assert state.forum_publier("c" * 32, "tp2-ex0", BOB, "another exercise")
    thread = state.forum_fil("tp2-ex3", 200)
    assert [m["id"] for m in thread] == [m1, m2], thread
    assert thread[0]["account"] == ALICE and thread[0]["hidden"] is False
    # AT THE MINUTE, not the day: a thread is read in order. AND IN EXPLICIT
    # UTC: without the "Z", the page displays server time as if it were the
    # reader's.
    assert len(thread[0]["created_at"]) == 17 and thread[0]["created_at"].endswith("Z"), \
        thread[0]["created_at"]
    # ONE THREAD PER EXERCISE: nothing leaks from one exercise into another.
    assert len(state.forum_fil("tp2-ex0", 200)) == 1
    # LA LIMITE BORNE LES RACINES, ET GARDE LES PLUS RÉCENTES. Elle gardait
    # les plus ANCIENNES : sur un fil de dix mille messages, cela affichait
    # les deux cents premiers messages du semestre et jamais celui qu'on vient
    # d'écrire. La fenêtre remonte donc le temps depuis maintenant, puis rend
    # ce qu'elle a gardé dans l'ordre de lecture.
    assert state.forum_fil("tp2-ex3", 1) == thread[-1:]

    # THE PRIMARY KEY IS THE RULE: the same report twice is one row.
    assert state.forum_signaler(m2, ALICE) == [(m2,)]
    assert state.forum_signaler(m2, ALICE) == []
    # And a made-up id inserts NOTHING -- no orphan row carrying a `sub` for
    # nothing. It is the `SELECT ... FROM forum_message` that holds it.
    assert state.forum_signaler("f" * 32, ALICE) == []
    assert count("forum_report", ALICE) == 1
    assert state.forum_signaler(m2, BOB) == [(m2,)]       # two accounts, yes
    queue = state.forum_signalements(200)
    assert len(queue) == 1, queue
    assert queue[0]["id"] == m2 and queue[0]["report_count"] == 2
    assert queue[0]["text"] == "same problem here"
    assert queue[0]["exercise_id"] == "tp2-ex3"

    # HIDE, THEN RESTORE: the state changes, the journal grows, in ONE
    # statement. Two autocommit `_query` calls would leave a hidden message
    # that nothing explains if the connection dropped in between.
    assert state.forum_moderer("d" * 32, m2, ALICE, "hide") == [(m2,)]
    assert state.forum_fil("tp2-ex3", 200)[1]["hidden"] is True
    assert state.forum_moderer("e" * 32, m2, ALICE, "restore") == [(m2,)]
    assert state.forum_fil("tp2-ex3", 200)[1]["hidden"] is False
    assert count("forum_moderation", ALICE) == 2          # APPEND-ONLY: both stay
    assert state.forum_moderer("9" * 32, "f" * 32, ALICE, "hide") == []
    # THE SCHEMA'S CHECK, EXERCISED WITHOUT GOING THROUGH THE PYTHON GUARD: two
    # actions exist, and it is Postgres that refuses the third.
    assert state._query(
        "INSERT INTO forum_moderation"
        " (action_id, message_id, account, action)"
        " VALUES (%s, %s, %s, 'supprimer')",
        ("7" * 32, m2, ALICE)) is None

    # DELETE YOUR OWN, NEVER SOMEONE ELSE'S. The `account` clause IS the
    # access control: there is no prior read to make lie.
    assert state.forum_supprimer(m2, ALICE) == []         # not theirs
    assert state.forum_supprimer(m1, ALICE) == [(m1,)]
    assert state.forum_supprimer(m1, ALICE) == []         # already gone
    assert [m["id"] for m in state.forum_fil("tp2-ex3", 200)] == [m2]
    # Give them one back: `deletion()` below checks that EVERY table had
    # something to erase.
    assert state.forum_publier("1" * 32, "tp2-ex3", ALICE, "I'm back")
    print("ok   forum: thread per exercise, unique report, journaled moderation")


def identity():
    """The chosen name and group number: a JOURNAL whose last row is
    authoritative.

    THE TWO SHAPES THAT ONLY GET EXERCISED ON A REAL DATABASE: the
    `DISTINCT ON (account) ... ORDER BY account, created_at DESC` that brings
    back the latest profile for several accounts in one pass, and the LATERAL
    join that hangs that same latest profile off every reported name. Both
    compile in your head.
    """
    # Nothing set: not an error, it is anonymity by default.
    assert state.forum_profils([ALICE, BOB]) == {}
    # `EMPTY_PROFILE`, RATHER THAN A LITERAL: the redesign added four
    # preference columns, and a copy here would have failed this check for the
    # sole reason that it did not know about them. What is being proven is
    # that an account with no row reads as an empty profile, not the list of
    # columns.
    assert state.forum_profil(ALICE) == state.EMPTY_PROFILE
    assert state.forum_profil_ecrire("p" * 32, ALICE, "Alice", 3, True, False)
    assert state.forum_profil_ecrire("q" * 32, BOB, "Bob", 7, False, True)
    # THE LAST ROW IS AUTHORITATIVE, and the old one stays: changing a name
    # does not erase the history a moderator wants to be able to read back.
    assert state.forum_profil_ecrire("r" * 32, ALICE, "Alice B", 3, True, True)
    assert count("forum_profile", ALICE) == 2
    profiles = state.forum_profils([ALICE, BOB, "sub-personne"])
    assert profiles[ALICE] == dict(state.EMPTY_PROFILE, display_name="Alice B",
                                   group_number=3, display_name_public=True,
                                   group_number_public=True)
    assert profiles[BOB]["display_name"] == "Bob" and profiles[BOB]["group_number"] == 7
    assert "sub-personne" not in profiles
    # THE SCHEMA'S CHECK, EXERCISED WITHOUT GOING THROUGH THE PYTHON GUARD: a
    # group runs from 1 to 99, and Postgres refuses the rest.
    assert state.forum_profil_ecrire("s" * 32, ALICE, "Alice", 0, False, False) \
        is False
    assert state.forum_profil_ecrire("t" * 32, ALICE, "Alice", 100, False, False) \
        is False

    # REPORTING A NAME: same two protections as for a message.
    message = state.forum_fil("tp2-ex3", 200, ALICE)[0]["id"]
    assert state.forum_auteur(message) in (ALICE, BOB)
    assert state.forum_auteur("f" * 32) is None
    assert state.forum_nom_signaler(message, BOB) == [(message,)]
    assert state.forum_nom_signaler(message, BOB) == []      # only once
    assert state.forum_nom_signaler("f" * 32, BOB) == []     # nothing orphaned
    reported = state.forum_noms_signales(200)
    assert len(reported) == 1 and reported[0]["id"] == message, reported
    # THE LATERAL JOIN: the name returned is the LATEST, not the first.
    author = state.forum_auteur(message)
    assert reported[0]["display_name"] == \
        state.forum_profils([author])[author]["display_name"]
    assert reported[0]["report_count"] == 1
    # ALICE REPORTS IN TURN, on another message. Without this line she has NO
    # row in `forum_reported_name`, and `deletion()`'s precondition ("there is
    # something to erase in the thirteen tables") does not hold -- meaning the
    # most recently added table is the only one whose erasure is not exercised.
    assert state.forum_nom_signaler("b" * 32, ALICE) == [("b" * 32,)]
    print("ok   identity: journal, last row wins, schema bounds, reported name")


def stuck_and_helpful():
    """WHAT ONLY A REAL DATABASE PROVES about the redesign's two new writes.

    Both are the kind of statement that compiles in your head and fails in
    production:

      * `forum_open_to_group` is an UPDATE whose `WHERE` IS the access
        control AND the one-way rule at once -- `account = %s AND visibility =
        'private'`. Split into a read then a write, two clicks could race
        past it; written this way, the second one finds nothing.
      * `forum_voter` is an `INSERT ... SELECT` whose `WHERE` refuses one's
        own message AND -1 on a question, over a primary key that turns the
        second vote into a change of mind. Four rules, one statement.

    And `forum_fil`'s LATERAL join, which derives the retained answer from
    the append-only journal rather than from a column.
    """
    BLOQUE = "8" * 32
    thread = state.forum_fil("tp2-ex3", 200, ALICE)
    assert thread, "the forum() step should have left a message behind"

    # A "stuck here" post: private by default, and only its author sees it in
    # the raw row -- `forum_vue` does the filtering, this proves the storage.
    assert state.forum_publier(BLOQUE, "tp2-ex3", ALICE, "stuck",
                               "compilation", "unclear-error", "private")
    stuck = [m for m in state.forum_fil("tp2-ex3", 200, ALICE)
             if m["id"] == BLOQUE][0]
    assert stuck["visibility"] == "private" and stuck["step"] == "compilation"

    # THE `WHERE` IS THE RULE. Not theirs: nothing. Theirs: once, and only
    # from `private` -- replaying finds nothing to open, so the reverse
    # transition cannot be expressed at all.
    assert state.forum_open_to_group(BLOQUE, BOB) == []
    assert state.forum_open_to_group(BLOQUE, ALICE) != []
    assert state.forum_open_to_group(BLOQUE, ALICE) == []
    assert [m for m in state.forum_fil("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["visibility"] == "group"

    # LE VOTE : son propre message refusé, un id inventé refusé, et le second
    # vote qui devient un changement d'avis -- tout par la même instruction.
    assert state.forum_voter(BLOQUE, ALICE, 1) == []           # one's own row
    assert state.forum_voter("0" * 32, BOB, 1) == []           # unknown id
    assert state.forum_voter(BLOQUE, BOB, 1) != []
    assert state.forum_voter(BLOQUE, BOB, 1) != []             # idempotent
    # LE -1 SUR UNE QUESTION EST REFUSÉ PAR L'INSTRUCTION, et c'est LA règle
    # qui compte : une question ne peut pas être enterrée par un vote. On
    # l'éprouve en l'envoyant, parce que la page ne dessine pas ce bouton --
    # ce qui n'est justement pas ce qui l'interdit.
    assert state.forum_voter(BLOQUE, BOB, -1) == []
    seen = [m for m in state.forum_fil("tp2-ex3", 200, BOB)
           if m["id"] == BLOQUE][0]
    assert seen["upvotes"] == 1 and seen["downvotes"] == 0
    assert seen["my_vote"] == 1
    assert [m for m in state.forum_fil("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["my_vote"] == 0
    # AND THE OTHER WAY AROUND, on a message BOB posted elsewhere: voting is
    # symmetric, and `forget` must erase both sides.
    assert state.forum_voter("c" * 32, ALICE, 1) != []

    # UNE RÉPONSE, ELLE, ACCEPTE LE -1 -- et le `WHERE` de l'INSERT est ce qui
    # fait la différence entre les deux, pas un `if` quelque part.
    REPONSE = "7" * 32
    assert state.forum_repondre(REPONSE, "tp2-ex3", BOB, "essaie ça", BLOQUE) != []
    # L'APLATISSEMENT : répondre à une RÉPONSE vise la RACINE.
    ENCORE = "6" * 32
    assert state.forum_repondre(ENCORE, "tp2-ex3", ALICE, "merci", REPONSE) != []
    par_id = {m["id"]: m for m in state.forum_fil("tp2-ex3", 200, ALICE)}
    assert par_id[REPONSE]["reply_to"] == BLOQUE
    assert par_id[ENCORE]["reply_to"] == BLOQUE, "une réponse vise la RACINE"
    # LE `WHERE` REFUSE UNE RACINE D'UN AUTRE FIL, et un id inventé.
    assert state.forum_repondre("5" * 32, "tp2-ex0", BOB, "x", BLOQUE) == []
    assert state.forum_repondre("5" * 32, "tp2-ex3", BOB, "x", "0" * 32) == []
    assert state.forum_voter(REPONSE, ALICE, -1) != []
    assert state.forum_voter(REPONSE, ALICE, 1) != []          # changement d'avis
    apres = {m["id"]: m for m in state.forum_fil("tp2-ex3", 200, ALICE)}
    assert apres[REPONSE]["upvotes"] == 1 and apres[REPONSE]["downvotes"] == 0
    assert state.forum_devoter(REPONSE, ALICE) != []
    assert state.forum_devoter(REPONSE, ALICE) == []
    assert {m["id"]: m for m in state.forum_fil("tp2-ex3", 200, ALICE)}[
        REPONSE]["upvotes"] == 0

    # LA FENÊTRE SE BORNE PAR RACINE : une réponse ne survit JAMAIS sans sa
    # question. Avec une limite de 1, on obtient la dernière racine ET toutes
    # ses réponses -- jamais une réponse orpheline.
    court = state.forum_fil("tp2-ex3", 1, ALICE)
    racines = [m for m in court if not m["reply_to"]]
    assert len(racines) == 1, court
    assert all(m["reply_to"] == racines[0]["id"]
               for m in court if m["reply_to"]), court

    # LE PERMALIEN rend la conversation entière, depuis n'importe lequel de
    # ses messages -- c'est ce qui donne un point d'arrivée à la recherche.
    fil_cle, conv = state.forum_conversation(ENCORE, ALICE)
    assert fil_cle == "tp2-ex3"
    assert {m["id"] for m in conv} == {BLOQUE, REPONSE, ENCORE}
    assert state.forum_conversation("0" * 32, ALICE) == (None, [])

    # LA RECHERCHE : LA CLAUSE DE CONFIDENTIALITÉ EST LE `WHERE`. Une question
    # privée ne remonte que chez son auteur -- pas chez un autre compte, et
    # PAS chez un modérateur non plus, qui n'a aucune exception ici.
    PRIVEE = "4" * 32
    assert state.forum_publier(PRIVEE, "tp2-ex3", ALICE,
                               "mon segfault mysterieux", "execution",
                               "wrong-result", "private")
    a_elle = [r["id"] for r in state.forum_search("segfault", ALICE, 5)]
    a_lui = [r["id"] for r in state.forum_search("segfault", BOB, 5)]
    assert PRIVEE in a_elle, a_elle
    assert PRIVEE not in a_lui, a_lui
    assert state.forum_search("", ALICE, 5) == []
    # `websearch_to_tsquery` NE LÈVE PAS sur une entrée hostile : c'est ce qui
    # permet de l'appeler à chaque frappe sans valider quoi que ce soit avant.
    for hostile in ("&& ||", '"', "a:*!", "'; DROP TABLE forum_message; --"):
        assert state.forum_search(hostile, ALICE, 5) is not None, hostile

    # « QUESTIONS DU MOMENT » : des RACINES, jamais des réponses -- sinon les
    # réponses passeraient devant les questions qu'elles répondent.
    top = state.forum_top(24, 50)
    assert top is not None and all(r["id"] != REPONSE for r in top), top
    assert any(r["id"] == BLOQUE for r in top)

    # THE RETAINED ANSWER IS DERIVED FROM THE JOURNAL, and reversible, and it
    # edits NOTHING: the text is byte-for-byte what it was.
    before = seen["text"]
    assert state.forum_moderer("m" * 32, BLOQUE, BOB, "retain") != []
    retained = [m for m in state.forum_fil("tp2-ex3", 200, ALICE)
                if m["id"] == BLOQUE][0]
    assert retained["retained"] is True and retained["text"] == before
    assert state.forum_moderer("n" * 32, BLOQUE, BOB, "unretain") != []
    assert [m for m in state.forum_fil("tp2-ex3", 200, ALICE)
            if m["id"] == BLOQUE][0]["retained"] is False

    # THE INSTRUCTOR'S AGGREGATE: counts and steps, and nothing that names
    # anyone. `min(created_at)` and the FILTER both need a real planner.
    rows = state.forum_help_rows(50, 24)
    line = [r for r in rows if r["step"] == "compilation"][0]
    assert line["people"] == 1 and line["opened"] == 1, line
    assert "account" not in line and "text" not in line, line

    # THE CALENDAR: a GROUP BY over dates, which is the whole feature.
    days = state.read_practice_days(ALICE, 91)
    assert isinstance(days, list)
    assert all(set(d) == {"date", "attempts"} for d in days), days
    print("ok   stuck/helpful: one-way transition, three refusals, "
          "derived retention")


def leaderboard_rows():
    """THE RANKING'S ONE QUERY, and it is not an ordinary one.

    A `DISTINCT ON` sub-select for the latest profile, a LEFT JOIN so an
    opted-in account with a quiet week still produces a row, and a
    `count(...) FILTER (WHERE ...)` for the window. Every part of that
    compiles in your head and can still be wrong.

    OPT-IN IS THE `WHERE`, not a filter applied afterwards: an account that
    did not tick the box must produce NO ROW, so there is nothing downstream
    to forget to hide.
    """
    assert state.forum_profil_ecrire("u" * 32, ALICE, "Alice", 3, True, True,
                                     alias="Rotor cuivre", leaderboard_opt_in=True)
    assert state.forum_profil_ecrire("v" * 32, BOB, "Bob", 3, False, True,
                                     alias="Palier lisse", leaderboard_opt_in=False)
    rows = state.leaderboard_rows(3, 7)
    assert [r["account"] for r in rows] == [ALICE], rows
    # A quiet week still produces a row, at zero: the cohort size is what the
    # privacy threshold reads, and it must not depend on the week.
    assert rows[0]["recent"] >= 0 and rows[0]["lifetime"] >= rows[0]["recent"]
    # The whole course, and a group nobody is in.
    assert [r["account"] for r in state.leaderboard_rows(None, 7)] == [ALICE]
    assert state.leaderboard_rows(99, 7) == []
    # Opting in later adds the row, with no other change to the profile.
    assert state.forum_profil_ecrire("w" * 32, BOB, "Bob", 3, False, True,
                                     alias="Palier lisse", leaderboard_opt_in=True)
    assert {r["account"] for r in state.leaderboard_rows(3, 7)} == {ALICE, BOB}
    assert state.forum_taken_aliases() == {"Rotor cuivre", "Palier lisse"}
    # THE OBSERVED RARITY: two aggregates over real rows.
    rates, cohort = state.read_unlock_rates()
    assert isinstance(rates, dict) and cohort >= 1, (rates, cohort)
    print("ok   leaderboard: opt-in is the WHERE, a quiet week still counts")


def forum_privileges():
    """The forum GRANT: the API updates `hidden`, AND NOTHING ELSE.

    INCLUDING THE PROFILE: the chosen name and its visibility are an
    append-only journal, with no updatable column at all.

    This is a COLUMN GRANT (`UPDATE (hidden)`), not a table `UPDATE`. A
    message is immutable: the API must not be able to rewrite someone's text,
    change a report's author, or touch up the moderation journal. Ownership
    therefore does not depend on `state.py`'s discipline.

    Not played when both DSNs are the same -- there would be nothing to refuse.
    """
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
        # IDENTITY IS A JOURNAL TOO: a row is added, the name someone gave
        # themselves is not rewritten. Without this refusal, a stray query
        # could silently rename a student.
        ("forum_profile.display_name", "UPDATE forum_profile SET display_name = 'other'"),
        ("forum_profile.display_name_public",
         "UPDATE forum_profile SET display_name_public = true"),
        ("forum_reported_name",
         "UPDATE forum_reported_name SET account = 'sub-x'"),
        # "CA M'A AIDE" IS A FACT, NOT A COUNTER TO EDIT. Without this
        # refusal, a stray query could move someone's mark onto another
        # account -- the same class of rewrite the message text is protected
        # from.
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
    # AND THE TWO ALLOWED COLUMNS GO THROUGH. `hidden` is what moderation
    # changes; `visibility` is what an author changes to open their own
    # private question to their group. Without this half of the check, a GRANT
    # too narrow would leave either one mute in production and nowhere else --
    # which is exactly how the theme's missing `UPDATE` was found.
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("UPDATE forum_message SET hidden = hidden")
        cx.execute("UPDATE forum_message SET visibility = visibility")
        # ET LA TROISIÈME COLONNE ÉCRIVABLE DU FORUM : le signe d'un vote,
        # qu'on change en changeant d'avis (`ON CONFLICT ... DO UPDATE`). Sans
        # ce GRANT, « retirer mon vote » et « changer d'avis » échoueraient en
        # production et nulle part ailleurs -- la panne exacte que l'`UPDATE`
        # manquant du thème a coûté une fois.
        cx.execute("UPDATE forum_helpful SET value = value")
    print("ok   forum: only `hidden` and `visibility` are writable, "
          "the rest is append-only")


def preferences():
    """THE THEME: the only write in this file that OVERWRITES instead of appending.

    This is an `ON CONFLICT ... DO UPDATE` on the primary key, and it requires
    an UPDATE GRANT the progression tables do not have. Replaying it must
    replace the row, not add a second one nor raise.
    """
    assert state.read_theme(ALICE) == "", "a fresh account has no theme"
    assert state.write_theme(ALICE, "light")
    assert state.read_theme(ALICE) == "light"
    assert state.write_theme(ALICE, "dark")               # overwrites, does not duplicate
    assert state.read_theme(ALICE) == "dark"
    assert count("display_preference", ALICE) == 1
    # THE SCHEMA'S CHECK IS THE LAST BARRIER, and `write_theme` should not even
    # reach it: a value off the list comes back False without touching the DB.
    assert state.write_theme(ALICE, "neon") is False
    assert state.read_theme(ALICE) == "dark"
    # ISOLATED LIKE THE REST: Alice's theme is not Bob's.
    assert state.write_theme(BOB, "light")
    assert state.read_theme(ALICE) == "dark" and state.read_theme(BOB) == "light"
    print("ok   the theme writes, overwrites, and stays this account's own")


def deletion():
    before = {t: count(t, ALICE) for t in TABLES}
    assert all(before.values()), "useless test: nothing to erase " + str(before)
    assert state.forget(ALICE)
    after = {t: count(t, ALICE) for t in TABLES}
    assert not any(after.values()), after
    # THE TWELVE DELETEs ARE IN A SINGLE STATEMENT, and the unreferenced CTEs
    # run anyway -- that is what is checked here, not PostgreSQL's docs.
    assert count("exercise_draft", BOB) == 1, "erased from the neighbor!"
    assert state.read_progress(BOB)["xp"] == 15
    # AND THE NEIGHBOR'S MESSAGES STAY. Erasing one's account does not erase
    # other people's conversation -- only what this person wrote.
    # (deux messages plus la réponse que BOB a écrite sous la question d'ALICE
    # : c'est justement le cas qui compte -- effacer un compte ne doit pas
    # emporter la réponse que quelqu'un d'autre a écrite dedans.)
    assert count("forum_message", BOB) == 3, "message erased from the neighbor!"
    assert count("forum_report", BOB) == 1
    assert state.forget(ALICE)                            # replayable
    # ET LE TRAVAIL DE L'ÉQUIPE SURVIT. Effacer un membre ne doit pas emporter
    # le devoir de trois autres personnes : ce n'est pas un effacement, c'est
    # la suppression des données de quelqu'un d'autre. Ce qui part, c'est
    # l'appartenance d'alice et les révisions qu'elle a signées.
    assert _rows("SELECT count(*) FROM team_document WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team_submission WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team WHERE team_id = 'g04-e01'") == 1
    assert _rows("SELECT count(*) FROM team_member"
                 " WHERE team_id = 'g04-e01' AND account = %s", (CLEO,)) == 1
    print("ok   \"Delete my data\" empties the fifteen account tables, leaves "
          "the team's work, and touches nobody else's")


def _inscrire(assignment_id, groupe, numero, comptes):
    """Une équipe déjà constituée, avec les droits de l'ADMIN.

    Volontairement écrit ici plutôt qu'appelé via `state` : l'application n'a
    ni UPDATE ni DELETE sur `team`, et `team_privileges()` plus bas le prouve.
    """
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
    """Les tables d'équipe, remises à zéro par l'ADMIN.

    Ce fichier écrit dans une base qui SURVIT d'une exécution à l'autre, et
    `forget()` ne touche pas les trois tables d'équipe -- c'est justement ce
    qu'il doit faire. Sans ce nettoyage, la deuxième exécution partirait d'un
    listage de la première et ne prouverait plus ce qu'elle croit prouver.
    """
    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        cx.execute("DELETE FROM team_submission")
        cx.execute("DELETE FROM team_revision")
        cx.execute("DELETE FROM team_document")
        cx.execute("DELETE FROM team_member")
        cx.execute("DELETE FROM team")


def teams():
    """LE CHOIX D'ÉQUIPE, ET LES DEUX FORMES QUI N'EXISTENT QU'EN VRAI.

    La première : `team_join` crée l'équipe si personne n'y était encore ET
    compte la place dans le `WHERE` de l'INSERT -- une CTE modifiante qui
    alimente un `INSERT ... SELECT ... WHERE`, la forme qui compile dans la
    tête et échoue en production. Deux étudiants sur la dernière place
    passeraient tous les deux un `if` posé côté routeur.

    La seconde : la clé primaire `(assignment_id, account)` EST la règle « une
    seule équipe par devoir », et la clé étrangère composite refuse une
    appartenance dont l'équipe n'existe pas -- deux instructions différentes
    les écrivent.
    """
    _reset_teams()
    # LES ÉQUIPES SONT CRÉÉES À LA VOLÉE : rien n'existe avant que quelqu'un
    # n'y entre. Peupler douze équipes vides par groupe à la publication
    # ferait douze lignes que personne ne lit.
    assert state.team_join(ALICE, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           4) == "g04-e01"
    assert state.team_join(CLEO, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           4) == "g04-e01"
    # DEUX FOIS, NON : la clé primaire dit qu'on est sur UNE équipe.
    assert state.team_join(ALICE, "devoir", "g04-e02", 4, 2, "Équipe 2",
                           4) is None

    equipe = state.team_of(ALICE, "devoir")
    assert equipe["team_id"] == "g04-e01" and equipe["number"] == 1
    assert equipe["group_number"] == 4 and equipe["label"] == "Équipe 1"
    assert state.team_of("sub-personne", "devoir") is None
    assert state.team_of(ALICE, "autre-devoir") is None
    assert sorted(state.team_roster("devoir", "g04-e01")) == sorted([ALICE, CLEO])

    # LA PLACE EST COMPTÉE DANS LE `WHERE`, jamais relue avant : une équipe
    # pleine refuse, et c'est Postgres qui compte.
    assert state.team_join(BOB, "devoir", "g04-e01", 4, 1, "Équipe 1",
                           2) is None
    assert state.team_join(BOB, "devoir", "g06-e01", 6, 1, "Équipe 1",
                           4) == "g06-e01"
    # DEUX GROUPES, DEUX « ÉQUIPE 1 », DEUX DOCUMENTS. Sans le groupe dans la
    # poignée, les deux sections travailleraient dans le même fichier.
    assert state.team_of(BOB, "devoir")["team_id"] == "g06-e01"
    assert state.team_roster("devoir", "g04-e01") != state.team_roster(
        "devoir", "g06-e01")

    # LA LISTE QUE L'ÉTUDIANT PARCOURT : par groupe, avec le remplissage, et
    # SANS aucun compte -- une liste de choix n'a pas à dire qui est où.
    liste = state.team_counts("devoir", 4)
    assert liste[0] == {"number": 1, "team_id": "g04-e01", "label": "Équipe 1",
                        "members": 2}, liste
    # `g04-e02` EXISTE ET EST VIDE : la tentative refusée plus haut a quand
    # même créé l'équipe, parce que la CTE qui la crée s'exécute toujours --
    # seule l'inscription a été refusée par la clé primaire. Sans effet
    # visible : le service liste de toute façon les `count` équipes du devoir,
    # celles qui ont une ligne comme celles qui n'en ont pas. Une ligne de
    # bruit vaut mieux qu'un aller-retour de vérification avant chaque INSERT.
    assert [e["members"] for e in liste] == [2, 0], liste
    assert state.team_counts("devoir", 6)[0]["members"] == 1

    # QUITTER LAISSE L'ÉQUIPE EN PLACE : son numéro est celui de Moodle, et
    # elle porte peut-être déjà un document. La supprimer renumérioterait tout.
    assert state.team_leave(CLEO, "devoir")
    assert state.team_of(CLEO, "devoir") is None
    assert state.team_counts("devoir", 4)[0]["members"] == 1

    # UNE APPARTENANCE SANS ÉQUIPE EST REFUSÉE PAR POSTGRES, pas par du Python.
    import psycopg
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        try:
            cx.execute("INSERT INTO team_member (team_id, assignment_id, account)"
                       " VALUES ('g09-e09', 'devoir', 'sub-x')")
            raise AssertionError("une équipe inexistante a été acceptée")
        except psycopg.errors.ForeignKeyViolation:
            pass

    # « MES ÉQUIPES », SANS DEVOIR : la lecture qui répond AVANT l'ouverture,
    # pour qu'un étudiant vérifie son choix pendant qu'il peut encore le
    # changer.
    _inscrire("autre-devoir", 6, 2, [ALICE])
    miennes = state.team_memberships(ALICE)
    assert {m["assignment_id"]: m["team_id"] for m in miennes} == {
        "devoir": "g04-e01", "autre-devoir": "g06-e02"}, miennes
    assert sorted(m["number"] for m in miennes) == [1, 2]
    assert state.team_memberships("sub-personne") == []
    print("ok   teams: on prend une place libre, la place est comptée dans le "
          "WHERE, et deux groupes ont chacun leur « Équipe 1 »")


def team_documents():
    """LA CTE MODIFIANTE QUI ALIMENTE L'INSERT DE RÉVISION, et sa coalescence.

    Repart du listage de `teams()` -- `team_formation()` vient de laisser une
    équipe scellée sous le même nom, et ce qui est éprouvé ici est le
    document, pas la façon dont l'équipe s'est constituée.

    C'est exactement la forme que ce fichier existe pour attraper : un UPSERT
    dans une CTE non référencée (qui doit s'exécuter quand même), suivi d'un
    `INSERT ... SELECT` dont le `WHERE NOT EXISTS` EST la règle de coalescence,
    plus un `IS DISTINCT FROM` sur une sous-requête ordonnée.
    """
    fenetre = 120
    _reset_teams()
    _inscrire("devoir", 4, 1, [ALICE, CLEO])
    _inscrire("devoir", 6, 1, [BOB])

    def ecrire(compte, texte, window=fenetre):
        return state.write_team_document("g04-e01", "dev-a", compte,
                                         {"main.c": texte}, uuid.uuid4().hex,
                                         window)

    # LE DOCUMENT VIDE ET LA BASE MUETTE NE SE RESSEMBLENT PAS : `{}` est une
    # équipe qui n'a pas commencé.
    assert state.read_team_document("g04-e01", "dev-a") == {}
    assert ecrire(ALICE, "un\n")
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "un\n"}
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 1

    # DANS LA FENÊTRE, LE MÊME AUTEUR N'EN OUVRE PAS UNE SECONDE : c'est ce
    # qui évite une ligne Postgres par frappe.
    assert ecrire(ALICE, "deux\n") and ecrire(ALICE, "trois\n")
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 1
    # ...et le DOCUMENT, lui, a bien suivi : l'UPSERT de la CTE s'exécute même
    # si personne ne le référence.
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "trois\n"}

    # UN AUTRE AUTEUR EN OUVRE UNE TOUT DE SUITE : sans ça, la trace du
    # coéquipier qui tape dans la fenêtre de quelqu'un d'autre n'existerait pas.
    assert ecrire(CLEO, "quatre\n")
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 2

    # DEUX ÉCRITURES IDENTIQUES N'EN FONT PAS DEUX (`IS DISTINCT FROM`).
    assert ecrire(CLEO, "quatre\n", window=0)
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 2
    # Une fenêtre nulle sur un texte DIFFÉRENT en ouvre une : c'est le chemin
    # de la restauration.
    assert ecrire(CLEO, "cinq\n", window=0)
    assert _rows("SELECT count(*) FROM team_revision WHERE team_id = 'g04-e01'") == 3

    lignes = state.read_team_revisions("g04-e01", "dev-a", 10)
    assert [r["account"] for r in lignes] == [CLEO, CLEO, ALICE], lignes
    assert all(r["bytes"] > 0 for r in lignes)

    # L'ÉQUIPE EST DANS LE `WHERE` : une révision de l'équipe 1 ne résout pas
    # pour l'équipe 2, et il n'y a donc aucun `if` à oublier côté Python.
    identifiant = lignes[0]["revision_id"]
    assert state.read_team_revision("g04-e01", identifiant) == {"main.c": "cinq\n"}
    assert state.read_team_revision("g06-e01", identifiant) == {}

    # DEUX ÉQUIPES, DEUX DOCUMENTS, sur le même exercice.
    assert state.write_team_document("g06-e01", "dev-a", BOB, {"main.c": "bob\n"},
                                     uuid.uuid4().hex, fenetre)
    assert state.read_team_document("g04-e01", "dev-a") == {"main.c": "cinq\n"}
    assert state.read_team_document("g06-e01", "dev-a") == {"main.c": "bob\n"}
    print("ok   team_document: un UPSERT et une révision coalescée en UNE "
          "instruction, isolés par équipe")


def team_submissions():
    """UNE SEULE REMISE PAR ÉQUIPE, tenue par la clé primaire."""
    assert state.read_team_submission("devoir", "g04-e01") == {}
    assert state.write_team_submission("devoir", "g04-e01", ALICE,
                                       {"Devoir/main.c": "x\n"})
    assert state.read_team_submission("devoir", "g04-e01")["submitted_by"] == ALICE
    # REMETTRE À NOUVEAU REMPLACE, ça n'ajoute pas une seconde remise : une
    # équipe qui trouve un bogue à 22 h doit pouvoir corriger.
    assert state.write_team_submission("devoir", "g04-e01", CLEO,
                                       {"Devoir/main.c": "y\n"})
    assert _rows("SELECT count(*) FROM team_submission WHERE team_id = 'g04-e01'") == 1
    assert state.read_team_submission("devoir", "g04-e01")["submitted_by"] == CLEO
    assert state.write_team_submission("devoir", "g06-e01", BOB, {"Devoir/main.c": "b\n"})
    assert state.read_team_submission("devoir", "g06-e01")["submitted_by"] == BOB
    # ET LE LISTAGE DE L'ENSEIGNANT COMPTE SANS NOMMER.
    equipes = {e["team_id"]: e for e in state.read_teams("devoir")}
    assert equipes["g04-e01"]["members"] == 2 and equipes["g04-e01"]["group_number"] == 4
    assert equipes["g06-e01"]["members"] == 1
    print("ok   team_submission: une seule remise par équipe, remplaçable")


def team_privileges():
    """CE QUI RESTE REFUSÉ, maintenant que les étudiants prennent leur place.

    La garantie a changé deux fois, et il faut savoir laquelle tient. Elle
    était « rejoindre est INEXPRIMABLE, il n'y a pas d'INSERT » -- tombée avec
    le listage, que l'enseignant ne pouvait pas écrire (il ne voit jamais un
    `sub`). Elle est maintenant :

      * le `WHERE` de chaque écriture (éprouvé par `teams()`) : la place est
        comptée dans l'INSERT, et le SERVICE n'y laisse passer que tant que le
        devoir est fermé ;
      * et CE QUI N'EST PAS ACCORDÉ DU TOUT, ici. Pas d'UPDATE sur `team` ni
        sur `team_member` : changer d'équipe, c'est en SORTIR et ENTRER
        ailleurs -- deux écritures dont chacune porte sa condition. Un UPDATE
        de `team_id` les contournerait toutes les deux, y compris la date.

    Non joué quand les deux DSN sont identiques -- il n'y aurait rien à refuser.
    """
    if ADMIN_DSN == DSN:
        print("--   team privileges: NOT PLAYED (no distinct CTESTER_DB_ADMIN_DSN)")
        return
    import psycopg
    refuses = (
        # UNE ÉQUIPE NE SE SUPPRIME NI NE SE MODIFIE DEPUIS L'APPLICATION :
        # elle porte le document de trois ou quatre personnes, et son numéro
        # est celui de Moodle.
        ("team DELETE", "DELETE FROM team WHERE team_id = 'g04-e01'"),
        ("team.number", "UPDATE team SET number = 9"),
        ("team.group_number", "UPDATE team SET group_number = 9"),
        ("team.label", "UPDATE team SET label = 'Pirate'"),
        # LE CŒUR : changer d'équipe par un UPDATE court-circuiterait le
        # comptage des places ET la date de fermeture.
        ("team_member.team_id", "UPDATE team_member SET team_id = 'g04-e01'"),
        ("team_member.account", "UPDATE team_member SET account = 'sub-x'"),
        # L'HISTOIRE NE SE RÉÉCRIT PAS.
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
    # ET CE QUI DOIT PASSER PASSE : sans cette moitié, un GRANT trop étroit
    # resterait muet en production et nulle part ailleurs.
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
