# Anti-farming

## Menaces et reponses

| Abus | Reponse de conception |
| --- | --- |
| Rejouer un exercice simple | recompense unique/famille, plafonds et variantes |
| IA ou scripts de soumissions | pratique separee de verification; quotas existants et idempotence |
| Memoriser/leaker un defi | pool de variantes, rotation et retrait rapide |
| Feedback exploitable | conserver les frontieres de secret actuelles |
| Multi-comptes/partage | ne pas rendre XP decisive; consentement/OIDC quand necessaire; revue seulement si une fonction a enjeu le justifie |
| Exploit de temps | serveur autoritaire, horodatages, etats transactionnels |

Tout controle doit avoir un cout pedagogique faible. Ne jamais empecher de pratiquer parce qu'un plafond de recompense est atteint. Les indicateurs d'alerte (rafales, variantes identiques, incoherences) servent a ajuster les mecanismes, non a declarer une triche automatiquement.
