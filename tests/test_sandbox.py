#!/usr/bin/env python3
"""End-to-end checks of the sandbox build scripts, on a fixture written to a temporary
directory, so they run on a bare clone without any content repository.
"""
import json
import os
import re
import select
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
UNITY = ROOT / "tests" / "fixture" / "unity"

sys.path.insert(0, str(WORKER))
import judge  # noqa: E402
import local_build  # noqa: E402

NONCE = "e2e0123456789abcdef0123456789abc"

# The io reference solution: correct, and sloppy enough to make gcc say something.
IO_SOLUTION = """#include <stdio.h>

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

IO_CASES = [{"stdin": "2026\n2000\n", "expect": [26]},
            {"stdin": "2026\n1990\n", "expect": [36]},
            {"stdin": "2026\n1974\n", "expect": [52]},
            {"stdin": "2100\n2012\n", "expect": [88]}]

MODULE_H = """#ifndef MODULE_H
#define MODULE_H

int somme(int a, int b);
int produit(int a, int b);
double moyenne(int a, int b);

#endif /* MODULE_H */
"""

MODULE_C = """#include "module.h"

int somme(int a, int b)
{
    return a + b;
}

int produit(int a, int b)
{
    return a * b;
}

double moyenne(int a, int b)
{
    return (a + b) / 2.0;
}
"""

TEST_NAME = "test_module.c"

# Every identifier here is deliberately absent from the module: the leak checks below
# count them, and need something to bite on.
TEST_SOURCE = """#include "unity.h"
#include "module.h"

void setUp(void) {}
void tearDown(void) {}

static void test_somme_additionne_deux_entiers(void)
{
    TEST_ASSERT_EQUAL_INT(7, somme(3, 4));
}

static void test_somme_supporte_les_negatifs(void)
{
    TEST_ASSERT_EQUAL_INT(-1, somme(3, -4));
}

static void test_produit_multiplie_deux_entiers(void)
{
    TEST_ASSERT_EQUAL_INT(12, produit(3, 4));
}

static void test_produit_par_zero_vaut_zero(void)
{
    TEST_ASSERT_EQUAL_INT(0, produit(9999, 0));
}

