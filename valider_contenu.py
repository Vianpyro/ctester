#!/usr/bin/env python3
"""Valide le CONTENU du dépôt de tests : chaque corrigé passe-t-il son test ?

    python3 valider_contenu.py ../unittests

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
import runner  # noqa: E402

CC = os.environ.get("CC", "gcc")
STD = os.environ.get("CTESTER_STD", "gnu2x")
TIMEOUT = 30
# Drapeaux gcc supplementaires, pour mesurer une option avant de la deployer :
#   CTESTER_EXTRA="-fsanitize=undefined -fno-sanitize-recover" ... valider_contenu.py
# Les 72 corriges de reference servent alors de banc d'essai : un diagnostic sur
# du code juste est soit un vrai defaut du corrige, soit un faux positif a ecarter.
EXTRA = os.environ.get("CTESTER_EXTRA", "").split()


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
    conf = runner.load_config(entree["path"], "io.json")
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


def main():
    racine = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "unittests")
    runner.TESTS = racine
    unity_dir = os.path.join(racine, "unity")

    # ABSENT ET VIDE NE SONT PAS LA MÊME PANNE. sous_dossiers() avale l'OSError
    # -- c'est le bon choix pour le worker, dont la boucle ne doit pas mourir sur
    # un clone en cours -- mais ici c'est un humain qui lit, et « aucun exercice
    # trouvé » sur un chemin qui n'existe pas l'envoie chercher un bug dans son
    # dépôt de tests au lieu de le cloner.
    if not os.path.isdir(racine):
        print("ce répertoire n'existe pas : " + racine)
        return 1

    # tout=True : on valide AUSSI ce qui n'est pas encore ouvert aux étudiants.
    entrees = runner.catalogue(tout=True)
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
            quiz = runner.load_config(entree["path"], "quiz.json")
            justes = {q["id"]: q["answer"] for q in quiz["questions"]}
            note = runner.grade_quiz(quiz, justes)
            if note["passed"] != note["total"]:
                casses.append((ident, "le corrigé ne se valide pas lui-même : "
                                      + str(note["wrong"][:3])))
            else:
                ok += 1
            continue

        sol_dir = os.path.join(racine, "solutions",
                               *ident.split("-", 1)) if "-" in ident else \
            os.path.join(racine, "solutions", ident)
        if not os.path.isdir(sol_dir) or not sources(sol_dir):
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
