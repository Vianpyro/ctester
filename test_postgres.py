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

WHY THIS FILE EXISTS. `test_ctester.py` simulates the database: what it
exercises is the HTTP boundary, not the SQL. But the progression and forum
writes are not ordinary SQL -- a data-modifying CTE feeding an INSERT, a
data-modifying CTE feeding an UPDATE, an `unnest` of a parameterized array, an
INSERT ... SELECT whose `WHERE` clause IS the access control, a `DISTINCT ON`
and a LATERAL join for the latest profile, twelve DELETEs in a single
statement. These shapes compile in your head and fail in production; there is
no middle ground.

WITHOUT `CTESTER_DB_DSN`, IT DOES NOTHING AND EXITS 0. That is deliberate: it
must be runnable everywhere without becoming one more reason not to run the
other checks. It is NOT in the Ansible verification -- it writes, and the only
database the role knows is the students'.
"""

import os
import sys

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

TABLES = ("exercise_draft", "exercise_state", "practice_attempt",
          "progress_event", "xp_transaction", "achievement_unlocked",
          "forum_message", "forum_report", "forum_moderation",
          "forum_profile", "forum_reported_name", "display_preference")

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
    assert state.write_state(ALICE, "tp2-ex3", "valide", {"submission.c": "sent"})
    assert state.read_resume(ALICE, "tp2-ex3")["submission.c"] == "int main(void){}"
    # AND "valide" DOES NOT GO BACKWARDS. People keep poking at a solved
    # exercise; without the schema's CASE, the dashboard would say the
    # opposite of what happened.
    assert state.write_state(ALICE, "tp2-ex3", "essaye", {"submission.c": "broken"})
    assert state.read_states(ALICE) == [{"exercice_id": "tp2-ex3", "statut": "valide"}]
    assert state.write_state(ALICE, "tp2-ex3", "perfect", {}) is False
    print("ok   draft, state, and \"valide\" does not go backwards")


def practice_attempts():
    verdict = {"status": "ok", "total": 3, "passed": 3}
    assert state.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert state.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert state.write_practice_attempt(ALICE, "job-2", "tp2-ex3",
                                       {"status": "ok", "total": 3, "passed": 1})
    assert state.read_practice_summary(ALICE) == [
        {"exercice_id": "tp2-ex3", "tentatives": 2, "reussites": 1}]
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
        ALICE, "tp6-ex1", "reussite:tp6-ex1", 30, "first solve",
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
    assert [s["id"] for s in view["succes"]] == [
        "premiere-competence", "premiere-reussite", "cinq-reussites"], view["succes"]
    assert all(len(s["obtenu_le"]) == 10 for s in view["succes"]), view["succes"]
    assert len(view["transactions"]) == 3
    assert view["transactions"][0]["motif"] == "first solve"
    print("ok   achievements without duplicates, and reading the facts (day-level dates)")


def mastery_evidence():
    """The journal's other write: a fact WITHOUT XP, and reading it back typed.

    No new table -- it is `progress_event` that carries both. This check is
    therefore also proof that the existing GRANT is enough: if phase 2 had
    needed one more privilege, it would fail here.
    """
    written = state.record_event(ALICE, "verification:verif-tp2:job-v1",
                              "VerificationEvaluated", "verif-tp2", "policy-1",
                              {"job": "job-v1", "reussi": False})
    assert written == "verification:verif-tp2:job-v1", written
    # Replaying the same poll writes nothing: same key, same refusal.
    assert state.record_event(ALICE, "verification:verif-tp2:job-v1",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v1", "reussi": True}) is None
    # A RETRY, though, is a different job and so a different fact: attempts
    # stay historical.
    assert state.record_event(ALICE, "verification:verif-tp2:job-v2",
                             "VerificationEvaluated", "verif-tp2", "policy-1",
                             {"job": "job-v2", "reussi": True})

    facts = state.read_events(ALICE, "VerificationEvaluated")
    # NEWEST FIRST: it is the latest attempt that makes the band.
    assert [f["charge"]["job"] for f in facts] == ["job-v2", "job-v1"], facts
    assert facts[0]["charge"]["reussi"] is True
    assert facts[0]["exercice_id"] == "verif-tp2"
    # THE TYPE FILTER IS REAL: practice solves from the same account live in
    # the same table and must not surface here.
    assert count("progress_event", ALICE) > len(facts)
    assert state.read_events(ALICE, "ExerciceReussi")
    # And none of this touched the balance.
    assert state.read_progress(ALICE)["xp"] == 20
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
    assert thread[0]["utilisateur"] == ALICE and thread[0]["masque"] is False
    # AT THE MINUTE, not the day: a thread is read in order. AND IN EXPLICIT
    # UTC: without the "Z", the page displays server time as if it were the
    # reader's.
    assert len(thread[0]["cree_le"]) == 17 and thread[0]["cree_le"].endswith("Z"), \
        thread[0]["cree_le"]
    # ONE THREAD PER EXERCISE: nothing leaks from one exercise into another.
    assert len(state.forum_fil("tp2-ex0", 200)) == 1
    assert state.forum_fil("tp2-ex3", 1) == thread[:1]    # the limit applies

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
    assert queue[0]["id"] == m2 and queue[0]["signalements"] == 2
    assert queue[0]["texte"] == "same problem here"
    assert queue[0]["exercice_id"] == "tp2-ex3"

    # HIDE, THEN RESTORE: the state changes, the journal grows, in ONE
    # statement. Two autocommit `_query` calls would leave a hidden message
    # that nothing explains if the connection dropped in between.
    assert state.forum_moderer("d" * 32, m2, ALICE, "masquer") == [(m2,)]
    assert state.forum_fil("tp2-ex3", 200)[1]["masque"] is True
    assert state.forum_moderer("e" * 32, m2, ALICE, "retablir") == [(m2,)]
    assert state.forum_fil("tp2-ex3", 200)[1]["masque"] is False
    assert count("forum_moderation", ALICE) == 2          # APPEND-ONLY: both stay
    assert state.forum_moderer("9" * 32, "f" * 32, ALICE, "masquer") == []
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
    assert state.forum_profil(ALICE) == {"pseudo": None, "groupe": None,
                                        "pseudo_public": False,
                                        "groupe_public": False}
    assert state.forum_profil_ecrire("p" * 32, ALICE, "Alice", 3, True, False)
    assert state.forum_profil_ecrire("q" * 32, BOB, "Bob", 7, False, True)
    # THE LAST ROW IS AUTHORITATIVE, and the old one stays: changing a name
    # does not erase the history a moderator wants to be able to read back.
    assert state.forum_profil_ecrire("r" * 32, ALICE, "Alice B", 3, True, True)
    assert count("forum_profile", ALICE) == 2
    profiles = state.forum_profils([ALICE, BOB, "sub-personne"])
    assert profiles[ALICE] == {"pseudo": "Alice B", "groupe": 3,
                              "pseudo_public": True, "groupe_public": True}
    assert profiles[BOB]["pseudo"] == "Bob" and profiles[BOB]["groupe"] == 7
    assert "sub-personne" not in profiles
    # THE SCHEMA'S CHECK, EXERCISED WITHOUT GOING THROUGH THE PYTHON GUARD: a
    # group runs from 1 to 99, and Postgres refuses the rest.
    assert state.forum_profil_ecrire("s" * 32, ALICE, "Alice", 0, False, False) \
        is False
    assert state.forum_profil_ecrire("t" * 32, ALICE, "Alice", 100, False, False) \
        is False

    # REPORTING A NAME: same two protections as for a message.
    message = state.forum_fil("tp2-ex3", 200)[0]["id"]
    assert state.forum_auteur(message) in (ALICE, BOB)
    assert state.forum_auteur("f" * 32) is None
    assert state.forum_nom_signaler(message, BOB) == [(message,)]
    assert state.forum_nom_signaler(message, BOB) == []      # only once
    assert state.forum_nom_signaler("f" * 32, BOB) == []     # nothing orphaned
    reported = state.forum_noms_signales(200)
    assert len(reported) == 1 and reported[0]["id"] == message, reported
    # THE LATERAL JOIN: the name returned is the LATEST, not the first.
    author = state.forum_auteur(message)
    assert reported[0]["pseudo"] == state.forum_profils([author])[author]["pseudo"]
    assert reported[0]["signalements"] == 1
    # ALICE REPORTS IN TURN, on another message. Without this line she has NO
    # row in `forum_reported_name`, and `deletion()`'s precondition ("there is
    # something to erase in the twelve tables") does not hold -- meaning the
    # most recently added table is the only one whose erasure is not exercised.
    assert state.forum_nom_signaler("b" * 32, ALICE) == [("b" * 32,)]
    print("ok   identity: journal, last row wins, schema bounds, reported name")


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
         "UPDATE forum_moderation SET action = 'retablir'"),
        # IDENTITY IS A JOURNAL TOO: a row is added, the name someone gave
        # themselves is not rewritten. Without this refusal, a stray query
        # could silently rename a student.
        ("forum_profile.display_name", "UPDATE forum_profile SET display_name = 'other'"),
        ("forum_profile.display_name_public",
         "UPDATE forum_profile SET display_name_public = true"),
        ("forum_reported_name",
         "UPDATE forum_reported_name SET account = 'sub-x'"),
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
    # AND `hidden` GOES THROUGH: it is the only state moderation needs to
    # change, and the only one the GRANT allows. Without this check, a GRANT
    # too narrow would leave moderation mute with nothing saying so.
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("UPDATE forum_message SET hidden = hidden")
    print("ok   forum: only `hidden` is writable, the rest is append-only")


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
    assert count("forum_message", BOB) == 2, "message erased from the neighbor!"
    assert count("forum_report", BOB) == 1
    assert state.forget(ALICE)                            # replayable
    print("ok   \"Delete my data\" empties the twelve tables, and only their own")


def main():
    apply_schema()
    append_only()
    for user in (ALICE, BOB):
        state.forget(user)
    drafts_and_states()
    practice_attempts()
    grants()
    achievements_and_reading()
    mastery_evidence()
    account_isolation()
    forum()
    identity()
    forum_privileges()
    preferences()
    deletion()
    state.forget(BOB)
    print("\nthe SQL holds up on a real PostgreSQL.")


if __name__ == "__main__":
    main()
