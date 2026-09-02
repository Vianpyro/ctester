# Journal de decisions

## D-001 — Separer pratique et maitrise

**Statut:** Accepted.

**Decision:** seule une verification independante explicitement eligible constitue une preuve forte de maitrise; XP reste distinct.

**Raison:** l'aide et l'IA peuvent etre utiles a la pratique mais ne prouvent pas l'autonomie.

**Alternatives:** assimiler toute reussite du juge a la competence (rejetee).

**Consequences:** nouveaux types de contenu/tentatives et une UI qui explique la difference.

## D-002 — Pas de detecteur IA comme fondation

**Statut:** Accepted.

**Decision:** concevoir des demonstrations de transfert/variantes plutot que classifier l'origine du code.

**Raison:** detection peu fiable et pedagogiquement fragile.

**Alternatives:** detection automatique/sanction (rejetee comme mecanisme principal).

**Consequences:** aucune score IA dans mastery, rating ou discipline.

## D-003 — Evolution incremental compatible avec l'architecture

**Statut:** Accepted.

**Decision:** conserver API Python, page existante, runner et Postgres optionnel; ajouter migrations et projection serveur sans framework ou bus distribue.

**Raison:** l'application est petite, ses frontieres de securite sont importantes et un changement d'architecture serait hors sujet.

**Alternatives:** replatforming/event bus externe (rejetes pour maintenant).

**Consequences:** table outbox et workers simples si necessaire; flux anonyme intact.

## D-004 — Le classement est secondaire et opt-in

**Statut:** Accepted.

**Decision:** pas de ranked avant la Phase 5; pas de leaderboard global par defaut.

**Raison:** le public est debutant et l'objectif est la progression personnelle.

**Alternatives:** classement des le lancement (rejetee).

**Consequences:** consentement et pseudonymes prealables; mastery/anti-farming avant rating.

## D-005 — Politique de valeurs configurable

**Statut:** Accepted.

**Decision:** XP, niveaux, seuils, recence, ratio de recommandations et rating sont versionnes/configures, tous PROVISOIRES tant qu'ils ne sont pas pilotes.

**Raison:** eviter l'illusion de precision et les migrations de logique fragiles.

**Alternatives:** chiffres hard-codes (rejetee).

**Consequences:** stocker policy/version dans les attributions et evidences.

## D-006 — Contexte est orthogonal a la competence

**Statut:** Accepted.

**Decision:** preferer un contexte d'ingenierie configurable sans changer la competence evaluee.

**Raison:** donner du sens sans favoriser un parcours d'etude particulier.

**Alternatives:** pistes par programme fixes (rejetee).

**Consequences:** revue d'equivalence de variantes et preferences reversibles.
