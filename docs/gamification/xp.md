# XP

XP est une mesure de progression et d'engagement, jamais d'aptitude ou de note. Chaque attribution est une `XPTransaction` immuable: utilisateur, source, montant, raison affichable, evenement source, politique/version et date. Le solde est derive de ces transactions; aucune UI ne modifie un solde directement.

Sources envisagees: premiere resolution d'une nouvelle famille, verification, exploration utile, contribution cooperative verifiee et accomplissement. **PROVISOIRE:** montants, plafonds et multiplicateurs ne sont pas fixes. La politique doit etre declarative, versionnee et testable avant activation.

## Ce qui est implemente (phase 1)

Une seule source: la **premiere** reussite complete d'un exercice publie, constatee par l'API en lisant le verdict du worker. `app/politique.py` porte les montants (par difficulte annoncee), le plafond quotidien et sa `version`; `transaction_xp` garde montant, motif, exercice, version et date. Le solde n'est jamais stocke: il est recalcule a la lecture.

L'idempotence tient par la cle: l'identifiant d'evenement vaut `reussite:<exercice>` et sa cle primaire refuse le doublon. Un sondage rejoue, un worker relance et une reussite refaite retombent tous dessus. Une reussite au-dela du plafond du jour s'enregistre a **zero** plutot que de disparaitre: le fait a eu lieu et se relit, et la pratique n'est jamais bloquee pour autant. Voir [decisions.md](decisions.md) D-007.

Anti-farming: une source idempotente par evenement, plafond par famille/periode, rendement decroissant des repetitions et aucune valeur pour les echecs envoyes en masse. Le plafonnement doit afficher «deja recompense pour cette activite» sans cacher le feedback pedagogique. Les corrections de fraude/erreur sont des transactions de correction motivees, reservees a un role admin et auditees.
