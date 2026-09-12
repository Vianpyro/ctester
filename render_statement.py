#!/usr/bin/env python3
"""Rendre UN énoncé Typst et regarder le résultat, sans rien publier.

C'est la boucle de travail d'un enseignant qui écrit un `statement.typ` :

    python3 render_statement.py ../unittests/content/exercises/tp2-ex3
    python3 render_statement.py typst/fixture --out /tmp/apercu

Les SVG sortent dans `--out` (par défaut un répertoire temporaire dont le chemin
est imprimé), un fichier par thème et par page. Aucun contenu n'est publié,
aucun pointeur n'est touché : c'est `publish_content.py` qui fait ça.

`--png` rend en PNG à la place, parce qu'un navigateur ouvre un SVG dans un
onglet mais qu'une visionneuse d'images ne le fait pas toujours -- et que la
question qu'on se pose à ce moment-là est « est-ce que ça a l'air correct ».
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import typst_build


def main(argv=None):
    parser = argparse.ArgumentParser(description="render one Typst statement")
    parser.add_argument("exercise", help="the exercise directory (the one with statement.typ)")
    parser.add_argument("--out", default="", help="where to write the pages")
    parser.add_argument("--png", action="store_true",
                        help="render PNG instead of SVG, to eyeball it")
    parser.add_argument("--theme", choices=typst_build.THEMES + ("both",),
                        default="both", help="which theme to render")
    args = parser.parse_args(argv)

    try:
        genre, _ = typst_build.statement_of(args.exercise)
    except typst_build.TypstError as exc:
        print("%s: %s" % (args.exercise, exc), file=sys.stderr)
        return 1
    if genre != "typ":
        print("%s porte un statement.md : il n'y a rien à compiler, la page le "
              "rend elle-même." % args.exercise, file=sys.stderr)
        return 1

    sortie = args.out or tempfile.mkdtemp(prefix="ctester-apercu-")
    os.makedirs(sortie, exist_ok=True)
    themes = typst_build.THEMES if args.theme == "both" else (args.theme,)

    if args.png:
        return _png(args.exercise, sortie, themes)

    # LE CHEMIN NORMAL PASSE PAR LE MÊME `render()` QUE LA PUBLICATION, cache
    # compris : ce qu'on regarde ici est exactement ce qui serait publié, pas
    # une seconde façon de compiler qui pourrait dériver.
    try:
        rendu, du_cache = typst_build.render(args.exercise,
                                             os.path.basename(os.path.abspath(args.exercise)))
    except typst_build.TypstError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    ecrits = []
    for theme in themes:
        for numero, octets in enumerate(rendu[theme], 1):
            chemin = os.path.join(sortie, "%s-%d.svg" % (theme, numero))
            with open(chemin, "wb") as fh:
                fh.write(octets)
            ecrits.append(chemin)
    print("%d page(s) par thème%s" % (len(rendu[themes[0]]),
                                      " (depuis le cache)" if du_cache else ""))
    for chemin in ecrits:
        print("  " + chemin)
    return 0


def _png(exercise, sortie, themes):
    """Le même document, en PNG. Un chemin à part, et il le dit.

    `render()` ne rend que du SVG parce que c'est ce qui est publié ; demander
    un PNG ici veut dire relancer typst à la main, avec les mêmes options. Elles
    sont donc recopiées d'un seul endroit -- `_argv` — puis le format est
    remplacé, plutôt que d'écrire une seconde ligne de commande.
    """
    travail = tempfile.mkdtemp(prefix="ctester-typst-")
    try:
        typst_build._preparer(exercise, travail)
        for theme in themes:
            argv, env, cwd = typst_build._argv(travail, theme)
            argv = [a.replace("svg", "png") if a in ("svg", theme + "-{p}.svg") else a
                    for a in argv]
            argv += ["--ppi", "200"]
            fin = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=typst_build.TIMEOUT, env=env, cwd=cwd)
            if fin.returncode != 0:
                print((fin.stderr or fin.stdout).strip(), file=sys.stderr)
                return 1
        for nom in sorted(os.listdir(travail)):
            if nom.endswith(".png"):
                shutil.copy2(os.path.join(travail, nom), os.path.join(sortie, nom))
                print("  " + os.path.join(sortie, nom))
        return 0
    finally:
        shutil.rmtree(travail, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
