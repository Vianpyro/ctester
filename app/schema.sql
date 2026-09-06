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
-- moderator can only hide or restore it -- hence `hidden`, the only column the
-- API is allowed to update (see the GRANT in VHome: `UPDATE (hidden)`, not
-- `UPDATE`). There is no editing: a message corrected after the fact would
-- make a report unreadable.
CREATE TABLE IF NOT EXISTS forum_message (
    message_id  TEXT        PRIMARY KEY,   -- uuid4().hex, generated in Python
    exercise_id TEXT        NOT NULL,      -- a PUBLIC catalog id
    account     TEXT        NOT NULL,
    text        TEXT        NOT NULL,
    hidden      BOOLEAN     NOT NULL DEFAULT false,
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
    action     TEXT        NOT NULL CHECK (action IN ('hide', 'restore')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
