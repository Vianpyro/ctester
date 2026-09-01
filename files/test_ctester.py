#!/usr/bin/env python3
"""Auto-vérification de ctester. `python3 test_ctester.py` -- aucune dépendance.

CE QUI EST VÉRIFIÉ ICI SE TROMPE SANS PLANTER, et c'est pour ça que ce fichier
existe : le parsing d'une sortie Unity qui n'est PAS fiable, la correction d'un
quiz, l'appariement d'une sortie libre, la liste blanche d'en-têtes, le rang
dans la file, les quotas, le refus d'une clé fausse, l'impossibilité de servir
un fichier arbitraire -- et surtout le fait qu'un corrigé ne franchit jamais la
frontière vers le conteneur web. Un service cassé sur l'un de ces points
continue de répondre 200 à tout le monde.

Pas de pytest : ce fichier tourne sur le contrôleur ET sur le Dell, avec le
python3 qui s'y trouve.
"""

import json
import os
import shutil
import sys
import tempfile
import time

# Les deux chemins, parce que le déploiement sépare ce que le dépôt garde
# ensemble : runner.py vit à la racine du projet (il tourne sur l'hôte), app.py
# dans app/ (il est monté dans le conteneur). Dans le dépôt, les trois fichiers
# sont côte à côte et le second chemin ne résout rien.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

import app      # noqa: E402
import runner   # noqa: E402

UNITY_OK = """\
test_tp1.c:12:test_addition:PASS
test_tp1.c:19:test_soustraction:PASS

-----------------------
2 Tests 0 Failures 0 Ignored
OK
"""

UNITY_FAIL = """\
test_tp1.c:12:test_addition:PASS
test_tp1.c:19:test_pop_pile_vide:FAIL: Expected 42 Was 0
test_tp1.c:25:test_realloc:FAIL: Expected NULL Was 0x7ffd
test_tp1.c:31:test_ignore:IGNORE

-----------------------
4 Tests 2 Failures 1 Ignored
FAIL
"""

QUIZ = {
    "label": "TP de démonstration",
    "questions": [
        {"id": "q1", "group": "G1", "label": "23", "type": "bin8",
         "answer": "00010111"},
        {"id": "q2", "group": "G1", "label": "167", "type": "hex8",
         "answer": "A7"},
        {"id": "q3", "group": "G2", "label": "10110001 en complément à 2",
         "type": "int", "answer": "-79"},
    ],
}


# --------------------------------------------------------------------------
# Unity
# --------------------------------------------------------------------------

def test_parse_unity():
    ok = runner.parse_unity(UNITY_OK)
    assert ok == {"total": 2, "passed": 2, "ignored": 0, "failed": []}, ok

    bad = runner.parse_unity(UNITY_FAIL)
    assert bad["total"] == 4 and bad["passed"] == 1 and bad["ignored"] == 1, bad
    assert bad["failed"] == ["test_pop_pile_vide", "test_realloc"], bad

    # LE POINT LE PLUS IMPORTANT DE CETTE FONCTION : la valeur attendue par le
    # test ne doit JAMAIS ressortir. C'est ce qui empêche de reconstituer les
    # cas de test en quelques soumissions.
    assert "Expected 42" not in repr(bad), bad

    # Programme qui plante avant la fin : pas de ligne de résumé. Doit rendre
    # None, pas un faux 0/0 qui ressemblerait à une réussite.
    assert runner.parse_unity("test_tp1.c:12:test_a:PASS\nSegmentation fault") is None
    assert runner.parse_unity("") is None


def test_parse_unity_hostile():
    """La sortie est sous le contrôle de l'étudiant : elle est traitée en données."""
    forged = (
        "<script>alert(1)</script>:1:nom avec espaces et ; rm -rf /:FAIL: x\n"
        "t.c:1:" + "z" * 200 + ":FAIL: x\n"
        "1 Tests 1 Failures 0 Ignored\n"
    )
    got = runner.parse_unity(forged)
    # Aucun des deux noms n'est retenu : le premier contient des espaces et un
    # `;`, le second dépasse 64 caractères. Rien de tout ça ne ressort, donc
    # rien de tout ça n'atteint le navigateur d'un autre étudiant ni un log.
    assert got["failed"] == [], got
    assert got["total"] == 1, got

    # Un dernier résumé qui écrase les précédents : Unity écrit le sien en
    # sortant, donc c'est le dernier qui fait foi.
    two = runner.parse_unity("9 Tests 0 Failures 0 Ignored\n2 Tests 2 Failures 0 Ignored\n")
    assert two["total"] == 2 and two["passed"] == 0, two


