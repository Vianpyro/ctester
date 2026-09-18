#!/usr/bin/env python3
import json
import os
import re
import select
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
CONTENT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                       else ROOT.parent / "unittests" / "content").resolve()
SOLUTIONS = pathlib.Path(os.environ.get("CTESTER_SOLUTIONS") or next(
    (c for c in (CONTENT.parent / "solutions",
                 CONTENT.parent.parent / "solutions") if c.is_dir()),
    CONTENT.parent / "solutions")).resolve()
UNITY = CONTENT / "shared" / "unity"


def assessment(exercise):
    return CONTENT / "exercises" / exercise / "assessment"


def corrected(exercise):
    for candidate in (SOLUTIONS / exercise,
                     SOLUTIONS.joinpath(*exercise.split("-", 1))):
        if candidate.is_dir():
            return candidate
    raise SystemExit("no reference solution found for " + exercise
                     + " under " + str(SOLUTIONS))

sys.path.insert(0, str(WORKER))
import judge  # noqa: E402

NONCE = "e2e0123456789abcdef0123456789abc"

STD = "gnu23"
if subprocess.run(["gcc", "-std=gnu23", "-E", "-"], input="", capture_output=True,
                  text=True).returncode != 0:
    STD = "gnu2x"


SETTINGS = {
    "CTESTER_C_STD": STD,
    "CTESTER_SANITIZERS": "-fsanitize=address,undefined",
    "CTESTER_ASAN_OPTIONS": "exitcode=86:detect_leaks=0",
    "CTESTER_COMPILE_TIMEOUT": "10",
    "CTESTER_RUN_TIMEOUT": "5",
}


def render(name, root):
    text = (WORKER / name).read_text(encoding="utf-8")
    text = text.replace("/in/", f"{root}/in/").replace("/work", f"{root}/work")
    script = root / name
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def run(mode, files, exercise, **settings):
    root = pathlib.Path(tempfile.mkdtemp(prefix="e2e-"))
    (root / "work").mkdir()
    (root / "in/src").mkdir(parents=True)
    for name, content in files.items():
        (root / "in/src" / name).write_text(content, encoding="utf-8")

    if mode == "io":
        (root / "in/cases").mkdir()
        conf = json.loads(
            (assessment(exercise) / "io.json").read_text(encoding="utf-8"))
        for i, case in enumerate(conf["cases"], 1):
            (root / "in/cases" / ("%02d.in" % i)).write_text(case["stdin"], encoding="utf-8")
        script = render("build-io.sh", root)
        cases = conf["cases"]
    else:
        shutil.copytree(assessment(exercise), root / "in/tests")
        shutil.copytree(UNITY, root / "in/unity")
        script = render("build-unity.sh", root)
        cases = None

    done = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          env={**os.environ, **SETTINGS, **settings,
                               "CTESTER_NONCE": NONCE}, cwd=root)
    return done.returncode, done.stdout, cases, root


