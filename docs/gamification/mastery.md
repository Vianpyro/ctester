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

## Ce qui est LIVRE (phase 2)

Le modele D, dans sa forme la plus pauvre en nombres : **une bande par
COUVERTURE**, sans seuil, sans poids de recence et sans degradation. Pour une
competence, on regarde la DERNIERE tentative de chacune des verifications
ouvertes qui la portent :

| Situation | Bande |
| --- | --- |
| toutes reussies (et il y en a au moins une) | `verifie` |
| au moins une reussie, pas toutes | `en-progression` |
| au moins une tentee, aucune reussie | `a-consolider` |
| aucune tentee | `non-verifie` |

Le compte brut accompagne le mot en toutes lettres (« 1 verification reussie sur
2, 1 tentee »), jamais un score. Les evidences brutes sont conservees : chaque
tentative laisse sa ligne, la bande ne lit que la derniere, et un succes deja
obtenu ne se retire pas. Rien de tout ca ne fait bouger un XP ni une note.

**Pourquoi aucun seuil.** Un seuil serait un nombre a calibrer, et on n'a pas de
donnees. La couverture s'echelonne toute seule : ajouter une verification a une
competence rend « verifie » plus exigeant sans qu'une constante bouge. Le jour ou
une cohorte a ete observee, un `seuil_preuves` et un poids de recence se posent
dans `app/politique.py` et `bande_maitrise()` est la seule fonction a relire.

**Ce qui n'est PAS livre :** variantes parametrees a graine serveur, defi
chronometre (donc pas d'alternative accessible a definir), competences
principales/secondaires ([skills.md](skills.md)), vue de preparation aux
examens, et tout affichage chiffre de la maitrise. Voir
[D-010](decisions.md) et [roadmap.md](roadmap.md).

## Format des verifications

Une verification est un exercice ordinaire du catalogue portant
`verification: true` dans son `exercise.json` -- **le drapeau ne depend pas du
mode**. Les trois premieres, pour les TP ouverts :

| Id | Mode | Forme |
| --- | --- | --- |
| `verif-tp1` | quiz | lire un octet donne dans les deux sens, et l'ecrire |
| `verif-tp2` | quiz | predire ce que quatre programmes affichent, sans compiler |
| `verif-tp2-debogage` | io | corriger un programme qui compile et repond faux |

Elles vivent dans la collection `verifications`, apparaissent au menu avec une
etiquette « verification », et ne figurent dans aucun export `main.c`.

