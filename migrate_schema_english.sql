-- One-time migration: rename the French table/column identifiers in the live
-- Postgres schema to match the English `app/schema.sql`. Run this ONCE, by
-- hand, with the admin DSN, BEFORE deploying a code revision that expects the
-- new names -- `schema.sql`'s `CREATE TABLE IF NOT EXISTS` will not rename an
-- existing table, it would just leave the old one orphaned with real student
-- data in it.
--
--   psql "$CTESTER_DB_ADMIN_DSN" -f migrate_schema_english.sql
--
-- Idempotent: every rename is guarded so a second run is a no-op instead of an
-- error, in case the tick that verifies the schema runs mid-migration.
--
-- ALSO TRANSLATES THE ENUM-STYLE VALUES ('essaye'/'valide' in
-- exercise_state.status, 'masquer'/'retablir' in forum_moderation.action) at
-- the bottom of this script: those are a wire-format value shared with the
-- API response, the JS frontend and the test suites, so this migration must
-- run in the same deploy as that whole-stack change, not before it.

-- THE DECOYS, AND THIS BLOCK EXISTS BECAUSE IT ALREADY HAPPENED ONCE. Deploying
-- the English `schema.sql` before this migration does not fail on the tables it
-- renames: `CREATE TABLE IF NOT EXISTS` CREATES them, EMPTY, right next to the
-- French ones that still hold every student's work. The rename below would then
-- die on "relation already exists", and the API -- which reads the new names --
-- serves an empty account to everyone in the meantime.
--
-- So: an empty table under the new name is that accident, and it is dropped. A
-- NON-EMPTY one means the API has been writing into it since, and this script
-- REFUSES rather than choose which half of a student's work to keep. That
-- decision belongs to a human reading both tables.
DO $$
DECLARE
    r RECORD;
    lignes BIGINT;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('brouillon_exercice',    'exercise_draft'),
        ('etat_exercice',         'exercise_state'),
        ('tentative_pratique',    'practice_attempt'),
        ('evenement_progression', 'progress_event'),
        ('transaction_xp',        'xp_transaction'),
        ('succes_obtenu',         'achievement_unlocked'),
        ('forum_signalement',     'forum_report'),
        ('forum_profil',          'forum_profile'),
        ('forum_nom_signale',     'forum_reported_name'),
        ('preference_affichage',  'display_preference')
    ) AS paires(old_name, new_name)
    LOOP
        IF EXISTS (SELECT 1 FROM pg_tables
                   WHERE schemaname = 'public' AND tablename = r.old_name)
           AND EXISTS (SELECT 1 FROM pg_tables
                       WHERE schemaname = 'public' AND tablename = r.new_name)
        THEN
            EXECUTE format('SELECT count(*) FROM %I', r.new_name) INTO lignes;
            IF lignes > 0 THEN
                RAISE EXCEPTION
                    'MIGRATION STOPPED: % (French, with the real data) and % '
                    '(English, % row(s)) both exist. The API has written into '
                    'the new table since a premature schema.sql. Merge the two '
                    'by hand, then re-run this script.',
                    r.old_name, r.new_name, lignes;
            END IF;
            EXECUTE format('DROP TABLE %I', r.new_name);
            RAISE NOTICE 'dropped the empty % created by a premature schema.sql',
                         r.new_name;
        END IF;
    END LOOP;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'brouillon_exercice') THEN
        ALTER TABLE brouillon_exercice RENAME TO exercise_draft;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'etat_exercice') THEN
        ALTER TABLE etat_exercice RENAME TO exercise_state;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'tentative_pratique') THEN
        ALTER TABLE tentative_pratique RENAME TO practice_attempt;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evenement_progression') THEN
        ALTER TABLE evenement_progression RENAME TO progress_event;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'transaction_xp') THEN
        ALTER TABLE transaction_xp RENAME TO xp_transaction;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'succes_obtenu') THEN
        ALTER TABLE succes_obtenu RENAME TO achievement_unlocked;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'forum_signalement') THEN
        ALTER TABLE forum_signalement RENAME TO forum_report;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'forum_profil') THEN
        ALTER TABLE forum_profil RENAME TO forum_profile;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'forum_nom_signale') THEN
        ALTER TABLE forum_nom_signale RENAME TO forum_reported_name;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'preference_affichage') THEN
        ALTER TABLE preference_affichage RENAME TO display_preference;
    END IF;
END $$;

