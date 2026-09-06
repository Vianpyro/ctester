# Modele de contenu

Chaque definition versionnee d'exercice comporte: id stable, enonce, type (`practice|verification|challenge`), skills principales/secondaires, contexte, difficulte qualitative, prerequis, variante/famille, politique d'aide/IA, et eligibility XP/maitrise/succes/classe. Les tests et solutions restent dans le depot prive; les metadonnees publiques sont une projection sure.

## Contrat de contenu (architecture v2)

Chaque `exercise.json` porte, a plat, `skills` (liste, sans doublon, chacune
validee contre les `skills` declarees dans `catalog.json`), `difficulty`
(`intro|foundation|intermediate|advanced`, facultative), `contexts` (liste de
textes libres) et `verification` (booleen, `false` par defaut -- voir
[mastery.md](mastery.md)):

```json
{
  "skills": ["variables", "arithmetic-operators"],
  "contexts": ["electrical"],
  "difficulty": "foundation",
  "verification": false
}
```

`content_catalog.discover()` **refuse de publier** un contenu dont une
skill n'est pas dans `catalog.json`, une `difficulty` hors de la liste
fermee, ou un `contexts`/`prerequisites` mal forme -- c'est bloquant, pas un
tag ignore silencieusement. `publish_content.py` projette ces champs tels
quels dans le catalogue public ; il n'y a plus de bloc `learning` imbrique.

Une `ExerciseVariant` est une instance d'une famille: parametres, contraintes et graines serveur; elle garde un lien vers la version de contenu qui l'a creee. Les variations changent valeurs, tailles, cas limites, noms ou contexte sans invalider l'objectif. Les valeurs servant a une verification ou au classe ne sont jamais choisies par le client -- `publish_content.py` interdit `seed` et `cases` en projection publique.

Cycle auteur: brouillon -> revue pedagogique/equivalence -> tests prives (`verify_content.py`) -> publie -> retire. Retirer bloque les nouvelles tentatives sans detruire les evidences historiques. Toute modification qui change la difficulte ou les skills cree une nouvelle revision (le hachage de ce qui est publie), sans redeploiement -- voir CLAUDE.md, "Le contenu (architecture v2)".
