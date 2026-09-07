-- ctester -- state for students who choose to sign in.
--
-- SQLITE WOULD HAVE BEEN ENOUGH, AND THAT BELONGS HERE rather than in a
-- conversation nobody will find in six months. The real load is 27 students,
-- one term, a few dozen writes an hour at the peak of a lab session, and a
-- single process doing the writing. `sqlite3` ships with Python: nothing to
-- install in the exposed container, no service to watch, no backup to arrange.
-- Technically it is the right tool, and it would still be at ten times this size.
--
-- Postgres is chosen anyway, and the reason is not technical: this repository is
-- also a portfolio, and running a real database -- a versioned schema, an
-- application role with limited rights, backups, a migration -- is exactly the
-- exercise being sought. That should not be dressed up as a performance need:
-- there is none. Nobody should read this file in two years and believe a load
-- constraint forced Postgres.
--
-- The UNLOGGED / journalled split below is in fact the only place where the
-- choice buys anything visible, and it is a detail.
--
-- THERE IS NO PERSONALLY IDENTIFYING DATA HERE. `account` is the opaque
-- `sub` issued by Rauthy -- not a name, not an email, not a student number. The
-- display name lives in the token, in the browser, and never crosses this line.

-- The draft: what has not been submitted yet. UNLOGGED -- so out of the WAL,
-- not replicated, and TRUNCATED by Postgres after an unclean shutdown. That is
-- accepted: the price of a crash is "the unsubmitted work of the last session",
-- and the browser keeps a local copy of it anyway.
CREATE UNLOGGED TABLE IF NOT EXISTS exercise_draft (
    account     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,   -- JSON {filename: contents}
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, exercise_id)
);

-- The state: what has been submitted at least once. An ordinary table, so WAL,
-- so restorable. It is the only thing here whose loss would be noticed -- a
-- dashboard that forgets what was solved is worth nothing.
--
-- A CHECK rather than a validation in Python: the database is the last place
-- where the rule can hold for EVERY write path, including a psql session opened
-- at midnight. The API validates too, but this does not depend on the API.
--
CREATE TABLE IF NOT EXISTS exercise_state (
    account     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    status      TEXT        NOT NULL CHECK (status IN ('attempted', 'solved')),
    sources     TEXT        NOT NULL,   -- JSON {filename: contents}
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, exercise_id)
);

-- A practice attempt is an immutable fact written by the API only after it has
-- read the worker's result.  It is deliberately not a mastery score: the
-- current self-service judge can be fooled, and practice is still valuable
-- when it fails.  `job_id` makes polling/retries idempotent.
CREATE TABLE IF NOT EXISTS practice_attempt (
    job_id       TEXT        PRIMARY KEY,
    account      TEXT        NOT NULL,
    exercise_id  TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    total        INTEGER     NOT NULL CHECK (total >= 0),
    passed       INTEGER     NOT NULL CHECK (passed >= 0 AND passed <= total),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS practice_attempt_account_completed_idx
    ON practice_attempt (account, completed_at DESC);

-- The two state tables are covered by their primary key.  Practice history is
-- read newest-first per user, hence its one explicit index above.

-- --------------------------------------------------------------------------
-- Progression (phase 1): XP, a derived level and a few achievements, for
-- signed-in accounts only. THREE FACT TABLES, none of them a balance.
--
-- The XP balance, the level, the practiced skills and the recommendation are
-- PROJECTIONS: the API (`services/progression.py`) recomputes them on read
-- from these facts and the public catalog. Nothing is cached here.
--
-- ponytail: no projection table. The balance is a `sum()` over a few dozen
-- rows per student, and a materialized projection would be a second place
-- where the truth can diverge. Revisit the day the sum is felt, not before.
--
-- THE EVENT ID IS THE FACT, NOT THE CALL. "reussite:tp2-ex3" reads as one, and
-- its primary key is what makes the write idempotent: a replayed HTTP poll, a
-- restarted worker or two concurrent requests cannot create the same XP
-- twice. It is also what forbids farming -- solving the same exercise twice
-- produces the same id twice.

-- The journal (outbox): what the server observed, in the clear and for audit.
-- `payload` carries the strict minimum -- the originating job and the
-- difficulty used in the computation -- never the submitted code nor a secret
-- verdict detail.
CREATE TABLE IF NOT EXISTS progress_event (
    account    TEXT        NOT NULL,
    event_id   TEXT        NOT NULL,
    type       TEXT        NOT NULL,
    exercise_id TEXT,
    policy     TEXT        NOT NULL,
    payload    TEXT        NOT NULL DEFAULT '{}',   -- minimal JSON
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, event_id)
);

