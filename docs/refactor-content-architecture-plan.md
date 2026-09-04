# CTESTER — plan de refactor global de contenu

Analyse en lecture seule des dépôts ctester, unittests, solutions et VHome
(2026-09-04). Ce fichier est un plan, sans implémentation.

## Executive summary

La cible recommandée est : exercice autonome à ID stable; collections génériques
et ordonnées; bonus = exercice; catalogue public projeté depuis un contenu privé
validé. L'ajout d'un exercice, bonus ou collection utilisant quiz, IO ou Unity
ne requiert aucun changement backend. Les solutions restent dans un dépôt privé
séparé et, à terme, hors du Dell de production.

## Architecture actuelle

- runner.py découvre 73 configurations sous unittests: tp1/quiz.json, tpN/exN,
  devoir et bonus. Il dérive ID, ordre et groupe des chemins tpN/exN.
- quiz.json, io.json et unity.json déterminent le mode; ils portent aussi
  label, statement, templates, learning, available_from et des secrets.
- publish_catalogue() filtre ce contenu en tps.json, tp/id.json et quiz/id.json
  dans src/app. find_tp() est la porte API et tp_path() celle du worker.
- Les futurs contenus sont absents, pas verrouillés. L'UI est deux sélecteurs
  groupe/exercice.
- La persistance utilise déjà exercice_id (drafts, états, tentatives, XP, forum).
- VHome sépare correctement web (app RO + spool RW), worker root, et sandbox
  gVisor. Le web ne monte jamais tests ni solutions. IO ne monte pas io.json;
  Unity monte seulement le test de l'exercice. Les solutions ne vont jamais au
  sandbox.

## Problèmes du modèle actuel

1. Identité, chemin, ordre, groupe et URL sont couplés à tpN/exN.
2. TP est une convention spéciale; multi-collection et hors-collection sont
   difficiles.
3. available_from cache au lieu de montrer/verrouiller.
4. Public et privé cohabitent dans les configurations; le filtre est bon mais
   devient plus fragile avec de nouveaux champs.
5. Le worker publie dans le clone de l'application.
6. valider_contenu.py suppose tests/solutions et reconstruit les chemins.

## Architecture cible

Conserver trois dépôts logiques : application; contenu privé (actuel unittests,
renommage Git facultatif); solutions privées.

    content/
      catalog.json
      exercises/<exercise-id>/
        exercise.json
        statement.md
        public/
        assessment/{quiz.json|io.json|unity.json}
      collections/<collection-id>.json
      shared/unity/

Le publisher ne copie jamais récursivement ce contenu : il construit une
projection allowlistée dans published/<content-sha>, puis bascule atomiquement
published/current. Le web monte uniquement current en lecture seule.

