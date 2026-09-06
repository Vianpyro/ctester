#!/usr/bin/env python3
"""Verify the test repo's CONTENT: does every reference solution pass its test?

    python3 verify_content.py ../unittests/content
    CTESTER_SOLUTIONS=../solutions python3 verify_content.py ../unittests/content

A wrong test sends a student hunting for a bug that does not exist -- worse
than no test at all. This script is the only proof that a test is correct: it
compiles each exercise's reference solution and requires it to pass.

IT IMPORTS runner.py RATHER THAN REDOING ITS CHECKS. Reimplementing
`check_case` here would give two definitions of "this case passes", which
would silently drift apart -- and validation would then say the opposite of
the judge. What is measured here is exactly what the student will get.

Does not run on the server: this is a controller tool, and it needs gcc.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_catalog  # noqa: E402
import runner  # noqa: E402

CC = os.environ.get("CC", "gcc")
STD = os.environ.get("CTESTER_STD", "gnu2x")
TIMEOUT = 30
# Extra gcc flags, to measure an option before deploying it:
#   CTESTER_EXTRA="-fsanitize=undefined -fno-sanitize-recover" ... verify_content.py
# The 72 reference solutions then serve as a test bench: a diagnostic on
# correct code is either a real defect in the solution or a false positive to
# dismiss.
EXTRA = os.environ.get("CTESTER_EXTRA", "").split()
# SOLUTIONS LIVE IN A SEPARATE REPO, and the gitlink that mounted them under
# `unittests/solutions` disappeared in phase 8: the content/solutions pair is
# reunited here, through a given path, and never through a shared tree.
SOLUTIONS = os.environ.get("CTESTER_SOLUTIONS", "")


def gcc(args, cwd):
    done = subprocess.run([CC] + args, cwd=cwd, capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    return done.returncode, done.stderr


def sources(chemin):
    return sorted(f for f in os.listdir(chemin) if f.endswith(".c"))


def valider_unity(entree, sol_dir, unity_dir, travail):
    """Compiles the solution + the test + Unity, and requires zero failures."""
    objets = []
    for src in sources(sol_dir):
        obj = os.path.join(travail, src[:-2] + ".o")
        rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir, "-c",
                       os.path.join(sol_dir, src), "-o", obj], travail)
        if rc:
            return "the solution does not compile:\n" + err.strip()[:400]
        objets.append(obj)

    # -DUNITY_INCLUDE_DOUBLE: the same macro as build-unity.sh, for the same
    # reason. Without it, Unity 2.6 compiles TEST_ASSERT_DOUBLE_WITHIN into a
    # stub that FAILS, and verification would then contradict the judge -- or,
    # worse, validate content the judge refuses.
    binaire = os.path.join(travail, "t")
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
    verdict = runner.verdict(done.returncode, done.stdout)
    if verdict.get("status") != "ok":
        return verdict.get("message", "") + "\n" + done.stdout.strip()[:400]
    if verdict["passed"] != verdict["total"]:
        return "only %d/%d tests, failures: %s" % (
            verdict["passed"], verdict["total"], ", ".join(verdict["failed"]))
    return ""


def valider_io(entree, sol_dir, travail):
    """Compiles the solution, runs it on every case, applies the judge's rules."""
    conf = entree["config"]
    binaire = os.path.join(travail, "t")
    rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir]
                  + [os.path.join(sol_dir, f) for f in sources(sol_dir)]
                  + ["-o", binaire, "-lm"], travail)
    if rc:
        return "the solution does not compile:\n" + err.strip()[:400]

    tol = float(conf.get("tolerance", runner.DEFAULT_TOLERANCE))
    for numero, cas in enumerate(conf.get("cases", []), 1):
        try:
            done = subprocess.run([binaire], input=cas.get("stdin", ""),
                                  capture_output=True, text=True,
                                  errors="replace", timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return "case %d: the program does not terminate" % numero
        raison = runner.check_case(cas, done.stdout, tol)
        if raison:
            return "case %d (%r): %s\n      output: %r" % (
                numero, cas.get("stdin", ""), raison, done.stdout[:200])
    return ""


def solutions_racine(contenu):
    """The solutions root: `CTESTER_SOLUTIONS`, or the first neighbor found.

    The gitlink that mounted solutions UNDER the content is gone; depending on
    whether the clone was kept next to the test repo or next to this repo, it
    is one or two levels up. Trying both beats requiring a variable for a path
    one can already see.
    """
    if SOLUTIONS:
        return os.path.abspath(SOLUTIONS)
    for haut in (os.pardir, os.path.join(os.pardir, os.pardir)):
        candidat = os.path.abspath(os.path.join(contenu, haut, "solutions"))
        if os.path.isdir(candidat):
            return candidat
    return os.path.abspath(os.path.join(contenu, os.pardir, "solutions"))


def solutions_dir(racine, ident):
    """This exercise's reference solution directory, or None.

    TWO ACCEPTED LAYOUTS, because the solutions repo was not migrated along
    with the content: `tp2-ex3` as-is first, then `tp2/ex3`. The id stays the
    key either way -- nothing here rebuilds a path from anything but it.
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
    # The solutions repo sits NEXT TO the content, not inside it.
    sol_racine = solutions_racine(racine)

    # ABSENT AND EMPTY ARE NOT THE SAME FAILURE. "no exercise found" on a path
    # that does not exist sends someone hunting for a bug in the test repo
    # instead of cloning it.
    if not os.path.isdir(racine):
        print("this directory does not exist: " + racine)
        return 1

    # THE VALIDATED MODEL FIRST, like the publisher: content that does not
    # pass `discover()` has no reference solution to check, it has errors to
    # fix. No date is applied -- an exercise opening in November must be
    # provable in September, or the date would suspend validation on exactly
    # what has never run.
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
            # A quiz has no solution to compile: its reference IS the test
            # file. We check that it grades itself at 100%, which catches a
            # malformed answer for its own type.
            quiz = entree["config"]
            justes = {q["id"]: q["answer"] for q in quiz["questions"]}
            note = runner.grade_quiz(quiz, justes)
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
