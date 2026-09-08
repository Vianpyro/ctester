#!/usr/bin/env python3
"""Exercises the TWO SANDBOX SCRIPTS with a real gcc, no Docker.

    python3 test_sandbox.py [path/to/unittests/content]

test_ctester.py tests runner.py against manufactured output, test_page.js
tests the page against a cardboard DOM. Nobody tested build-io.sh or
build-unity.sh -- yet that is EXACTLY where the confidentiality invariant
lives: the phase split, the nonce protocol, and the fact that phase 2's
stderr is discarded. A broken template only shows up in production.

So we take the real scripts, move /in and /work into a temporary directory,
and run them as-is with bash, then feed their output to the real runner.py.
What is NOT covered: gVisor, capabilities, the absence of network -- none of
those affect the script's output.

Controller tool, not a server one: it needs gcc, like verify_content.py. Does
not run on the Dell.
"""
import importlib.util
import os
import select
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ICI = pathlib.Path(__file__).resolve().parent
# THE PRIVATE CONTENT ROOT (the one carrying catalog.json, exercises/ and
# shared/unity), with reference solutions NEXT TO IT: since phase 8 solutions
# are no longer mounted under the content, they live in their own repo.
CONTENU = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                       else ICI.parent / "unittests" / "content").resolve()
SOLUTIONS = pathlib.Path(os.environ.get("CTESTER_SOLUTIONS") or next(
    (c for c in (CONTENU.parent / "solutions",
                 CONTENU.parent.parent / "solutions") if c.is_dir()),
    CONTENU.parent / "solutions")).resolve()
UNITY = CONTENU / "shared" / "unity"


def assessment(exercice):
    """An exercise's grading directory -- the same gate as tp_path."""
    return CONTENU / "exercises" / exercice / "assessment"


def corrige(exercice):
    """The reference solution's directory. `tp6-ex1` first, then `tp6/ex1`."""
    for candidat in (SOLUTIONS / exercice,
                     SOLUTIONS.joinpath(*exercice.split("-", 1))):
        if candidat.is_dir():
            return candidat
    raise SystemExit("no reference solution found for " + exercice
                     + " under " + str(SOLUTIONS))

spec = importlib.util.spec_from_file_location("runner", ICI / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

NONCE = "e2e0123456789abcdef0123456789abc"

# This machine's gcc may be older than the sandbox image's, which accepts
# gnu23. Same dialect, different spelling.
STD = "gnu23"
if subprocess.run(["gcc", "-std=gnu23", "-E", "-"], input="", capture_output=True,
                  text=True).returncode != 0:
    STD = "gnu2x"


# What the worker passes the container in deployment (SANDBOX_ENV in
# runner.py). The scripts have the SAME defaults: repeating them here makes
# this test check the path actually taken in production, the one where the
# variables are supplied, not just the defaults.
REGLAGES = {
    "CTESTER_C_STD": STD,
    "CTESTER_SANITIZERS": "-fsanitize=address,undefined",
    "CTESTER_ASAN_OPTIONS": "exitcode=86:detect_leaks=0",
    "CTESTER_COMPILE_TIMEOUT": "10",
    "CTESTER_RUN_TIMEOUT": "5",
}


def rendre(nom, racine):
    """The real script, with /in and /work moved into the temp directory."""
    texte = (ICI / nom).read_text(encoding="utf-8")
    texte = texte.replace("/in/", f"{racine}/in/").replace("/work", f"{racine}/work")
    script = racine / nom
    script.write_text(texte, encoding="utf-8")
    script.chmod(0o755)
    return script


def lancer(mode, fichiers, exercice, **reglages):
    """Sets up the tree, runs it, returns (code, stdout)."""
    racine = pathlib.Path(tempfile.mkdtemp(prefix="e2e-"))
    (racine / "work").mkdir()
    (racine / "in/src").mkdir(parents=True)
    for nom, contenu in fichiers.items():
        (racine / "in/src" / nom).write_text(contenu, encoding="utf-8")

    if mode == "io":
        (racine / "in/cases").mkdir()
        conf = runner.json.loads(
            (assessment(exercice) / "io.json").read_text(encoding="utf-8"))
        # The names verdict_io expects: "01", "02"... and nothing else.
        for i, cas in enumerate(conf["cases"], 1):
            (racine / "in/cases" / ("%02d.in" % i)).write_text(cas["stdin"], encoding="utf-8")
        script = rendre("build-io.sh", racine)
        cases = conf["cases"]
    else:
        shutil.copytree(assessment(exercice), racine / "in/tests")
        shutil.copytree(UNITY, racine / "in/unity")
        script = rendre("build-unity.sh", racine)
        cases = None

    done = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          env={**os.environ, **REGLAGES, **reglages,
                               "CTESTER_NONCE": NONCE}, cwd=racine)
    return done.returncode, done.stdout, cases, racine


