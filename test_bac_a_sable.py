#!/usr/bin/env python3
"""Eprouve les DEUX SCRIPTS DU BAC A SABLE avec un vrai gcc, sans Docker.

    python3 test_bac_a_sable.py [chemin/vers/unittests/content]

test_ctester.py teste runner.py sur des sorties fabriquees, test_page.js teste
la page sur un DOM en carton. Personne ne testait build-io.sh ni
build-unity.sh -- or c'est LA que vit l'invariant de confidentialite : le
decoupage en phases, le protocole du nonce, et le fait que la stderr de la
phase 2 soit jetee. Un template casse ne se voit qu'en production.

On prend donc les vrais scripts, on deplace /in et /work vers un repertoire
temporaire, et on les execute tels quels avec bash, puis on passe leur sortie
au vrai runner.py. Ce qui n'est PAS couvert : gVisor, les capabilities,
l'absence de reseau -- aucun n'influe sur la sortie du script.

Outil de controleur, pas de serveur : il lui faut gcc, comme a
valider_contenu.py. Ne tourne pas sur le Dell.
"""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ICI = pathlib.Path(__file__).resolve().parent
# LA RACINE DU CONTENU PRIVE (celle qui porte catalog.json, exercises/ et
# shared/unity), et les corriges A COTE : depuis la phase 8 les solutions ne
# sont plus montees sous le contenu, elles vivent dans leur propre depot.
CONTENU = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                       else ICI.parent / "unittests" / "content").resolve()
SOLUTIONS = pathlib.Path(os.environ.get("CTESTER_SOLUTIONS") or next(
    (c for c in (CONTENU.parent / "solutions",
                 CONTENU.parent.parent / "solutions") if c.is_dir()),
    CONTENU.parent / "solutions")).resolve()
UNITY = CONTENU / "shared" / "unity"


def assessment(exercice):
    """Le repertoire de correction d'un exercice -- la meme porte que tp_path."""
    return CONTENU / "exercises" / exercice / "assessment"


def corrige(exercice):
    """Le repertoire du corrige. `tp6-ex1` d'abord, puis `tp6/ex1`."""
    for candidat in (SOLUTIONS / exercice,
                     SOLUTIONS.joinpath(*exercice.split("-", 1))):
        if candidat.is_dir():
            return candidat
    raise SystemExit("corrige introuvable pour " + exercice
                     + " sous " + str(SOLUTIONS))

spec = importlib.util.spec_from_file_location("runner", ICI / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

NONCE = "e2e0123456789abcdef0123456789abc"

# Le gcc de cette machine peut etre plus ancien que celui de l'image du bac a
# sable, qui accepte gnu23. Meme dialecte, autre orthographe.
STD = "gnu23"
if subprocess.run(["gcc", "-std=gnu23", "-E", "-"], input="", capture_output=True,
                  text=True).returncode != 0:
    STD = "gnu2x"


# Ce que le worker passe au conteneur en deploiement (SANDBOX_ENV dans
# runner.py). Les scripts ont les MEMES valeurs par defaut : les repeter ici
# fait que ce test verifie le chemin reellement emprunte en production, celui ou
# les variables sont fournies, et pas seulement les defauts.
REGLAGES = {
    "CTESTER_C_STD": STD,
    "CTESTER_SANITIZERS": "-fsanitize=address,undefined",
    "CTESTER_ASAN_OPTIONS": "exitcode=86:detect_leaks=0",
    "CTESTER_COMPILE_TIMEOUT": "10",
    "CTESTER_RUN_TIMEOUT": "5",
}


def rendre(nom, racine):
    """Le vrai script, avec /in et /work deplaces vers le repertoire temporaire."""
    texte = (ICI / nom).read_text(encoding="utf-8")
    texte = texte.replace("/in/", f"{racine}/in/").replace("/work", f"{racine}/work")
    script = racine / nom
    script.write_text(texte, encoding="utf-8")
    script.chmod(0o755)
    return script


def lancer(mode, fichiers, exercice):
    """Monte l'arborescence, execute, retourne (code, stdout)."""
    racine = pathlib.Path(tempfile.mkdtemp(prefix="e2e-"))
    (racine / "work").mkdir()
    (racine / "in/src").mkdir(parents=True)
    for nom, contenu in fichiers.items():
        (racine / "in/src" / nom).write_text(contenu, encoding="utf-8")

    if mode == "io":
        (racine / "in/cases").mkdir()
        conf = runner.json.loads(
            (assessment(exercice) / "io.json").read_text(encoding="utf-8"))
        # Les noms que verdict_io attend : "01", "02"... et pas autre chose.
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
                          env={**os.environ, **REGLAGES, "CTESTER_NONCE": NONCE}, cwd=racine)
    return done.returncode, done.stdout, cases, racine


def sources_c(dossier):
    return sorted(f.name for f in dossier.iterdir() if f.suffix == ".c")


rates = []


def montrer(res):
    apercu = {k: v for k, v in res.items() if k not in ("warnings", "gcc")}
    print("      verdict : " + runner.json.dumps(apercu, ensure_ascii=False)[:300])


def check(cond, libelle):
    print(("ok    " if cond else "ECHEC ") + libelle)
    if not cond:
        rates.append(libelle)