-- XP grants, append-only, one per source event.
--
-- `amount >= 0` AND NOT `> 0`: a solve past the daily cap is recorded at zero
-- rather than silently dropped. The fact happened, it reads back, and the
-- student can see they were already rewarded today.
--
-- ponytail: no foreign key to progress_event. The two tables share
-- (account, event_id), both are inserted in ONE statement, and `forget`
-- erases them together. One more constraint would only protect against a
-- psql session opened at midnight.
CREATE TABLE IF NOT EXISTS xp_transaction (
    account    TEXT        NOT NULL,
    event_id   TEXT        NOT NULL,
    amount     INTEGER     NOT NULL CHECK (amount >= 0),
    reason     TEXT        NOT NULL,
    exercise_id TEXT,
    policy     TEXT        NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, event_id)
);

-- The daily cap sums the day's grants for a student: the one read that does
-- not go through the primary key prefix.
CREATE INDEX IF NOT EXISTS xp_transaction_day_idx
    ON xp_transaction (account, granted_at DESC);

-- Achievements unlocked, append-only. The primary key IS the "one unlock
-- only" rule; `event_id` says which fact triggered it.
CREATE TABLE IF NOT EXISTS achievement_unlocked (
    account       TEXT        NOT NULL,
    achievement_id TEXT       NOT NULL,
    event_id      TEXT        NOT NULL,
    policy        TEXT        NOT NULL,
    unlocked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, achievement_id)
);

-- --------------------------------------------------------------------------
-- Peer help forum (MVP): ONE thread per published exercise, for signed-in
-- accounts only. This is NOT gamification -- nothing here grants XP, unlocks
-- an achievement, or touches the three tables above.
--
-- WHAT IS STORED, AND NOTHING ELSE: the author's opaque `sub`, the message id,
-- the PUBLIC exercise, the text, the dates, the visible/hidden state, the
-- author of a report, and moderation actions. No name, no email, no student
-- number, no persistent nickname: to other students, a post is signed
-- "Participant", and it is the API that derives that word from the `sub`
-- without ever letting it out.
--
-- THE PLATFORM CLOSES IN DECEMBER. No season, no carryover between terms:
-- these three tables empty out with the database at the end of the course.

