-- Drafts are also kept in the browser, so losing them in a crash is acceptable.
CREATE UNLOGGED TABLE IF NOT EXISTS exercise_draft (
    account     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, exercise_id)
);

CREATE TABLE IF NOT EXISTS exercise_state (
    account     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    status      TEXT        NOT NULL CHECK (status IN ('attempted', 'solved')),
    sources     TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, exercise_id)
);

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

CREATE TABLE IF NOT EXISTS progress_event (
    account    TEXT        NOT NULL,
    event_id   TEXT        NOT NULL,
    type       TEXT        NOT NULL,
    exercise_id TEXT,
    policy     TEXT        NOT NULL,
    payload    TEXT        NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, event_id)
);

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

CREATE INDEX IF NOT EXISTS xp_transaction_day_idx
    ON xp_transaction (account, granted_at DESC);

CREATE TABLE IF NOT EXISTS achievement_unlocked (
    account       TEXT        NOT NULL,
    achievement_id TEXT       NOT NULL,
    event_id      TEXT        NOT NULL,
    policy        TEXT        NOT NULL,
    unlocked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account, achievement_id)
);

CREATE TABLE IF NOT EXISTS forum_message (
    message_id  TEXT        PRIMARY KEY,
    exercise_id TEXT        NOT NULL,
    account     TEXT        NOT NULL,
    text        TEXT        NOT NULL,
    hidden      BOOLEAN     NOT NULL DEFAULT false,

    step         TEXT,
    blocked_kind TEXT,

    visibility  TEXT        NOT NULL DEFAULT 'thread'
                            CHECK (visibility IN ('private', 'group', 'thread')),

    reply_to    TEXT,

    search      tsvector    GENERATED ALWAYS AS (to_tsvector('french', text)) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forum_message_thread_idx
    ON forum_message (exercise_id, created_at);

CREATE TABLE IF NOT EXISTS forum_report (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

CREATE TABLE IF NOT EXISTS forum_moderation (
    action_id  TEXT        PRIMARY KEY,
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,

    action     TEXT        NOT NULL CHECK (action IN ('hide', 'restore',
                                                      'retain', 'unretain')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forum_moderation_latest_idx
    ON forum_moderation (message_id, created_at DESC);

CREATE TABLE IF NOT EXISTS forum_profile (
    profile_id            TEXT        PRIMARY KEY,
    account               TEXT        NOT NULL,
    display_name          TEXT,
    group_number          SMALLINT    CHECK (group_number BETWEEN 1 AND 99),
    display_name_public   BOOLEAN     NOT NULL DEFAULT false,
    group_number_public   BOOLEAN     NOT NULL DEFAULT false,

    alias                 TEXT,

    plate_frame           TEXT,
    badges_public         BOOLEAN     NOT NULL DEFAULT false,

    leaderboard_opt_in    BOOLEAN     NOT NULL DEFAULT false,
    set_by_moderator      BOOLEAN     NOT NULL DEFAULT false,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forum_profile_latest_idx
    ON forum_profile (account, created_at DESC);

CREATE TABLE IF NOT EXISTS forum_reported_name (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

CREATE TABLE IF NOT EXISTS forum_helpful (
    message_id TEXT        NOT NULL,
    account    TEXT        NOT NULL,

    value      SMALLINT    NOT NULL DEFAULT 1 CHECK (value IN (-1, 1)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, account)
);

CREATE TABLE IF NOT EXISTS display_preference (
    account    TEXT        NOT NULL PRIMARY KEY,
    theme      TEXT        NOT NULL CHECK (theme IN ('light', 'dark')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scratch_draft (
    account     TEXT        NOT NULL PRIMARY KEY,
    code        TEXT        NOT NULL CHECK (length(code) <= 65536),
    header_name TEXT        NOT NULL DEFAULT '',
    header      TEXT        NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scratch_draft_header_check
        CHECK (header_name ~ '^([A-Za-z0-9_]{1,32}\.h)?$'
               AND length(header) <= 65536
               AND (header_name <> '' OR header = ''))
);

CREATE TABLE IF NOT EXISTS team (

    team_id       TEXT        NOT NULL,
    assignment_id TEXT        NOT NULL,

    group_number  SMALLINT    NOT NULL CHECK (group_number BETWEEN 1 AND 99),
    number        SMALLINT    NOT NULL CHECK (number BETWEEN 1 AND 99),
    label         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS team_member (
    team_id       TEXT        NOT NULL,
    assignment_id TEXT        NOT NULL,
    account       TEXT        NOT NULL,
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assignment_id, account),
    FOREIGN KEY (team_id, assignment_id)
        REFERENCES team (team_id, assignment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS team_member_roster_idx
    ON team_member (assignment_id, team_id);

CREATE TABLE IF NOT EXISTS team_document (
    team_id     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, exercise_id)
);

CREATE TABLE IF NOT EXISTS team_revision (
    revision_id TEXT        PRIMARY KEY,
    team_id     TEXT        NOT NULL,
    exercise_id TEXT        NOT NULL,
    account     TEXT        NOT NULL,
    sources     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS team_revision_recent_idx
    ON team_revision (team_id, exercise_id, created_at DESC);

CREATE TABLE IF NOT EXISTS team_submission (
    assignment_id TEXT        NOT NULL,
    team_id       TEXT        NOT NULL,

    submitted_by  TEXT        NOT NULL,
    files         TEXT        NOT NULL,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assignment_id, team_id)
);

-- Repairs for databases created by earlier versions. Every statement must stay
-- idempotent, and an index must come after the ALTER that adds its column.
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS step         TEXT;
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS blocked_kind TEXT;
ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS visibility   TEXT NOT NULL
    DEFAULT 'thread';

ALTER TABLE forum_message DROP CONSTRAINT IF EXISTS forum_message_visibility_check;
ALTER TABLE forum_message ADD  CONSTRAINT forum_message_visibility_check
    CHECK (visibility IN ('private', 'group', 'thread'));

ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS reply_to TEXT;

ALTER TABLE forum_message ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (to_tsvector('french', text)) STORED;

ALTER TABLE forum_helpful ADD COLUMN IF NOT EXISTS value SMALLINT NOT NULL
    DEFAULT 1;

ALTER TABLE forum_helpful DROP CONSTRAINT IF EXISTS forum_helpful_value_check;
ALTER TABLE forum_helpful ADD  CONSTRAINT forum_helpful_value_check
    CHECK (value IN (-1, 1));

ALTER TABLE scratch_draft ADD COLUMN IF NOT EXISTS header_name TEXT NOT NULL DEFAULT '';
ALTER TABLE scratch_draft ADD COLUMN IF NOT EXISTS header      TEXT NOT NULL DEFAULT '';

ALTER TABLE scratch_draft DROP CONSTRAINT IF EXISTS scratch_draft_header_check;
ALTER TABLE scratch_draft ADD  CONSTRAINT scratch_draft_header_check
    CHECK (header_name ~ '^([A-Za-z0-9_]{1,32}\.h)?$'
           AND length(header) <= 65536
           AND (header_name <> '' OR header = ''));

CREATE INDEX IF NOT EXISTS forum_message_search_idx
    ON forum_message USING GIN (search);
CREATE INDEX IF NOT EXISTS forum_message_reply_idx
    ON forum_message (reply_to, created_at);

ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS alias              TEXT;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS plate_frame        TEXT;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS badges_public      BOOLEAN
    NOT NULL DEFAULT false;
ALTER TABLE forum_profile ADD COLUMN IF NOT EXISTS leaderboard_opt_in BOOLEAN
    NOT NULL DEFAULT false;

BEGIN;
ALTER TABLE forum_moderation DROP CONSTRAINT IF EXISTS forum_moderation_action_check;
ALTER TABLE forum_moderation ADD  CONSTRAINT forum_moderation_action_check
    CHECK (action IN ('hide', 'restore', 'retain', 'unretain'));
COMMIT;

CREATE INDEX IF NOT EXISTS team_member_roster_idx
    ON team_member (assignment_id, team_id);

ALTER TABLE team ADD COLUMN IF NOT EXISTS number SMALLINT;
ALTER TABLE team DROP COLUMN IF EXISTS invite_code;
ALTER TABLE team DROP COLUMN IF EXISTS sealed_at;
ALTER TABLE team_member DROP COLUMN IF EXISTS locked_at;

UPDATE team SET group_number = 1 WHERE group_number IS NULL;
UPDATE team SET number = 1 WHERE number IS NULL;
ALTER TABLE team ALTER COLUMN group_number SET NOT NULL;
ALTER TABLE team ALTER COLUMN number SET NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'team_sealed_has_a_group') THEN
        ALTER TABLE team DROP CONSTRAINT team_sealed_has_a_group;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'team_number_range') THEN
        ALTER TABLE team ADD CONSTRAINT team_number_range
            CHECK (number BETWEEN 1 AND 99);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS team_number_idx
    ON team (assignment_id, group_number, number);
DROP INDEX IF EXISTS team_invite_code_idx;

-- Solve events used to be keyed 'reussite:<exercise>', and that key is what
-- prevents a second XP grant. Rows are renamed unless the account already has
-- the new id, in which case both stay untouched.
UPDATE progress_event p SET event_id = 'solved:' || substr(p.event_id, 10)
 WHERE p.event_id LIKE 'reussite:%'
   AND NOT EXISTS (SELECT 1 FROM progress_event q
                    WHERE q.account = p.account
                      AND q.event_id = 'solved:' || substr(p.event_id, 10));
UPDATE xp_transaction x SET event_id = 'solved:' || substr(x.event_id, 10)
 WHERE x.event_id LIKE 'reussite:%'
   AND NOT EXISTS (SELECT 1 FROM xp_transaction y
                    WHERE y.account = x.account
                      AND y.event_id = 'solved:' || substr(x.event_id, 10));
UPDATE achievement_unlocked SET event_id = 'solved:' || substr(event_id, 10)
 WHERE event_id LIKE 'reussite:%';

-- The judge's run journal, ingested by the admin app. `account` is empty for an
-- anonymous run and for a Console session, whose job carries no owner by design;
-- `exercise_id = ':console'` tells those two apart. Because the column exists, forget()
-- must clear it: a student's deletion request takes their run history with it.
CREATE TABLE IF NOT EXISTS judge_run (
    job_id       TEXT        PRIMARY KEY,
    exercise_id  TEXT        NOT NULL,
    account      TEXT        NOT NULL DEFAULT '',
    status       TEXT        NOT NULL,
    kind         TEXT        NOT NULL,
    duration_s   REAL,
    queue_wait_s REAL,
    worker_id    TEXT        NOT NULL,
    cache_hit    BOOLEAN     NOT NULL DEFAULT false,
    reprises     INTEGER     NOT NULL DEFAULT 0,
    finished_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS judge_run_finished_idx ON judge_run (finished_at DESC);

-- One row per journal file: results/ is read-only to the API, so the judge's files are never
-- truncated and the offset is how far each has been read.
CREATE TABLE IF NOT EXISTS judge_journal_cursor (
    filename    TEXT   PRIMARY KEY,
    byte_offset BIGINT NOT NULL DEFAULT 0
);

-- Grants are listed table by table, never schema-wide, so a new table without
-- its grant is caught by the checks. Append-only tables get no UPDATE, and forum
-- messages are immutable apart from the two moderated columns.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctester_app') THEN
        RETURN;
    END IF;

    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE'
            ' ON exercise_draft, exercise_state, practice_attempt,'
            '    display_preference, scratch_draft'
            ' TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON progress_event, xp_transaction, achievement_unlocked'
            ' TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON forum_message, forum_report, forum_moderation, forum_helpful'
            ' TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, DELETE'
            ' ON forum_profile, forum_reported_name'
            ' TO ctester_app';

    EXECUTE 'GRANT UPDATE (hidden, visibility) ON forum_message TO ctester_app';

    EXECUTE 'GRANT UPDATE (value) ON forum_helpful TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT ON team TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, DELETE ON team_member TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, UPDATE'
            ' ON team_document, team_submission TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, DELETE ON team_revision TO ctester_app';

    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE'
            ' ON judge_run, judge_journal_cursor'
            ' TO ctester_app';
END
$$;