def run_console(source, entry=None, budget=20, header=None, **settings):
    root = pathlib.Path(tempfile.mkdtemp(prefix="console-"))
    (root / "work").mkdir()
    (root / "in/src").mkdir(parents=True)
    (root / "in/src/main.c").write_text(source, encoding="utf-8")
    if header:
        name, text = header
        (root / "in/src" / name).write_text(text, encoding="utf-8")
    script = render("build-scratch.sh", root)
    proc = subprocess.Popen(
        ["bash", str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0, cwd=root,
        env={**os.environ, **SETTINGS, **settings, "CTESTER_NONCE": NONCE})
    seen, start = b"", time.time()
    while time.time() - start < budget:
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready:
            package = os.read(proc.stdout.fileno(), 65536)
            if not package:
                break
            seen += package
        if entry and entry[0].encode() in seen:
            proc.stdin.write(entry[1].encode())
            proc.stdin.flush()
            entry = None
    return proc, seen, root


def phases(output):
    marker = (NONCE + " RUN\n").encode()
    if marker not in output:
        return output, b""
    before, after = output.split(marker, 1)
    return before, after


def sources_c(directory):
    return sorted(f.name for f in directory.iterdir() if f.suffix == ".c")


def module_c(files, exercise, name="calendrier.c"):
    if name not in files:
        raise SystemExit(
            f"reference solution for {exercise!r} has no {name} "
            f"(files found: {sorted(files)}) -- solutions repo out of sync?")
    return name


failures = []


def show(res):
    preview = {k: v for k, v in res.items() if k not in ("warnings", "gcc")}
    print("      verdict: " + json.dumps(preview, ensure_ascii=False)[:300])


def check(cond, label):
    print(("ok    " if cond else "FAIL  ") + label)
    if not cond:
        failures.append(label)


print("\n--- 0a. the prompt arrives BEFORE anything is typed ---")
DIALOGUE = """#include <stdio.h>

int main(void)
{
    int n;
    printf("Entrez un nombre : ");
    scanf("%d", &n);
    printf("le double est %d\\n", n * 2);
    return 0;
}
"""
proc, seen, _ = run_console(DIALOGUE, entry=("Entrez un nombre : ", "21\n"))
before, after = phases(seen)
check(b"Entrez un nombre : " in after,
      "the prompt is readable BEFORE the program has received anything")
check(b"le double est 42" in after,
      "and the typed answer comes back processed: " + repr(after[-40:]))
check(before == b"", "gcc said nothing, so the `build` phase is empty")
check(NONCE.encode() not in after,
      "the phase marker never crosses the boundary")
proc.kill()

print("\n--- 0b. `while (1);` dies on CPU TIME ---")
proc, seen, _ = run_console("int main(void){ for(;;); }", budget=25,
                             CTESTER_CPU_SECONDS="2")
proc.wait(timeout=10)
_, after = phases(seen)
check(proc.returncode not in (0, None),
      "the program is killed (code %r)" % proc.returncode)
check(b"Killed" not in after and b"ulimit" not in after,
      "and its output contains NO bash noise: " + repr(after[:120]))

print("\n--- 0c. ...but a program that WAITS survives the same cap ---")
proc, seen, _ = run_console(DIALOGUE, budget=6, CTESTER_CPU_SECONDS="2")
_, after = phases(seen)
check(proc.poll() is None,
      "it is still alive after 6 s of wall time with a 2 s CPU cap")
check(b"Entrez un nombre : " in after, "and it is indeed waiting for its input")
proc.kill()

print("\n--- 0d. a compilation error exits with 10, with gcc's text ---")
proc, seen, _ = run_console("int main(void){ return zzz; }", budget=25)
proc.wait(timeout=15)
before, after = phases(seen)
check(proc.returncode == 10, "exit code 10 (%r)" % proc.returncode)
check(b"zzz" in before, "gcc's text is in the `build` phase")
check(after == b"", "and nothing ran")

print("\n--- 0d bis. the Console header is found next to main.c ---")
proc, seen, _ = run_console(
    '#include <stdio.h>\n#include "pile.h"\n\n'
    'int triple(int n) { return N * n; }\n\n'
    'int main(void)\n{\n    printf("triple : %d\\n", triple(14));\n    return 0;\n}\n',
    header=("pile.h", "#ifndef PILE_H\n#define PILE_H\n#define N 3\nint triple(int n);\n#endif\n"),
    budget=25)
proc.wait(timeout=15)
before, after = phases(seen)
check(proc.returncode == 0, "exit code 0 (%r): %r" % (proc.returncode, before[-200:]))
check(b"triple : 42" in after, "the macro and the prototype from pile.h are used: " + repr(after[-40:]))
proc, seen, _ = run_console('#include "pile.h"\nint main(void){ return N; }\n', budget=25)
proc.wait(timeout=15)
before, _ = phases(seen)
check(proc.returncode == 10 and b"pile.h" in before,
      "without the header, gcc says so in the `build` phase (%r)" % proc.returncode)

print("\n--- 0e. build-scratch.sh knows NEITHER cases NOR tests ---")
_scratch_text = "\n".join(
    line for line in (WORKER / "build-scratch.sh").read_text(encoding="utf-8").splitlines()
    if not line.lstrip().startswith("#"))
for _forbidden in ("/in/cases", "/in/tests", "/in/unity", "io.json",
                  "unity.json", "expect"):
    check(_forbidden not in _scratch_text,
          "no build-scratch.sh instruction touches %s" % _forbidden)
check(_scratch_text.count("/in/") == _scratch_text.count("/in/src"),
      "the only /in path it reads is /in/src")


CARELESS = """#include <stdio.h>

int main(void)
{
    int annee, naissance, inutilisee;
    printf("Annee actuelle : ");
    scanf("%d", &annee);
    printf("Annee de naissance : ");
    scanf("%d", &naissance);
    printf("Age : %d\\n", annee - naissance);
    return 0;
}
"""
rc, out, cases, _ = run("io", {"submission.c": CARELESS}, "tp2-ex0")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 1. correct but sloppy code ---")
show(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      "the verdict is a SUCCESS")
check(res.get("warnings"), "the warnings block is still attached")
check("inutilisee" in res.get("warnings", ""),
      "and it names the offending variable: " + res.get("warnings", "").strip().splitlines()[-1][:70])
check(res["passed"] == res["total"],
      f"every case passes ({res['passed']}/{res['total']})")

WITHOUT_AMPERSAND = CARELESS.replace('scanf("%d", &naissance)', 'scanf("%d", naissance)')
rc, out, cases, _ = run("io", {"submission.c": WITHOUT_AMPERSAND}, "tp2-ex0")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 2. scanf without & ---")
text = res.get("warnings", "") + res.get("gcc", "")
check("int *" in text, "gcc says it expected an int *")
check("naissance" in text or "%d" in text, "and points at the faulty conversion")
for line in text.strip().splitlines():
    if "expects argument" in line:
        print("      " + line.strip()[:100])

sol = corrected("tp7-ex1")
files = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
name = module_c(files, "tp7-ex1")
files[name] += "\nstatic int never_used_e2e = 42;\n"
rc, out, cases, root = run("unity", files, "tp7-ex1")
res = judge.verdict(rc, out, "unity", NONCE)
test_src = (root / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
own_sources = "\n".join(files.values())
tokens = {m for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in own_sources and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
leaks = sorted(j for j in tokens if j in str(res))
print("\n--- 3. no leak ---")
show(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      f"the reference solution passes ({res.get('passed')}/{res.get('total')})")
check(bool(res.get("warnings")), "warnings are indeed present (otherwise this check is empty)")
check("test_calendrier" not in str(res), "no mention of the test file")
check(not leaks, "no identifier specific to the test in the verdict"
      + (" -- LEAKED: " + ", ".join(leaks[:8]) if leaks else ""))
check(len(tokens) > 5, f"the check had something to bite on ({len(tokens)} identifiers watched)")


sol = corrected("tp2-ex0")
buggy = (sol / sources_c(sol)[0]).read_text(encoding="utf-8")
OVERFLOW = "    int t_e2e[3];\n    t_e2e[7] = 1;\n    return "
buggy = buggy.replace("    return ", OVERFLOW, 1)
rc, out, cases, _ = run("io", {"submission.c": buggy}, "tp2-ex0")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 4. overflow in io mode: the report is returned ---")
case = res["cases"][0] if res["cases"] else {}
check("debord" in case.get("reason", "") or "débord" in case.get("reason", ""),
      "the judge names the error class: " + case.get("reason", "(no failing case)")[:60])
check("AddressSanitizer" in case.get("stderr", ""),
      "and the ASan report reaches the student")
for line in case.get("stderr", "").splitlines():
    if "ERROR:" in line or "submission.c:" in line:
        print("      " + line.strip()[:96])
        break

sol = corrected("tp7-ex1")
files = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
c_name = module_c(files, "tp7-ex1")
files[c_name] = ("static int overflow_e2e[4];\n" + files[c_name]).replace(
    "return", "overflow_e2e[9] = 1;\n    return", 1)
rc, out, cases, root = run("unity", files, "tp7-ex1")
res = judge.verdict(rc, out, "unity", NONCE)
print("\n--- 5. overflow in unity mode: the fact, without the report ---")
show(res)
check(res["status"] == "memory_error",
      "the verdict is a memory overflow, not a \"failed test\"")
check("AddressSanitizer" not in str(res) and "#0" not in str(res),
      "no fragment of the ASan report leaked")
test_src = (root / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
own_sources = "\n".join(files.values())
tokens = {m for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in own_sources and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
leaks = sorted(j for j in tokens if j in str(res))
check(not leaks, "no identifier from the test file in the verdict"
      + (" -- LEAKED: " + ", ".join(leaks[:8]) if leaks else ""))

LOOP = '#include <stdio.h>\nint main(void){ while (1) {} return 0; }\n'
rc, out, cases, _ = run("io", {"submission.c": LOOP}, "tp2-ex0",
                           CTESTER_RUN_TIMEOUT="2")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 6a. infinite loop in io mode ---")
case = res["cases"][0] if res.get("cases") else {}
check(res.get("passed") == 0, "no case passes (status %r)" % res["status"])
check("boucle infinie" in case.get("reason", ""),
      "the message names the infinite loop: " + case.get("reason", "(none)")[:80])

sol = corrected("tp7-ex1")
files = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
name = module_c(files, "tp7-ex1")
files[name] += (
    "\n__attribute__((constructor)) static void loop_e2e(void)"
    " { while (1) {} }\n")
rc, out, cases, _ = run("unity", files, "tp7-ex1", CTESTER_RUN_TIMEOUT="2")
res = judge.verdict(rc, out, "unity", NONCE)
print("\n--- 6b. infinite loop in unity mode ---")
show(res)
check(res["status"] == "timeout", "the verdict is a timeout, not a crash")
check("boucle infinie" in res.get("message", ""),
      "and the message names the infinite loop")

print()
print("%d CHECK(S) FAILED" % len(failures) if failures
      else "the sandbox holds its invariants")
sys.exit(1 if failures else 0)
