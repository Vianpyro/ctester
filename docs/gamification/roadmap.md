# Roadmap d'implementation

## Phase 0 — documentation (actuelle)

Livrable: ce repertoire, revue avec enseignant/proprietaire et resolution des questions bloquantes. Aucun schema ni API de jeu n'est implemente.

## Phase 1 — progression fondamentale

Objectif: comptes connectes voient skills, XP/niveau et quelques accomplissements sans modifier le juge. Pre-requis: migrations versionnees, metadonnees publiques de contenu, ecriture serveur autoritaire des tentatives, outbox idempotente, export/suppression, tests de non-regression anonyme. Exclut: classe, reset saisonnier et formule complexe de mastery.

## Phase 2 — maitrise verifiee (valeur educative prioritaire)

Ajouter variantes de verification, evidence, projection de maitrise provisoire, recommandations et vue de preparation aux examens. Pre-requis: politique d'aide, accommodation, contenu revise pour transfert, scripts de test secrets, pilote et validation pedagogique. Ne pas annoncer une prediction de note.

## Phase 3 — profil et accomplissements

Ajouter collection, titres/cosmetiques justifies et profil prive/public opt-in. Auditer les criteres, confidentialite et inequites avant chaque ajout.

## Phase 4 — social

Objectifs collectifs et contribution sans partage de solution, avec moderation/politique. Mesurer pression sociale et retirer toute mecanique nuisible.

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
