# Taxonomie de competences

## Modele

Une `Skill` est une capacite observable, stable et independante du contexte. Elle possede un identifiant stable, titre, description pedagogique, prerequis, ordre suggere, objectifs et statut de publication. Une activite declare ses competences principales et secondaires; les secondaires ne doivent pas etre creditees par accident.

## Arbre initial PROVISOIRE

- Fondamentaux: systemes de nombres, binaire/hexadecimal, memoire, compilation.
- C: `main`, bibliotheques, I/O, variables, types, operateurs.
- Logique: AND/OR/XOR/NOT, bitwise.
- Controle: conditions, `switch`, `while`, `do while`, `for`.
- Fonctions: declaration, parametres, retours, bibliotheques.
- Organisation: top-down, bottom-up, modules/projets.
- Pointeurs: adresses, dereferencement, passage par reference.
- Structures: tableaux 1D/2D, chaines.
- Algorithmes: conception, complexite.

Le responsable de contenu versionne la taxonomie: supprimer ou scinder une competence ne reecrit jamais silencieusement l'historique; une table de correspondance permet les aggregats. Une UI affiche d'abord les competences du module courant, prerequis et prochaine action, pas l'arbre complet intimidant.
