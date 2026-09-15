#!/usr/bin/env python3
"""Checks that every reference solution passes its exercise's tests."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
import content_catalog  # noqa: E402
import judge  # noqa: E402

CC = os.environ.get("CC", "gcc")
STD = os.environ.get("CTESTER_STD", "gnu2x")
TIMEOUT = 30
EXTRA = os.environ.get("CTESTER_EXTRA", "").split()
SOLUTIONS = os.environ.get("CTESTER_SOLUTIONS", "")


def gcc(args, cwd):
    done = subprocess.run([CC] + args, cwd=cwd, capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    return done.returncode, done.stderr


def sources(chemin):
    return sorted(f for f in os.listdir(chemin) if f.endswith(".c"))


def valider_unity(entree, sol_dir, unity_dir, travail):
    objets = []
    for src in sources(sol_dir):
        obj = os.path.join(travail, src[:-2] + ".o")
        rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir, "-c",
                       os.path.join(sol_dir, src), "-o", obj], travail)
        if rc:
            return "the solution does not compile:\n" + err.strip()[:400]
        objets.append(obj)

    binaire = os.path.join(travail, "t")
    # Unity excludes doubles by default, and TEST_ASSERT_DOUBLE_WITHIN then always fails.
    rc, err = gcc(EXTRA + ["-DUNITY_INCLUDE_DOUBLE"] + objets
                  + [os.path.join(entree["path"], f)
                     for f in sources(entree["path"])]
                  + [os.path.join(unity_dir, "unity.c"),
                     "-I" + unity_dir, "-I" + entree["path"], "-I" + sol_dir,
                     "-o", binaire, "-lm"], travail)
    if rc:
        return "linking fails:\n" + err.strip()[:400]

    done = subprocess.run([binaire], capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    verdict = judge.verdict(done.returncode, done.stdout)
    if verdict.get("status") != "ok":
        return verdict.get("message", "") + "\n" + done.stdout.strip()[:400]
    if verdict["passed"] != verdict["total"]:
        return "only %d/%d tests, failures: %s" % (
            verdict["passed"], verdict["total"], ", ".join(verdict["failed"]))
    return ""


def valider_io(entree, sol_dir, travail):
    conf = entree["config"]
    binaire = os.path.join(travail, "t")
    rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir]
                  + [os.path.join(sol_dir, f) for f in sources(sol_dir)]
                  + ["-o", binaire, "-lm"], travail)
    if rc:
        return "the solution does not compile:\n" + err.strip()[:400]

    tol = conf.get("tolerance", judge.DEFAULT_TOLERANCE)
    for numero, cas in enumerate(conf.get("cases", []), 1):
        try:
            done = subprocess.run([binaire], input=cas.get("stdin", ""),
                                  capture_output=True, text=True,
                                  errors="replace", timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return "case %d: the program does not terminate" % numero
        raison = judge.check_case(cas, done.stdout, tol)
        if raison:
            return "case %d (%r): %s\n      output: %r" % (
                numero, cas.get("stdin", ""), raison, done.stdout[:200])
    return ""


def solutions_racine(contenu):
    if SOLUTIONS:
        return os.path.abspath(SOLUTIONS)
    for haut in (os.pardir, os.path.join(os.pardir, os.pardir)):
        candidat = os.path.abspath(os.path.join(contenu, haut, "solutions"))
        if os.path.isdir(candidat):
            return candidat
    return os.path.abspath(os.path.join(contenu, os.pardir, "solutions"))


def solutions_dir(racine, ident):
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
    sol_racine = solutions_racine(racine)

    if not os.path.isdir(racine):
        print("this directory does not exist: " + racine)
        return 1

    try:
        model = content_catalog.discover(racine)
    except content_catalog.ContentValidationError as exc:
        print("invalid content:")
        for erreur in exc.errors:
            print("  - " + erreur)
        return 1
    entrees = [{"id": e["id"], "mode": e["mode"], "config": e["config"],
                "path": os.path.join(e["path"], "assessment")}
               for e in model["exercises"].values()]
    if not entrees:
        print("no exercise found in " + racine)
        return 1

    ok, sautes, casses = 0, [], []
    for entree in entrees:
        ident, mode = entree["id"], entree["mode"]
        if mode == "quiz":
            quiz = entree["config"]
            justes = {q["id"]: q["answer"] for q in quiz["questions"]}
            note = judge.grade_quiz(quiz, justes)
            if note["passed"] != note["total"]:
                casses.append((ident, "the reference solution does not validate itself: "
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
            probleme = "validator error: %s" % exc
        finally:
            subprocess.run(["rm", "-rf", travail], check=False)

        if probleme:
            casses.append((ident, probleme))
        else:
            ok += 1

    print("%d exercise(s) validated" % ok)
    if sautes:
        print("\n%d WITH NO REFERENCE SOLUTION (so unproven):" % len(sautes))
        print("   " + ", ".join(sautes))
    if casses:
        print("\n%d FAILING:" % len(casses))
        for ident, probleme in casses:
            print("\n  %s" % ident)
            for ligne in probleme.splitlines():
                print("      " + ligne)
    return 1 if casses else 0


if __name__ == "__main__":
    sys.exit(main())
