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


def sources(path):
    return sorted(f for f in os.listdir(path) if f.endswith(".c"))


def validate_unity(entry, sol_dir, unity_dir, workdir):
    objects = []
    for src in sources(sol_dir):
        obj = os.path.join(workdir, src[:-2] + ".o")
        rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir, "-c",
                       os.path.join(sol_dir, src), "-o", obj], workdir)
        if rc:
            return "the solution does not compile:\n" + err.strip()[:400]
        objects.append(obj)

    binary = os.path.join(workdir, "t")
    # Unity excludes doubles by default, and TEST_ASSERT_DOUBLE_WITHIN then always fails.
    rc, err = gcc(EXTRA + ["-DUNITY_INCLUDE_DOUBLE"] + objects
                  + [os.path.join(entry["path"], f)
                     for f in sources(entry["path"])]
                  + [os.path.join(unity_dir, "unity.c"),
                     "-I" + unity_dir, "-I" + entry["path"], "-I" + sol_dir,
                     "-o", binary, "-lm"], workdir)
    if rc:
        return "linking fails:\n" + err.strip()[:400]

    done = subprocess.run([binary], capture_output=True, text=True,
                          errors="replace", timeout=TIMEOUT, check=False)
    verdict = judge.verdict(done.returncode, done.stdout)
    if verdict.get("status") != "ok":
        return verdict.get("message", "") + "\n" + done.stdout.strip()[:400]
    if verdict["passed"] != verdict["total"]:
        return "only %d/%d tests, failures: %s" % (
            verdict["passed"], verdict["total"], ", ".join(verdict["failed"]))
    return ""


def validate_io(entry, sol_dir, workdir):
    conf = entry["config"]
    binary = os.path.join(workdir, "t")
    rc, err = gcc(EXTRA + ["-std=" + STD, "-Wall", "-I" + sol_dir]
                  + [os.path.join(sol_dir, f) for f in sources(sol_dir)]
                  + ["-o", binary, "-lm"], workdir)
    if rc:
        return "the solution does not compile:\n" + err.strip()[:400]

    tol = conf.get("tolerance", judge.DEFAULT_TOLERANCE)
    for number, case in enumerate(conf.get("cases", []), 1):
        try:
            done = subprocess.run([binary], input=case.get("stdin", ""),
                                  capture_output=True, text=True,
                                  errors="replace", timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return "case %d: the program does not terminate" % number
        reason = judge.check_case(case, done.stdout, tol)
        if reason:
            return "case %d (%r): %s\n      output: %r" % (
                number, case.get("stdin", ""), reason, done.stdout[:200])
    return ""


def solutions_root(content):
    if SOLUTIONS:
        return os.path.abspath(SOLUTIONS)
    for top in (os.pardir, os.path.join(os.pardir, os.pardir)):
        candidate = os.path.abspath(os.path.join(content, top, "solutions"))
        if os.path.isdir(candidate):
            return candidate
    return os.path.abspath(os.path.join(content, os.pardir, "solutions"))


def solutions_dir(root, ident):
    for candidate in ([os.path.join(root, ident)]
                     + ([os.path.join(root, *ident.split("-", 1))]
                        if "-" in ident else [])):
        if os.path.isdir(candidate) and sources(candidate):
            return candidate
    return None


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                             else os.path.join("unittests", "content"))
    unity_dir = os.path.join(root, "shared", "unity")
    sol_root = solutions_root(root)

    if not os.path.isdir(root):
        print("this directory does not exist: " + root)
        return 1

    try:
        model = content_catalog.discover(root)
    except content_catalog.ContentValidationError as exc:
        print("invalid content:")
        for error in exc.errors:
            print("  - " + error)
        return 1
    entries = [{"id": e["id"], "mode": e["mode"], "config": e["config"],
                "path": os.path.join(e["path"], "assessment")}
               for e in model["exercises"].values()]
    if not entries:
        print("no exercise found in " + root)
        return 1

    ok, skipped, broken = 0, [], []
    for entry in entries:
        ident, mode = entry["id"], entry["mode"]
        if mode == "quiz":
            quiz = entry["config"]
            # Derived by the grader itself: the key of a text, number or cloze question is
            # not a submission, so only the judge knows how a student would send it.
            try:
                note = judge.grade_quiz(quiz, judge.quiz_key(quiz))
            except (ValueError, KeyError, TypeError) as exc:
                broken.append((ident, "the quiz cannot be graded: %s" % exc))
                continue
            if note["passed"] != note["total"]:
                broken.append((ident, "the reference solution does not validate itself: "
                                      + str(note["wrong"][:3])))
            else:
                ok += 1
            continue

        sol_dir = solutions_dir(sol_root, ident)
        if sol_dir is None:
            skipped.append(ident)
            continue

        workdir = tempfile.mkdtemp(prefix="validate-")
        try:
            if mode == "unity":
                problem = validate_unity(entry, sol_dir, unity_dir, workdir)
            else:
                problem = validate_io(entry, sol_dir, workdir)
        except Exception as exc:  # noqa: BLE001
            problem = "validator error: %s" % exc
        finally:
            subprocess.run(["rm", "-rf", workdir], check=False)

        if problem:
            broken.append((ident, problem))
        else:
            ok += 1

    print("%d exercise(s) validated" % ok)
    if skipped:
        print("\n%d WITH NO REFERENCE SOLUTION (so unproven):" % len(skipped))
        print("   " + ", ".join(skipped))
    if broken:
        print("\n%d FAILING:" % len(broken))
        for ident, problem in broken:
            print("\n  %s" % ident)
            for line in problem.splitlines():
                print("      " + line)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
