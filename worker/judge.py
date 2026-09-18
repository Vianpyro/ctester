"""The Rust judge's grading rules, for the content tools: they grade exactly like the service."""

import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TOLERANCE = 0.005


def binary():
    name = "ctester-judge.exe" if os.name == "nt" else "ctester-judge"
    return (os.environ.get("CTESTER_JUDGE_BIN")
            or os.path.join(ROOT, "judge", "target", "release", name))


def _call(request):
    path = binary()
    if not os.path.isfile(path):
        raise SystemExit("ctester-judge not found at %s: run `cargo build --release` in "
                         "judge/, or set CTESTER_JUDGE_BIN" % path)
    done = subprocess.run([path, "grade"], input=json.dumps(request), capture_output=True,
                          text=True, encoding="utf-8", check=False)
    if done.returncode != 0:
        raise ValueError(done.stderr.strip())
    return json.loads(done.stdout)


def verdict(rc, output, mode="unity", nonce="", cases=(), tolerance=DEFAULT_TOLERANCE):
    """With a nonce, the warnings block is split out and attached, as the service does."""
    return _call({"op": "verdict", "mode": mode, "rc": rc, "output": output, "nonce": nonce,
                   "cases": list(cases), "tolerance": tolerance})


def check_case(case, output, tolerance=DEFAULT_TOLERANCE):
    return _call({"op": "check_case", "case": case, "output": output,
                   "tolerance": tolerance})["reason"]


def grade_quiz(quiz, answers):
    return _call({"op": "grade_quiz", "quiz": quiz, "answers": answers})