def test_verdict_codes():
    assert runner.verdict(10, "erreur.c:3: error: ...")["status"] == "compile_error"
    assert runner.verdict(10, "x" * 99999)["gcc"] == "x" * runner.MAX_GCC_CHARS
    link = runner.verdict(11, "peu importe")
    assert link["status"] == "link_error" and "gcc" not in link, link
    assert runner.verdict(12, "")["status"] == "compile_timeout"
    assert runner.verdict(137, "")["status"] == "timeout"
    assert runner.verdict(0, UNITY_OK)["kind"] == "unity"
    assert runner.verdict(139, "Segmentation fault")["status"] == "error"


# --------------------------------------------------------------------------
# Mode quiz
# --------------------------------------------------------------------------

def test_quiz_normalisation():
    ok = runner.check_answer
    # Binaire : espaces, souligné et préfixe 0b acceptés.
    assert ok("bin8", "00010111", "00010111") == (True, "")
    assert ok("bin8", "0001 0111", "00010111")[0]
    assert ok("bin8", "0b0001_0111", "00010111")[0]
    # Bonne valeur, mauvaise longueur : faux, MAIS avec l'explication. C'est la
    # différence entre « tu n'as pas compris » et « tu n'as pas lu l'énoncé ».
    juste, indice = ok("bin8", "10111", "00010111")
    assert not juste and "8 bits" in indice, indice
    assert ok("bin8", "00010110", "00010111") == (False, "")
    assert ok("bin8", "quarante-deux", "00010111")[0] is False

    # Hexadécimal : casse, 0x, zéros de tête, suffixe h.
    for given in ("A7", "a7", "0xa7", "0XA7", "00a7", "a7h"):
        assert ok("hex8", given, "A7")[0], given
    assert ok("hex8", "A8", "A7") == (False, "")
    assert ok("hex8", "zz", "A7")[0] is False

    # Entier : espaces, +, et le signe moins Unicode du PDF de l'énoncé.
    for given in ("-79", " -79 ", "−79"):
        assert ok("int", given, "-79")[0], given
    assert ok("int", "+84", "84")[0]
    assert ok("int", "79", "-79") == (False, "")


def test_grade_quiz():
    parfait = runner.grade_quiz(QUIZ, {"q1": "0001 0111", "q2": "0xa7", "q3": "-79"})
    assert parfait == {"status": "ok", "kind": "quiz", "total": 3, "passed": 3,
                       "wrong": []}, parfait

    partiel = runner.grade_quiz(QUIZ, {"q1": "10111", "q2": "A7"})
    assert partiel["passed"] == 1 and partiel["total"] == 3, partiel
    par_id = {w["id"]: w for w in partiel["wrong"]}
    assert "8 bits" in par_id["q1"]["hint"]
    assert par_id["q3"]["hint"] == "non répondu"   # absente, pas fausse
    # Le libellé de la question remonte pour que l'étudiant sache laquelle,
    # mais la bonne réponse ne remonte jamais.
    assert par_id["q3"]["label"] == "10110001 en complément à 2"
    assert "-79" not in json.dumps(partiel, ensure_ascii=False), partiel


def test_public_quiz_hides_answers():
    """LA FRONTIÈRE. Si ce test tombe, le corrigé est servi au navigateur."""
    public = runner.public_quiz(QUIZ)
    blob = json.dumps(public, ensure_ascii=False)
    assert "answer" not in blob, blob
    for question in QUIZ["questions"]:
        assert question["answer"] not in blob, question
        assert question["label"] in blob      # les questions, elles, sont publiques
    assert set(public["questions"][0]) == {"id", "group", "label", "type"}

    # Une clé ajoutée au corrigé demain ne doit pas fuiter par défaut.
    QUIZ["questions"][0]["commentaire_prof"] = "piège classique"
    try:
        assert "piège" not in json.dumps(runner.public_quiz(QUIZ), ensure_ascii=False)
    finally:
        del QUIZ["questions"][0]["commentaire_prof"]


