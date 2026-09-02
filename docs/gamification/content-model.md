# Modele de contenu

Chaque definition versionnee d'exercice comporte: id stable, enonce, type (`practice|verification|challenge`), skills principales/secondaires, contexte, difficulte qualitative, prerequis, variante/famille, politique d'aide/IA, et eligibility XP/maitrise/succes/classe. Les tests et solutions restent dans le depot prive; les metadonnees publiques sont une projection sure.

Une `ExerciseVariant` est une instance d'une famille: parametres, contraintes et graines serveur; elle garde un lien vers la version de contenu qui l'a creee. Les variations changent valeurs, tailles, cas limites, noms ou contexte sans invalider l'objectif. Les valeurs servant a une verification ou au classe ne sont jamais choisies par le client.

Cycle auteur: brouillon -> revue pedagogique/equivalence -> tests prives -> publie -> retire. Retirer bloque les nouvelles tentatives sans detruire les evidences historiques. Toute modification qui change la difficulte ou les skills cree une nouvelle version. L'integration avec le catalogue actuel doit etendre `tps.json` par des metadonnees publiques seulement.
