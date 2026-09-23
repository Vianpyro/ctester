"""Runs the sandbox's own build-*.sh on the host, so the content tools compile exactly
like the service. `/in/` and `/work` are rewritten to a temporary tree.

No isolation: this only runs content the moderator wrote, never a submission.
"""

import json
import os
import shutil
import subprocess
import tempfile

WORKER = os.path.dirname(os.path.abspath(__file__))

SETTINGS = {
    "CTESTER_SANITIZERS": "-fsanitize=address,undefined",
    "CTESTER_ASAN_OPTIONS": "exitcode=86:detect_leaks=0",
    "CTESTER_COMPILE_TIMEOUT": "10",
    "CTESTER_RUN_TIMEOUT": "5",
}

_STD = None


def c_std():
    """gnu23 needs gcc 13; the host and the sandbox image do not always agree."""
    global _STD
    if _STD is None:
        done = subprocess.run([os.environ.get("CC", "gcc"), "-std=gnu23", "-E", "-"],
                              input="", capture_output=True, text=True, check=False)
        _STD = "gnu23" if done.returncode == 0 else "gnu2x"
    return _STD


def environment(nonce="", **settings):
    values = dict(os.environ, CTESTER_C_STD=c_std(), **SETTINGS)
    values.update({key: str(value) for key, value in settings.items()})
    values["CTESTER_NONCE"] = nonce
    return values


def render(name, root):
    """The build script, with the sandbox's absolute paths pointed at a temporary tree."""
    with open(os.path.join(WORKER, name), encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("/in/", "%s/in/" % root).replace("/work", "%s/work" % root)
    script = os.path.join(str(root), name)
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(script, 0o755)
    return script


def sources(directory):
    """What a submission would carry: the headers too, since the build only sees /in/src."""
    return sorted(name for name in os.listdir(directory) if name.endswith((".c", ".h")))


def read(directory):
    files = {}
    for name in sources(directory):
        with open(os.path.join(directory, name), encoding="utf-8", errors="replace") as fh:
            files[name] = fh.read()
    return files


def run(mode, files, assessment, unity="", nonce="", **settings):
    """Stages `files` as a submission and runs the mode's build script.

    Returns (returncode, stdout, cases, root); the caller owns `root` and removes it.
    """
    root = tempfile.mkdtemp(prefix="ctester-build-")
    os.makedirs(os.path.join(root, "work"))
    os.makedirs(os.path.join(root, "in", "src"))
    for name, text in files.items():
        with open(os.path.join(root, "in", "src", name), "w", encoding="utf-8") as fh:
            fh.write(text)

    cases = None
    if mode == "io":
        os.makedirs(os.path.join(root, "in", "cases"))
        with open(os.path.join(assessment, "io.json"), encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        for number, case in enumerate(cases, 1):
            with open(os.path.join(root, "in", "cases", "%02d.in" % number),
                      "w", encoding="utf-8") as fh:
                fh.write(case.get("stdin", ""))
        script = render("build-io.sh", root)
    else:
        shutil.copytree(assessment, os.path.join(root, "in", "tests"))
        shutil.copytree(unity, os.path.join(root, "in", "unity"))
        script = render("build-unity.sh", root)

    done = subprocess.run(["bash", script], capture_output=True, text=True, cwd=root,
                          env=environment(nonce, **settings), check=False)
    return done.returncode, done.stdout, cases, root
