#!/usr/bin/env python3
"""Checks that every reference solution passes its exercise's tests."""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
import content_catalog  # noqa: E402
import judge  # noqa: E402
import local_build  # noqa: E402

SOLUTIONS = os.environ.get("CTESTER_SOLUTIONS", "")
NONCE = "verify0123456789abcdef0123456789a"


def failure(result):
    """The judge's own message, plus gcc's text when it is the compilation that failed."""
    return (result.get("message", "") + "\n" + (result.get("gcc") or "")).strip()[:400]


def validate_unity(entry, sol_dir, unity_dir):
    rc, out, _, root = local_build.run("unity", local_build.read(sol_dir),
                                       entry["path"], unity_dir)
    shutil.rmtree(root, ignore_errors=True)
    result = judge.verdict(rc, out, "unity")
    if result.get("status") != "ok":
        return failure(result)
    if result["passed"] != result["total"]:
        return "only %d/%d tests, failures: %s" % (
            result["passed"], result["total"], ", ".join(result["failed"]))
    return ""


def validate_io(entry, sol_dir):
    rc, out, cases, root = local_build.run("io", local_build.read(sol_dir),
                                            entry["path"], nonce=NONCE)
    shutil.rmtree(root, ignore_errors=True)
    tol = entry["config"].get("tolerance", judge.DEFAULT_TOLERANCE)
    result = judge.verdict(rc, out, "io", NONCE, cases, tol)
    if result.get("status") != "ok":
        return failure(result)
    bad = result.get("cases") or []
    if bad:
        first = bad[0]
        return "case %s (%r): %s\n      output: %r" % (
            first.get("case"), first.get("stdin", ""), first.get("reason", ""),
            first.get("stdout", "")[:200])
    return ""


def solutions_dir(ident, exercise_dir):
    """An exercise carries its own reference solution, so one clone of the content
    repository is enough to check it. CTESTER_SOLUTIONS is for a base that files them
    elsewhere: <that root>/<exercise id>."""
    candidates = [os.path.join(exercise_dir, "solution")]
    if SOLUTIONS:
        candidates.append(os.path.join(os.path.abspath(SOLUTIONS), ident))
    for candidate in candidates:
        if os.path.isdir(candidate) and local_build.sources(candidate):
            return candidate
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: verify_content.py <content root>")
        return 2
    root = os.path.abspath(sys.argv[1])
    unity_dir = os.path.join(root, "shared", "unity")

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
                "dir": e["path"], "path": os.path.join(e["path"], "assessment")}
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

        sol_dir = solutions_dir(ident, entry["dir"])
        if sol_dir is None:
            skipped.append(ident)
            continue

        try:
            if mode == "unity":
                problem = validate_unity(entry, sol_dir, unity_dir)
            else:
                problem = validate_io(entry, sol_dir)
        except Exception as exc:  # noqa: BLE001
            problem = "validator error: %s" % exc

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