Une collection contient id, title, description facultative, release facultative
et items (liste ordonnée d'IDs). Elle ne définit ni identité ni release des
exercices. Un bonus est un exercice ordinaire. Un exercice peut être sans
collection ou appartenir à plusieurs collections.

## Exercise model, release et modes

exercise.json exige schema_version, id, title et release; il peut porter summary,
skills, difficulty, contexts et prerequisites. statement.md est obligatoire
pour les exercices de code. ID proposé : [a-z0-9][a-z0-9-]{0,62}, stable après
publication et jamais réutilisé.

Difficulty est intrinsèque (intro/foundation/intermediate/advanced), non le
numéro de TP. Skills sont des IDs indépendants validés par catalog.json.
Contexts sont facultatifs. Prerequisites sont seulement informatifs en phase 1.
Ne pas créer expected_level/course_position : les collections portent le parcours.

Release est par exercice : available, scheduled ou archived, avec date ISO-8601
et fuseau (America/Toronto à confirmer). Le catalogue montre scheduled avec
cadenas/date; une fonction serveur unique impose l'accès à détail, quiz,
brouillon, forum et soumission, et le worker revalide avant exécution.

Conserver la détection du mode : exactement un fichier assessment parmi quiz,
IO, Unity; aucun champ mode dupliqué dans exercise.json. Le validateur impose
les exigences du mode. Un quatrième moteur reste un changement backend/sandbox
explicite et revu.

## Content discovery et validation

Une bibliothèque/CLI commune au worker, à CI et aux tests doit :

1. Scanner seulement exercises/*/exercise.json et collections/*.json.
2. Valider IDs, schéma, dates, paths, skills, collections, prerequisites,
   fichiers soumis, assets publics, mode unique et contraintes de mode.
3. Construire le modèle interne ID -> chemin privé.
4. Valider les solutions avec le vrai juge.
5. Générer une release atomique et un manifest de révision.

Échecs bloquants : JSON/ID invalides, doublons, fichiers/statement manquants,
collection/skill/référence inconnue, cycle de prérequis, release invalide,
asset hors racine, mode absent/multiple ou config contradictoire. Exercice sans
collection : avertissement configurable. Solution absente : échec CI par défaut.

Le catalogue public contient version, révision, collections, résumés et état
d'accès. Détails : statement, templates et assets explicitement publics.
Il exclut paths, cases, stdin/expect, answers, notes, seeds, tests, commandes
et solutions. Ajouter un champ public exige une extension explicite d'allowlist.

## Solutions : options et recommandation

### Option A — deux dépôts

Avantages : permissions, ownership, historique et deploy keys distincts; réduit
la fuite accidentelle. Inconvénients : conventions/PRs couplés, synchronisation
double et gitlink confus. Sécurité : frontière Git utile mais root Dell voit les
deux clones. Complexité faible-moyenne; Ansible garde deux clés/clones.

### Option B — un dépôt, répertoires séparés

Avantages : PR atomique et CI simple. Inconvénients : permissions par dossier
non robustes, CODEOWNERS = revue et non frontière, tout clone lit les solutions.
Risque humain élevé; rejeté.

### Option C — contenu unifié conceptuellement, solutions hors web tier

Avantages : relation par ID/manifest, CI peut réunir temporairement les deux,
solutions absentes du web et à terme du Dell. Inconvénients : bundle/manifest,
versions et reproductibilité. Complexité moyenne, sécurité la meilleure.

Choix : C, via A durant migration. Garder solutions distinct de content,
supprimer le sous-module et le clone sous content/solutions. À court terme Dell
garde le clone séparé pour la validation; à moyen terme CI privée valide le
couple contenu/solutions et déploie contenu/tests, jamais les solutions.

## Security model

| Niveau | Autorisé | Interdit |
|---|---|---|
| Navigateur | catalogue/détails, ses données | tests, réponses, attentes, solutions, chemins |
| Web/API | publication RO, spool RW, DB limitée | Docker, contenu privé, solutions |
| Worker | contenu privé, spool, Docker, publication | confiance dans ID/path client |
| Sandbox IO | sources, cas matérialisés | io.json, attentes, solutions, réseau |
| Sandbox Unity | sources, test courant, Unity | solutions, autres tests, réseau |

Les contrôles actuels de filtrage quiz, sortie Unity/ASan, paths, whitelist de
fichiers, réseau absent et gVisor sont des invariants. Ajouter tests récursifs
de fuite pour answer, expect, stdin, note et path dans toute projection.

## Ansible / deployment

VHome doit remplacer /opt/ctester/tests par content-private, créer
/opt/ctester/published root-owned, monter published/current:/catalog:ro dans le
web et régler STATIC vers ce montage. Worker reçoit CONTENT_PRIVATE/PUBLISHED;
ReadWritePaths couvre spool et published, pas le clone app.

Le timer contenu tire des révisions cohérentes, valide contenu et solutions,
publie, contrôle les fuites, puis bascule current et son témoin de SHAs. En
échec current reste intact. Conserver N releases : rollback = repointer current,
sans rollback de données. Deploy keys restent RO et distinctes.

## Migration, API et UI

1. Inventorier les 73 IDs et commencer par mapping identitaire (tp2-ex1 reste
   tp2-ex1).
2. Migrer exercices/tests/solutions sans changement d'ID; créer collections
   TP, bonus et devoir reproduisant l'ordre actuel.
3. Publier v2 en parallèle et comparer IDs, modes, files, détails et access.
4. Accepter temporairement tp comme alias de exercise_id; conserver ou rediriger
   tps.json, tp/id.json et ?tp=id.
5. Retirer regex TP et parsing UI après la fenêtre de compatibilité.

Les tables sont déjà par exercice_id : pas de migration SQL si IDs inchangés.
Pour un renommage indispensable : migration transactionnelle de toutes les
tables/événements, table d'aliases et transformation de reussite:<id>; jamais
réutiliser un ID.

API cible : catalog.json v2, exercises/id, exercise_id dans les corps et spool,
et find_exercise(id,purpose) unique. UI cible : collections repliables,
progression par collection, hors-collection, cadenas/date, recherche locale et
filtres skills/context/difficulty, liens /exercise/id. L'export main.c devient
une capacité explicite de collection.

## Gamification et contribution

XP, practice, mastery, verified mastery, bests, streaks et challenges doivent
référencer exercise_id, jamais (tp, exercise). Skills deviennent catalogue
indépendant. Le juge libre reste une preuve de pratique, non de maîtrise vérifiée.

Workflow contributeur : dossier, metadata, statement, public, assessment/tests,
solution, collection; CLI validate; PR CI. Aucun backend à modifier pour les
trois modes existants.

## Decision records

Decision: exercise ID explicite. Context: ID dérivé du chemin. Options:
conserver/dériver/explicite. Chosen: explicite stable. Why: persistance et
multi-collection. Consequences: mapping + compatibilité URL.

Decision: collection générique, bonus exercice. Context: TP/bonus spéciaux.
Options: hardcode/catégories/collections. Chosen: collections. Why: aucun code
par parcours. Consequences: ordre hors noms.

Decision: release serveur par exercice. Context: futurs masqués. Options:
UI/filtre/catalogue verrouillé. Chosen: verrouillé. Why: UX + sécurité.
Consequences: access unique et fuseau.

Decision: mode par fichier assessment. Context: détection actuelle. Options:
champ/détection/plugins. Chosen: détection allowlistée. Why: une vérité.
Consequences: nouveau moteur = code/revue.

Decision: catalogue projeté hors app. Context: worker écrit dans src/app.
Options: conserver/Jinja/release publisher. Chosen: publisher. Why: frontière,
atomicité, rollback. Consequences: VHome/volumes.

Decision: solutions séparées, CI/manifest. Context: gitlink. Options A/B/C.
Chosen: C via A. Why: sécurité au-delà de Git. Consequences: supprimer gitlink.

## Design invariants

1. Nouvel exercice/bonus/collection sans backend pour quiz/IO/Unity.
2. ID stable, sans slash, non réutilisable.
3. Collection non identitaire; exercice multi/hors collection possible.
4. Web/navigateur n'ont jamais secrets, tests, solutions ou paths.
5. Client ne choisit ni path ni fichiers; worker revalide.
6. Mode a une seule source de vérité.
7. Release imposée serveur et worker.
8. Contenu invalide ne remplace jamais publication active.
9. Rollback catalogue atomique sans rollback DB.
10. Données utilisateur restent valides.
11. Anonymat, quotas, spool, gVisor et OIDC facultatif subsistent.
12. Nouveau champ public exige allowlist.

## Phases, tests et rollback

| Phase | Objectif | Dépôts | Risque / rollback |
|---|---|---|---|
| 0 | ADR, schéma, inventaire IDs | tous | aucune modification runtime |
| 1 | CLI validation/modèle/fixtures | ctester, content | ne pas publier v2 |
| 2 | arborescence + mapping + CI solutions | content, solutions | branches v1 |
| 3 | publisher/catalogue v2 | ctester | current reste v1 |
| 4 | access, worker/spool, compat API | ctester | feature flag v1 |
| 5 | UI catalogue | ctester | UI v1 |
| 6 | volumes/timers/permissions/releases | VHome | repointer current |
| 7 | bascule et monitoring | tous | rollback publication/UI |
| 8 | retrait héritage TP/gitlink | tous | après compatibilité |
| 9 | fondations gamification | ctester | migrations add-only |

Ajouter golden tests catalogue v1/v2, fuzz paths, matrice release sur chaque
route, tests permissions/volumes, fuite JSON/Unity-ASan, solutions par mode,
UI locked/deep-links, SQL aliases et publication interrompue. Repasser
test_ctester, test_api, test_parite pendant coexistence, test_page,
valider_contenu, test_bac_a_sable et test_postgres.

## Change matrix

| Repository | File/Directory | Change | Reason | Risk | Phase |
|---|---|---|---|---|---|
| ctester | runner.py | discovery/publisher/access | modèle explicite | élevé | 1-4 |
| ctester | valider_contenu.py | CLI schéma + solutions | erreurs avant prod | moyen | 1-2 |
| ctester | catalogue.py, routers | v2/exercise_id | accès unique | élevé | 3-4 |
| ctester | spool.py, schemas, web | compat + UX catalogue | données/UI | moyen | 4-5 |
| unittests/content | exercises, collections, catalog | migration contenu | autonomie | élevé | 2 |
| unittests | CI, .gitmodules | validation/retrait gitlink | sécurité Git | moyen | 1-8 |
| solutions | structure, CI, policy | IDs, preuve, accès | sécurité | élevé | 2 |
| VHome | defaults/tasks/compose/unit/timer | volumes/release | frontière runtime | élevé | 6 |
| VHome | README/playbook/inventory | runbook/rollback | exploitation | moyen | 6 |

## Open questions

1. CI privée peut-elle valider sans déployer les solutions sur Dell ?
2. Quel statut/politique pour devoir ?
3. Prérequis informatifs ou bloquants ?
4. Fuseau officiel et sort des jobs à l'archivage ?
5. Export main.c : conservé, pour quelles collections ?
6. Qui possède le catalogue skills/le changement de schéma ?

## Critère final

Oui : un contributeur ajoute metadata, consigne, templates, assessment, tests,
solution et collections; validate/CI/publisher le découvrent. Aucun changement
ctester n'est requis pour quiz, IO ou Unity. Nouveau moteur ou nouveau champ
public reste un changement logiciel/sécurité explicite.
