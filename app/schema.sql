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

-- --------------------------------------------------------------------------
-- Progression (phase 1) : XP, niveau dérivé et quelques succès, pour les
-- comptes connectés seulement. TROIS TABLES DE FAITS, aucune de solde.
--
-- Le solde XP, le niveau, les compétences pratiquées et la recommandation sont
-- des PROJECTIONS : `app.py` les recalcule à la lecture depuis ces faits et le
-- catalogue public. Rien n'est mis en cache ici.
--
-- ponytail: pas de table de projection. Le solde est un `sum()` sur quelques
-- dizaines de lignes par étudiant, et une projection matérialisée serait un
-- deuxième endroit où la vérité peut diverger. À reprendre le jour où la somme
-- se voit, pas avant.
--
-- L'IDENTIFIANT D'ÉVÉNEMENT EST LE FAIT, PAS L'APPEL. « reussite:tp2-ex3 » se
-- lit, et sa clé primaire est ce qui rend l'écriture idempotente : un sondage
-- HTTP rejoué, un worker relancé ou deux requêtes concurrentes ne peuvent pas
-- créer deux fois le même XP. C'est aussi ce qui interdit le farming -- réussir
-- deux fois le même exercice produit deux fois le même identifiant.

-- Le journal (outbox) : ce que le serveur a constaté, en clair et pour l'audit.
-- `charge` porte le strict minimum -- le job d'origine et la difficulté ayant
-- servi au calcul -- jamais le code soumis ni un détail secret du verdict.
CREATE TABLE IF NOT EXISTS evenement_progression (
    utilisateur  TEXT        NOT NULL,
    evenement_id TEXT        NOT NULL,
    type         TEXT        NOT NULL,
    exercice_id  TEXT,
    politique    TEXT        NOT NULL,
    charge       TEXT        NOT NULL DEFAULT '{}',   -- JSON minimal
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, evenement_id)
);

-- Les attributions d'XP, en ajout seul, une par événement source.
--
-- `montant >= 0` ET PAS `> 0` : une réussite au-delà du plafond quotidien est
-- enregistrée à zéro plutôt que passée sous silence. Le fait a eu lieu, il se
-- relit, et l'étudiant peut voir qu'il a déjà été récompensé aujourd'hui.
--
-- ponytail: pas de clé étrangère vers evenement_progression. Les deux tables
-- partagent (utilisateur, evenement_id), l'insertion des deux se fait dans UNE
-- seule instruction, et `forget` les efface ensemble. Une contrainte de plus ne
-- protégerait ici que d'un psql ouvert à minuit.
CREATE TABLE IF NOT EXISTS transaction_xp (
    utilisateur  TEXT        NOT NULL,
    evenement_id TEXT        NOT NULL,
    montant      INTEGER     NOT NULL CHECK (montant >= 0),
    motif        TEXT        NOT NULL,
    exercice_id  TEXT,
    politique    TEXT        NOT NULL,
    accorde_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, evenement_id)
);

-- Le plafond quotidien somme les attributions du jour pour un étudiant :
-- c'est la seule lecture qui ne passe pas par le préfixe de la clé primaire.
CREATE INDEX IF NOT EXISTS transaction_xp_jour_idx
    ON transaction_xp (utilisateur, accorde_le DESC);

-- Les succès obtenus, en ajout seul. La clé primaire EST la règle « une seule
-- obtention » ; `evenement_id` dit lequel des faits l'a déclenchée.
CREATE TABLE IF NOT EXISTS succes_obtenu (
    utilisateur  TEXT        NOT NULL,
    succes_id    TEXT        NOT NULL,
    evenement_id TEXT        NOT NULL,
    politique    TEXT        NOT NULL,
    obtenu_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, succes_id)
);

-- --------------------------------------------------------------------------
-- Forum d'entraide (MVP) : UN fil par exercice publié, pour les comptes
-- connectés seulement. Ce n'est PAS de la gamification -- rien ici n'accorde
-- d'XP, ne débloque de succès ni ne touche aux trois tables ci-dessus.
--
-- CE QUI EST STOCKÉ, ET RIEN D'AUTRE : le `sub` opaque de l'auteur,
-- l'identifiant du message, l'exercice PUBLIC, le texte, les dates, l'état
-- visible/masqué, l'auteur d'un signalement, et les actions de modération. Ni
-- nom, ni courriel, ni numéro étudiant, ni pseudonyme persistant : aux autres
-- étudiants, une publication s'annonce « Participant », et c'est l'API qui
-- dérive ce mot du `sub` sans jamais le laisser sortir.
--
-- LA PLATEFORME FERME EN DÉCEMBRE. Aucune saison, aucun report entre sessions :
-- ces trois tables se vident avec la base à la fin du cours.

