# Niveaux

Un niveau est une presentation derivee du XP total, pas une qualification. Une table de seuils versionnee (`level_policy`) traduit XP en niveau et titre eventuel; son edition conserve le calcul historique ou migre explicitement selon une decision publiee. Ne pas promettre une cadence de niveau avant observation d'usage.

**Phase 1:** `app/politique.py` porte la table de seuils (`niveaux`), sans titre — « expert » sur un compteur d'activite laisserait croire a une qualification. Le rang, le palier courant et l'XP restant sont derives a chaque lecture de `GET /progres`; rien n'est stocke, donc editer les seuils ne demande pas de migration.

Un level-up est detecte lors de l'enregistrement idempotent d'une transaction, annonce une fois, et ne donne pas de privilege academique. Il peut debloquer une cosmetique ou une explication, jamais une competence ni un contenu obligatoire. L'interface montre niveau, XP et progression vers le prochain niveau sans pression de connexion quotidienne.