-- A message is IMMUTABLE. Its author can delete it (the row disappears), a
-- moderator can only hide or restore it, and its author can open a private
-- one to their group -- hence `hidden` and `visibility`, the only two columns
-- the API is allowed to update (see the GRANT in VHome: `UPDATE (hidden,
-- visibility)`, not `UPDATE`). ADDING `visibility` TO THAT GRANT IS REQUIRED:
-- without it "rendre visible à mon groupe" fails in production and nowhere
-- else, exactly like the theme's `UPDATE` did. There is no editing: a message
-- corrected after the fact would make a report unreadable, and the text
-- column stays out of every GRANT for that reason.
CREATE TABLE IF NOT EXISTS forum_message (
    message_id  TEXT        PRIMARY KEY,   -- uuid4().hex, generated in Python
    exercise_id TEXT        NOT NULL,      -- a PUBLIC catalog id
    account     TEXT        NOT NULL,
    text        TEXT        NOT NULL,
    hidden      BOOLEAN     NOT NULL DEFAULT false,
    -- "I'm stuck here" (design 1g). WHERE it hurts and WHAT KIND of wall,
    -- both from CLOSED lists validated in `services/forum.py`: they are what
    -- the instructor's aggregate groups by, and free text would make that
    -- aggregate useless on the morning it matters. NULL for an ordinary
    -- question, which is still the default gesture.
    step         TEXT,
    blocked_kind TEXT,
    -- WHO SEES IT, AND PRIVATE IS THE DEFAULT for a "stuck" post. The only
    -- transition allowed is private -> group, by its author (see
    -- `forum_open_to_group`): the reverse would hide what others have
    -- already read, and break the immutability social.md sets out.
    --
    -- `thread` is the ordinary public post -- the only value the forum had
    -- before this column, hence the DEFAULT: an old row reads as what it was.
    visibility  TEXT        NOT NULL DEFAULT 'thread'
                            CHECK (visibility IN ('private', 'group', 'thread')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A thread is read per exercise, oldest to newest: the one read that does not
-- go through the primary key.
CREATE INDEX IF NOT EXISTS forum_message_thread_idx
    ON forum_message (exercise_id, created_at);

-- The report. THE PRIMARY KEY IS THE RULE: the same account cannot report the
-- same message twice, and Postgres holds it -- not a read followed by a
-- write, which would leave the race open.
CREATE TABLE IF NOT EXISTS forum_report (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,      -- the author of the REPORT
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

-- Moderation actions, APPEND-ONLY. A message gets hidden, then restored, and
-- both read back: "the message was hidden then restored" is information, not
-- noise to overwrite. The current state lives in `forum_message.hidden`; this
-- is its journal.
--
-- ponytail: no foreign key to forum_message. Both are written in ONE
-- statement (see `moderate_forum_message` in state.py), and a message deleted
-- by its author leaves a journal row that shows up nowhere -- that is the
-- intended behavior of a journal.
CREATE TABLE IF NOT EXISTS forum_moderation (
    action_id  TEXT        PRIMARY KEY,   -- uuid4().hex, generated in Python
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,      -- the MODERATOR who acted
    -- FOUR ACTIONS, AND THE LAST TWO CARRY THEIR OWN STATE. `hide`/`restore`
    -- mirror `forum_message.hidden`; `retain`/`unretain` mark the answer the
    -- instructor stands behind, and there is NO column for them -- the latest
    -- row for a message is the answer. Retaining an answer edits nothing,
    -- which is the whole point of an immutable message.
    action     TEXT        NOT NULL CHECK (action IN ('hide', 'restore',
                                                      'retain', 'unretain')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The read that matters for retained answers: the latest action per message.
CREATE INDEX IF NOT EXISTS forum_moderation_latest_idx
    ON forum_moderation (message_id, created_at DESC);

-- THE CHOSEN IDENTITY, AND IT IS OPTIONAL ON BOTH SIDES. A name one gave
-- oneself, a group number, and for each the right not to show it. Nothing
-- here comes from an OIDC claim: no legal name, no email -- what the student
-- writes is what the student decided to write.
--
-- APPEND-ONLY, LIKE THE REST OF THE FORUM: the last row for an account is
-- authoritative (see `forum_profile` in state.py). No UPDATE, so no UPDATE
-- GRANT, so no distracted statement rewrites someone's name; and the history
-- of name changes is exactly what a moderator wants to be able to read back.
--
-- `set_by_moderator` marks the row written by the instructor when clearing a
-- reported name. The student can then choose another one: a repeat offender
-- is a human matter, not a state machine.
CREATE TABLE IF NOT EXISTS forum_profile (
    profile_id            TEXT        PRIMARY KEY,  -- uuid4().hex, generated in Python
    account               TEXT        NOT NULL,
    display_name          TEXT,                      -- NULL = no name chosen
    group_number          SMALLINT    CHECK (group_number BETWEEN 1 AND 99),
    display_name_public   BOOLEAN     NOT NULL DEFAULT false,
    group_number_public   BOOLEAN     NOT NULL DEFAULT false,
    -- THE LEADERBOARD NAME IS DRAWN, NOT DERIVED. Stored here rather than
    -- computed from the `sub`, because a name derived from the sub could
    -- never be redrawn -- and being able to redraw it as often as one likes
    -- is what makes the leaderboard bearable. It is NEVER the display name:
    -- someone who shows their name in a thread still appears under this one
    -- in a ranking. Append-only, so the previous alias stays readable, which
    -- is what a moderator needs when an alias gets reported.
    alias                 TEXT,
    -- THE PLATE FRAME, and it is decoration only: no advantage, no access,
    -- nothing another student can be measured against. An unknown value
    -- simply does not display (see `policy.FRAMES`) rather than raising.
    plate_frame           TEXT,
    badges_public         BOOLEAN     NOT NULL DEFAULT false,
    -- OPT-IN, AND NOWHERE ELSE. False means the account is absent from every
    -- ranking, including its own group's -- not "ranked but hidden". The
    -- aggregate reads this column; there is no second filter to forget.
    leaderboard_opt_in    BOOLEAN     NOT NULL DEFAULT false,
    set_by_moderator      BOOLEAN     NOT NULL DEFAULT false,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The read that matters: the last row for an account, or for a handful of
-- accounts at once when rendering a thread.
CREATE INDEX IF NOT EXISTS forum_profile_latest_idx
    ON forum_profile (account, created_at DESC);

-- Reporting a NAME, not a message. Same rule and same primary key as
-- `forum_report`: an account reports a name at most once per carrying
-- message. The message serves as the handle -- there is no account id on the
-- browser side, and there must not be one.
CREATE TABLE IF NOT EXISTS forum_reported_name (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,      -- the author of the REPORT
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

-- "THIS HELPED ME": a usefulness counter, NOT a popularity vote. Same shape
-- and same rule as `forum_report` -- the primary key IS "once per account" --
-- and deliberately the same shape for a reason: an account can mark a message
-- useful once, and Postgres holds that, not a read followed by a write.
--
-- IT GRANTS NOTHING. No XP, no achievement, no card: a message written to be
-- upvoted is a message written for the counter. What it buys is a thread
-- where the answer that worked is findable, which is the whole ask of
-- design 1f.
--
-- NO SELF-MARKING is enforced by the API (`forum_mark_helpful`), not by a CHECK: the
-- constraint would need the message's author in this row, i.e. a second copy
-- of a `sub` this table has no reason to carry.
CREATE TABLE IF NOT EXISTS forum_helpful (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,      -- the one who found it useful
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

-- --------------------------------------------------------------------------
-- Display preferences: the theme, and nothing else for now.
--
-- WHY THIS TABLE EXISTS WHEN `localStorage` WAS ENOUGH. It was enough on ONE
-- device. A student working at the lab then at home started over from the
-- default theme every time, and the setting that took thirty seconds to
-- choose did not follow them. The account is already what carries the draft
-- from one machine to another; the theme travels the same way.
--
-- LOCAL STORAGE STAYS, AND IT IS NOT REDUNDANT: it is what the `<head>`
-- script reads before the first paint. The server answers well after the
-- first paint -- if it had to be awaited, every visit would show the
-- dark-to-light flash this script exists precisely to avoid.
--
-- ONE ROW PER ACCOUNT, UPDATED IN PLACE. This is the only table in this
-- schema, along with the draft and the state, that is not append-only:
-- someone's old theme is not a fact to read back, and a journal would grow a
-- row on every click of a button made to be clicked. The matching GRANT (see
-- VHome) carries `UPDATE`, as for `exercise_draft`.
--
-- LOGGED, unlike the draft: losing the setting would only cost a click, but
-- the table is tiny -- one row per account -- and a TRUNCATE after an unclean
-- shutdown would send everyone back to the default theme on the morning
-- everyone would notice least why.
--
-- The CHECK is the same defense as elsewhere: the value comes from a request
-- body, and `state.write_theme()` already validates it. The constraint holds
-- for EVERY write path, including a psql session opened at midnight.
CREATE TABLE IF NOT EXISTS display_preference (
    account    TEXT        NOT NULL PRIMARY KEY,
    theme      TEXT        NOT NULL CHECK (theme IN ('light', 'dark')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- TEAM ASSIGNMENTS: a group is not a team, and this is where the difference
-- becomes a fact rather than a convention.
--
-- A GROUP is the course section an instructor put a student in. On this
-- platform it has always been `forum_profile.group_number` -- a number the
-- STUDENT types into their own profile, used to decide who can read a
-- question opened "to my group". It is self-declared, and that is fine for
-- what it does.
--
-- A TEAM is three or four students who hand in one piece of assessed work
-- together. It cannot be self-declared: a student who could pick their team
-- could pick the team whose work is furthest along. So it is not stored
-- anywhere a student can write, and the application role has NO INSERT,
-- UPDATE or DELETE on the two tables below -- only `SELECT` (see the GRANT
-- in VHome). Rosters are loaded by the instructor with `import_teams.py`,
-- through the admin DSN.
--
-- REUSING `group_number` FOR TEAMS WAS THE OBVIOUS SHORTCUT AND IT IS THE
-- WRONG ONE: the two answer different questions ("which section are you in"
-- versus "who do you hand in with"), they have different authorities, and a
-- single column would have made the forum's visibility rule and an
-- assignment's access control the same rule by accident.

-- One team, for ONE assignment. A team is not a durable object that outlives
-- the work: the same four students on the next assignment are a new row, and
-- that is what keeps `team_member` free of a date range nobody would maintain.
CREATE TABLE IF NOT EXISTS team (
    team_id       TEXT        NOT NULL,
    assignment_id TEXT        NOT NULL,   -- a PUBLISHED assignment id
    -- THE COURSE GROUP THE TEAM BELONGS TO, and it is the instructor's, not
    -- the student's self-declared one. It is here so that an instructor
    -- reading the roster sees sections, and so a future per-section deadline
    -- has somewhere to hang. It is NEVER read as an authorization: team
    -- membership is.
    group_number  SMALLINT    NOT NULL CHECK (group_number BETWEEN 1 AND 99),
    label         TEXT,                   -- what students see: "Équipe 2"
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, assignment_id)
);

-- WHO IS ON IT. THE PRIMARY KEY IS THE RULE -- one team per assignment per
-- account -- and Postgres holds it, not a read followed by a write. Without
-- it, a roster loaded twice with a corrected line would leave a student on
-- two teams, and every query below would then have to pick one.
--
-- The composite foreign key is the one place in this schema where a FK earns
-- its keep: a membership row whose team does not exist would name an
-- assignment nobody can find, and the roster is written by a script, not by
-- the statement that created the team.
CREATE TABLE IF NOT EXISTS team_member (
    team_id       TEXT        NOT NULL,
    assignment_id TEXT        NOT NULL,
    account       TEXT        NOT NULL,   -- the opaque OIDC `sub`
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assignment_id, account),
    FOREIGN KEY (team_id, assignment_id)
        REFERENCES team (team_id, assignment_id) ON DELETE CASCADE
);

-- The read that matters on the other side: "who else is on my team".
CREATE INDEX IF NOT EXISTS team_member_roster_idx
    ON team_member (assignment_id, team_id);

-- THE SHARED DOCUMENT: one per (team, exercise), and it is the authoritative
-- one. `exercise_draft` stays exactly what it was -- one row per (account,
-- exercise) -- and nothing here changes it: an exercise outside an assignment
-- never reaches this table, and a student not on a team keeps the individual
-- path. The two live side by side rather than behind an `if team_mode` spread
-- through the state layer.
--
-- LOGGED, unlike `exercise_draft`. The individual draft can be TRUNCATEd
-- after an unclean shutdown because the browser holds a copy; this one is
-- four people's graded work and no browser holds all of it.
--
-- `updated_by` IS WHO SAVED, and it is only ever used to attribute a
-- revision. It is not a lock and not an owner: every member writes here.
CREATE TABLE IF NOT EXISTS team_document (
    team_id     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,   -- JSON {filename: contents}
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, exercise_id)
);

-- THE HISTORY, APPEND-ONLY. It exists for recovery, for an instructor
-- investigating an assignment, and for "how did this get here" -- never for
-- a grade. There is deliberately no contribution percentage anywhere in this
-- application: a number counting typed characters would immediately become
-- the thing people optimise, and it would be wrong about the person who
-- thinks before typing.
--
-- NOT ONE ROW PER KEYSTROKE. A revision is written only when the last one
-- for this document is older than the coalescing window OR was written by
-- somebody else -- and that rule is the `WHERE NOT EXISTS` of a single
-- INSERT (see `write_team_document` in state.py), not a read followed by a
-- write that two members would race through.
CREATE TABLE IF NOT EXISTS team_revision (
    revision_id TEXT        PRIMARY KEY,  -- uuid4().hex, generated in Python
    team_id     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    account     TEXT        NOT NULL,     -- who was typing
    sources     TEXT        NOT NULL,     -- JSON {filename: contents}
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The two reads: the newest revisions of one document, and the coalescing
-- test that decides whether to write another one.
CREATE INDEX IF NOT EXISTS team_revision_recent_idx
    ON team_revision (team_id, exercise_id, created_at DESC);

-- THE HAND-IN. THE PRIMARY KEY IS THE RULE: one submission per team per
-- assignment, which is what the assignment sheet asks for. Handing in again
-- before the deadline replaces it -- a team that finds a bug at 22:00 must be
-- able to fix it -- and `submitted_by` says who pressed the button last.
-- What was handed in before is not lost: `team_revision` holds it.
CREATE TABLE IF NOT EXISTS team_submission (
    assignment_id TEXT        NOT NULL,
    team_id       TEXT        NOT NULL,
    -- NOT `account`: this row belongs to the TEAM, and "Supprimer mes
    -- données" must not take three other people's hand-in with it. The
    -- column name is what `test_suppression_couvre_toutes_les_tables` reads
    -- to decide, so it is load-bearing rather than cosmetic.
    submitted_by  TEXT        NOT NULL,
    files         TEXT        NOT NULL,   -- JSON {archive path: contents}
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assignment_id, team_id)
);

-- --------------------------------------------------------------------------
-- MIGRATIONS: WHAT `CREATE TABLE IF NOT EXISTS` CANNOT DO.
--
-- THIS SECTION EXISTS BECAUSE THE FILE ABOVE IS A NO-OP ON A DATABASE THAT
-- ALREADY HAS ITS TABLES. `IF NOT EXISTS` guards the CREATE, so replaying the
-- schema on every convergence is free -- but a column ADDED to a table that
-- already exists is never applied, and the replay says nothing. That is not a
-- theoretical gap: the redesign added `visibility` to `forum_message`, the
-- Dell replayed this file without complaint, and the next task in the Ansible
-- role failed with `column "visibility" of relation "forum_message" does not
-- exist` -- the GRANT was the first thing to touch a column the schema
-- believed it had created.
--
-- EVERY STATEMENT HERE IS IDEMPOTENT, and that is the whole contract: this
-- file is replayed at EVERY convergence, so a migration that could only run
-- once would break the run after it. `ADD COLUMN IF NOT EXISTS` is a no-op on
-- a fresh database (the CREATE above already made the column) and repairs an
-- old one.
--
-- A MIGRATION STAYS HERE ONCE WRITTEN. Deleting it the day every host has run
-- it would be safe and pointless: it costs one catalog lookup per column per
-- convergence, and the day someone restores a backup from before it, the
-- schema repairs itself again. `migrate_schema_english.sql` is the opposite
-- case and stays a manual script: renaming tables that hold real data cannot
-- be made idempotent, and must not run unattended.

-- "Je suis bloqué ici" (design 1g). NOT NULL WITH A DEFAULT on a table that
-- already holds messages: Postgres backfills without rewriting the table, and
-- every message written before this column reads as `thread` -- the ordinary
-- public post, which is exactly what it was.
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS step         TEXT;
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS blocked_kind TEXT;
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS visibility   TEXT NOT NULL
    DEFAULT 'thread';

-- The CHECK travels separately from the column: `ADD COLUMN IF NOT EXISTS`
-- carries the DEFAULT but a constraint added inline would be re-added under a
-- new name on every replay. Named, dropped and re-added, it stays one
-- constraint no matter how many times this file runs.
ALTER TABLE forum_message DROP CONSTRAINT IF EXISTS forum_message_visibility_check;
ALTER TABLE forum_message ADD  CONSTRAINT forum_message_visibility_check
    CHECK (visibility IN ('private', 'group', 'thread'));

-- The plate, the drawn alias and the leaderboard opt-in (designs 1c/1d).
-- `false` FOR BOTH FLAGS IS THE ONLY SAFE BACKFILL: an existing account has
-- consented to nothing, so it joins no ranking and shows no badge until its
-- owner ticks the box.
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS alias              TEXT;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS plate_frame        TEXT;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS badges_public      BOOLEAN
    NOT NULL DEFAULT false;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS leaderboard_opt_in BOOLEAN
    NOT NULL DEFAULT false;

-- THE RETAINED ANSWER WIDENED AN EXISTING CHECK, and this is the failure that
-- would NOT have shown up at deploy time: the old constraint still read
-- `('hide', 'restore')`, so the schema looked applied and the first click on
-- "Retenir comme réponse" would have been refused by Postgres, months later,
-- with nothing in the page to explain it.
--
-- ONE TRANSACTION, so there is no instant where the journal accepts an
-- unknown action. Postgres makes DDL transactional; without the BEGIN, the
-- drop would commit on its own and leave the table briefly unguarded.
BEGIN;
ALTER TABLE forum_moderation DROP CONSTRAINT IF EXISTS forum_moderation_action_check;
ALTER TABLE forum_moderation ADD  CONSTRAINT forum_moderation_action_check
    CHECK (action IN ('hide', 'restore', 'retain', 'unretain'));
COMMIT;

-- Team assignments. Every statement above is a `CREATE TABLE IF NOT EXISTS`,
-- so a database that predates this feature gets the tables on the next
-- converge and needs nothing here. The index below is repeated for the same
-- reason the others are: it costs one catalog lookup and it repairs a
-- database restored from a backup taken before it.
CREATE INDEX IF NOT EXISTS team_member_roster_idx
    ON team_member (assignment_id, team_id);

-- --------------------------------------------------------------------------
-- LES DROITS DU RÔLE APPLICATIF, ICI ET PAS DANS ANSIBLE.
--
-- ILS VIVAIENT DANS `VHome/roles/ctester/tasks/main.yml`, ET C'ÉTAIT LA
-- MAUVAISE MOITIÉ DU DÉPÔT. Une table et ses droits sont le MÊME FAIT : une
-- table sans son GRANT est muette, un GRANT sans sa table ne s'applique pas.
-- Les séparer sur deux dépôts, c'est garantir qu'un jour l'un part sans
-- l'autre -- et ça s'est produit TROIS FOIS : l'`UPDATE` du thème, la colonne
-- `visibility` du forum, puis les cinq tables d'équipe. Les trois fois, la
-- panne n'existait qu'en production, parce que c'est le seul endroit où le
-- rôle applicatif est utilisé.
--
-- LE SIGNE QUI A TRANCHÉ : `test_postgres.py` devait RECOPIER ces GRANT pour
-- les éprouver. Quand un harnais duplique une règle pour la tester, la règle
-- est au mauvais endroit. Il applique maintenant ce fichier, point.
--
-- CE QUI RESTE À ANSIBLE, ET POURQUOI : `CREATE ROLE ctester_app LOGIN
-- PASSWORD ...`. Le mot de passe vient du vault, et un secret n'a rien à
-- faire dans un dépôt d'application. Le rôle est créé AVANT que ce fichier ne
-- soit appliqué -- c'est déjà l'ordre des tâches.
--
-- D'OÙ LE `DO` CONDITIONNEL : sans rôle, on ne grante rien plutôt que de
-- faire échouer tout le fichier sous `ON_ERROR_STOP=1`. C'est ce qui garde
-- `schema.sql` applicable sur une base de test nue, ce qu'il a toujours
-- promis. `EXECUTE` parce que PL/pgSQL n'exécute pas une commande utilitaire
-- autrement.
--
-- JAMAIS UN GRANT SUR LE SCHÉMA, toujours table par table : `GRANT ... ON ALL
-- TABLES IN SCHEMA public` couvrirait d'avance une table pas encore écrite,
-- et le jour où on en ajoute une par erreur, elle serait déjà ouverte.
--
-- `test_ctester.py::test_chaque_table_a_ses_droits` refuse une table qui
-- n'apparaît dans aucun GRANT ci-dessous. Ajouter une table sans ses droits
-- fait donc échouer la suite, au lieu d'échouer en production dans six mois.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctester_app') THEN
        RETURN;
    END IF;

    -- CE QUI S'ÉCRASE : un brouillon, un état, une tentative, un thème. Ce
    -- sont les seules tables du schéma qui ne sont pas en ajout seul, et
    -- l'`UPDATE` y est nécessaire (`ON CONFLICT ... DO UPDATE`).
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE'
            ' ON exercise_draft, exercise_state, practice_attempt,'
            '    display_preference'
            ' TO ctester_app';

    -- LA PROGRESSION EST EN AJOUT SEUL, ET C'EST POSTGRES QUI LE TIENT : pas
    -- d'UPDATE dans ce GRANT. L'API n'en a pas besoin -- ses deux écritures
    -- sont des `INSERT ... ON CONFLICT DO NOTHING` -- donc une correction
    -- d'XP a posteriori demande un accès d'administration explicite, pas une
    -- ligne de Python. DELETE reste : « Supprimer mes données » couvre ces
    -- tables aussi.
    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON progress_event, xp_transaction, achievement_unlocked'
            ' TO ctester_app';

    -- LE FORUM EST EN AJOUT SEUL LUI AUSSI, à deux colonnes près (plus bas).
    -- Un message est immuable : son auteur le supprime, un modérateur le
    -- masque, PERSONNE ne le réécrit.
    --
    -- ET CE GRANT N'AJOUTE RIEN SUR LES TABLES DE PROGRESSION, délibérément :
    -- le forum n'accorde pas d'XP, ne débloque pas de succès et ne lit pas la
    -- progression. Une fonctionnalité sociale qui gagnerait au passage un
    -- privilège sur les tables de valeur serait exactement la dérive que la
    -- phase 1 a fermée.
    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON forum_message, forum_report, forum_moderation, forum_helpful'
            ' TO ctester_app';

    -- L'IDENTITÉ CHOISIE EST UN JOURNAL : changer de nom ajoute une ligne, la
    -- dernière fait foi. Sans `UPDATE`, aucune requête distraite ne peut
    -- réécrire le nom que quelqu'un s'est donné.
    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON forum_profile, forum_reported_name'
            ' TO ctester_app';

    -- UN GRANT DE COLONNE, PAS DE TABLE. `UPDATE (hidden, visibility)`
    -- autorise exactement deux gestes : masquer/rétablir pour la modération,
    -- et ouvrir sa propre question privée à son groupe pour son auteur. Avec
    -- un `UPDATE` de table, une ligne de Python distraite pourrait réécrire
    -- le texte de quelqu'un, ou changer l'auteur d'un message.
    -- `test_postgres.py` éprouve les DEUX moitiés -- que ces deux colonnes
    -- passent, et que `text` et `account` soient refusés.
    EXECUTE 'GRANT UPDATE (hidden, visibility) ON forum_message TO ctester_app';

    -- LE LISTAGE DES ÉQUIPES EST EN LECTURE SEULE, et c'est CE GRANT qui rend
    -- vraie la phrase « l'appartenance est autoritaire ». Rejoindre une
    -- équipe n'est pas « refusé par un `if` » : c'est inexprimable, parce
    -- qu'il n'y a pas d'INSERT. `import_teams.py` écrit avec le DSN
    -- d'administration, et c'est le seul chemin.
    EXECUTE 'GRANT SELECT ON team TO ctester_app';

    -- DELETE, ET RIEN D'AUTRE : « Supprimer mes données » retire
    -- l'appartenance de son PROPRE compte. Pas d'INSERT, pas d'UPDATE --
    -- personne ne rejoint une équipe, et personne n'en change.
    EXECUTE 'GRANT SELECT, DELETE ON team_member TO ctester_app';

    -- Le document partagé et la remise s'écrasent (`ON CONFLICT DO UPDATE`),
    -- comme le brouillon et le thème. Pas de DELETE : ils appartiennent à
    -- l'ÉQUIPE, et effacer un membre ne doit pas emporter le devoir de trois
    -- autres personnes -- c'est pour ça qu'ils sont absents de `forget()`.
    EXECUTE 'GRANT SELECT, INSERT, UPDATE'
            ' ON team_document, team_submission TO ctester_app';

    -- L'historique est en ajout seul, comme le forum : une révision est un
    -- fait, et son auteur n'est pas une colonne à corriger après coup. DELETE
    -- reste pour « Supprimer mes données ».
    EXECUTE 'GRANT SELECT, INSERT, DELETE ON team_revision TO ctester_app';
END
$$;