-- Un message est IMMUABLE. Son auteur peut le supprimer (la ligne disparaît),
-- un modérateur peut seulement le masquer ou le rétablir -- d'où `masque`, la
-- seule colonne que l'API a le droit de mettre à jour (voir le GRANT dans
-- VHome : `UPDATE (masque)`, pas `UPDATE`). Il n'y a pas d'édition : un
-- message corrigé après coup rendrait un signalement illisible.
CREATE TABLE IF NOT EXISTS forum_message (
    message_id  TEXT        PRIMARY KEY,   -- uuid4().hex, généré en Python
    exercice_id TEXT        NOT NULL,      -- un identifiant PUBLIC du catalogue
    utilisateur TEXT        NOT NULL,
    texte       TEXT        NOT NULL,
    masque      BOOLEAN     NOT NULL DEFAULT false,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Un fil se lit par exercice, du plus ancien au plus récent : c'est la seule
-- lecture qui ne passe pas par la clé primaire.
CREATE INDEX IF NOT EXISTS forum_message_fil_idx
    ON forum_message (exercice_id, cree_le);

-- Le signalement. LA CLÉ PRIMAIRE EST LA RÈGLE : un même compte ne peut pas
-- signaler deux fois le même message, et c'est Postgres qui le tient -- pas
-- une lecture suivie d'une écriture, qui laisserait la course ouverte.
CREATE TABLE IF NOT EXISTS forum_signalement (
    message_id  TEXT        NOT NULL,
    utilisateur TEXT        NOT NULL,      -- l'auteur du SIGNALEMENT
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, utilisateur)
);

-- Les actions de modération, EN AJOUT SEUL. On masque, on rétablit, et les deux
-- se relisent : « le message a été masqué puis rétabli » est une information,
-- pas un bruit à écraser. L'état courant vit dans `forum_message.masque` ;
-- ceci en est le journal.
--
-- ponytail: pas de clé étrangère vers forum_message. Les deux s'écrivent dans
-- UNE instruction (voir `forum_moderer` dans etat.py), et un message supprimé
-- par son auteur laisse une ligne de journal qui ne s'affiche nulle part --
-- c'est le comportement voulu d'un journal.
CREATE TABLE IF NOT EXISTS forum_moderation (
    action_id   TEXT        PRIMARY KEY,   -- uuid4().hex, généré en Python
    message_id  TEXT        NOT NULL,
    utilisateur TEXT        NOT NULL,      -- le MODÉRATEUR qui a agi
    action      TEXT        NOT NULL CHECK (action IN ('masquer', 'retablir')),
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- L'IDENTITÉ CHOISIE, ET ELLE EST FACULTATIVE DES DEUX CÔTÉS. Un nom qu'on
-- s'est donné, un numéro de groupe, et pour chacun le droit de ne pas
-- l'afficher. Rien ici ne vient d'un claim OIDC : ni nom légal, ni courriel --
-- ce que l'étudiant écrit est ce que l'étudiant a décidé d'écrire.
--
-- EN AJOUT SEUL, COMME LE RESTE DU FORUM : la dernière ligne d'un compte fait
-- foi (voir `forum_profil` dans etat.py). Aucun UPDATE, donc aucun GRANT
-- d'UPDATE, donc pas d'instruction distraite qui réécrit le nom de quelqu'un ;
-- et l'historique des changements de nom est précisément ce qu'une modération
-- veut pouvoir relire.
--
-- `par_moderateur` marque la ligne écrite par l'équipe du cours quand elle
-- efface un nom signalé. L'étudiant peut en choisir un autre ensuite : le
-- récidiviste est une affaire humaine, pas une machine à états.
CREATE TABLE IF NOT EXISTS forum_profil (
    profil_id      TEXT        PRIMARY KEY,  -- uuid4().hex, généré en Python
    utilisateur    TEXT        NOT NULL,
    pseudo         TEXT,                     -- NULL = aucun nom choisi
    groupe         SMALLINT    CHECK (groupe BETWEEN 1 AND 99),
    pseudo_public  BOOLEAN     NOT NULL DEFAULT false,
    groupe_public  BOOLEAN     NOT NULL DEFAULT false,
    par_moderateur BOOLEAN     NOT NULL DEFAULT false,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- La lecture qui compte : la dernière ligne d'un compte, ou de quelques comptes
-- à la fois quand on affiche un fil.
CREATE INDEX IF NOT EXISTS forum_profil_dernier_idx
    ON forum_profil (utilisateur, cree_le DESC);

-- Signaler un NOM, pas un message. Même règle et même clé primaire que
-- `forum_signalement` : un compte ne signale un nom qu'une fois par message
-- porteur. Le message sert de poignée -- il n'y a pas d'identifiant de compte
-- côté navigateur, et il ne doit pas y en avoir.
CREATE TABLE IF NOT EXISTS forum_nom_signale (
    message_id  TEXT        NOT NULL,
    utilisateur TEXT        NOT NULL,      -- l'auteur du SIGNALEMENT
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, utilisateur)
);