static void test_moyenne_garde_la_demie(void)
{
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 3.5, moyenne(3, 4));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_somme_additionne_deux_entiers);
    RUN_TEST(test_somme_supporte_les_negatifs);
    RUN_TEST(test_produit_multiplie_deux_entiers);
    RUN_TEST(test_produit_par_zero_vaut_zero);
    RUN_TEST(test_moyenne_garde_la_demie);
    return UNITY_END();
}
"""

FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="e2e-content-"))


def _fixture():
    io_dir = FIXTURE / "exercises/io-demo/assessment"
    io_dir.mkdir(parents=True)
    (io_dir / "io.json").write_text(json.dumps({"cases": IO_CASES}), encoding="utf-8")

    unity_dir = FIXTURE / "exercises/unity-demo/assessment"
    unity_dir.mkdir(parents=True)
    (unity_dir / "unity.json").write_text("{}", encoding="utf-8")
    (unity_dir / TEST_NAME).write_text(TEST_SOURCE, encoding="utf-8")


_fixture()


def module_files():
    return {"module.h": MODULE_H, "module.c": MODULE_C}


def run(mode, files, exercise, **settings):
    assessment = FIXTURE / "exercises" / exercise / "assessment"
    rc, out, cases, root = local_build.run(
        mode, files, str(assessment), str(UNITY), NONCE, **settings)
    return rc, out, cases, pathlib.Path(root)


def run_console(source, entry=None, budget=20, header=None, **settings):
    root = pathlib.Path(tempfile.mkdtemp(prefix="console-"))
    (root / "work").mkdir()
    (root / "in/src").mkdir(parents=True)
    (root / "in/src/main.c").write_text(source, encoding="utf-8")
    if header:
        name, text = header
        (root / "in/src" / name).write_text(text, encoding="utf-8")
    script = local_build.render("build-scratch.sh", root)
    proc = subprocess.Popen(
        ["bash", str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0, cwd=root,
        env=local_build.environment(NONCE, **settings))
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


failures = []


def show(res):
    preview = {k: v for k, v in res.items() if k not in ("warnings", "gcc")}
    print("      verdict: " + json.dumps(preview, ensure_ascii=False)[:300])


def check(cond, label):
    print(("ok    " if cond else "FAIL  ") + label)
    if not cond:
        failures.append(label)


print("\n--- 0a. the prompt arrives before any input ---")
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

print("\n--- 0b. `while (1);` hits the CPU limit ---")
proc, seen, _ = run_console("int main(void){ for(;;); }", budget=25,
                             CTESTER_CPU_SECONDS="2")
proc.wait(timeout=10)
_, after = phases(seen)
check(proc.returncode not in (0, None),
      "the program is killed (code %r)" % proc.returncode)
check(b"Killed" not in after and b"ulimit" not in after,
      "and its output contains NO bash noise: " + repr(after[:120]))

print("\n--- 0c. a program waiting for input survives it ---")
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

print("\n--- 0e. the Console header is found next to main.c ---")
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

print("\n--- 0f. build-scratch.sh sees no cases and no tests ---")
_scratch_text = "\n".join(
    line for line in (WORKER / "build-scratch.sh").read_text(encoding="utf-8").splitlines()
    if not line.lstrip().startswith("#"))
for _forbidden in ("/in/cases", "/in/tests", "/in/unity", "io.json",
                  "unity.json", "expect"):
    check(_forbidden not in _scratch_text,
          "no build-scratch.sh instruction touches %s" % _forbidden)
check(_scratch_text.count("/in/") == _scratch_text.count("/in/src"),
      "the only /in path it reads is /in/src")


CARELESS = IO_SOLUTION
rc, out, cases, _ = run("io", {"submission.c": CARELESS}, "io-demo")
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
rc, out, cases, _ = run("io", {"submission.c": WITHOUT_AMPERSAND}, "io-demo")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 2. scanf without & ---")
text = res.get("warnings", "") + res.get("gcc", "")
check("int *" in text, "gcc says it expected an int *")
check("naissance" in text or "%d" in text, "and points at the faulty conversion")
for line in text.strip().splitlines():
    if "expects argument" in line:
        print("      " + line.strip()[:100])

files = module_files()
name = "module.c"
files[name] += "\nstatic int never_used_e2e = 42;\n"
rc, out, cases, root = run("unity", files, "unity-demo")
res = judge.verdict(rc, out, "unity", NONCE)
test_src = (root / "in/tests" / TEST_NAME).read_text(encoding="utf-8")
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
check(TEST_NAME[:-2] not in str(res), "no mention of the test file")
check(not leaks, "no identifier specific to the test in the verdict"
      + (" -- LEAKED: " + ", ".join(leaks[:8]) if leaks else ""))
check(len(tokens) > 5, f"the check had something to bite on ({len(tokens)} identifiers watched)")


buggy = IO_SOLUTION
OVERFLOW = "    int t_e2e[3];\n    t_e2e[7] = 1;\n    return "
buggy = buggy.replace("    return ", OVERFLOW, 1)
rc, out, cases, _ = run("io", {"submission.c": buggy}, "io-demo")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 4. overflow in io mode: the report is returned ---")
case = res["cases"][0] if res["cases"] else {}
check(case.get("reason") == "memory",
      "the judge names the error class: " + case.get("reason", "(no failing case)")[:60])
check("AddressSanitizer" in case.get("stderr", ""),
      "and the ASan report reaches the student")
for line in case.get("stderr", "").splitlines():
    if "ERROR:" in line or "submission.c:" in line:
        print("      " + line.strip()[:96])
        break

files = module_files()
c_name = "module.c"
files[c_name] = ("static int overflow_e2e[4];\n" + files[c_name]).replace(
    "return", "overflow_e2e[9] = 1;\n    return", 1)
rc, out, cases, root = run("unity", files, "unity-demo")
res = judge.verdict(rc, out, "unity", NONCE)
print("\n--- 5. overflow in unity mode: the fact, without the report ---")
show(res)
check(res["status"] == "memory_error",
      "the verdict is a memory overflow, not a \"failed test\"")
check("AddressSanitizer" not in str(res) and "#0" not in str(res),
      "no fragment of the ASan report leaked")
test_src = (root / "in/tests" / TEST_NAME).read_text(encoding="utf-8")
own_sources = "\n".join(files.values())
tokens = {m for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in own_sources and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
leaks = sorted(j for j in tokens if j in str(res))
check(not leaks, "no identifier from the test file in the verdict"
      + (" -- LEAKED: " + ", ".join(leaks[:8]) if leaks else ""))

LOOP = '#include <stdio.h>\nint main(void){ while (1) {} return 0; }\n'
rc, out, cases, _ = run("io", {"submission.c": LOOP}, "io-demo",
                           CTESTER_RUN_TIMEOUT="2")
res = judge.verdict(rc, out, "io", NONCE, cases, 0.005)
print("\n--- 6a. infinite loop in io mode ---")
case = res["cases"][0] if res.get("cases") else {}
check(res.get("passed") == 0, "no case passes (status %r)" % res["status"])
check(case.get("reason") == "interrupted",
      "the reason names the interruption: " + case.get("reason", "(none)")[:80])

files = module_files()
name = "module.c"
files[name] += (
    "\n__attribute__((constructor)) static void loop_e2e(void)"
    " { while (1) {} }\n")
rc, out, cases, _ = run("unity", files, "unity-demo", CTESTER_RUN_TIMEOUT="2")
res = judge.verdict(rc, out, "unity", NONCE)
print("\n--- 6b. infinite loop in unity mode ---")
show(res)
check(res["status"] == "timeout", "the verdict is a timeout, not a crash")

print()
print("%d check(s) failed" % len(failures) if failures
      else "the sandbox holds its invariants")
sys.exit(1 if failures else 0)
