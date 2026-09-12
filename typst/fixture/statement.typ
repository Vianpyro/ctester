#import "@local/ctester:1.0.0": *

= Analyse d'un tampon

Écris une fonction qui parcourt un tableau d'entiers et rend la plus grande
valeur qu'il contient. Le tableau n'est jamais vide.

#signature(fichier: "tampon.h", "int maximum(const int valeurs[], int n);")

== Ce que la fonction doit faire

La recherche est linéaire : on retient le premier élément, puis on garde le plus
grand des deux à chaque tour. Le coût est donc $O(n)$, et il n'y a pas mieux --
il faut bien lire chaque case au moins une fois.

Pour un tableau de $n$ éléments, le nombre de comparaisons vaut
$sum_(i=1)^(n-1) 1 = n - 1$.

#note[
  `const` devant `valeurs` dit que la fonction ne modifie pas le tableau. Ce
  n'est pas une décoration : le compilateur refusera une écriture dedans, et
  c'est exactement ce qu'on veut vérifier ici.
]

== Un squelette

```c
#include <stdio.h>

int maximum(const int valeurs[], int n) {
    int plus_grand = valeurs[0];
    for (int i = 1; i < n; i++) {
        /* à compléter */
    }
    return plus_grand;
}
```

#attention[
  `for (int i = 0; ...)` compare la première case avec elle-même. Ça marche,
  mais le `n - 1` ci-dessus devient faux.
]

== Les cas de test

#let valeurs = (12, 42, 7, 91, 23)

Le juge exécute la fonction sur ces cinq valeurs, un préfixe à la fois. Le
tableau ci-dessous est *calculé* à partir de la liste, pas recopié à la main :

#table(
  columns: 3,
  [n], [préfixe], [maximum attendu],
  ..range(1, valeurs.len() + 1)
    .map(n => (
      str(n),
      valeurs.slice(0, n).map(str).join(", "),
      str(calc.max(..valeurs.slice(0, n))),
    ))
    .flatten(),
)

#exemple[
  Pour `n = 3`, le tableau vaut #raw(valeurs.slice(0, 3).map(str).join(", "))
  et la fonction rend #raw(str(calc.max(..valeurs.slice(0, 3)))).
]

#pagebreak()

= Comment le juge s'y prend

#mermaid(
  alt: "Le code de l'étudiant est compilé, exécuté sur chaque cas, puis comparé",
  "graph TD
  A[Ta soumission] --> B[Compilation]
  B --> C{Compile ?}
  C -->|non| D[Erreur de compilation]
  C -->|oui| E[Un cas de test]
  E --> F{Bonne valeur ?}
  F -->|non| G[Cas echoue]
  F -->|oui| H[Cas reussi]",
)

== La mémoire pendant le parcours

#figure(
  image("images/memoire.svg", width: 90%),
  caption: [`plus_grand` ne bouge que lorsqu'une case le dépasse.],
)

Le tableau reste en place ; seule la variable locale est réécrite.
