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
-- THERE IS NO PERSONALLY IDENTIFYING DATA HERE. `utilisateur` is the opaque
-- `sub` issued by Rauthy -- not a name, not an email, not a student number. The
-- display name lives in the token, in the browser, and never crosses this line.

-- The draft: what has not been submitted yet. UNLOGGED -- so out of the WAL,
-- not replicated, and TRUNCATED by Postgres after an unclean shutdown. That is
-- accepted: the price of a crash is "the unsubmitted work of the last session",
-- and the browser keeps a local copy of it anyway.
CREATE UNLOGGED TABLE IF NOT EXISTS brouillon_exercice (
    utilisateur TEXT        NOT NULL,
    exercice_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,   -- JSON {filename: contents}
    maj         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, exercice_id)
);

-- The state: what has been submitted at least once. An ordinary table, so WAL,
-- so restorable. It is the only thing here whose loss would be noticed -- a
-- dashboard that forgets what was solved is worth nothing.
--
-- A CHECK rather than a validation in Python: the database is the last place
-- where the rule can hold for EVERY write path, including a psql session opened
-- at midnight. The API validates too, but this does not depend on the API.
CREATE TABLE IF NOT EXISTS etat_exercice (
    utilisateur TEXT        NOT NULL,
    exercice_id TEXT        NOT NULL,
    statut      TEXT        NOT NULL CHECK (statut IN ('essaye', 'valide')),
    sources     TEXT        NOT NULL,   -- JSON {filename: contents}
    maj         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, exercice_id)
);

-- A practice attempt is an immutable fact written by the API only after it has
-- read the worker's result.  It is deliberately not a mastery score: the
-- current self-service judge can be fooled, and practice is still valuable
-- when it fails.  `job_id` makes polling/retries idempotent.
CREATE TABLE IF NOT EXISTS tentative_pratique (
    job_id       TEXT        PRIMARY KEY,
    utilisateur  TEXT        NOT NULL,
    exercice_id  TEXT        NOT NULL,
    statut       TEXT        NOT NULL,
    total        INTEGER     NOT NULL CHECK (total >= 0),
    reussis      INTEGER     NOT NULL CHECK (reussis >= 0 AND reussis <= total),
    terminee_le  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tentative_pratique_utilisateur_finie_idx
    ON tentative_pratique (utilisateur, terminee_le DESC);

-- The two state tables are covered by their primary key.  Practice history is
-- read newest-first per user, hence its one explicit index above.
