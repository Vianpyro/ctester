# XP

XP est une mesure de progression et d'engagement, jamais d'aptitude ou de note. Chaque attribution est une `XPTransaction` immuable: utilisateur, source, montant, raison affichable, evenement source, politique/version et date. Le solde est derive de ces transactions; aucune UI ne modifie un solde directement.

Sources envisagees: premiere resolution d'une nouvelle famille, verification, exploration utile, contribution cooperative verifiee et accomplissement. **PROVISOIRE:** montants, plafonds et multiplicateurs ne sont pas fixes. La politique doit etre declarative, versionnee et testable avant activation.

Anti-farming: une source idempotente par evenement, plafond par famille/periode, rendement decroissant des repetitions et aucune valeur pour les echecs envoyes en masse. Le plafonnement doit afficher «deja recompense pour cette activite» sans cacher le feedback pedagogique. Les corrections de fraude/erreur sont des transactions de correction motivees, reservees a un role admin et auditees.