# --- 1. Un code correct mais neglige : il REUSSIT, avec des avertissements ---
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
print("\n--- 1. code correct mais neglige ---")
montrer(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      "le verdict est une REUSSITE")
check(res.get("warnings"), "le bloc d'avertissements est quand meme attache")
check("inutilisee" in res.get("warnings", ""),
      "et il nomme la variable en cause : " + res.get("warnings", "").strip().splitlines()[-1][:70])
check(res["passed"] == res["total"],
      f"tous les cas passent ({res['passed']}/{res['total']})")

# --- 2. scanf sans & : gcc dit precisement ce qui manque ---------------------
SANS_ESPERLUETTE = NEGLIGE.replace('scanf("%d", &naissance)', 'scanf("%d", naissance)')
rc, out, cases, _ = lancer("io", {"submission.c": SANS_ESPERLUETTE}, "tp2-ex0")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 2. scanf sans & ---")
texte = res.get("warnings", "") + res.get("gcc", "")
check("int *" in texte, "gcc dit qu'il attendait un int *")
check("naissance" in texte or "%d" in texte, "et pointe la conversion fautive")
for ligne in texte.strip().splitlines():
    if "expects argument" in ligne:
        print("      " + ligne.strip()[:100])

# --- 3. NON-FUITE : rien du fichier de test dans les avertissements ----------
sol = corrige("tp6-ex1")
fichiers = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
# On rend le corrige volontairement bavard pour FORCER des avertissements :
# sans avertissement, le controle passerait pour de mauvaises raisons.
fichiers["calendrier.c"] += "\nstatic int jamais_utilisee_e2e = 42;\n"
rc, out, cases, racine = lancer("unity", fichiers, "tp6-ex1")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(runner.verdict(rc, reste), av)
test_src = (racine / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
sien = "\n".join(fichiers.values())
jetons = {m for m in runner.re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in sien and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
fuites = sorted(j for j in jetons if j in str(res))
print("\n--- 3. non-fuite ---")
montrer(res)
check(res["status"] == "ok" and res["passed"] == res["total"],
      f"le corrige passe ({res.get('passed')}/{res.get('total')})")
check(bool(res.get("warnings")), "des avertissements sont bien presents (sinon controle vide)")
check("test_calendrier" not in str(res), "aucune mention du fichier de test")
check(not fuites, "aucun identifiant propre au test dans le verdict"
      + (" -- FUITES : " + ", ".join(fuites[:8]) if fuites else ""))
check(len(jetons) > 5, f"le controle avait de quoi mordre ({len(jetons)} identifiants surveilles)")


# --- 4. ASan en mode io : le rapport complet, il n'y a rien a taire ---------
sol = corrige("tp2-ex0")
buggy = (sol / sources_c(sol)[0]).read_text(encoding="utf-8")
DEBORDE = "    int t_e2e[3];\n    t_e2e[7] = 1;\n    return "
buggy = buggy.replace("    return ", DEBORDE, 1)
rc, out, cases, _ = lancer("io", {"submission.c": buggy}, "tp2-ex0")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(
    runner.verdict_io(rc, reste, cases, NONCE, 0.005), av)
print("\n--- 4. debordement en mode io : le rapport est rendu ---")
cas = res["cases"][0] if res["cases"] else {}
check("debord" in cas.get("reason", "") or "débord" in cas.get("reason", ""),
      "le juge nomme la classe d'erreur : " + cas.get("reason", "(aucun cas rate)")[:60])
check("AddressSanitizer" in cas.get("stderr", ""),
      "et le rapport d'ASan remonte a l'etudiant")
for ligne in cas.get("stderr", "").splitlines():
    if "ERROR:" in ligne or "submission.c:" in ligne:
        print("      " + ligne.strip()[:96])
        break

# --- 5. ASan en mode unity : le FAIT, jamais le rapport ---------------------
sol = corrige("tp6-ex1")
fichiers = {p.name: p.read_text(encoding="utf-8") for p in sol.iterdir()}
nom_c = "calendrier.c"
fichiers[nom_c] = ("static int deborde_e2e[4];\n" + fichiers[nom_c]).replace(
    "return", "deborde_e2e[9] = 1;\n    return", 1)
rc, out, cases, racine = lancer("unity", fichiers, "tp6-ex1")
av, reste = runner.extraire_avertissements(out, NONCE)
res = runner.avec_avertissements(runner.verdict(rc, reste), av)
print("\n--- 5. debordement en mode unity : le fait, sans le rapport ---")
montrer(res)
check(res["status"] == "memory_error",
      "le verdict est un debordement memoire, pas un « test rate »")
check("AddressSanitizer" not in str(res) and "#0" not in str(res),
      "aucun fragment du rapport d'ASan n'a fuite")
test_src = (racine / "in/tests/test_calendrier.c").read_text(encoding="utf-8")
sien = "\n".join(fichiers.values())
jetons = {m for m in runner.re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", test_src)
          if m not in sien and not m.startswith(("TEST_", "UNITY"))
          and m not in ("static", "return", "include", "stdbool", "unsigned")}
fuites = sorted(j for j in jetons if j in str(res))
check(not fuites, "aucun identifiant du fichier de test dans le verdict"
      + (" -- FUITES : " + ", ".join(fuites[:8]) if fuites else ""))

print()
print("%d CONTROLE(S) EN ECHEC" % len(rates) if rates
      else "le bac a sable tient ses invariants")
sys.exit(1 if rates else 0)
