# Questions ouvertes

| Question | Decision requise avant | Recommandation initiale |
| --- | --- | --- |
| Quelle politique IA s'applique a chaque type d'activite? | verification | afficher une politique par contenu et demander accord explicite |
| Quels formats de verification sont valides/accessible? | ~~Phase 2~~ **provisoirement tranche** | [D-010](decisions.md) : quiz de lecture/prediction et debogage io, trois activites pour `tp1` et `tp2`. Accessibilite: aucun temps limite, donc aucune alternative a definir. Validation pedagogique et accommodations **non faites** -- critere de sortie: une session pilote |
| Quel modele, seuils et recence de mastery? | affichage chiffre | **ne bloque plus** : la phase 2 n'affiche aucun chiffre de maitrise, seulement des bandes par couverture sans seuil ([mastery.md](mastery.md)). A rejuger avant d'en afficher un |
| Quels montants/plafonds XP et niveaux? | ~~Phase 1 activee~~ **provisoirement tranche** | `app/politique.py`, version `pilote-1`: 10/15/20/30 XP par difficulte, plafond 100/jour, sept paliers. Valeurs non observees, a rejuger apres une session |
| Quelle retention/export pour tentatives/evenements? | premiere migration | politique institutionnelle et minimisation avant collecte |
| Quels roles enseignants/admin et quels acces? | premiere migration | moindre privilege/audit |
| Quelle proportion de contexte prefere/exploration? | recommandations | preference modifiable, aucun ratio initial impose |
| Les defis chronometres ont-ils une alternative? | tout temps limite | oui, definie avant publication |
| Quand et comment reinitialiser XP/rating? | saisons | pas de reset avant pilote |
| Quel pseudonyme/age minimum/taille de cohorte pour tableaux? | classement | consentement, seuil de taille et resultats personnels sinon |
| Comment traiter erreurs du runner et replays? | toute attribution | tentative serveur idempotente et politique de reprise ecrite |
| Quelle validation institutionnelle pour comparer examen/mastery? | analytics | consentement, agregation, pas de consequence individuelle |

Une question est cloturee seulement par une decision datee dans [decisions.md](decisions.md), une politique de produit et, si necessaire, des tests d'acceptation.