-- Column renames. `ALTER TABLE ... RENAME COLUMN IF EXISTS` requires PG 15+;
-- guarded with information_schema checks instead so this also runs on older
-- Postgres.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('exercise_draft',        'utilisateur',    'account'),
        ('exercise_draft',        'exercice_id',    'exercise_id'),
        ('exercise_draft',        'maj',            'updated_at'),
        ('exercise_state',        'utilisateur',    'account'),
        ('exercise_state',        'exercice_id',    'exercise_id'),
        ('exercise_state',        'statut',         'status'),
        ('exercise_state',        'maj',            'updated_at'),
        ('practice_attempt',      'utilisateur',    'account'),
        ('practice_attempt',      'exercice_id',    'exercise_id'),
        ('practice_attempt',      'statut',         'status'),
        ('practice_attempt',      'reussis',        'passed'),
        ('practice_attempt',      'terminee_le',    'completed_at'),
        ('progress_event',        'utilisateur',    'account'),
        ('progress_event',        'evenement_id',   'event_id'),
        ('progress_event',        'exercice_id',    'exercise_id'),
        ('progress_event',        'politique',      'policy'),
        ('progress_event',        'charge',         'payload'),
        ('progress_event',        'cree_le',        'created_at'),
        ('xp_transaction',        'utilisateur',    'account'),
        ('xp_transaction',        'evenement_id',   'event_id'),
        ('xp_transaction',        'montant',        'amount'),
        ('xp_transaction',        'motif',          'reason'),
        ('xp_transaction',        'exercice_id',    'exercise_id'),
        ('xp_transaction',        'politique',      'policy'),
        ('xp_transaction',        'accorde_le',     'granted_at'),
        ('achievement_unlocked',  'utilisateur',    'account'),
        ('achievement_unlocked',  'succes_id',      'achievement_id'),
        ('achievement_unlocked',  'evenement_id',   'event_id'),
        ('achievement_unlocked',  'politique',      'policy'),
        ('achievement_unlocked',  'obtenu_le',      'unlocked_at'),
        ('forum_message',         'exercice_id',    'exercise_id'),
        ('forum_message',         'utilisateur',    'account'),
        ('forum_message',         'texte',          'text'),
        ('forum_message',         'masque',         'hidden'),
        ('forum_message',         'cree_le',        'created_at'),
        ('forum_report',          'utilisateur',    'account'),
        ('forum_report',          'cree_le',        'created_at'),
        ('forum_moderation',      'utilisateur',    'account'),
        ('forum_moderation',      'cree_le',        'created_at'),
        ('forum_profile',         'profil_id',      'profile_id'),
        ('forum_profile',         'utilisateur',    'account'),
        ('forum_profile',         'pseudo',         'display_name'),
        ('forum_profile',         'groupe',         'group_number'),
        ('forum_profile',         'pseudo_public',  'display_name_public'),
        ('forum_profile',         'groupe_public',  'group_number_public'),
        ('forum_profile',         'par_moderateur', 'set_by_moderator'),
        ('forum_profile',         'cree_le',        'created_at'),
        ('forum_reported_name',   'utilisateur',    'account'),
        ('forum_reported_name',   'cree_le',        'created_at'),
        ('display_preference',    'utilisateur',    'account'),
        ('display_preference',    'maj',            'updated_at')
    ) AS renames(table_name, old_name, new_name)
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = r.table_name
                     AND column_name = r.old_name)
        THEN
            EXECUTE format('ALTER TABLE %I RENAME COLUMN %I TO %I',
                           r.table_name, r.old_name, r.new_name);
        END IF;
    END LOOP;
END $$;

-- Indexes: dropped and recreated under their new name rather than renamed in
-- place, since `schema.sql` declares them with the new names via
-- `CREATE INDEX IF NOT EXISTS` and a stale old name would just sit next to
-- them unused.
DROP INDEX IF EXISTS tentative_pratique_utilisateur_finie_idx;
DROP INDEX IF EXISTS transaction_xp_jour_idx;
DROP INDEX IF EXISTS forum_message_fil_idx;
DROP INDEX IF EXISTS forum_profil_dernier_idx;

-- Enum-style VALUES: 'essaye'/'valide' -> 'attempted'/'solved',
-- 'masquer'/'retablir' -> 'hide'/'restore'. The CHECK constraint is dropped
-- and recreated too: `CREATE TABLE IF NOT EXISTS` is a no-op on a table that
-- already exists, so it would never update an old constraint's allowed
-- values on its own, and the constraint's auto-generated name does not
-- follow a table/column rename.
--
-- DROP THE CONSTRAINT FIRST, THEN UPDATE. The old CHECK still reads
-- `IN ('essaye', 'valide')` -- it survived the table and column rename under
-- its generated name -- so an UPDATE run before the drop is refused by the
-- very constraint this script is here to replace.
DO $$
DECLARE
    con RECORD;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'exercise_state'
                 AND column_name = 'status') THEN
        FOR con IN SELECT conname FROM pg_constraint
                    WHERE conrelid = 'exercise_state'::regclass AND contype = 'c'
        LOOP
            EXECUTE format('ALTER TABLE exercise_state DROP CONSTRAINT %I', con.conname);
        END LOOP;
        UPDATE exercise_state SET status = 'attempted' WHERE status = 'essaye';
        UPDATE exercise_state SET status = 'solved' WHERE status = 'valide';
        ALTER TABLE exercise_state
            ADD CONSTRAINT exercise_state_status_check
            CHECK (status IN ('attempted', 'solved'));
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'forum_moderation'
                 AND column_name = 'action') THEN
        FOR con IN SELECT conname FROM pg_constraint
                    WHERE conrelid = 'forum_moderation'::regclass AND contype = 'c'
        LOOP
            EXECUTE format('ALTER TABLE forum_moderation DROP CONSTRAINT %I', con.conname);
        END LOOP;
        UPDATE forum_moderation SET action = 'hide' WHERE action = 'masquer';
        UPDATE forum_moderation SET action = 'restore' WHERE action = 'retablir';
        ALTER TABLE forum_moderation
            ADD CONSTRAINT forum_moderation_action_check
            CHECK (action IN ('hide', 'restore'));
    END IF;
END $$;

-- Re-run app/schema.sql after this script (as the role owning the tables) to
-- create the new indexes and pick up any table this migration found nothing
-- to rename for (a fresh database, or one already migrated).
