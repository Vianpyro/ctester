# Écrire un énoncé en Typst

Un énoncé d'exercice s'écrit dans `statement.md` (Markdown) ou dans
`statement.typ` (Typst). **Pas les deux** : la validation refuse un exercice qui
porte les deux fichiers, plutôt que d'en choisir un en silence et de vous
laisser corriger celui que personne ne lit.

## 1. Lequel choisir

**`statement.md` reste le défaut, et ce n'est pas de la nostalgie.** Il est rendu
dans le navigateur, donc son texte est sélectionnable, copiable, trouvable au
`Ctrl+F` et lisible par un lecteur d'écran. Les 77 énoncés du cours sont en
Markdown et n'ont aucune raison de bouger.

**`statement.typ` quand la mise en page fait partie de l'explication** — et
acceptez ce que ça coûte : Typst rend un SVG où **les lettres sont des tracés**,
pas du texte. Sur une consigne Typst, l'étudiant ne peut ni sélectionner, ni
copier, ni faire chercher un mot par son navigateur ; une synthèse vocale ne lit
rien. C'est une vraie perte, et c'est la raison pour laquelle ce n'est pas le
défaut.

| Vous voulez | Écrivez |
|---|---|
| du texte, des listes, un bloc de code, une formule simple | `statement.md` |
| un tableau | `statement.typ` |
| un tableau calculé à partir de valeurs | `statement.typ` |
| un diagramme (Mermaid) | `statement.typ` |
| une image, un schéma | `statement.typ` |
| une formule que `$...$` du Markdown ne sait pas rendre | `statement.typ` |
| plusieurs pages | `statement.typ` |

En cas de doute : écrivez en Markdown, et migrez le jour où vous butez.

## 2. La structure d'un exercice

```text
exercises/tp2-ex3/
├── exercise.json          inchangé
├── statement.typ          l'énoncé
├── images/                vos figures (facultatif)
│   └── memoire.svg
├── public/files.json      inchangé
└── assessment/            inchangé -- Typst n'y a AUCUN accès
```

`assessment/` n'est pas copié dans le répertoire où l'énoncé est compilé : un
corrigé ne peut pas se retrouver dans une consigne, même par accident.

## 3. Le fichier minimal

```typst
= Titre de l'exercice

Du texte ordinaire.
```

C'est tout. **Vous n'écrivez aucun préambule** : la mise en page, la palette, la
largeur de colonne et la coloration du C sont appliquées par le build.

Ajoutez la ligne d'import **seulement si vous voulez les helpers** (`#note`,
`#mermaid`, `#signature`, `#exemple`, `#attention`) :

```typst
#import "@local/ctester:1.0.0": *

= Titre
```

## 4. Markdown → Typst

La syntaxe de Typst ressemble beaucoup à celle de Markdown. Il n'y a **pas** de
traducteur : ce tableau suffit.

| Markdown | Typst |
|---|---|
| `# Titre` | `= Titre` |
| `## Sous-titre` | `== Sous-titre` |
| `**gras**` | `*gras*` |
| `*italique*` | `_italique_` |
| `` `code` `` | `` `code` `` |
| ` ```c ... ``` ` | ` ```c ... ``` ` |
| `- puce` | `- puce` |
| `1. numéro` | `+ numéro` |
| `[texte](url)` | `#link("url")[texte]` |

Attention aux deux inversions : en Typst `*` est le **gras** et `_` l'italique,
l'inverse du Markdown.

## 5. Du code C

Un bloc clôturé, avec le langage. La coloration est **la même que celle de
l'éditeur** — un `int` a la couleur qu'il a dans la fenêtre d'à côté.

````typst
```c
#include <stdio.h>

int main(void) {
    printf("Bonjour\n");
    return 0;
}
```
````

Pour un prototype que l'étudiant doit recopier à l'octet près :

```typst
#signature(fichier: "calendrier.h", "int diff_dates(int j1, int m1, int a1);")
```

## 6. Des maths

Entre `$ ... $`. Pas de bibliothèque, pas de police à charger : Typst compose
les formules lui-même.

```typst
Le coût est $O(n log n)$.

$ sum_(i=1)^n i = (n(n+1))/2 $

$ x = (-b plus.minus sqrt(b^2 - 4a c))/(2a) $
```

Un `$` collé au texte (`$O(n)$`) donne une formule dans la ligne ; entouré
d'espaces (`$ ... $`), une formule centrée sur sa propre ligne.

## 7. Un tableau

```typst
#table(
  columns: 3,
  [Entrée], [Sortie], [Pourquoi],
  [`0`], [`0`], [cas limite],
  [`5`], [`120`], [$5!$],
)
```

La première ligne est mise en gras et sur fond de panneau automatiquement.

### Un tableau calculé

C'est ce que Markdown ne peut pas faire : les lignes sont **dérivées** de vos
valeurs, donc corriger la liste corrige le tableau.

