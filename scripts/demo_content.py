#!/usr/bin/env python3
"""Write a small demo content root and publish it.

Lighthouse needs the page to actually load something: served on its own, the bundle asks
its own origin for /catalog.json and gets a 404, so nothing renders and the layout never
moves. A green report would then mean nothing. This gives the API real content to serve,
over the same pipeline production uses -- content_catalog.discover, then publish_content.

Also handy on its own: it gives a working site locally without the real backend.

    python3 scripts/demo_content.py --out /tmp/ctester-demo
    CTESTER_KEY=dev CTESTER_PUBLISHED=/tmp/ctester-demo/published \
    CTESTER_PAGE=frontend/dist CTESTER_SPOOL=/tmp/ctester-demo/spool \
    CTESTER_RESULTS=/tmp/ctester-demo/results python3 app/main.py
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "worker"))

SKILLS = ["boucles", "entrees-sorties", "tableaux", "types", "conditions"]

# The quiz the Lighthouse config deep-links to. Named here so the two stay in step.
QUIZ_ID = "tp1-ex3"

# Long enough to matter. The shifts this whole exercise is meant to catch come from a
# statement growing from one placeholder line into a real brief, so a one-word statement
# would measure nothing.
STATEMENT = """## Ce qu'on te demande

Écris un programme qui lit deux entiers sur l'entrée standard, puis affiche %s.

Les deux nombres arrivent l'un après l'autre, séparés par un retour à la ligne. Tu peux
supposer qu'ils tiennent tous les deux dans un `int` et qu'aucun des deux n'est négatif.

### Comment ton programme est lu

Le juge lit les **nombres** de ta sortie, dans l'ordre où ils apparaissent. Le texte qui
les entoure est libre : `Résultat = 42` et `42` sont lus exactement pareil. Tu peux donc
écrire la phrase qui te semble la plus claire.

### Un point de départ

```c
#include <stdio.h>

int main(void) {
    int a, b;
    scanf("%%d", &a);
    scanf("%%d", &b);
    /* à toi de jouer */
    return 0;
}
```

### Ce qui coince souvent

- Oublier le `&` devant la variable dans `scanf` : le programme compile, puis plante.
- Lire les deux nombres dans le mauvais ordre. Le premier lu est le premier donné.
- Afficher autre chose que des nombres quand le calcul échoue : le juge ne verra rien à lire.

Prends le temps de tester avec de petites valeurs avant de lancer le test complet.
"""

EXERCISES = [
    ("tp1-ex1", "Additionner deux entiers", "io", "leur somme",
     ["entrees-sorties", "types"], "intro"),
    ("tp1-ex2", "Le plus grand des deux", "io", "le plus grand des deux",
     ["conditions", "entrees-sorties"], "intro"),
    (QUIZ_ID, "Ce que tu as retenu", "quiz", "", ["types", "conditions"], "intro"),
    ("tp2-ex1", "Somme d'un tableau", "io", "la somme des valeurs lues",
     ["tableaux", "boucles"], "foundation"),
    ("tp2-ex2", "Compter les pairs", "io", "combien d'entre eux sont pairs",
     ["boucles", "conditions"], "foundation"),
    ("tp2-ex3", "Inverser l'ordre", "io", "les mêmes valeurs en ordre inverse",
     ["tableaux", "boucles"], "intermediate"),
]

COLLECTIONS = [
    ("tp1", "TP 1 : premiers programmes", ["tp1-ex1", "tp1-ex2", QUIZ_ID]),
    ("tp2", "TP 2 : tableaux et boucles", ["tp2-ex1", "tp2-ex2", "tp2-ex3"]),
]

QUIZ_QUESTIONS = [
    {"id": "q1", "group": "Exercice 1 — les types", "type": "int",
     "label": "Combien d'octets occupe un int sur la machine du juge ?",
     "width": 1, "answer": 4},
    {"id": "q2", "group": "Exercice 1 — les types", "type": "choice",
     "label": "Quel format printf affiche un entier signé ?",
     "options": ["%d", "%s", "%c", "%f"], "answer": "%d"},
    {"id": "q3", "group": "Exercice 2 — les conditions", "type": "bool",
     "label": "En C, 0 est considéré comme faux.", "answer": True},
    {"id": "q4", "group": "Exercice 2 — les conditions", "type": "int",
     "label": "Que vaut 7 / 2 en division entière ?", "answer": 3},
    # `row` and `col` lay a group out as a table: every question of the group carries both,
    # the headers keep this order, and no two share a cell. Without them it is a plain list.
    {"id": "q5", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "-58", "col": "signe-valeur", "label": "-58 en signe-valeur",
     "answer": "10111010"},
    {"id": "q6", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "-58", "col": "complément à 1", "label": "-58 en complément à 1",
     "answer": "11000101"},
    {"id": "q7", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "-58", "col": "complément à 2", "label": "-58 en complément à 2",
     "answer": "11000110"},
    {"id": "q8", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "75", "col": "signe-valeur", "label": "75 en signe-valeur",
     "answer": "01001011"},
    {"id": "q9", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "75", "col": "complément à 1", "label": "75 en complément à 1",
     "answer": "01001011"},
    {"id": "q10", "group": "Exercice 3 — entiers signés sur 8 bits", "type": "bin8",
     "row": "75", "col": "complément à 2", "label": "75 en complément à 2",
     "answer": "01001011"},
]


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_content(root):
    write(os.path.join(root, "catalog.json"),
          {"schema_version": 1, "skills": sorted(SKILLS)})

    for ident, title, mode, asked, skills, difficulty in EXERCISES:
        directory = os.path.join(root, "exercises", ident)
        write(os.path.join(directory, "exercise.json"),
              {"schema_version": 1, "id": ident, "title": title, "skills": skills,
               "difficulty": difficulty, "release": {"state": "available"}})
        write_text(os.path.join(directory, "statement.md"), STATEMENT % asked)
        assessment = os.path.join(directory, "assessment")
        if mode == "quiz":
            write(os.path.join(assessment, "quiz.json"), {"questions": QUIZ_QUESTIONS})
            continue
        write(os.path.join(assessment, "io.json"),
              {"cases": [{"stdin": "2\n3\n", "expect": [5]},
                         {"stdin": "10\n7\n", "expect": [17]}]})
        write(os.path.join(directory, "public", "files.json"),
              {"files": [{"name": "main.c", "template":
                          "#include <stdio.h>\n\nint main(void) {\n    // Écris ton code ici\n"
                          "    return 0;\n}\n"}]})

    for ident, title, items in COLLECTIONS:
        write(os.path.join(root, "collections", ident + ".json"),
              {"schema_version": 1, "id": ident, "title": title, "items": items,
               "release": {"state": "available"}})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "demo"),
                        help="directory to hold content/ and published/")
    args = parser.parse_args(argv)

    import publish_content

    root = os.path.join(args.out, "content")
    dest = os.path.join(args.out, "published")
    write_content(root)
    # --no-render: every statement here is Markdown, so there is nothing for Typst to do
    # and no reason to need its binary.
    code = publish_content.main([root, dest, "--no-render"])
    if code:
        return code
    print("demo content published to %s (quiz: %s)" % (dest, QUIZ_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