# --------------------------------------------------------------------------
# Mode io
# --------------------------------------------------------------------------

def test_extract_numbers():
    assert runner.extract_numbers("Surface = 15 cm2") == [15.0, 2.0]
    assert runner.extract_numbers("I = 2,50 A") == [2.5]
    assert runner.extract_numbers("rien du tout") == []
    assert runner.extract_numbers("-3.5 et +4") == [-3.5, 4.0]


def test_match_subsequence():
    tol = runner.DEFAULT_TOLERANCE
    # L'invite contient des nombres, la valeur attendue arrive après : c'est le
    # cas normal, et c'est pour lui que l'appariement est une sous-suite.
    sortie = "Entrez la longueur (max 100) : 5\nLargeur : 3\nSurface = 15 cm2"
    assert runner.match_subsequence(runner.extract_numbers(sortie), [15], tol)
    # L'ORDRE compte : 2 équipes et 0 surplus n'est pas 0 équipe et 2 surplus.
    assert runner.match_subsequence([7.0, 2.0], [7, 2], tol)
    assert not runner.match_subsequence([2.0, 7.0], [7, 2], tol)
    # Un affichage en %.2f d'une valeur au-dessus de 1 reste dans la tolérance.
    assert runner.match_subsequence([23.88], [23.88459], tol)
    # Une division entière au lieu d'une division réelle, elle, échoue.
    assert not runner.match_subsequence([2.0], [2.5], tol)
    # Zéro exact : la tolérance relative vaut zéro, d'où le plancher absolu.
    assert runner.match_subsequence([0.0], [0], tol)
    assert not runner.match_subsequence([0.01], [0], tol)


def test_check_case():
    tol = runner.DEFAULT_TOLERANCE
    case = {"contains": "laminaire", "absent": ["turbulent", "transitoire"]}
    assert runner.check_case(case, "L'ecoulement est LAMINAIRE", tol) == ""
    # Accents et casse indifférents des deux côtés.
    assert runner.check_case(case, "écoulement laminaire", tol) == ""
    assert runner.check_case(case, "ecoulement turbulent", tol) != ""
    # LE PIÈGE QUE `absent` EXISTE POUR FERMER : un programme dont l'invite
    # énumère les trois réponses passerait les trois cas sans rien calculer.
    invite = "laminaire, turbulent ou transitoire ? -> laminaire"
    assert runner.check_case(case, invite, tol) != ""


def test_in_range():
    """Intervalle plutot que valeur : pour un programme qui tire au hasard."""
    tol = runner.DEFAULT_TOLERANCE
    cinq_des = {"in_range": [1, 6], "count": 5}
    assert runner.check_case(cinq_des, "3 1 6 2 4", tol) == ""
    # AU MOINS N, ET PAS TOUS : une invite qui contient un nombre hors bornes
    # ne doit pas faire echouer un programme correct.
    assert runner.check_case(cinq_des, "Lancer 100 fois : 3 1 6 2 4", tol) == ""
    rate = runner.check_case(cinq_des, "3 1 6", tol)
    assert "3 valeurs entre 1 et 6" in rate and "au moins 5" in rate, rate
    # Des valeurs hors bornes ne comptent pas.
    assert runner.check_case(cinq_des, "0 7 8 9 10", tol) != ""

    # La moyenne d'un million de lances : bornes serrees, une seule valeur.
    moyenne = {"in_range": [3.4, 3.6]}
    assert runner.check_case(moyenne, "Moyenne : 3.4997", tol) == ""
    assert runner.check_case(moyenne, "Moyenne : 2.9", tol) != ""


