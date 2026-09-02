# Modele de contenu

Chaque definition versionnee d'exercice comporte: id stable, enonce, type (`practice|verification|challenge`), skills principales/secondaires, contexte, difficulte qualitative, prerequis, variante/famille, politique d'aide/IA, et eligibility XP/maitrise/succes/classe. Les tests et solutions restent dans le depot prive; les metadonnees publiques sont une projection sure.

## Contrat de contenu disponible maintenant

Les fichiers `quiz.json`, `io.json` et `unity.json` acceptent deja facultativement ce bloc, publie dans `tps.json` apres liste blanche:

```json
"learning": {
  "skills": ["variables", "arithmetic-operators"],
  "context": "electrical",
  "difficulty": "foundation"
}
```

Skills sont des identifiants minuscules stables; contextes acceptes: `mechanical`, `electrical`, `automated-production`, `aerospace`, `logistics`, `computing`, `general-engineering`; difficultes: `intro`, `foundation`, `intermediate`, `advanced`. Les tags inconnus sont ignores a la publication afin de ne pas bloquer la pratique; `valider_contenu.py` devra les rendre invalides avant que le cours s'en serve pour la maitrise.

Une `ExerciseVariant` est une instance d'une famille: parametres, contraintes et graines serveur; elle garde un lien vers la version de contenu qui l'a creee. Les variations changent valeurs, tailles, cas limites, noms ou contexte sans invalider l'objectif. Les valeurs servant a une verification ou au classe ne sont jamais choisies par le client.

Cycle auteur: brouillon -> revue pedagogique/equivalence -> tests prives -> publie -> retire. Retirer bloque les nouvelles tentatives sans detruire les evidences historiques. Toute modification qui change la difficulte ou les skills cree une nouvelle version. L'integration avec le catalogue actuel doit etendre `tps.json` par des metadonnees publiques seulement.
