# Modele d'evenements

L'architecture actuelle n'est pas event-driven: le web depose un job, le worker ecrit un resultat, et l'etat de dashboard est aujourd'hui ecrit par le navigateur. Un bus distribue n'est pas justifie en Phase 1. **Decision:** utiliser d'abord une table d'evenements transactionnelle (outbox) dans Postgres, produite cote serveur; des consommateurs synchrones/worker peuvent ensuite deriver projections.

Evenements minimaux: `ExerciseStarted`, `ExerciseSubmitted`, `ExerciseEvaluated`, `PracticeCompleted`, `VerificationStarted`, `VerificationEvaluated`, `MasteryChanged`, `XPGranted`, `AchievementUnlocked`. Les evenements competition/saison arrivent seulement avec leurs phases. Chaque evenement a id UUID, version/schema, user pseudonymise, correlation/attempt id, horodatage serveur, payload minimal et policy/content version.

Regles: ordre par aggregate/attempt, consommateurs idempotents, aucune reemission lors d'un retry HTTP, et journal immuable. Les resultat secrets du runner sont projetes vers un resume explicitement autorise avant l'evenement. L'API doit authentifier l'utilisateur et le worker; le client ne peut pas emettre `XPGranted` ou `VerificationEvaluated`.