def test_check_case_diagnostics():
    """Les deux échecs fréquents disent CE QUI s'est passé, pas juste « faux ».

    Le cas réel : un étudiant teste l'exercice 3 (deux scanf) contre les entrées
    de l'exercice 2 (une seule valeur). Le second scanf échoue, la variable reste
    non initialisée, la division donne inf. « la sortie ne contient pas les
    valeurs attendues » serait vrai et parfaitement inutile.
    """
    tol = runner.DEFAULT_TOLERANCE
    case = {"expect": [23.88459]}
    inf = runner.check_case(
        case, "Entrez la tension (V) : L'intensite est : inf A", tol)
    assert "inf ou nan" in inf and "autant de valeurs" in inf, inf

    aucun = runner.check_case(case, "Entrez la tension (V) : ", tol)
    assert "aucun nombre" in aucun and "bon exercice" in aucun, aucun

    # Une vraie erreur de calcul garde le message générique : c'est bien une
    # erreur de valeur, et il ne faut pas envoyer l'étudiant sur une fausse piste.
    faux = runner.check_case(case, "resultat : 42.0", tol)
    assert faux == "la sortie ne contient pas les valeurs attendues, dans l'ordre"

    # Le cas réel de l'exercice 7 : le calcul est juste, le printf oublie la
    # troisième valeur. Deux nombres affichés, trois attendus -- déduction sûre,
    # une sous-suite de 3 ne tient pas dans 2 nombres.
    partiel = runner.check_case(
        {"expect": [4, 3, 4]},
        "Entrez le nombre de pennys : On obtient ainsi 4 livre(s) et 3 shilling(s).",
        tol)
    assert "que 2 nombres" in partiel and "en attend 3" in partiel, partiel
    # Le NOMBRE de valeurs est dans l'énoncé ; leurs VALEURS ne sortent pas d'ici.
    assert "[4, 3, 4]" not in partiel

    # Assez de nombres mais les mauvais : on retombe sur le message générique,
    # parce que là c'est bien la formule qui est fausse.
    assert runner.check_case({"expect": [4, 3, 4]}, "9 puis 9 puis 9", tol) == \
        "la sortie ne contient pas les valeurs attendues, dans l'ordre"

    # Et surtout, aucun faux positif sur des mots français ordinaires.
    for mot in ("inferieur", "inférieur", "nanometre", "information", "infini"):
        assert runner.NONFINITE_RE.search(mot) is None, mot
    for mot in ("inf", "-inf", "NaN", "Inf A", "nan\n", "-nan"):
        assert runner.NONFINITE_RE.search(mot) is not None, mot


def test_split_runs_and_verdict_io():
    nonce = "abc123"
    sortie = (
        "bruit avant\n"
        + nonce + " BEGIN 01\nSurface = 15\n" + nonce + " END 01 0\n"
        + nonce + " BEGIN 02\nSurface = 9\n" + nonce + " END 02 0\n"
        + nonce + " BEGIN 03\n" + nonce + " END 03 137\n"
    )
    runs = runner.split_runs(sortie, nonce)
    assert set(runs) == {"01", "02", "03"}
    assert runs["01"] == ("Surface = 15", 0)
    assert runs["03"][1] == 137

    cases = [{"stdin": "5\n3\n", "expect": [15]},
             {"stdin": "12\n7\n", "expect": [84]},
             {"stdin": "1\n1\n", "expect": [1]}]
    got = runner.verdict_io(0, sortie, cases, nonce, runner.DEFAULT_TOLERANCE)
    assert got["kind"] == "io" and got["total"] == 3 and got["passed"] == 1, got
    par_cas = {c["case"]: c for c in got["cases"]}
    assert par_cas[2]["stdin"] == "12\n7\n"       # ses entrées : oui
    assert par_cas[2]["stdout"] == "Surface = 9"  # sa sortie : oui
    assert "84" not in json.dumps(got)            # la valeur attendue : jamais
    assert "interrompu" in par_cas[3]["reason"]

    # Un étudiant ne connaît pas le nonce, donc un faux marqueur ne crée rien.
    forge = "deadbeef BEGIN 01\n0 Failures\ndeadbeef END 01 0\n"
    vide = runner.verdict_io(0, forge, cases, nonce, runner.DEFAULT_TOLERANCE)
    assert vide["passed"] == 0, vide

    # Une erreur de compilation court-circuite tout, avec la stderr de gcc.
    rate = runner.verdict_io(10, "sub.c:3: error: ...", cases, nonce, 0.005)
    assert rate["status"] == "compile_error"
    # Le plafond du conteneur entier donne UN message, pas trois cas « pas
    # terminé » qui laisseraient croire à trois pannes distinctes.
    coupe = runner.verdict_io(137, "", cases, nonce, 0.005)
    assert coupe["status"] == "timeout" and "cases" not in coupe, coupe


# --------------------------------------------------------------------------
# Bac à sable et modes
# --------------------------------------------------------------------------

