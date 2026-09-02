# Modele de domaine conceptuel

## Entites autoritaires

| Entite | But et champs essentiels | Cycle |
| --- | --- | --- |
| UserPreference | `user_id` opaque, contextes, consentements | modifiable/supprimable |
| Skill / SkillVersion | taxonomie, prerequis, publication | versionnee |
| ExerciseDefinition / Variant | contenu, tags, policy/version, seed serveur | publie/retire, jamais reecrit |
| Attempt | user, variante, type, statut, timestamps, resultat minimal | immuable apres evaluation |
| MasteryEvidence | tentative de verification, skill, resultat/version | append-only, invalide seulement motive |
| XPTransaction | source/evenement, montant, policy/version | append-only/correction |
| Achievement / UserAchievement | definition et preuve d'obtention | versionnee/append-only |
| Season / RatingHistory | contexte competif et changements | archive |

## Derive, cache, analytique

`MasteryRecord`, niveau, recommendations, solde XP, divisions et leaderboard sont **derives** et recalculables depuis les entites autoritaires. Ils peuvent etre caches avec version de calcul et date de rafraichissement; un cache ne devient jamais preuve. Les analytics sont pseudonymises/agreges, separes du chemin transactionnel et soumis a retention.

## Relations et migration

Un User a plusieurs tentatives/preferences/transactions; une tentative cible une variante et fournit des evidences; une skill a plusieurs contenus/evidences; une saison a des ratings. Utiliser l'actuel `sub` OIDC comme cle interne pseudonymisee seulement lorsque connecte. Ne pas modifier les tables `etat_exercice` pour y surcharger ce domaine: introduire des tables migrees et conserver la compatibilite du parcours facultatif. Les ecritures a valeur utilisent IDs d'evenement uniques et contraintes d'unicite.
