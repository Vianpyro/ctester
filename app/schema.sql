-- ctester -- l'état des étudiants qui choisissent de se connecter.
--
-- SQLITE AURAIT SUFFI, ET IL FAUT L'ÉCRIRE ICI plutôt que dans une discussion
-- qui aura disparu dans six mois. La charge réelle est de 27 étudiants, une
-- session, quelques dizaines d'écritures par heure au pic d'un laboratoire, et
-- un seul processus qui écrit. `sqlite3` est dans la bibliothèque standard de
-- Python : zéro dépendance à installer dans le conteneur exposé, zéro service à
-- surveiller, zéro sauvegarde à organiser. Techniquement, c'est le bon outil, et
-- ça le resterait même à dix fois cette taille.
--
-- Postgres est choisi quand même, et la raison n'est pas technique : ce dépôt
-- est aussi un portfolio, et tenir une vraie base -- un schéma versionné, un
-- rôle applicatif aux droits limités, des sauvegardes, une migration -- est
-- précisément l'exercice recherché. Il ne faut pas maquiller ça en besoin de
-- performance : il n'y en a pas. Personne ne doit lire ce fichier dans deux ans
-- en croyant qu'une contrainte de charge a imposé Postgres.
--
-- La distinction UNLOGGED / journalisé ci-dessous est d'ailleurs le seul endroit
-- où le choix rapporte quelque chose de visible, et c'est un détail.
--
-- IL N'Y A AUCUNE DONNÉE NOMINATIVE ICI. `utilisateur` est le `sub` opaque
-- émis par Rauthy -- pas un nom, pas un courriel, pas un code permanent. Le nom
-- affiché à l'écran vient du jeton, dans le navigateur, et ne franchit jamais
-- cette frontière.

-- Le brouillon : ce qui n'a pas encore été soumis. UNLOGGED -- donc hors du
-- WAL, non répliqué, et VIDÉE par Postgres après un arrêt brutal. C'est
-- assumé : le prix d'un crash est « le travail non soumis de la dernière
-- séance », et le navigateur en garde de toute façon une copie locale.
CREATE UNLOGGED TABLE IF NOT EXISTS brouillon_exercice (
    utilisateur TEXT        NOT NULL,
    exercice_id TEXT        NOT NULL,
    sources     TEXT        NOT NULL,   -- JSON {nom_de_fichier: contenu}
    maj         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, exercice_id)
);

-- L'état : ce qui a été soumis au moins une fois. Table normale, donc WAL,
-- donc restaurable. C'est la seule chose de ce schéma dont la perte se
-- remarquerait -- un tableau de bord qui oublie ce qui a été validé ne sert
-- plus à rien.
--
-- Le CHECK plutôt qu'une validation en Python : la base est le dernier endroit
-- où la règle peut être vraie pour TOUS les chemins d'écriture, y compris un
-- psql ouvert à minuit. L'API valide aussi, mais ceci ne dépend pas d'elle.
CREATE TABLE IF NOT EXISTS etat_exercice (
    utilisateur TEXT        NOT NULL,
    exercice_id TEXT        NOT NULL,
    statut      TEXT        NOT NULL CHECK (statut IN ('essaye', 'valide')),
    sources     TEXT        NOT NULL,   -- JSON {nom_de_fichier: contenu}
    maj         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (utilisateur, exercice_id)
);

-- Pas d'index supplémentaire : les deux seules requêtes de lecture sont
-- « cet utilisateur, cet exercice » et « tous les exercices de cet
-- utilisateur ». La clé primaire commence par `utilisateur`, elle couvre donc
-- les deux. Un index de plus serait un index à maintenir sans lecteur.