def test_detect_mode():
    tmp = tempfile.mkdtemp(prefix="ctester-")
    try:
        for name, fichier in (("quiz", "quiz.json"), ("io", "io.json"),
                              ("unity", "unity.json"), ("vide", None)):
            d = os.path.join(tmp, name)
            os.makedirs(d)
            if fichier:
                open(os.path.join(d, fichier), "w").close()
        assert runner.detect_mode(os.path.join(tmp, "quiz")) == "quiz"
        assert runner.detect_mode(os.path.join(tmp, "io")) == "io"
        assert runner.detect_mode(os.path.join(tmp, "unity")) == "unity"
        assert runner.detect_mode(os.path.join(tmp, "vide")) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_declared_files():
    """Les noms de fichiers viennent de l'énoncé, jamais de l'étudiant."""
    # Défaut : la forme des laboratoires 2 à 4, un seul programme.
    assert runner.declared_files({}) == [{"name": "submission.c", "template": ""}]

    module = runner.declared_files({"files": [
        {"name": "calendrier.h", "template": "#define VRAI 1\n"},
        {"name": "calendrier.c"},
    ]})
    assert [f["name"] for f in module] == ["calendrier.h", "calendrier.c"]
    assert module[0]["template"] == "#define VRAI 1\n"
    assert module[1]["template"] == ""

    # La configuration est écrite à la main : une faute de frappe ne doit pas
    # devenir un chemin. Ce qui n'est pas un simple nom de fichier est ignoré.
    sales = runner.declared_files({"files": [
        {"name": "../../etc/passwd"}, {"name": "a/b.c"}, {"name": "bon.c"},
        {"name": "script.sh"}, {"name": ".hidden"},
    ]})
    assert [f["name"] for f in sales] == ["bon.c"], sales
    # Et si TOUT est rejeté, on retombe sur le défaut plutôt que sur zéro fichier.
    assert runner.declared_files({"files": [{"name": "x.sh"}]})[0]["name"] \
        == "submission.c"


def test_catalogue_order_and_grouping():
    """L'ordre du menu est NUMÉRIQUE, et le regroupement sort du nom du dossier.

    Le tri texte est le piège : avec 13 TP, tp10 passerait avant tp2 et le menu
    partirait en désordre au dixième laboratoire -- invisible tant qu'il n'y en
    a que deux.
    """
    assert runner.group_of("tp2-ex3") == "TP 2"
    assert runner.group_of("tp10") == "TP 10"
    assert runner.group_of("bricolage") == "Autres"

    desordre = ["tp10-ex1", "tp2-ex3", "tp1", "tp2-ex0", "tp13-ex0", "bricolage"]
    assert sorted(desordre, key=runner.sort_key) == [
        "tp1", "tp2-ex0", "tp2-ex3", "tp10-ex1", "tp13-ex0", "bricolage"]
    # LE MÊME PIÈGE UN CRAN PLUS BAS : les exercices d'un TP sont triés entre
    # eux, et ex10 ne doit pas passer avant ex2.
    assert sorted(["ex10", "ex2", "ex1", "ex0"], key=runner.sort_key) == [
        "ex0", "ex1", "ex2", "ex10"]

    # Arborescence à DEUX NIVEAUX : un dossier par TP, un sous-dossier par
    # exercice. Un TP dont la configuration est à sa racine (le quiz) reste une
    # entrée à lui seul.
    tmp = tempfile.mkdtemp(prefix="ctester-")
    ancien = runner.TESTS
    try:
        runner.TESTS = tmp
        arbre = (("solutions", "tp1", None, None),
                 ("tp1", None, "quiz.json", "TP1 : encodage"),
                 ("tp2", "ex0", "io.json", "TP2 : ex.0 âge"),
                 ("tp2", "ex10", "io.json", "TP2 : ex.10 tardif"),
                 ("tp2", "ex2", "io.json", "TP2 : ex.2 Watt"),
                 ("tp10", "ex0", "unity.json", "TP 10 — ex.0 chaînes"))
        for tp, exercice, conf, label in arbre:
            d = os.path.join(tmp, tp) if exercice is None \
                else os.path.join(tmp, tp, exercice)
            os.makedirs(d, exist_ok=True)
            if conf is None:
                # Un corrigé de référence : du code, aucune configuration.
                with open(os.path.join(d, "calendrier.c"), "w") as fh:
                    fh.write("int f(void){return 0;}\n")
                continue
            with open(os.path.join(d, conf), "w", encoding="utf-8") as fh:
                json.dump({"label": label, "questions": [], "cases": []}, fh)
        entries = runner.catalogue()
        chemin_ex2 = runner.tp_path("tp2-ex2")
        introuvable = runner.tp_path("tp99-ex1")
        publiable = [{k: v for k, v in e.items() if k != "path"} for e in entries]
    finally:
        runner.TESTS = ancien
        shutil.rmtree(tmp, ignore_errors=True)

    assert [e["id"] for e in entries] == [
        "tp1", "tp2-ex0", "tp2-ex2", "tp2-ex10", "tp10-ex0"], entries
    # L'identifiant reste PLAT : il repart vers le navigateur et revient dans une
    # soumission, et une barre oblique dedans rouvrirait la traversée de
    # répertoire que TP_RE ferme.
    assert all(runner.TP_RE.match(e["id"]) for e in entries)
    assert chemin_ex2.endswith(os.path.join("tp2", "ex2")), chemin_ex2
    # `solutions/` NE DOIT JAMAIS DEVENIR UNE ENTRÉE. Les corrigés de référence y
    # vivent, et une entrée de catalogue est montée dans le bac à sable : ce
    # serait servir la solution au code de l'étudiant. Ils sont hors d'atteinte
    # parce qu'aucun fichier de configuration ne se trouve à ces deux niveaux --
    # ce test est là pour que ça reste vrai.
    assert not any(e["id"].startswith("solutions") for e in entries), entries
    assert introuvable is None
    # Le chemin serveur ne doit pas partir vers le conteneur web.
    assert all("path" not in e for e in publiable)
    assert [e["group"] for e in entries] == [
        "TP 1", "TP 2", "TP 2", "TP 2", "TP 10"]
    # Le second menu ne répète pas ce que le premier affiche déjà. Deux formes de
    # préfixe sont acceptées, parce que les libellés sont écrits à la main.
    assert [e["short"] for e in entries] == [
        "encodage", "ex.0 âge", "ex.2 Watt", "ex.10 tardif", "ex.0 chaînes"]
    # Et un libellé sans préfixe survit entier plutôt que d'être raboté.
    assert runner.PREFIX_RE.sub("", "Aire d'un cercle") == "Aire d'un cercle"


