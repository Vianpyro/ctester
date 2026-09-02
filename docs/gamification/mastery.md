# Maitrise et verification

## Contrat

La maitrise indique une capacite demontree, pas une prediction de note. La pratique est une evidence faible; une verification independante est une evidence forte. L'ecran doit dire «maitrise verifiee» et proposer le prochain exercice, jamais promettre une note d'examen.

## Verification

Une verification est une activite explicitement marquee, nouvelle par rapport a la pratique et rattachee a des skills. Formats possibles: variante parametree, lecture de code, prediction, debogage, modification, raisonnement de bord ou mini-tache. Elle peut etre limitee dans le temps, mais une alternative accessible doit etre definie. Etats: `eligible -> demarree -> soumise -> evaluee -> reussie|a reprendre`; les reessais restent historiques.

## Modeles et recommandation

- A: moyenne ponderee des verifications. Simple, mais la confiance est invisible.
- B: rating par skill. Reactif, mais difficile a expliquer.
- C: confiance/bayesienne. Exprime bien l'incertitude, mais est plus complexe.
- D: hybride: statut lisible fonde sur les verifications recentes + nombre/breadth de preuves.

**Recommandation PROVISOIRE: D.** Conserver les evidences brutes, exposer une bande («a consolider / en progression / verifie») et calculer une valeur interne explicable. Seuils, poids de recence, difficulte et degradation sont a valider par donnees; ne pas les choisir maintenant. Une faible confiance recommande de pratiquer; elle ne baisse ni XP ni une note. Voir [analytics.md](analytics.md).
