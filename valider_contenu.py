#!/usr/bin/env python3
"""Valide le CONTENU du dépôt de tests : chaque corrigé passe-t-il son test ?

    python3 valider_contenu.py ../unittests/content
    CTESTER_SOLUTIONS=../solutions python3 valider_contenu.py ../unittests/content

Un test faux envoie un étudiant chercher un bug qui n'existe pas -- c'est pire
que pas de test du tout. Ce script est la seule preuve qu'un test est juste : il
compile la solution de référence de chaque exercice et exige qu'elle passe.

IL IMPORTE runner.py PLUTÔT QUE DE REFAIRE SES VÉRIFICATIONS. Réimplémenter
`check_case` ici donnerait deux définitions de « ce cas passe », qui dériveraient
l'une de l'autre en silence -- et la validation dirait alors le contraire du
juge. Ce qui est mesuré ici est exactement ce que l'étudiant obtiendra.

Ne tourne pas sur le serveur : c'est un outil de contrôleur, et il lui faut gcc.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_catalogue  # noqa: E402
import runner  # noqa: E402

CC = os.environ.get("CC", "gcc")
STD = os.environ.get("CTESTER_STD", "gnu2x")
TIMEOUT = 30
# Drapeaux gcc supplementaires, pour mesurer une option avant de la deployer :
#   CTESTER_EXTRA="-fsanitize=undefined -fno-sanitize-recover" ... valider_contenu.py
# Les 72 corriges de reference servent alors de banc d'essai : un diagnostic sur
# du code juste est soit un vrai defaut du corrige, soit un faux positif a ecarter.
EXTRA = os.environ.get("CTESTER_EXTRA", "").split()
# LES SOLUTIONS VIVENT DANS UN AUTRE DÉPÔT, et le gitlink qui les montait sous
# `unittests/solutions` a disparu en phase 8 : le couple contenu/solutions est
# réuni ici, par un chemin donné, et jamais par une arborescence partagée.
SOLUTIONS = os.environ.get("CTESTER_SOLUTIONS", "")


def gcc(args, cwd):
    done = subprocess.run([CC] + args, cwd=cwd, capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    return done.returncode, done.stderr


def sources(chemin):
    return sorted(f for f in os.listdir(chemin) if f.endswith(".c"))


def valider_unity(entree, sol_dir, unity_dir, travail):
    """Compile la solution + le test + Unity, et exige zéro échec."""
    objets = []
    for src in sources(sol_dir):
        obj = os.path.join(travail, src[:-2] + ".o")
        rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir, "-c",
                       os.path.join(sol_dir, src), "-o", obj], travail)
        if rc:
            return "la solution ne compile pas :\n" + err.strip()[:400]
        objets.append(obj)

    # -DUNITY_INCLUDE_DOUBLE : la même macro que build-unity.sh, et pour la même
    # raison. Sans elle, Unity 2.6 compile TEST_ASSERT_DOUBLE_WITHIN en une
    # souche qui ÉCHOUE, et la validation contredirait le juge -- ou, pire,
    # validerait un contenu que le juge refuse.
    binaire = os.path.join(travail, "t")
    rc, err = gcc(EXTRA + ["-DUNITY_INCLUDE_DOUBLE"] + objets
                  + [os.path.join(entree["path"], f)
                     for f in sources(entree["path"])]
                  + [os.path.join(unity_dir, "unity.c"),
                     "-I" + unity_dir, "-I" + entree["path"], "-I" + sol_dir,
                     "-o", binaire, "-lm"], travail)
    if rc:
        return "l'édition de liens échoue :\n" + err.strip()[:400]

    done = subprocess.run([binaire], capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    verdict = runner.verdict(done.returncode, done.stdout)
    if verdict.get("status") != "ok":
        return verdict.get("message", "") + "\n" + done.stdout.strip()[:400]
    if verdict["passed"] != verdict["total"]:
        return "%d/%d tests seulement, échecs : %s" % (
            verdict["passed"], verdict["total"], ", ".join(verdict["failed"]))
    return ""


def valider_io(entree, sol_dir, travail):
    """Compile la solution, la lance sur chaque cas, applique les règles du juge."""
    conf = entree["config"]
    binaire = os.path.join(travail, "t")
    rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir]
                  + [os.path.join(sol_dir, f) for f in sources(sol_dir)]
                  + ["-o", binaire, "-lm"], travail)
    if rc:
        return "la solution ne compile pas :\n" + err.strip()[:400]

    tol = float(conf.get("tolerance", runner.DEFAULT_TOLERANCE))
    for numero, cas in enumerate(conf.get("cases", []), 1):
        try:
            done = subprocess.run([binaire], input=cas.get("stdin", ""),
                                  capture_output=True, text=True,
                                  errors="replace", timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return "cas %d : le programme ne termine pas" % numero
        raison = runner.check_case(cas, done.stdout, tol)
        if raison:
            return "cas %d (%r) : %s\n      sortie : %r" % (
                numero, cas.get("stdin", ""), raison, done.stdout[:200])
    return ""


def solutions_racine(contenu):
    """La racine des corrigés : `CTESTER_SOLUTIONS`, ou le premier voisin trouvé.

    Le gitlink qui montait les solutions SOUS le contenu a disparu ; selon qu'on
    a gardé le clone à côté du dépôt de tests ou à côté de ce dépôt, il est à un
    ou deux niveaux au-dessus. Chercher les deux vaut mieux que d'imposer une
    variable pour un chemin qu'on peut voir.
    """
    if SOLUTIONS:
        return os.path.abspath(SOLUTIONS)
    for haut in (os.pardir, os.path.join(os.pardir, os.pardir)):
        candidat = os.path.abspath(os.path.join(contenu, haut, "solutions"))
        if os.path.isdir(candidat):
            return candidat
    return os.path.abspath(os.path.join(contenu, os.pardir, "solutions"))


def solutions_dir(racine, ident):
    """Le répertoire du corrigé de cet exercice, ou None.

    DEUX DISPOSITIONS ACCEPTÉES, parce que le dépôt de solutions n'a pas été
    migré avec le contenu : `tp2-ex3` d'abord tel quel, puis `tp2/ex3`. L'ID
    reste la clé dans les deux cas -- rien ici ne reconstruit un chemin depuis
    autre chose que lui.
    """
    for candidat in ([os.path.join(racine, ident)]
                     + ([os.path.join(racine, *ident.split("-", 1))]
                        if "-" in ident else [])):
        if os.path.isdir(candidat) and sources(candidat):
            return candidat
    return None


def main():
    racine = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                             else os.path.join("unittests", "content"))
    unity_dir = os.path.join(racine, "shared", "unity")
    # Le dépôt de solutions est à CÔTÉ du contenu, plus dedans.
    sol_racine = solutions_racine(racine)

    # ABSENT ET VIDE NE SONT PAS LA MÊME PANNE. « aucun exercice trouvé » sur un
    # chemin qui n'existe pas envoie chercher un bug dans le dépôt de tests au
    # lieu de le cloner.
    if not os.path.isdir(racine):
        print("ce répertoire n'existe pas : " + racine)
        return 1

    # LE MODÈLE VALIDÉ D'ABORD, comme le publisher : un contenu qui ne passe pas
    # `discover()` n'a pas de corrigé à éprouver, il a des erreurs à corriger.
    # Aucune date n'est appliquée -- un exercice qui ouvre en novembre doit être
    # prouvé en septembre, sinon la date suspendrait la validation exactement
    # sur ce qui n'a jamais tourné.
    try:
        model = content_catalogue.discover(racine)
    except content_catalogue.ContentValidationError as exc:
        print("contenu invalide :")
        for erreur in exc.errors:
            print("  - " + erreur)
        return 1
    entrees = [{"id": e["id"], "mode": e["mode"], "config": e["config"],
                "path": os.path.join(e["path"], "assessment")}
               for e in model["exercises"].values()]
    if not entrees:
        print("aucun exercice trouvé dans " + racine)
        return 1

    ok, sautes, casses = 0, [], []
    for entree in entrees:
        ident, mode = entree["id"], entree["mode"]
        if mode == "quiz":
            # Un quiz n'a pas de solution à compiler : son corrigé EST le
            # fichier de test. On vérifie qu'il se corrige lui-même à 100 %,
            # ce qui attrape une réponse mal formée pour son propre type.
            quiz = entree["config"]
            justes = {q["id"]: q["answer"] for q in quiz["questions"]}
            note = runner.grade_quiz(quiz, justes)
            if note["passed"] != note["total"]:
                casses.append((ident, "le corrigé ne se valide pas lui-même : "
                                      + str(note["wrong"][:3])))
            else:
                ok += 1
            continue

        sol_dir = solutions_dir(sol_racine, ident)
        if sol_dir is None:
            sautes.append(ident)
            continue

        travail = tempfile.mkdtemp(prefix="valider-")
        try:
            if mode == "unity":
                probleme = valider_unity(entree, sol_dir, unity_dir, travail)
            else:
                probleme = valider_io(entree, sol_dir, travail)
        except Exception as exc:  # noqa: BLE001
            probleme = "erreur du validateur : %s" % exc
        finally:
            subprocess.run(["rm", "-rf", travail], check=False)

        if probleme:
            casses.append((ident, probleme))
        else:
            ok += 1

    print("%d exercice(s) validé(s)" % ok)
    if sautes:
        print("\n%d SANS SOLUTION DE RÉFÉRENCE (donc non prouvés) :" % len(sautes))
        print("   " + ", ".join(sautes))
    if casses:
        print("\n%d EN ÉCHEC :" % len(casses))
        for ident, probleme in casses:
            print("\n  %s" % ident)
            for ligne in probleme.splitlines():
                print("      " + ligne)
    return 1 if casses else 0


if __name__ == "__main__":
    sys.exit(main())