def test_docker_argv():
    for mode in ("unity", "io"):
        argv = runner.docker_argv("/spool/abc", "/tests/tp1", "ctester-abc", mode,
                                  "n0nce")
        for flag in ("--network", "--read-only", "--cap-drop", "--pids-limit",
                     "--security-opt", "--runtime"):
            assert flag in argv, (mode, flag)
        assert "--privileged" not in argv
        assert argv[argv.index("--user") + 1] == "65534:65534"
        # Tous les montages sont en lecture seule, sans exception : un :rw ici
        # serait une porte vers l'hôte.
        for i, item in enumerate(argv):
            if item == "-v":
                assert argv[i + 1].endswith(":ro"), argv[i + 1]

    # LE RÉPERTOIRE DE SOURCES, pas un fichier : `#include "calendrier.h"` ne
    # résout que si le .h et le .c sont montés côte à côte.
    for mode in ("unity", "io"):
        argv = runner.docker_argv("/spool/abc", "/tests/tp1", "c", mode, "n")
        assert "/spool/abc/src:/in/src:ro" in " ".join(argv), mode
        assert "submission.c" not in " ".join(argv), mode

    io_argv = runner.docker_argv("/spool/abc", "/tests/tp1", "c", "io", "n0nce")
    mounts = " ".join(io_argv)
    # EN MODE io LE RÉPERTOIRE DES TESTS N'ENTRE PAS : io.json contient les
    # valeurs attendues, seules les entrées sont extraites dans le job.
    assert "/tests/tp1" not in mounts, mounts
    assert "/spool/abc/cases:/in/cases:ro" in mounts
    assert "CTESTER_NONCE=n0nce" in io_argv

    unity_argv = runner.docker_argv("/spool/abc", "/tests/tp1", "c", "unity")
    assert "/tests/tp1:/in/tests:ro" in " ".join(unity_argv)