def lancer_console(source, entree=None, budget=20, **reglages):
    """La Console : le script tel quel, un vrai gcc, et PERSONNE au clavier.

    On rend le processus VIVANT, pas son code de sortie : ce qu'il faut
    éprouver ici est qu'une invite arrive AVANT qu'on ait écrit sur l'entrée
    standard -- c'est-à-dire précisément ce qu'un `subprocess.run()` ne peut
    pas voir, puisqu'il attend la fin.
    """
    racine = pathlib.Path(tempfile.mkdtemp(prefix="console-"))
    (racine / "work").mkdir()
    (racine / "in/src").mkdir(parents=True)
    (racine / "in/src/main.c").write_text(source, encoding="utf-8")
    script = rendre("build-scratch.sh", racine)
    proc = subprocess.Popen(
        ["bash", str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0, cwd=racine,
        env={**os.environ, **REGLAGES, **reglages, "CTESTER_NONCE": NONCE})
    vu, debut = b"", time.time()
    while time.time() - debut < budget:
        pret, _, _ = select.select([proc.stdout], [], [], 0.2)
        if pret:
            paquet = os.read(proc.stdout.fileno(), 65536)
            if not paquet:
                break
            vu += paquet
        if entree and entree[0].encode() in vu:
            proc.stdin.write(entree[1].encode())
            proc.stdin.flush()
            entree = None
    return proc, vu, racine


def phases(sortie):
    """(ce que gcc a dit, ce que le programme a écrit), coupé sur le marqueur."""
    marqueur = (NONCE + " RUN\n").encode()
    if marqueur not in sortie:
        return sortie, b""
    avant, apres = sortie.split(marqueur, 1)
    return avant, apres


def sources_c(dossier):
    return sorted(f.name for f in dossier.iterdir() if f.suffix == ".c")


def module_c(fichiers, exercice, nom="calendrier.c"):
    """The module's .c file among a fetched solution's files, or a clear error.

    tp6-ex1 is the two-file module fixture declared in its public/files.json;
    a solutions checkout missing calendrier.c is a content/solutions sync
    problem to report, not a KeyError to chase through a traceback.
    """
    if nom not in fichiers:
        raise SystemExit(
            f"reference solution for {exercice!r} has no {nom} "
            f"(files found: {sorted(fichiers)}) -- solutions repo out of sync?")
    return nom


rates = []


def montrer(res):
    apercu = {k: v for k, v in res.items() if k not in ("warnings", "gcc")}
    print("      verdict: " + runner.json.dumps(apercu, ensure_ascii=False)[:300])


def check(cond, libelle):
    print(("ok    " if cond else "FAIL  ") + libelle)
    if not cond:
        rates.append(libelle)


# --- 0. LA CONSOLE ---------------------------------------------------------
# EN PREMIER, ET SANS AUCUN CONTENU. Ces contrôles ne lisent ni exercice, ni
# corrigé, ni Unity : la Console n'a pas d'exercice, c'est tout son sujet. Ils
# tournent donc même sur une machine où le dépôt de tests privé n'est pas
# cloné, ce qui est exactement l'endroit où l'on veut pouvoir les lancer.

print("\n--- 0a. l'invite arrive AVANT qu'on tape ---")
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
proc, vu, _ = lancer_console(DIALOGUE, entree=("Entrez un nombre : ", "21\n"))
avant, apres = phases(vu)
# C'EST TOUTE LA FONCTIONNALITÉ, ET C'EST LE SEUL HARNAIS QUI PEUT LA PROUVER.
# Sans le constructeur de build-scratch.sh, la glibc met stdout en tampon de
# BLOC dès qu'il n'est pas un terminal : cette invite n'apparaîtrait qu'à la
# fin du programme, et le terminal aurait l'air gelé au moment précis où il
# demande quelque chose. Mesuré avant de l'écrire : aucune invite en 25 s.
check(b"Entrez un nombre : " in apres,
      "l'invite est lisible AVANT que le programme n'ait reçu quoi que ce soit")
check(b"le double est 42" in apres,
      "et la reponse tapee revient traitee : " + repr(apres[-40:]))
check(avant == b"", "gcc n'a rien dit, donc la phase `build` est vide")
check(NONCE.encode() not in apres,
      "le marqueur de phase ne franchit jamais la frontiere")
proc.kill()

print("\n--- 0b. `while (1);` meurt sur le TEMPS CPU ---")
proc, vu, _ = lancer_console("int main(void){ for(;;); }", budget=25,
                             CTESTER_CPU_SECONDS="2")
proc.wait(timeout=10)
_, apres = phases(vu)
check(proc.returncode not in (0, None),
      "le programme est tue (code %r)" % proc.returncode)
# LE BRUIT DE BASH NE DOIT PAS REMONTER. Avec un sous-shell, bash ecrivait
# « build.sh: line NN: 16 Killed ( ulimit ... ) » dans la sortie de
# l'etudiant : des entrailles de script au moment precis ou il faut lui
# expliquer sa boucle infinie. D'ou `ulimit` puis `exec`, sans sous-shell.
check(b"Killed" not in apres and b"ulimit" not in apres,
      "et sa sortie ne contient AUCUN bruit de bash : " + repr(apres[:120]))

print("\n--- 0c. ...mais un programme qui ATTEND survit au meme plafond ---")
# LA DISCRIMINATION, ET C'EST LA RAISON D'ETRE DU TEMPS CPU. Le temps mural ne
# distingue pas « l'etudiant reflechit » de « le programme tourne en rond » --
# c'est pour ca qu'un job note peut se contenter d'un `timeout -s KILL 5` et
# pas une session interactive. Un programme bloque dans scanf ne consomme
# aucun CPU, donc il doit survivre la ou le precedent meurt.
proc, vu, _ = lancer_console(DIALOGUE, budget=6, CTESTER_CPU_SECONDS="2")
_, apres = phases(vu)
check(proc.poll() is None,
      "il est toujours vivant apres 6 s murales avec 2 s de CPU au plafond")
check(b"Entrez un nombre : " in apres, "et il attend bien son entree")
proc.kill()

print("\n--- 0d. une erreur de compilation sort en 10, avec le texte de gcc ---")
proc, vu, _ = lancer_console("int main(void){ return zzz; }", budget=25)
proc.wait(timeout=15)
avant, apres = phases(vu)
check(proc.returncode == 10, "code de sortie 10 (%r)" % proc.returncode)
check(b"zzz" in avant, "le texte de gcc est dans la phase `build`")
check(apres == b"", "et rien n'a tourne")

print("\n--- 0e. build-scratch.sh ne connait NI cas, NI test ---")
# L'INVARIANT DE CONFIDENTIALITE DE CE SCRIPT, dit sur le script lui-meme.
# build-io.sh peut montrer la stderr de gcc parce qu'il ne voit pas les valeurs
# attendues ; celui-ci ne voit ni test, ni cas, ni contenu -- une affirmation
# plus forte, et qui doit rester vraie.
# LES COMMENTAIRES SONT RETIRES AVANT DE REGARDER : l'en-tete du script NOMME
# /in/cases et /in/tests, justement pour dire qu'il ne les monte pas. Ce qu'on
# verifie ici est qu'aucune INSTRUCTION ne les touche -- la prose a le droit
# d'en parler, le code n'a pas le droit d'y aller.
_texte_scratch = "\n".join(
    ligne for ligne in (ICI / "build-scratch.sh").read_text(encoding="utf-8").splitlines()
    if not ligne.lstrip().startswith("#"))
for _interdit in ("/in/cases", "/in/tests", "/in/unity", "io.json",
                  "unity.json", "expect"):
    check(_interdit not in _texte_scratch,
          "aucune instruction de build-scratch.sh ne touche %s" % _interdit)
# Et il ne monte QUE /in/src : c'est le seul chemin de /in qu'il lit.
check(_texte_scratch.count("/in/") == _texte_scratch.count("/in/src"),
      "le seul chemin de /in qu'il lit est /in/src")


# --- 1. Correct but sloppy code: it SUCCEEDS, with warnings -----------------
NEGLIGE = """#include <stdio.h>

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
rc, out, cases, _ = lancer("io", {"submission.c": NEGLIGE}, "tp2-ex0")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 1. correct but sloppy code ---")
montrer(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      "the verdict is a SUCCESS")
check(res.get("warnings"), "the warnings block is still attached")
check("inutilisee" in res.get("warnings", ""),
      "and it names the offending variable: " + res.get("warnings", "").strip().splitlines()[-1][:70])
check(res["passed"] == res["total"],
      f"every case passes ({res['passed']}/{res['total']})")

# --- 2. scanf without &: gcc says precisely what is missing -----------------
SANS_ESPERLUETTE = NEGLIGE.replace('scanf("%d", &naissance)', 'scanf("%d", naissance)')
rc, out, cases, _ = lancer("io", {"submission.c": SANS_ESPERLUETTE}, "tp2-ex0")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 2. scanf without & ---")
texte = res.get("warnings", "") + res.get("gcc", "")
check("int *" in texte, "gcc says it expected an int *")
check("naissance" in texte or "%d" in texte, "and points at the faulty conversion")
for ligne in texte.strip().splitlines():
    if "expects argument" in ligne:
        print("      " + ligne.strip()[:100])

# --- 3. NO LEAK: nothing from the test file in the warnings -----------------
sol = corrige("tp6-ex1")
fichiers = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
nom = module_c(fichiers, "tp6-ex1")
# The reference solution is made deliberately noisy to FORCE warnings:
# without a warning, this check would pass for the wrong reasons.
fichiers[nom] += "\nstatic int jamais_utilisee_e2e = 42;\n"
rc, out, cases, racine = lancer("unity", fichiers, "tp6-ex1")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(runner.verdict(rc, reste), av)
test_src = (racine / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
sien = "\n".join(fichiers.values())
jetons = {m for m in runner.re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in sien and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
fuites = sorted(j for j in jetons if j in str(res))
print("\n--- 3. no leak ---")
montrer(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      f"the reference solution passes ({res.get('passed')}/{res.get('total')})")
check(bool(res.get("warnings")), "warnings are indeed present (otherwise this check is empty)")
check("test_calendrier" not in str(res), "no mention of the test file")
check(not fuites, "no identifier specific to the test in the verdict"
      + (" -- LEAKED: " + ", ".join(fuites[:8]) if fuites else ""))
check(len(jetons) > 5, f"the check had something to bite on ({len(jetons)} identifiers watched)")


# --- 4. ASan in io mode: the full report, nothing to hide -------------------
sol = corrige("tp2-ex0")
buggy = (sol / sources_c(sol)[0]).read_text(encoding="utf-8")
DEBORDE = "    int t_e2e[3];\n    t_e2e[7] = 1;\n    return "
buggy = buggy.replace("    return ", DEBORDE, 1)
rc, out, cases, _ = lancer("io", {"submission.c": buggy}, "tp2-ex0")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 4. overflow in io mode: the report is returned ---")
cas = res["cases"][0] if res["cases"] else {}
check("debord" in cas.get("reason", "") or "débord" in cas.get("reason", ""),
      "the judge names the error class: " + cas.get("reason", "(no failing case)")[:60])
check("AddressSanitizer" in cas.get("stderr", ""),
      "and the ASan report reaches the student")
for ligne in cas.get("stderr", "").splitlines():
    if "ERROR:" in ligne or "submission.c:" in ligne:
        print("      " + ligne.strip()[:96])
        break

# --- 5. ASan in unity mode: the FACT, never the report ----------------------
sol = corrige("tp6-ex1")
fichiers = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
nom_c = module_c(fichiers, "tp6-ex1")
fichiers[nom_c] = ("static int deborde_e2e[4];\n" + fichiers[nom_c]).replace(
    "return", "deborde_e2e[9] = 1;\n    return", 1)
rc, out, cases, racine = lancer("unity", fichiers, "tp6-ex1")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(runner.verdict(rc, reste), av)
print("\n--- 5. overflow in unity mode: the fact, without the report ---")
montrer(res)
check(res["status"] == "memory_error",
      "the verdict is a memory overflow, not a \"failed test\"")
check("AddressSanitizer" not in str(res) and "#0" not in str(res),
      "no fragment of the ASan report leaked")
test_src = (racine / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
sien = "\n".join(fichiers.values())
jetons = {m for m in runner.re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in sien and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
fuites = sorted(j for j in jetons if j in str(res))
check(not fuites, "no identifier from the test file in the verdict"
      + (" -- LEAKED: " + ", ".join(fuites[:8]) if fuites else ""))

# --- 6. infinite loop: the timer cuts it off, and the judge SAYS so ---------
# The course's classic. RUN_TIMEOUT drops to 2 s here so this check does not
# cost 5 s per mode; it is the same clock, that of `timeout -s KILL`.
BOUCLE = '#include <stdio.h>\nint main(void){ while (1) {} return 0; }\n'
rc, out, cases, _ = lancer("io", {"submission.c": BOUCLE}, "tp2-ex0",
                           CTESTER_RUN_TIMEOUT="2")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 6a. infinite loop in io mode ---")
cas = res["cases"][0] if res.get("cases") else {}
check(res.get("passed") == 0, "no case passes (status %r)" % res["status"])
check("boucle infinie" in cas.get("reason", ""),
      "the message names the infinite loop: " + cas.get("reason", "(none)")[:80])

sol = corrige("tp6-ex1")
fichiers = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
nom = module_c(fichiers, "tp6-ex1")
fichiers[nom] += (
    "\n__attribute__((constructor)) static void boucle_e2e(void)"
    " { while (1) {} }\n")
rc, out, cases, _ = lancer("unity", fichiers, "tp6-ex1", CTESTER_RUN_TIMEOUT="2")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(runner.verdict(rc, reste), av)
print("\n--- 6b. infinite loop in unity mode ---")
montrer(res)
check(res["status"] == "timeout", "the verdict is a timeout, not a crash")
check("boucle infinie" in res.get("message", ""),
      "and the message names the infinite loop")

print()
print("%d CHECK(S) FAILED" % len(rates) if rates
      else "the sandbox holds its invariants")
sys.exit(1 if rates else 0)