```typst
#let valeurs = (12, 42, 7, 91, 23)

#table(
  columns: 2,
  [Indice], [Valeur],
  ..valeurs.enumerate().map(((i, v)) => (str(i), str(v))).flatten(),
)
```

## 8. Une image

Posez-la dans `images/` à côté de `statement.typ` :

```typst
#figure(
  image("images/memoire.svg", width: 90%),
  caption: [Ce que contient le tableau à la troisième itération.],
)
```

**Une image ne suit pas le thème.** Le texte, le code et les diagrammes sont
recompilés pour le thème clair et pour le sombre ; une image est reprise telle
quelle. Choisissez donc des couleurs lisibles sur les deux fonds, et ne peignez
pas de fond blanc — celui de la page doit se voir à travers. Préférez du SVG
écrit à la main quand la figure est simple : le dépôt de contenu n'a aucun
fichier binaire aujourd'hui, et c'est agréable.

Un document ne peut lire **que** des fichiers de son propre répertoire
d'exercice. `#image("../autre/x.png")` est refusé par le compilateur.

## 9. Un diagramme Mermaid

```typst
#mermaid(
  alt: "L'étudiant soumet, ctester compile, puis exécute les tests",
  "graph TD
  A[Etudiant] --> B[ctester]
  B --> C[Compilation]
  C --> D[Tests]",
)
```

Le diagramme prend les couleurs du thème, comme le reste. Écrivez `alt` : il ne
rend pas le diagramme accessible (voir §1), mais il vaut mieux que rien.

**Évitez les accents dans les libellés Mermaid** — sa grammaire est capricieuse
avec la ponctuation. Le texte autour, lui, est du français normal.

## 10. Les helpers ctester

Quatre encadrés, et il y en a quatre parce que quatre servent.

```typst
#note[Une précision utile. `const` empêche l'écriture, ce n'est pas décoratif.]

#attention[Ce qui coûte un verdict rouge : `i = 0` compare la case avec elle-même.]

#exemple[
  Entrée : `5 12 42 7 91 23` — sortie : `91`.
]

#signature(fichier: "tampon.h", "int maximum(const int v[], int n);")
```

Chacun accepte `titre:` si « Note », « Attention » ou « Exemple » ne convient
pas.

## 11. Plusieurs pages

Un `#pagebreak()` et rien d'autre. La page affiche les images l'une sous l'autre
dans la colonne de la consigne, qui défile.

N'en abusez pas : une consigne d'exercice tient presque toujours sur une page, et
seize est le maximum accepté.

## 12. Compiler chez soi

Il faut Docker **ou** un binaire `typst` 0.15.1.

```sh
# Rendre et écrire les SVG :
python3 render_statement.py ../unittests/content/exercises/tp2-ex3 --out /tmp/apercu

# Ou en PNG, pour simplement regarder :
python3 render_statement.py ../unittests/content/exercises/tp2-ex3 --out /tmp/apercu --png
xdg-open /tmp/apercu/dark-1.png
```

Avec un binaire plutôt que Docker :

```sh
CTESTER_TYPST_BIN=/chemin/vers/typst python3 render_statement.py ...
```

Pour voir l'énoncé **dans la vraie page** :

```sh
npm run build
python3 publish_content.py ../unittests/content /tmp/published
CTESTER_KEY=dev CTESTER_PUBLISHED=/tmp/published CTESTER_PAGE=frontend/dist \
  python3 app/main.py
```

## 13. Quand ça casse

Une erreur Typst **fait échouer toute la publication** : rien n'est écrit, la
release en service ne bouge pas, et le message nomme l'exercice, le fichier et
la ligne.

```
publish refused, the active release is untouched:
- tp2-ex3/statement.typ n'a pas compilé :
  error: unknown variable: tableu
    ┌─ statement.typ:12:3
```

Conséquence à connaître : **un `.typ` cassé bloque aussi la publication des
autres exercices**, y compris une correction de `statement.md` faite en même
temps. C'est voulu — un contenu invalide ne doit jamais remplacer une release
qui marche — mais ça veut dire qu'on corrige tout de suite.

Sur le serveur, le tick de cinq minutes le dit dans son journal :

```sh
journalctl -u ctester-tests -n 30
```

## 14. Ce que Typst ne fait pas ici

- **Pas de HTML** : le format publié est le SVG, et l'export HTML de Typst est
  expérimental.
- **Pas de Typst dans le navigateur** : l'étudiant reçoit des images, jamais un
  compilateur.
- **Pas de paquet Typst arbitraire** : seuls `@local/ctester` et
  `@preview/merman` sont disponibles, tous deux vendorés dans le dépôt de
  l'application. Le build n'a pas de réseau. Pour en ajouter un, il faut le
  vendorer — parlez-en plutôt que de l'importer.
- **Pas de police autre** que celles embarquées dans typst (Libertinus Serif
  pour le texte, DejaVu Sans Mono pour le code) : c'est ce qui rend le rendu
  identique sur toutes les machines.