def test_forbidden_includes():
    code = '#include <stdio.h>\n#include  "pile.h"\n#include <unistd.h>\nint main(){}\n'
    allowed = {"stdio.h", "stdlib.h", "pile.h"}
    assert runner.forbidden_includes(code, allowed) == ["unistd.h"]
    assert runner.forbidden_includes(code, None) == []   # pas de liste = pas de contrôle
    assert runner.forbidden_includes("int main(){}", allowed) == []
    # Espaces exotiques autour du # : gcc les accepte, la liste blanche aussi.
    assert runner.forbidden_includes("  #  include <net/if.h>", allowed) == ["net/if.h"]


# --------------------------------------------------------------------------
# File, quotas, HTTP
# --------------------------------------------------------------------------

def test_queue_position():
    jobs = [("aaa", 100.0, True), ("bbb", 101.0, False), ("ccc", 102.0, False)]
    assert app.queue_position(jobs, "bbb") == 1   # les terminés ne comptent pas
    assert app.queue_position(jobs, "ccc") == 2
    assert app.queue_position(jobs, "aaa") == 0
    assert app.queue_position(jobs, "inconnu") == 0


def test_quota():
    q = app.Quota(cooldown=15, hourly=3)
    now = time.time()
    assert q.check("ip", now) == 0
    wait = q.check("ip", now + 1)
    assert 0 < wait <= 15, wait
    # Une tentative refusée ne rallonge PAS le cooldown : sinon un étudiant
    # impatient se bannirait lui-même en cliquant.
    assert q.check("ip", now + 16) == 0
    assert q.check("ip", now + 40) == 0
    assert q.check("ip", now + 60) > 0            # plafond horaire atteint
    assert q.check("autre", now + 60) == 0        # et il est bien par client
    # La fenêtre glisse : une heure plus tard, tout est oublié.
    assert q.check("ip", now + 3700) == 0


