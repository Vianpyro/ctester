# Roadmap d'implementation

## Phase 0 — documentation (livree)

Livrable: ce repertoire, revue avec enseignant/proprietaire et resolution des questions bloquantes.

## Phase 1 — progression fondamentale (livree)

Objectif: comptes connectes voient skills, XP/niveau et quelques accomplissements sans modifier le juge. Exclut: classe, reset saisonnier et formule complexe de mastery.

**Ce qui est en place.** Trois tables de faits en ajout seul (`evenement_progression`, `transaction_xp`, `succes_obtenu`) dans `app/schema.sql`; une politique declarative et versionnee dans `app/politique.py`; l'attribution cote serveur a la lecture du verdict, idempotente par identifiant d'evenement `reussite:<exercice>`; `GET /progres` authentifie, qui derive solde, niveau, competences pratiquees, succes et recommandation sans rien mettre en cache; la vue `app/progres.js`, chargee au clic et seulement connectee; la suppression etendue a toutes les tables en une instruction. Les non-regressions anonyme et connectee sont dans `test_page.js`, les contrats et l'idempotence dans `test_ctester.py`.

**Ce qui reste ouvert.** Les montants, plafonds et seuils sont des valeurs de pilote non observees (voir [xp.md](xp.md) et [levels.md](levels.md)); aucune correction d'XP administrative n'existe encore, et le GRANT applicatif l'interdit deliberement.

## Hors phases — forum d'entraide MVP (livre)

Un lot volontairement place ENTRE la Phase 1 et la Phase 2, et qui n'appartient a
aucune des deux. Voir [D-008](decisions.md) et [social.md](social.md).

**Ce qui est en place.** Trois tables de faits (`forum_message`,
`forum_signalement`, `forum_moderation`) dans `app/schema.sql`, en ajout seul a
une colonne pres (`UPDATE (masque)` par GRANT de colonne); six routes derriere
`_who()`, toutes bornees par `find_tp()`; un role de moderation configure par
`CTESTER_FORUM_MODERATORS` et recalcule serveur a chaque appel; la vue
`app/forum.js`, chargee au clic et seulement connectee, avec un rendu Markdown
restreint assaini a chaque affichage ([D-009](decisions.md)); une charte visible
en permanence et avant la premiere publication; `DELETE /moi` etendu.

**Ce que ce lot ne fait PAS.** Il ne realise pas la Phase 4 : ni objectif de
classe, ni contribution mesuree, ni groupe-cours, ni visibilite configurable. Il
ne recompense rien — aucun XP, aucun succes, aucun compteur. Il ne remplace pas
la Phase 2, et ne dit rien de la maitrise.

**Ce qui reste ouvert.** L'equilibre du quota d'ecriture (10 s / 20 par heure et
par compte) et la longueur maximale (1200 caracteres) sont des valeurs non
observees. Le forum depend entierement d'une moderation humaine : sa charge reelle
a 27 etudiants n'est pas connue, et c'est le critere de sortie a surveiller.

## Phase 2 — maitrise verifiee (valeur educative prioritaire)

Ajouter variantes de verification, evidence, projection de maitrise provisoire, recommandations et vue de preparation aux examens. Pre-requis: politique d'aide, accommodation, contenu revise pour transfert, scripts de test secrets, pilote et validation pedagogique. Ne pas annoncer une prediction de note.

## Phase 3 — profil et accomplissements

Ajouter collection, titres/cosmetiques justifies et profil prive/public opt-in. Auditer les criteres, confidentialite et inequites avant chaque ajout.

## Phase 4 — social

Objectifs collectifs et contribution sans partage de solution, avec moderation/politique. Mesurer pression sociale et retirer toute mecanique nuisible. **Le forum MVP livre plus haut n'est PAS cette phase** : il n'agrege rien, ne mesure aucune contribution et ne connait pas de cohorte.

## Phase 5 — classe

Seulement quand verification, variantes, audit et anti-farming ont survecu a une session pilote. Definir rating, divisions, saisons et gestion d'incidents avant exposition publique.

## Phase 6/7 — contenu avance et analyse

Etendre les pools contextuels/evenements apres validation; analyser engagement, equite et correlation mastery-examen sous gouvernance appropriee.

## Checklist avant chaque phase

1. Decision record accepte et questions bloquantes resolues.
2. Migration reversible/testee et plan de rollback.
3. Contrats API versionnes; client ancien degrade correctement.
4. Tests unitaire, integration, idempotence, confidentialite et acces.
5. Instrumentation minimale, retention et responsable de revue definis.
6. Pilotage, support utilisateur et criteres de sortie annonces.