def test_client_id():
    assert app.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert app.client_id({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "1.2.3.4"
    assert app.client_id({}, "10.0.0.1") == "10.0.0.1"


def test_http_end_to_end():
    """Démarre l'API sur un port éphémère et la conduit de bout en bout.

    CE QUI EST VÉRIFIÉ ICI EST DE LA SÉCURITÉ, pas du confort : qu'une clé fausse
    soit refusée, qu'aucun chemin ne serve un fichier arbitraire, et que les
    plafonds répondent bien 429/503 au lieu d'accepter. Un refactor qui rouvre
    l'une de ces portes ne se voit pas autrement -- le service continuerait de
    marcher parfaitement.
    """
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    tmp = tempfile.mkdtemp(prefix="ctester-")
    spool, static = os.path.join(tmp, "spool"), os.path.join(tmp, "app")
    os.makedirs(spool)
    os.makedirs(os.path.join(static, "quiz"))
    with open(os.path.join(static, "tps.json"), "w", encoding="utf-8") as fh:
        json.dump([
            {"id": "tp1", "mode": "quiz", "label": "TP1", "files": []},
            {"id": "tp2-ex3", "mode": "io", "label": "TP2 ex.3",
             "files": [{"name": "submission.c", "template": ""}]},
            {"id": "tp6-ex1", "mode": "unity", "label": "TP6 ex.1",
             "files": [{"name": "calendrier.h", "template": ""},
                       {"name": "calendrier.c", "template": ""}]},
        ], fh)
    with open(os.path.join(static, "quiz", "tp1.json"), "w", encoding="utf-8") as fh:
        json.dump(runner.public_quiz(QUIZ), fh, ensure_ascii=False)
    with open(os.path.join(static, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<!doctype html>")

    app.SPOOL, app.STATIC, app.KEY, app.QUEUE_MAX = spool, static, "cle-de-test", 4
    app.Handler.quota = app.Quota(cooldown=0, hourly=100)  # testés ailleurs
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = None if payload is None else json.dumps(payload)
        conn.request(method, path, body, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def submit(**over):
        payload = {"key": "cle-de-test", "tp": "tp2-ex3",
                   "files": {"submission.c": "int main(){}"}}
        payload.update(over)
        return call("POST", "/submit", payload)

    try:
        assert call("GET", "/healthz") == (200, {"ok": True})
        assert ([t["id"] for t in call("GET", "/tps.json")[1]]
                == ["tp1", "tp2-ex3", "tp6-ex1"])
        assert call("GET", "/")[0] == 200
        # Rien d'autre n'est servi : liste blanche, pas de racine de fichiers.
        for path in ("/etc/passwd", "/../app/app.py", "/app.py", "/tps.json/../app.py"):
            assert call("GET", path)[0] == 404, path

        # Le quiz public est servi, le corrigé ne l'est nulle part.
        status, quiz = call("GET", "/quiz/tp1.json")
        assert status == 200 and "answer" not in json.dumps(quiz), quiz
        assert call("GET", "/quiz/tp2-ex3.json")[0] == 404   # pas un quiz
        assert call("GET", "/quiz/../tps.json")[0] == 404    # pas un TP

        assert submit(key="mauvaise")[0] == 403
        assert submit(key="")[0] == 403
        assert submit(tp="../etc")[0] == 400
        assert submit(tp="tp9")[0] == 400
        assert submit(files={"submission.c": "   "})[0] == 400
        assert submit(files={"submission.c": "x" * (app.MAX_CODE + 1)})[0] == 413
        assert submit(files="pas un objet")[0] == 400
        # LA LISTE BLANCHE DES NOMS. Un fichier que le TP ne déclare pas est
        # refusé -- pas ignoré en silence, sinon l'étudiant croit l'avoir soumis.
        rejet = submit(files={"submission.c": "int main(){}", "evil.c": "x"})
        assert rejet[0] == 400 and "evil.c" in rejet[1]["error"], rejet
        # Un quiz veut des réponses, pas du code.
        assert call("POST", "/submit",
                    {"key": "cle-de-test", "tp": "tp1",
                     "files": {"submission.c": "int main(){}"}})[0] == 400

        status, body = submit(files={"submission.c": "int main(void){return 0;}"})
        assert status == 200 and len(body["id"]) == 32, body
        job = os.path.join(spool, body["id"])
        with open(os.path.join(job, "job.json"), encoding="utf-8") as fh:
            assert json.load(fh)["tp"] == "tp2-ex3"
        with open(os.path.join(job, "files.json"), encoding="utf-8") as fh:
            assert json.load(fh) == {"submission.c": "int main(void){return 0;}"}

        # Un module : les deux fichiers arrivent, sous leurs noms imposés.
        status, mod = call("POST", "/submit", {
            "key": "cle-de-test", "tp": "tp6-ex1",
            "files": {"calendrier.h": "#define VRAI 1",
                      "calendrier.c": "#include \"calendrier.h\""}})
        assert status == 200, mod
        with open(os.path.join(spool, mod["id"], "files.json"), encoding="utf-8") as fh:
            depose = json.load(fh)
        assert sorted(depose) == ["calendrier.c", "calendrier.h"], depose

        # Une soumission de quiz dépose answers.json, pas submission.c : c'est
        # ce que le worker lira, et il n'y a pas de conteneur au bout.
        status, quiz_job = call("POST", "/submit",
                                {"key": "cle-de-test", "tp": "tp1",
                                 "answers": {"q1": "00010111", "q2": "", "q3": ""}})
        assert status == 200, quiz_job
        qdir = os.path.join(spool, quiz_job["id"])
        assert not os.path.exists(os.path.join(qdir, "submission.c"))
        with open(os.path.join(qdir, "answers.json"), encoding="utf-8") as fh:
            assert json.load(fh)["q1"] == "00010111"

        assert call("GET", "/r/" + body["id"])[1]["state"] in ("queued", "running")
        os.mkdir(os.path.join(job, ".lock"))
        assert call("GET", "/r/" + body["id"])[1] == {"state": "running"}
        with open(os.path.join(job, "result.json"), "w", encoding="utf-8") as fh:
            json.dump({"state": "done", "status": "ok", "kind": "io",
                       "total": 2, "passed": 2, "cases": []}, fh)
        assert call("GET", "/r/" + body["id"])[1]["status"] == "ok"
        assert call("GET", "/r/" + "f" * 32)[0] == 404      # balayé ou inexistant
        assert call("GET", "/r/pasunid")[0] == 400

        # Il reste le module et le quiz en file (2). Deux de plus atteignent
        # QUEUE_MAX=4, et le suivant est refusé.
        assert submit(files={"submission.c": "int b;"})[0] == 200
        assert submit(files={"submission.c": "int c;"})[0] == 200
        assert submit(files={"submission.c": "int d;"})[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
