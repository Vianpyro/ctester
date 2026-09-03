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
import re
import shutil
import sys
import tempfile
import time

# Les deux chemins, parce que les deux processus ne vivent pas au même endroit :
# runner.py à la racine (il tourne sur l'hôte), app.py dans app/ (il est monté
# dans le conteneur). Le dépôt a EXACTEMENT cette forme, et le clone déployé
# aussi -- ce fichier tourne donc à l'identique sur le contrôleur et sur le Dell.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

import app        # noqa: E402
import etat       # noqa: E402
import politique  # noqa: E402
import runner     # noqa: E402


def lire(chemin):
    """Le contenu d'un fichier du depot. Plusieurs controles lisent la
    source plutot que d'appeler : ce qui est verifie est justement qu'une
    regle est ECRITE la ou on la croit."""
    with open(chemin, encoding="utf-8") as fh:
        return fh.read()

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


def test_abandon_asan():
    """Le code 86 dit « débordement », et le dit differemment selon le mode.

    C'EST LA DISSYMETRIE QUI EST TESTEE, pas le message. En mode unity le
    rapport d'ASan a ete jeté par build-unity.sh (sa pile nomme la fonction de
    test), donc le verdict ne doit RIEN porter d'autre qu'un texte generique.
    En mode io il n'y a aucun test dans le conteneur, donc le rapport complet
    remonte par la stderr du cas.
    """
    unity = runner.verdict(runner.ASAN_EXIT, "peu importe ce qu'il a imprime")
    assert unity["status"] == "memory_error", unity
    assert "tableau" in unity["message"]
    # Rien de la sortie du conteneur ne doit transiter : ni champ gcc, ni echos.
    assert set(unity) == {"status", "message"}, unity
    assert "peu importe" not in str(unity)

    nonce = "n" * 32
    rapport = ("ERROR: AddressSanitizer: stack-buffer-overflow\n"
               "    #0 in remplir tableaux.c:12")
    sortie = ("%s BEGIN 01\n%s ERR 01\n%s\n%s END 01 %d\n"
              % (nonce, nonce, rapport, nonce, runner.ASAN_EXIT))
    io_res = runner.verdict_io(0, sortie, [{"stdin": "", "expect": [1]}],
                               nonce, 0.005)
    cas = io_res["cases"][0]
    assert "débordé" in cas["reason"], cas
    assert "tableaux.c:12" in cas["stderr"], cas

    # Le rapport complet passe : il fait plus long qu'une sortie de programme.
    long_rapport = ("%s BEGIN 01\n%s ERR 01\n%s\n%s END 01 %d\n"
                    % (nonce, nonce, "z" * 5000, nonce, runner.ASAN_EXIT))
    long_res = runner.verdict_io(0, long_rapport, [{"stdin": "", "expect": [1]}],
                                 nonce, 0.005)
    assert len(long_res["cases"][0]["stderr"]) == runner.MAX_STDERR


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


def test_learning_metadata_is_an_explicit_public_projection():
    conf = {"learning": {
        "skills": ["variables", "variables", "for", "bad skill", "pointers", "strings"],
        "context": "electrical", "difficulty": "foundation",
        "teacher_note": "never publish this",
    }}
    assert runner.learning_metadata(conf) == {
        "skills": ["variables", "for", "pointers", "strings"],
        "context": "electrical", "difficulty": "foundation",
    }
    assert runner.learning_metadata({"learning": {
        "skills": "variables", "context": "secret", "difficulty": "hard"
    }}) == {}


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
    assert runs["01"] == ("Surface = 15", "", 0)
    assert runs["03"][2] == 137

    cases = [{"stdin": "5\n3\n", "expect": [15]},
             {"stdin": "12\n7\n", "expect": [84]},
             {"stdin": "1\n1\n", "expect": [1]}]
    got = runner.verdict_io(0, sortie, cases, nonce, runner.DEFAULT_TOLERANCE)
    assert got["kind"] == "io" and got["total"] == 3 and got["passed"] == 1, got
    par_cas = {c["case"]: c for c in got["cases"]}
    assert par_cas[2]["stdin"] == "12\n7\n"       # ses entrées : oui
    assert par_cas[2]["stdout"] == "Surface = 9"  # sa sortie : oui
    # Les nombres que le juge a vus dans SA sortie : c'est ce qui rend
    # l'appariement en sous-suite lisible au lieu d'être une boîte noire.
    assert par_cas[2]["nombres"] == [9.0], par_cas[2]
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


def test_stderr_et_avertissements():
    """La stderr du programme et les avertissements gcc reviennent a l'etudiant.

    Les deux lui APPARTIENNENT : ce sont sa sortie d'erreur et les remarques du
    compilateur sur ses propres fichiers. Les jeter, comme on le faisait, privait
    du diagnostic le plus formateur qui soit.
    """
    nonce = "n0nce"
    sortie = (
        nonce + " WARN\n"
        "sub.c:4:9: warning: 'somme' is used uninitialized\n"
        + nonce + " ENDWARN\n"
        + nonce + " BEGIN 01\nResultat 12\n"
        + nonce + " ERR 01\nmise au point : i vaut 3\n"
        + nonce + " END 01 0\n"
    )
    avertissements, reste = runner.extraire_avertissements(sortie, nonce)
    assert "is used uninitialized" in avertissements
    # RETIRÉ du reste : un avertissement contenant `:FAIL` ou un nombre
    # tromperait les parseurs qui lisent ensuite.
    assert "warning" not in reste and "WARN" not in reste

    runs = runner.split_runs(reste, nonce)
    assert runs["01"] == ("Resultat 12", "mise au point : i vaut 3", 0)

    # Attachés a une REUSSITE : c'est la qu'ils servent le plus.
    reussite = runner.avec_avertissements({"status": "ok", "passed": 3,
                                           "total": 3}, avertissements)
    assert "uninitialized" in reussite["warnings"]
    # Mais pas a une erreur de compilation : la stderr complete est deja la.
    rate = runner.avec_avertissements(
        {"status": "compile_error", "gcc": "..."}, avertissements)
    assert "warnings" not in rate
    # Rien a signaler : pas de champ du tout, plutot qu'un bloc vide.
    assert "warnings" not in runner.avec_avertissements({"status": "ok"}, "")

    # Sans bloc, la sortie ressort intacte.
    assert runner.extraire_avertissements("abc", nonce) == ("", "abc")

    # Un faux bloc d'avertissements ne peut pas etre fabrique : le nonce est
    # tire par job et l'etudiant ne le voit jamais.
    faux = "deadbeef WARN\nmenteur\ndeadbeef ENDWARN\n"
    assert runner.extraire_avertissements(faux, nonce) == ("", faux)


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


def test_catalogue_available_from():
    """Une date future retire l'entrée du catalogue -- menu ET exécution.

    Le filtre est dans `catalogue()` justement pour que ces deux-là tombent
    ensemble : un TP retiré du menu mais que `tp_path()` résout encore serait
    ouvert à quiconque a gardé le lien de l'an dernier.
    """
    tmp = tempfile.mkdtemp(prefix="ctester-")
    ancien = runner.TESTS
    ancien_apercu = runner.APERCU
    try:
        runner.TESTS = tmp
        # Ce test mesure le FILTRE, pas l'environnement de qui le lance : un
        # CTESTER_APERCU exporté dans un shell ne doit pas faire passer la
        # suite pour la mauvaise raison.
        runner.APERCU = False
        for tp, date in (("tp1", "2000-01-01"), ("tp2", None),
                         ("tp3", "2999-01-01")):
            d = os.path.join(tmp, tp, "ex1")
            os.makedirs(d)
            conf = {"label": tp, "cases": []}
            if date is not None:
                conf["available_from"] = date
            with open(os.path.join(d, "io.json"), "w", encoding="utf-8") as fh:
                json.dump(conf, fh)
        ouverts = [e["id"] for e in runner.catalogue()]
        ferme = runner.tp_path("tp3-ex1")
    finally:
        runner.TESTS = ancien
        runner.APERCU = ancien_apercu
        shutil.rmtree(tmp, ignore_errors=True)

    # tp2 n'a PAS de date : l'absence de clé vaut « ouvert », sinon ajouter un
    # exercice en cours de session le rendrait invisible sans rien dire.
    assert ouverts == ["tp1-ex1", "tp2-ex1"], ouverts
    assert ferme is None


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


def test_publish_splits_catalogue_and_details():
    """Le catalogue publié porte le MENU ; la consigne et les gabarits, non.

    La consigne et les gabarits font les trois quarts de `tps.json` pour
    72 exercices dont un seul est ouvert : ils partent dans `tp/<id>.json`,
    chargé quand l'étudiant ouvre l'exercice.

    LES NOMS DE FICHIERS RESTENT, eux. C'est la liste blanche que
    `validate_files` oppose à une soumission ; les sortir de `tps.json`
    ouvrirait un trou, pas une optimisation.
    """
    tmp = tempfile.mkdtemp(prefix="ctester-")
    tests, app_dir = os.path.join(tmp, "tests"), os.path.join(tmp, "app")
    ancien_tests, ancien_app = runner.TESTS, runner.APP
    try:
        runner.TESTS, runner.APP = tests, app_dir
        os.makedirs(os.path.join(tests, "tp6", "ex1"))
        os.makedirs(app_dir)
        with open(os.path.join(tests, "tp6", "ex1", "unity.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"label": "TP6 : ex.1 bissextile",
                       "statement": "Écris est_bissextile.",
                       "files": [{"name": "calendrier.h",
                                  "template": "#define VRAI 1\n"},
                                 {"name": "calendrier.c", "template": ""}]}, fh)
        runner.publish_catalogue()
        with open(os.path.join(app_dir, "tps.json"), encoding="utf-8") as fh:
            publie = json.load(fh)
        with open(os.path.join(app_dir, "tp", "tp6-ex1.json"),
                  encoding="utf-8") as fh:
            detail = json.load(fh)
    finally:
        runner.TESTS, runner.APP = ancien_tests, ancien_app
        shutil.rmtree(tmp, ignore_errors=True)

    entree = publie[0]
    assert "statement" not in entree, entree
    assert [f["name"] for f in entree["files"]] == ["calendrier.h", "calendrier.c"]
    assert all("template" not in f for f in entree["files"]), entree["files"]
    # Le menu, lui, doit rester entier : c'est tout ce que la page a au départ.
    assert entree["label"] and entree["short"] and entree["group"]
    assert detail["statement"] == "Écris est_bissextile."
    assert detail["files"][0]["template"] == "#define VRAI 1\n"


def test_bonus_catalogue_is_explicit_and_always_open():
    tmp = tempfile.mkdtemp(prefix="ctester-")
    ancien = runner.TESTS
    try:
        runner.TESTS = tmp
        dossier = os.path.join(tmp, "bonus", "bonus-1")
        os.makedirs(dossier)
        with open(os.path.join(dossier, "io.json"), "w", encoding="utf-8") as fh:
            json.dump({"label": "Bonus : Clash 1", "cases": [],
                       "learning": {"skills": ["variables"],
                                    "context": "mechanical",
                                    "difficulty": "foundation"}}, fh)
        entries = runner.catalogue()
        assert [entry["id"] for entry in entries] == ["bonus-bonus-1"]
        assert entries[0]["group"] == "Bonus"
        assert runner.tp_path("bonus-bonus-1") == dossier
    finally:
        runner.TESTS = ancien
        shutil.rmtree(tmp, ignore_errors=True)


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
# Progression : politique, projections, suppression
# --------------------------------------------------------------------------

def test_politique_est_declarative():
    """Les chiffres sont dans la politique, et nulle part ailleurs.

    CE QUI EST VERIFIE ICI : qu'un pilote puisse changer un montant sans relire
    l'API. Un nombre d'equilibrage qui reapparait dans app.py rendrait la
    politique decorative, et c'est exactement ce que D-005 interdit.
    """
    assert politique.VERSION
    seuils = politique.POLITIQUE["niveaux"]
    assert seuils[0] == 0 and seuils == sorted(seuils) == list(dict.fromkeys(seuils))
    # Chaque succes a de quoi s'afficher SANS couleur ni icone : un titre et une
    # description, plus le fait dont il derive.
    ids = set()
    for succes in politique.POLITIQUE["succes"]:
        assert succes["titre"] and succes["description"]
        assert succes["sur"] and succes["seuil"] >= 1
        assert succes["id"] not in ids
        ids.add(succes["id"])
    assert set(politique.SUCCES) == ids
    # AUCUNE VALEUR D'EQUILIBRAGE NE S'ECRIT EN DUR DANS L'API. Sans ce
    # controle la politique deviendrait decorative : deux endroits ou changer un
    # montant, dont un que personne ne pense a relire.
    source = lire(os.path.join(HERE, "app", "app.py"))
    debut = source.index("# --- Progression (phase 1)")
    progression = source[debut:source.index("class Handler(", debut)]
    for montant in set(politique.POLITIQUE["xp"].values()):
        assert not re.search(r"%d" % montant, progression), montant
    assert not re.search(r"%d" % politique.plafond_quotidien(), progression)


def test_niveau_derive_du_solde():
    seuils = politique.POLITIQUE["niveaux"]
    assert politique.niveau(0)["rang"] == 1
    assert politique.niveau(-5)["rang"] == 1          # un solde ne recule pas
    assert politique.niveau(seuils[1])["rang"] == 2
    assert politique.niveau(seuils[1] - 1)["rang"] == 1
    au_bout = politique.niveau(seuils[-1] + 1000)
    assert au_bout["rang"] == len(seuils) and au_bout["prochain"] is None
    # `restant` est un nombre d'XP, pas un pourcentage : l'interface en fait une
    # phrase, et une barre sans phrase ne se lit pas a voix haute.
    assert politique.niveau(seuils[1] - 4)["restant"] == 4


def test_succes_derives_de_faits():
    assert politique.succes_atteints({}) == []
    assert politique.succes_atteints({"reussites": 1}) == ["premiere-reussite"]
    beaucoup = politique.succes_atteints({"reussites": 10, "competences": 3})
    assert set(beaucoup) == set(politique.SUCCES)
    # Un fait inconnu de l'appelant vaut zero : ajouter un critere ne doit pas
    # faire lever sur un appelant plus ancien.
    assert politique.succes_atteints({"inconnu": 99}) == []


CATALOGUE_DEMO = [
    {"id": "tp2-ex0", "learning": {"skills": ["variables"], "difficulty": "intro"}},
    {"id": "tp2-ex3", "learning": {"skills": ["variables", "arithmetic-operators"],
                                   "difficulty": "foundation"}},
    {"id": "tp6-ex1", "learning": {"skills": ["arrays-1d"]}},
    {"id": "tp1"},                                    # sans metadonnees : legal
]


def test_projection_des_competences():
    etats = [{"exercice_id": "tp2-ex0", "statut": "valide"},
             {"exercice_id": "tp2-ex3", "statut": "essaye"}]
    pratique = [{"exercice_id": "tp6-ex1", "tentatives": 2, "reussites": 0}]
    touches, reussis = app.exercise_facts(etats, pratique)
    assert touches == {"tp2-ex0", "tp2-ex3", "tp6-ex1"}
    assert reussis == {"tp2-ex0"}
    vue = app.skills_view(CATALOGUE_DEMO, touches, reussis)
    # L'ORDRE EST CELUI DU COURS, pas un tri par score : la premiere ligne est
    # la premiere competence rencontree, ce que l'etudiant reconnait.
    assert [c["id"] for c in vue] == ["variables", "arithmetic-operators", "arrays-1d"]
    assert vue[0] == {"id": "variables", "total": 2, "pratiques": 2, "reussis": 1}
    assert vue[2] == {"id": "arrays-1d", "total": 1, "pratiques": 1, "reussis": 0}


def test_recommandation_deterministe():
    etats = [{"exercice_id": "tp2-ex0", "statut": "valide"}]
    touches, reussis = app.exercise_facts(etats, [])
    # Deja pratique `variables` : on repart sur l'exercice non reussi qui la
    # reprend, pas sur le premier venu.
    assert app.recommander(CATALOGUE_DEMO, touches, reussis) == {
        "exercice_id": "tp2-ex3", "competence": "variables"}
    # Aucune competence en commun : le premier non reussi, dans l'ordre du cours.
    assert app.recommander(CATALOGUE_DEMO, set(), set()) == {
        "exercice_id": "tp2-ex0", "competence": None}
    # Tout reussi : rien a proposer, et on le dit au lieu d'inventer.
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert app.recommander(CATALOGUE_DEMO, tout, tout) is None
    assert app.recommander([], set(), set()) is None


def test_progression_ne_publie_rien_de_secret():
    faits = {"xp": 25, "succes": [{"id": "premiere-reussite",
                                   "obtenu_le": "2026-09-03", "politique": "x"},
                                  {"id": "disparu", "obtenu_le": "2026-09-03",
                                   "politique": "x"}],
             "transactions": [{"exercice_id": "tp2-ex0", "montant": 10,
                               "motif": "premiere reussite",
                               "accorde_le": "2026-09-03"}]}
    charge = app.progress_payload(
        CATALOGUE_DEMO, faits,
        [{"exercice_id": "tp2-ex0", "statut": "valide"}], [])
    assert charge["politique"] == politique.VERSION
    assert charge["xp"] == 25 and charge["niveau"]["rang"] >= 1
    assert charge["exercices"] == {"total": 4, "pratiques": 1, "reussis": 1}
    # Un succes dont la politique ne connait plus la definition ne s'affiche
    # pas -- il reste en base, il ne devient pas une ligne vide a l'ecran.
    assert [s["id"] for s in charge["succes"]] == ["premiere-reussite"]
    assert charge["succes"][0]["titre"] and charge["succes"][0]["description"]
    # RIEN DE SECRET NE TRAVERSE : ni chemin de tests, ni code soumis, ni
    # detail de verdict. Meme frontiere que publish_catalogue.
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("path", "answer", "statement", "sources", "template"):
        assert interdit not in texte, interdit


def test_suppression_couvre_toutes_les_tables():
    """`forget` efface CHAQUE table du schema, en une seule instruction.

    C'EST LA PROMESSE DU BANDEAU DE CONSENTEMENT. Ajouter une table de
    progression sans l'ajouter la laisserait des donnees derriere quelqu'un qui
    a demande leur suppression -- et personne ne s'en apercevrait, puisque plus
    rien ne les affiche.
    """
    schema = lire(os.path.join(HERE, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    assert len(tables) == 11, tables
    efface = lire(os.path.join(HERE, "app", "etat.py"))
    efface = efface[efface.index("def forget(user):"):]
    assert set(re.findall(r"DELETE FROM (\w+)", efface)) == tables
    # UNE SEULE INSTRUCTION : six `_query` en autocommit laisseraient un
    # etudiant a moitie efface si la connexion tombe au milieu.
    assert efface.count("_query(") == 1


def test_progression_degradee_sans_base():
    """Sans DSN, tout rend None/False et rien ne leve. Le juge, lui, continue."""
    assert not etat.enabled()
    assert etat.grant_first_solve("u", "tp", "e", 10, "m", "v", {}, 100) is None
    assert etat.unlock("u", ["premiere-reussite"], "e", "v") is False
    assert etat.unlock("u", [], "e", "v") is True     # rien a faire, pas un echec
    assert etat.read_progress("u") is None
    assert etat.forget("u") is False


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
    os.makedirs(os.path.join(static, "tp"))
    for tp_id in ("tp1", "tp2-ex3", "tp6-ex1"):
        with open(os.path.join(static, "tp", tp_id + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"statement": "consigne de " + tp_id, "files": []}, fh)
    with open(os.path.join(static, "index.html"), "w", encoding="utf-8") as fh:
        # Un script INLINE, comme celui du thème dans la vraie page : c'est lui
        # dont la CSP doit porter le hachage.
        fh.write('<!doctype html><script id="theme-init">var t=1;</script>'
                 '<script src="app.js"></script>')
    # `app.js` dépasse le seuil de compression : c'est lui qui éprouve la
    # négociation gzip plus bas. Les autres restent minuscules exprès.
    for nom, contenu in (("style.css", "body{}"), ("app.js", "// " + "x" * 2000),
                         ("quiz.js", "// quiz"), ("compte.js", "// compte"),
                         ("progres.js", "// progres"), ("forum.js", "// forum")):
        with open(os.path.join(static, nom), "w", encoding="utf-8") as fh:
            fh.write(contenu)
    os.makedirs(os.path.join(static, "vendor"))
    for chemin in app.VENDOR:
        with open(os.path.join(static, *chemin.split("/")), "w",
                  encoding="utf-8") as fh:
            fh.write("// " + chemin)

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

    def entetes_de(path, envoyees=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path, None, envoyees or {})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders())

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
        assert call("GET", "/style.css")[0] == 200
        assert call("GET", "/app.js")[0] == 200
        assert call("GET", "/quiz.js")[0] == 200
        assert call("GET", "/compte.js")[0] == 200
        assert call("GET", "/progres.js")[0] == 200
        assert call("GET", "/forum.js")[0] == 200
        # Les deux bibliothèques du rendu, sous leur nom versionné, et RIEN
        # d'autre sous `/vendor/` : la liste est close, pas un répertoire.
        for chemin in app.VENDOR:
            assert call("GET", "/" + chemin)[0] == 200, chemin
        # Rien d'autre n'est servi : liste blanche, pas de racine de fichiers.
        # `/app.py` reste un 404 : servir `/app.js` ne relâche pas la voisine.
        for path in ("/etc/passwd", "/../app/app.py", "/app.py",
                     "/tps.json/../app.py", "/etat.py", "/../app/etat.py",
                     "/vendor/", "/vendor/marked.umd.js",
                     "/vendor/../app.py", "/vendor/purify.min.js"):
            assert call("GET", path)[0] == 404, path

        # LA CSP EST SUR LE DOCUMENT, ET SUR LUI SEUL. Elle porte le hachage du
        # script inline de thème, et elle doit survivre au 304 : sinon elle
        # disparaîtrait dès la deuxième visite, c'est-à-dire presque toujours.
        code, tetes = entetes_de("/")
        assert code == 200 and "'sha256-" in tetes["Content-Security-Policy"]
        rejoue = entetes_de("/", {"If-None-Match": tetes["ETag"]})
        assert rejoue[0] == 304
        assert rejoue[1]["Content-Security-Policy"] \
            == tetes["Content-Security-Policy"]
        assert "Content-Security-Policy" not in entetes_de("/app.js")[1]

        # Le quiz public est servi, le corrigé ne l'est nulle part.
        status, quiz = call("GET", "/quiz/tp1.json")
        assert status == 200 and "answer" not in json.dumps(quiz), quiz
        assert call("GET", "/quiz/tp2-ex3.json")[0] == 404   # pas un quiz
        assert call("GET", "/quiz/../tps.json")[0] == 404    # pas un TP

        # Le détail d'un exercice : même porte que le quiz, donc même refus.
        assert call("GET", "/tp/tp2-ex3.json")[1]["statement"] == "consigne de tp2-ex3"
        assert call("GET", "/tp/../tps.json")[0] == 404      # pas un TP
        assert call("GET", "/tp/pasuntp.json")[0] == 404

        # REVALIDATION, PAS ABSENCE DE CACHE. `no-cache` fait repasser le
        # navigateur à chaque visite -- un correctif déployé se voit donc
        # toujours tout de suite, ce que `no-store` protégeait -- mais un
        # fichier inchangé revient vide au lieu de repartir en entier.
        for chemin in ("/", "/style.css", "/app.js", "/tps.json"):
            code, tetes = entetes_de(chemin)
            assert code == 200 and tetes["Cache-Control"] == "no-cache", chemin
            assert tetes.get("ETag"), chemin
            code, rejoue = entetes_de(chemin, {"If-None-Match": tetes["ETag"]})
            assert code == 304, (chemin, code)
            assert rejoue["ETag"] == tetes["ETag"], chemin
            # Une étiquette périmée doit bien renvoyer le fichier entier.
            assert entetes_de(chemin, {"If-None-Match": '"vieux"'})[0] == 200
        # La compression, et l'étiquette qui va avec. Deux corps différents
        # pour une même URL ne peuvent pas partager un ETag : un cache
        # intermédiaire servirait l'un en croyant valider l'autre.
        code, zippe = entetes_de("/app.js", {"Accept-Encoding": "gzip"})
        assert code == 200 and zippe["Content-Encoding"] == "gzip"
        assert zippe["Vary"] == "Accept-Encoding"
        assert zippe["ETag"] != entetes_de("/app.js")[1]["ETag"]
        assert entetes_de("/app.js", {"Accept-Encoding": "gzip",
                                      "If-None-Match": zippe["ETag"]})[0] == 304
        # L'étiquette compressée ne doit PAS valider la version en clair.
        assert entetes_de("/app.js", {"If-None-Match": zippe["ETag"]})[0] == 200

        # Un HEAD qui annoncerait une autre politique que le GET serait un piège
        # à revalidation.
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("HEAD", "/")
        tete = conn.getresponse()
        tete.read()
        conn.close()
        assert tete.getheader("Cache-Control") == "no-cache"
        assert tete.getheader("ETag") == entetes_de("/")[1]["ETag"]

        # UNE REQUÊTE REFUSÉE AVANT SON CORPS NE DOIT PAS CASSER LA CONNEXION.
        # En HTTP/1.1 elle est réutilisée : le corps laissé dans la socket
        # serait lu comme la ligne de requête suivante, et le navigateur
        # récolterait un 400 sur une requête parfaitement valide. C'est le cas
        # de tout PUT/POST refusé pour jeton expiré ou fonction désactivée.
        garde_vive = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        garde_vive.request("PUT", "/brouillon",
                           json.dumps({"tp": "tp2-ex3", "files": {}}),
                           {"Content-Type": "application/json"})
        refus = garde_vive.getresponse()
        refus.read()
        assert refus.status == 503, refus.status      # pas de persistance ici
        garde_vive.request("GET", "/healthz")
        suivante = garde_vive.getresponse()
        assert suivante.status == 200, suivante.status
        assert json.loads(suivante.read()) == {"ok": True}
        garde_vive.close()

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


def test_http_comptes():
    """Les routes de compte : sans jeton rien, avec un jeton rien d'autre que soi.

    LA BASE EST SIMULÉE, et c'est voulu : ce qui est éprouvé ici est la
    frontière, pas Postgres. Qu'un anonyme ne puisse ni lire ni écrire, que
    l'identité écrite vienne TOUJOURS du jeton et jamais du corps de la requête,
    que la liste blanche des noms de fichiers s'applique aussi au brouillon, et
    qu'un déploiement sans base n'offre simplement pas la connexion.
    """
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    tmp = tempfile.mkdtemp(prefix="ctester-comptes-")
    static = os.path.join(tmp, "app")
    os.makedirs(static)
    with open(os.path.join(static, "tps.json"), "w", encoding="utf-8") as fh:
        json.dump([
            {"id": "tp2-ex3", "mode": "io", "label": "TP2 ex.3",
             "files": [{"name": "submission.c", "template": ""}],
             "learning": {"skills": ["variables", "arithmetic-operators"],
                          "difficulty": "foundation"}},
            {"id": "tp2-ex0", "mode": "io", "label": "TP2 ex.0",
             "files": [{"name": "submission.c", "template": ""}],
             "learning": {"skills": ["variables"], "difficulty": "intro"}},
        ], fh)

    ecrit = {}          # (utilisateur, exercice) -> ce qui a été rangé

    class BaseSimulee:
        STATUSES = ("essaye", "valide")
        enabled = staticmethod(lambda: True)
        read_resume = staticmethod(lambda user, ex: ecrit.get((user, ex)))
        read_states = staticmethod(
            lambda user: [{"exercice_id": "tp2-ex3", "statut": "valide"}])
        read_practice_summary = staticmethod(lambda user: [
            {"exercice_id": ex, "tentatives": n, "reussites": solved}
            for (saved_user, ex), (n, solved) in pratique.items()
            if saved_user == user])
        @staticmethod
        def forget(user):
            for table in (ecrit, evenements, xp, obtenus):
                table.clear()
            return True

        @staticmethod
        def grant_first_solve(user, ex, event_id, amount, motif, policy,
                              payload, daily_cap):
            # LA CLE EST LE FAIT, pas l'appel : « reussite:<exercice> ». Rejouer
            # le meme verdict, ou reussir deux fois le meme exercice, retombe
            # sur la meme cle et ne cree rien.
            if (user, event_id) in evenements:
                return None
            evenements[(user, event_id)] = {"exercice_id": ex,
                                            "politique": policy,
                                            "charge": payload}
            deja = sum(t["montant"] for (who, _), t in xp.items() if who == user)
            xp[(user, event_id)] = {
                "exercice_id": ex, "montant": max(min(amount, daily_cap - deja), 0),
                "motif": motif, "accorde_le": "2026-09-03"}
            return xp[(user, event_id)]["montant"]

        @staticmethod
        def unlock(user, ids, event_id, policy):
            for succes_id in ids:
                obtenus.setdefault((user, succes_id),
                                   {"id": succes_id, "obtenu_le": "2026-09-03",
                                    "politique": policy})
            return True

        @staticmethod
        def read_progress(user):
            mien = lambda table: [v for (who, _), v in sorted(table.items())
                                  if who == user]
            return {"xp": sum(t["montant"] for t in mien(xp)),
                    "succes": mien(obtenus), "transactions": mien(xp)}

        @staticmethod
        def write_draft(user, ex, sources):
            ecrit[(user, ex)] = sources
            return True

        @staticmethod
        def write_state(user, ex, statut, sources):
            ecrit[(user, ex, statut)] = sources
            return True

        @staticmethod
        def write_practice_attempt(user, job_id, ex, result):
            key = (user, ex)
            if job_id not in jobs_pratique:
                jobs_pratique.add(job_id)
                count, solved = pratique.get(key, (0, 0))
                ok = result.get("total", 0) > 0 and result.get("passed") == result.get("total")
                pratique[key] = (count + 1, solved + int(ok))
            return True

    pratique, jobs_pratique = {}, set()
    evenements, xp, obtenus = {}, {}, {}
    spool = os.path.join(tmp, "spool")
    os.makedirs(spool)
    garde = (app.etat, app.current_user, app.STATIC, app.SPOOL, app.KEY,
             app.OIDC_ISSUER, app.OIDC_CLIENT_ID)
    app.etat = BaseSimulee
    app.STATIC = static
    app.SPOOL, app.KEY = spool, "cle-de-test"
    app.OIDC_ISSUER = "https://auth.exemple"
    app.OIDC_CLIENT_ID = "ctester"
    # Le jeton n'est pas validé ici -- il l'est par Rauthy, et ce test n'a pas de
    # Rauthy. Ce qui compte est que TOUT part de cette valeur et de rien d'autre.
    app.current_user = lambda headers: (
        "sub-alice" if headers.get("Authorization") == "Bearer bon" else None)
    app.Handler.state_quota = app.Quota(cooldown=0, hourly=1000)
    # Plusieurs soumissions de suite ici : le cooldown est eprouve ailleurs.
    app.Handler.quota = app.Quota(cooldown=0, hourly=1000)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, payload=None, jeton=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        entetes = {"Content-Type": "application/json"}
        if jeton:
            entetes["Authorization"] = "Bearer " + jeton
        conn.request(method, path, None if payload is None else json.dumps(payload),
                     entetes)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    try:
        assert call("GET", "/oidc.json")[1]["client_id"] == "ctester"

        # SANS JETON, AUCUNE PORTE. Ni lecture, ni écriture, ni suppression.
        assert call("GET", "/etats")[0] == 401
        assert call("GET", "/brouillon?ex=tp2-ex3")[0] == 401
        assert call("PUT", "/brouillon", {"tp": "tp2-ex3", "files": {}})[0] == 401
        assert call("DELETE", "/moi")[0] == 401
        assert call("PUT", "/brouillon", {"tp": "tp2-ex3", "files": {}},
                    jeton="inventé")[0] == 401

        # Avec un jeton : on écrit, et on relit ce qu'on a écrit.
        code = {"submission.c": "int main(void){return 0;}"}
        assert call("PUT", "/brouillon", {"tp": "tp2-ex3", "files": code},
                    jeton="bon")[0] == 200
        assert ecrit[("sub-alice", "tp2-ex3")] == code, ecrit
        assert call("GET", "/brouillon?ex=tp2-ex3", jeton="bon")[1]["sources"] == code

        # L'IDENTITÉ NE VIENT PAS DU CORPS. Un champ `utilisateur` envoyé par le
        # client est ignoré : sans ça, écrire chez le voisin serait une ligne de
        # JSON. C'est LA vérification de sécurité de cette route.
        ecrit.clear()
        assert call("PUT", "/brouillon",
                    {"tp": "tp2-ex3", "utilisateur": "sub-bob", "files": code},
                    jeton="bon")[0] == 200
        assert list(ecrit) == [("sub-alice", "tp2-ex3")], ecrit

        # La liste blanche des noms vaut aussi pour un brouillon.
        refus = call("PUT", "/brouillon",
                     {"tp": "tp2-ex3", "files": {"evil.c": "x"}}, jeton="bon")
        assert refus[0] == 400 and "evil.c" in refus[1]["error"], refus
        assert call("PUT", "/brouillon", {"tp": "tp9", "files": {}},
                    jeton="bon")[0] == 400
        assert call("GET", "/brouillon?ex=../tps", jeton="bon")[0] == 400
        assert call("PUT", "/brouillon",
                    {"tp": "tp2-ex3",
                     "files": {"submission.c": "x" * (app.MAX_CODE + 1)}},
                    jeton="bon")[0] == 413

        # Un statut inventé est refusé ici ET par la contrainte du schéma.
        assert call("PUT", "/etat",
                    {"tp": "tp2-ex3", "statut": "parfait", "files": code},
                    jeton="bon")[0] == 400
        assert call("PUT", "/etat",
                    {"tp": "tp2-ex3", "statut": "valide", "files": code},
                    jeton="bon")[0] == 200
        assert ("sub-alice", "tp2-ex3", "valide") in ecrit, ecrit

        assert call("GET", "/etats", jeton="bon")[1]["etats"][0]["statut"] == "valide"

        # Une tentative vient d'un job attribue au compte par le serveur, pas
        # du statut que le navigateur voudrait declarer. La lecture du verdict
        # cree le fait une fois; les polls suivants restent idempotents.
        status, submitted = call("POST", "/submit", {
            "key": "cle-de-test", "tp": "tp2-ex3", "files": code}, jeton="bon")
        assert status == 200, submitted
        job = os.path.join(spool, submitted["id"])
        with open(os.path.join(job, "job.json"), encoding="utf-8") as fh:
            assert json.load(fh) == {"tp": "tp2-ex3", "owner": "sub-alice"}
        with open(os.path.join(job, "result.json"), "w", encoding="utf-8") as fh:
            json.dump({"state": "done", "status": "ok", "total": 2, "passed": 2}, fh)
        assert call("GET", "/r/" + submitted["id"], jeton="bon")[0] == 200
        assert call("GET", "/r/" + submitted["id"], jeton="bon")[0] == 200
        # Le resultat garde le contrat historique du juge : l'identifiant de
        # job aleatoire suffit pour le sondage, meme si l'OIDC devient
        # momentanement indisponible apres la soumission. L'attribution reste
        # cote serveur, d'apres `owner` ecrit lors du POST authentifie.
        assert call("GET", "/r/" + submitted["id"])[0] == 200
        assert call("GET", "/pratique", jeton="bon")[1]["pratique"] == [
            {"exercice_id": "tp2-ex3", "tentatives": 1, "reussites": 1}]
        assert ("sub-alice", "tp2-ex3", "valide") in ecrit, ecrit
        # --- PROGRESSION : la valeur est produite par le SERVEUR ------------
        # Meme porte que tout le reste : sans jeton, rien.
        assert call("GET", "/progres")[0] == 401

        def verdict(code, resultat):
            """Depose un verdict de worker, comme le fait runner.py."""
            with open(os.path.join(spool, code, "result.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(resultat, fh)

        progres = call("GET", "/progres", jeton="bon")[1]
        # C'est la POLITIQUE qui dit combien vaut une reussite, pas l'API :
        # tp2-ex3 s'annonce `foundation` dans son catalogue.
        vaut = politique.POLITIQUE["xp"]["foundation"]
        assert progres["politique"] == politique.VERSION
        assert progres["xp"] == vaut, progres
        assert progres["niveau"]["rang"] == politique.niveau(vaut)["rang"]
        assert {s["id"] for s in progres["succes"]} == {"premiere-reussite",
                                                        "premiere-competence"}
        assert all(s["titre"] and s["description"] and s["obtenu_le"]
                   for s in progres["succes"])
        competences = {c["id"]: c for c in progres["competences"]}
        assert competences["variables"] == {"id": "variables", "total": 2,
                                            "pratiques": 1, "reussis": 1}
        # La recommandation est deterministe : le seul exercice non reussi, et
        # il reprend une competence deja pratiquee.
        assert progres["suivant"] == {"exercice_id": "tp2-ex0",
                                      "competence": "variables"}
        assert progres["exercices"] == {"total": 2, "pratiques": 1, "reussis": 1}

        # SONDER DEUX FOIS NE PAIE PAS DEUX FOIS. Le navigateur repasse sur
        # /r/<id> a chaque rafraichissement, et un worker relance rejoue le
        # meme verdict : les deux retombent sur le meme identifiant d'evenement.
        assert call("GET", "/r/" + submitted["id"], jeton="bon")[0] == 200
        assert call("GET", "/progres", jeton="bon")[1]["xp"] == vaut

        # REFAIRE LE MEME EXERCICE NON PLUS -- nouveau job, nouveau verdict
        # juste, zero XP de plus. C'est ce qui rend la pratique illimitee sans
        # la rendre farmable : on peut recommencer autant qu'on veut.
        encore = call("POST", "/submit", {
            "key": "cle-de-test", "tp": "tp2-ex3", "files": code}, jeton="bon")[1]
        verdict(encore["id"], {"state": "done", "status": "ok",
                               "total": 2, "passed": 2})
        assert call("GET", "/r/" + encore["id"], jeton="bon")[0] == 200
        assert call("GET", "/progres", jeton="bon")[1]["xp"] == vaut

        # UN ECHEC NE RAPPORTE RIEN. La pratique garde sa valeur pedagogique --
        # la tentative est enregistree, l'exercice compte comme pratique -- mais
        # elle ne produit aucune valeur de jeu.
        rate = call("POST", "/submit", {
            "key": "cle-de-test", "tp": "tp2-ex0", "files": code}, jeton="bon")[1]
        verdict(rate["id"], {"state": "done", "status": "ok",
                             "total": 2, "passed": 1})
        assert call("GET", "/r/" + rate["id"], jeton="bon")[0] == 200
        apres = call("GET", "/progres", jeton="bon")[1]
        assert apres["xp"] == vaut, apres
        assert len(apres["transactions"]) == 1
        assert apres["exercices"]["pratiques"] == 2, apres

        # LE PLAFOND QUOTIDIEN NE BLOQUE PAS LA PRATIQUE, il cesse seulement de
        # payer. Le fait est quand meme enregistre -- a zero -- pour qu'il se
        # relise : cacher l'attribution ferait croire a une perte.
        plafond = politique.POLITIQUE["plafond_quotidien"]
        politique.POLITIQUE["plafond_quotidien"] = 0
        try:
            plein = call("POST", "/submit", {
                "key": "cle-de-test", "tp": "tp2-ex0", "files": code},
                jeton="bon")[1]
            verdict(plein["id"], {"state": "done", "status": "ok",
                                  "total": 2, "passed": 2})
            assert call("GET", "/r/" + plein["id"], jeton="bon")[0] == 200
        finally:
            politique.POLITIQUE["plafond_quotidien"] = plafond
        plafonne = call("GET", "/progres", jeton="bon")[1]
        assert plafonne["xp"] == vaut, plafonne
        assert len(plafonne["transactions"]) == 2, plafonne["transactions"]
        assert min(t["montant"] for t in plafonne["transactions"]) == 0

        # LA BASE MUETTE SE DIT, et n'invente pas un solde a zero -- ce serait
        # annoncer a quelqu'un que son travail a disparu. Le juge, lui, continue.
        muette = BaseSimulee.read_progress
        BaseSimulee.read_progress = staticmethod(lambda user: None)
        assert call("GET", "/progres", jeton="bon")[0] == 503
        assert call("POST", "/submit", {"key": "cle-de-test", "tp": "tp2-ex3",
                                        "files": code})[0] == 200
        BaseSimulee.read_progress = muette

        # SUPPRIMER, C'EST TOUT SUPPRIMER : les brouillons, l'etat, les
        # tentatives, le journal, les XP et les succes. Une table oubliee ici
        # laisserait des donnees derriere quelqu'un qui a demande leur retrait.
        assert call("DELETE", "/moi", jeton="bon")[0] == 200 and not ecrit
        vide = call("GET", "/progres", jeton="bon")[1]
        assert vide["xp"] == 0 and vide["succes"] == [] and not vide["transactions"]

        # SANS BASE, LA CONNEXION N'EST MÊME PAS PROPOSÉE, et toutes les routes
        # de compte se ferment : c'est l'état d'un déploiement qui n'a pas changé.
        BaseSimulee.enabled = staticmethod(lambda: False)
        assert call("GET", "/oidc.json")[1] == {}
        assert call("GET", "/etats", jeton="bon")[0] == 503
        assert call("GET", "/progres", jeton="bon")[0] == 503
        assert call("PUT", "/brouillon", {"tp": "tp2-ex3", "files": code},
                    jeton="bon")[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()
        (app.etat, app.current_user, app.STATIC, app.SPOOL, app.KEY,
         app.OIDC_ISSUER, app.OIDC_CLIENT_ID) = garde
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Forum d'entraide (MVP)
# --------------------------------------------------------------------------

def test_forum_eteint_par_defaut():
    """SANS MODERATEUR CONFIGURE, LE FORUM N'EXISTE PAS. C'est le reglage sur.

    Un forum sans personne pour le moderer est un canal de partage de solutions
    avec une charte dessus. Le defaut doit donc etre « eteint », et il l'est par
    l'ABSENCE d'une variable -- pas par un booleen qu'on pourrait oublier
    d'ecrire.
    """
    garde = (app.OIDC_ISSUER, app.OIDC_CLIENT_ID, app.FORUM_MODERATORS, app.etat)
    try:
        app.OIDC_ISSUER = "https://auth.exemple"
        app.OIDC_CLIENT_ID = "ctester"
        app.etat = type("Base", (), {"enabled": staticmethod(lambda: True)})
        app.FORUM_MODERATORS = frozenset()
        assert app.oidc_enabled() and not app.forum_enabled()
        app.FORUM_MODERATORS = frozenset({"sub-mod"})
        assert app.forum_enabled()
        assert app.is_moderator("sub-mod") and not app.is_moderator("sub-alice")
        # Un `sub` vide n'est pas un moderateur, meme si la liste en contient un
        # vide par accident de configuration.
        assert not app.is_moderator("") and not app.is_moderator(None)
        # La CONNEXION reste la premiere condition : un forum sans compte n'a
        # personne a qui attribuer un message ni a qui offrir la suppression.
        app.OIDC_ISSUER = ""
        assert not app.forum_enabled()
    finally:
        (app.OIDC_ISSUER, app.OIDC_CLIENT_ID, app.FORUM_MODERATORS,
         app.etat) = garde


def test_forum_texte_borne_et_stocke_la_source():
    """Ce qu'un message a le droit d'etre : court, non vide, et SA SOURCE.

    LE SERVEUR NE REND RIEN ET N'ASSAINIT RIEN. Ce qui est stocke est le
    Markdown tel qu'il a ete tape -- balises comprises, sous leur forme source.
    Le rendu et l'assainissement se font a CHAQUE affichage, dans `forum.js` :
    assainir a l'ecriture seulement laisserait les messages deja en base hors de
    portee d'une regle resserree ensuite.
    """
    assert app.forum_texte("  Pourquoi mon while ne s'arrete pas ?  ") == (
        "Pourquoi mon while ne s'arrete pas ?", None)
    assert app.forum_texte("")[0] is None
    assert app.forum_texte("   \n  ")[0] is None
    assert app.forum_texte(None)[0] is None
    assert app.forum_texte(42)[0] is None
    assert app.forum_texte("x" * (app.FORUM_MAX_CHARS + 1))[0] is None
    assert app.forum_texte("x" * app.FORUM_MAX_CHARS)[0] is not None
    # LA SOURCE PASSE INTACTE, y compris ce qui ressemble a du HTML : c'est le
    # rendu qui l'echappe, et il le fera a chaque affichage.
    hostile = "<script>alert(1)</script> et **gras**"
    assert app.forum_texte(hostile)[0] == hostile
    assert app.forum_texte("[doc](https://exemple.test)")[0] \
        == "[doc](https://exemple.test)"
    # Les caracteres de controle partent : ils ne servent a rien dans du
    # Markdown et compliquent une relecture humaine pour rien.
    assert app.forum_texte("a\x00b\x07c")[0] == "abc"
    assert app.forum_texte("ligne 1\r\nligne 2")[0] == "ligne 1\nligne 2"


def test_forum_bibliotheques_epinglees():
    """Les deux bibliotheques du rendu sont VERSIONNEES, presentes, et servies.

    CE CONTROLE EXISTE PARCE QU'UN ASSAINISSEUR ABSENT NE SE VOIT PAS. La page
    retombe alors sur du texte brut -- c'est le bon comportement -- et personne
    ne remarque que le rendu a disparu. Ici, un nom qui ne correspond plus entre
    `VENDOR`, `forum.js` et le disque fait echouer la suite tout de suite.
    """
    assert len(app.VENDOR) == 2, app.VENDOR
    source = lire(os.path.join(HERE, "app", "forum.js"))
    for chemin in app.VENDOR:
        sur_disque = os.path.join(HERE, "app", *chemin.split("/"))
        assert os.path.exists(sur_disque), chemin
        assert '"' + chemin + '"' in source, chemin
        # Le nom PORTE la version : c'est ce qui rend l'epinglage impossible a
        # perdre, et une montee de version impossible a faire par accident.
        assert re.search(r"-\d+\.\d+\.\d+[.-]", chemin), chemin
    # `/vendor/` N'EST PAS UN REPERTOIRE OUVERT : la liste est close, comme
    # celle des `.js` de la page.
    assert "vendor/" in app.VENDOR[0] and "vendor/" in app.VENDOR[1]


def test_csp_du_document():
    """La CSP porte le hachage du script de theme, et rien d'autre n'est inline.

    ELLE N'EST PAS LA DEFENSE PRINCIPALE -- l'assainisseur et `textContent` le
    sont -- mais elle doit etre juste : une CSP qui oublie le script inline
    casse le theme, et une CSP qui oublie l'emetteur OIDC casse la connexion,
    toutes deux en silence.
    """
    page = lire(os.path.join(HERE, "app", "index.html")).encode()
    politique = app.csp(page, "https://auth.exemple/auth/v1")
    assert "default-src 'none'" in politique
    assert "'sha256-" in politique, politique
    assert "script-src 'self' 'sha256-" in politique
    # UN SEUL script inline dans la page : celui du theme. Un second passerait
    # ici en silence, d'ou le decompte.
    assert politique.count("'sha256-") == 1, politique
    # L'EMETTEUR OIDC EST DANS connect-src, en ORIGINE seulement : `compte.js`
    # y va chercher la decouverte puis le jeton.
    assert "connect-src 'self' https://auth.exemple" in politique
    assert "/auth/v1" not in politique, politique
    for interdit in ("frame-ancestors 'none'", "base-uri 'none'",
                     "form-action 'none'", "img-src 'self'"):
        assert interdit in politique, interdit
    # `style-src` garde 'unsafe-inline' : la page pose des attributs `style`
    # calcules (largeur de jauge, rang d'une coche). C'est un choix, il est
    # ecrit, et il ne doit pas deraper vers script-src.
    assert "style-src 'self' 'unsafe-inline'" in politique
    assert "unsafe-inline" not in politique.split("style-src")[0], politique
    assert "unsafe-eval" not in politique
    # Sans emetteur https, pas d'origine tierce du tout.
    assert app.csp(page, "").split("connect-src ")[1].startswith("'self';")


def test_forum_vue_ne_laisse_sortir_aucun_sub():
    """« Vous », « Participant », « Equipe du cours » -- et RIEN d'autre.

    CE CONTROLE EST LA FRONTIERE DE CONFIDENTIALITE DU FORUM. Un `sub` qui
    traverse, meme dans un champ que personne n'affiche, rend deux messages
    recollables au meme etudiant -- ce que ni un pseudonyme ni un identifiant
    stable ne doivent permettre en phase MVP.
    """
    garde = app.FORUM_MODERATORS
    try:
        app.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "utilisateur": "sub-alice", "texte": "moi",
                "masque": False, "cree_le": "2026-09-03 10:00"},
               {"id": "b" * 32, "utilisateur": "sub-bob", "texte": "lui",
                "masque": False, "cree_le": "2026-09-03 10:01"},
               {"id": "c" * 32, "utilisateur": "sub-mod", "texte": "eux",
                "masque": False, "cree_le": "2026-09-03 10:02"},
               {"id": "d" * 32, "utilisateur": "sub-bob", "texte": "cache",
                "masque": True, "cree_le": "2026-09-03 10:03"}]
        vu = app.forum_vue(fil, "sub-alice", False)
        assert [m["auteur"] for m in vu] == [
            "Vous", "Participant", "Équipe du cours"], vu
        assert [m["mien"] for m in vu] == [True, False, False]
        # UN MESSAGE MASQUE N'EXISTE PAS pour un etudiant ordinaire.
        assert len(vu) == 3
        texte = json.dumps(vu, ensure_ascii=False)
        for interdit in ("sub-alice", "sub-bob", "sub-mod", "utilisateur"):
            assert interdit not in texte, interdit
        # Un moderateur, LUI, voit le masque -- sinon il ne pourrait pas le
        # retablir -- et pas davantage d'identite pour autant.
        vu_mod = app.forum_vue(fil, "sub-mod", True)
        assert len(vu_mod) == 4 and vu_mod[3]["masque"] is True
        assert vu_mod[2]["auteur"] == "Vous"      # son propre message
        assert "sub-bob" not in json.dumps(vu_mod, ensure_ascii=False)
    finally:
        app.FORUM_MODERATORS = garde


def test_forum_identite_bornes_et_visibilite():
    """Le nom choisi et le numero de groupe : ce qui est accepte, ce qui sort.

    LA REGLE TIENT EN UNE LIGNE : rien ne s'affiche que son porteur n'ait
    rendu visible -- sauf le numero de groupe pour l'equipe du cours, en tout
    temps, et c'est ecrit dans le formulaire.
    """
    assert app.forum_pseudo(None) == (None, None)
    assert app.forum_pseudo("   ") == (None, None)
    assert app.forum_pseudo("  Lea   B ") == ("Lea B", None)
    assert app.forum_pseudo("Lea" + chr(10) + "B")[0] == "Lea B"   # une ligne
    for reserve in ("Vous", "participant", "Équipe du cours", "Anonyme"):
        assert app.forum_pseudo(reserve)[0] is None, reserve
    assert app.forum_pseudo("x" * (app.FORUM_PSEUDO_MAX + 1))[0] is None
    # La session n'ouvre que certains groupes (CTESTER_FORUM_GROUPES) ; hors
    # liste, rien ne passe -- pas même un numero valide 1..99.
    garde_g = app.FORUM_GROUPES
    try:
        app.FORUM_GROUPES = (4, 6)
        assert app.forum_groupe("04") == (4, None)
        for mauvais in (0, 100, -1, "sept", True, 7):
            assert app.forum_groupe(mauvais)[0] is None, mauvais
        app.FORUM_GROUPES = ()
        assert app.forum_groupe("07") == (7, None)
        for mauvais in (0, 100, -1, "sept", True):
            assert app.forum_groupe(mauvais)[0] is None, mauvais
    finally:
        app.FORUM_GROUPES = garde_g

    garde = app.FORUM_MODERATORS
    try:
        app.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "utilisateur": "sub-bob", "texte": "x",
                "masque": False, "cree_le": "2026-09-03T10:00Z"}]
        cache = {"sub-bob": {"pseudo": "Bob", "groupe": 7,
                             "pseudo_public": False, "groupe_public": False}}
        vu = app.forum_vue(fil, "sub-alice", False, cache)[0]
        assert vu["auteur"] == "Participant" and vu["groupe"] is None
        assert vu["nom_signalable"] is False
        # Le modérateur voit le groupe SANS que le nom devienne public pour
        # autant : deux cases, deux effets.
        vu_mod = app.forum_vue(fil, "sub-mod", True, cache)[0]
        assert vu_mod["auteur"] == "Participant" and vu_mod["groupe"] == 7
        montre = {"sub-bob": dict(cache["sub-bob"], pseudo_public=True)}
        vu2 = app.forum_vue(fil, "sub-alice", False, montre)[0]
        assert vu2["auteur"] == "Bob" and vu2["nom_signalable"] is True
        # Son propre nom reste « Vous » : on ne se signale pas soi-meme.
        a_moi = app.forum_vue(fil, "sub-bob", False, montre)[0]
        assert a_moi["auteur"] == "Vous" and a_moi["nom_signalable"] is False
        assert "sub-bob" not in json.dumps(
            [vu, vu_mod, vu2, a_moi], ensure_ascii=False)
    finally:
        app.FORUM_MODERATORS = garde


def test_http_forum():
    """Le forum de bout en bout : authentification, role, bornes, isolement.

    LA BASE EST SIMULEE, comme dans `test_http_comptes` : ce qui est eprouve ici
    est la FRONTIERE -- qui a le droit de quoi, ce qui traverse, et ce qui est
    refuse. Le SQL, lui, est eprouve par `test_postgres.py`, seul endroit ou il
    y a un vrai PostgreSQL pour repondre.
    """
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    tmp = tempfile.mkdtemp(prefix="ctester-forum-")
    static = os.path.join(tmp, "app")
    os.makedirs(static)
    with open(os.path.join(static, "tps.json"), "w", encoding="utf-8") as fh:
        json.dump([
            {"id": "tp2-ex3", "mode": "io", "label": "TP2 ex.3", "files": []},
            {"id": "tp2-ex0", "mode": "io", "label": "TP2 ex.0", "files": []},
        ], fh)

    messages, signales, journal = [], {}, []
    profils, noms_signales = {}, {}

    class BaseSimulee:
        enabled = staticmethod(lambda: True)

        @staticmethod
        def forum_fil(exercise_id, limite):
            return [dict(m) for m in messages
                    if m["exercice_id"] == exercise_id][:limite]

        @staticmethod
        def forum_publier(message_id, exercise_id, user, texte):
            messages.append({"id": message_id, "exercice_id": exercise_id,
                             "utilisateur": user, "texte": texte,
                             "masque": False, "cree_le": "2026-09-03 10:00"})
            return True

        @staticmethod
        def forum_supprimer(message_id, user):
            for m in list(messages):
                if m["id"] == message_id and m["utilisateur"] == user:
                    messages.remove(m)
                    return [(message_id,)]
            return []

        @staticmethod
        def forum_signaler(message_id, user):
            if not any(m["id"] == message_id for m in messages):
                return []                      # un identifiant invente
            if (message_id, user) in signales:
                return []                      # deja signale par lui
            signales[(message_id, user)] = True
            return [(message_id,)]

        @staticmethod
        def forum_signalements(limite):
            combien = {}
            for message_id, _who in signales:
                combien[message_id] = combien.get(message_id, 0) + 1
            return [{"id": m["id"], "exercice_id": m["exercice_id"],
                     "texte": m["texte"], "masque": m["masque"],
                     "cree_le": m["cree_le"],
                     "signalements": combien[m["id"]]}
                    for m in messages if m["id"] in combien][:limite]

        @staticmethod
        def forum_moderer(action_id, message_id, moderator, action):
            for m in messages:
                if m["id"] == message_id:
                    m["masque"] = action == "masquer"
                    journal.append((action_id, message_id, moderator, action))
                    return [(message_id,)]
            return []

        @staticmethod
        def forum_profils(utilisateurs):
            return {u: profils[u] for u in set(utilisateurs) if u in profils}

        @staticmethod
        def forum_profil(user):
            return profils.get(user, {"pseudo": None, "groupe": None,
                                      "pseudo_public": False,
                                      "groupe_public": False})

        @staticmethod
        def forum_profil_ecrire(profil_id, user, pseudo, groupe, pseudo_public,
                                groupe_public, par_moderateur=False):
            profils[user] = {"pseudo": pseudo, "groupe": groupe,
                             "pseudo_public": bool(pseudo_public),
                             "groupe_public": bool(groupe_public)}
            return True

        @staticmethod
        def forum_auteur(message_id):
            for m in messages:
                if m["id"] == message_id:
                    return m["utilisateur"]
            return None

        @staticmethod
        def forum_nom_signaler(message_id, user):
            if not any(m["id"] == message_id for m in messages):
                return []
            if (message_id, user) in noms_signales:
                return []
            noms_signales[(message_id, user)] = True
            return [(message_id,)]

        @staticmethod
        def forum_noms_signales(limite):
            combien = {}
            for message_id, _who in noms_signales:
                combien[message_id] = combien.get(message_id, 0) + 1
            sortie = []
            for m in messages:
                if m["id"] not in combien:
                    continue
                profil = profils.get(m["utilisateur"], {})
                sortie.append({"id": m["id"], "utilisateur": m["utilisateur"],
                               "pseudo": profil.get("pseudo"),
                               "groupe": profil.get("groupe"),
                               "cree_le": m["cree_le"],
                               "signalements": combien[m["id"]]})
            return sortie[:limite]

        @staticmethod
        def forget(user):
            for m in [m for m in messages if m["utilisateur"] == user]:
                messages.remove(m)
            for cle in [k for k in signales if k[1] == user]:
                del signales[cle]
            for cle in [k for k in noms_signales if k[1] == user]:
                del noms_signales[cle]
            profils.pop(user, None)
            journal[:] = [a for a in journal if a[2] != user]
            return True

    JETONS = {"alice": "sub-alice", "bob": "sub-bob", "mod": "sub-mod"}
    garde = (app.etat, app.current_user, app.STATIC, app.OIDC_ISSUER,
             app.OIDC_CLIENT_ID, app.FORUM_MODERATORS,
             app.Handler.forum_quota)
    app.etat = BaseSimulee
    app.STATIC = static
    app.OIDC_ISSUER = "https://auth.exemple"
    app.OIDC_CLIENT_ID = "ctester"
    app.FORUM_MODERATORS = frozenset()
    app.Handler.forum_quota = app.Quota(cooldown=0, hourly=1000)
    app.current_user = lambda entetes: JETONS.get(
        entetes.get("Authorization", "")[7:])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, payload=None, jeton=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        entetes = {"Content-Type": "application/json"}
        if jeton:
            entetes["Authorization"] = "Bearer " + jeton
        conn.request(method, path,
                     None if payload is None else json.dumps(payload), entetes)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def fil(jeton, ex="tp2-ex3"):
        return call("GET", "/forum?ex=" + ex, jeton=jeton)

    try:
        # --- ETEINT : toutes les routes le disent, et rien d'autre ne bouge --
        assert call("GET", "/oidc.json")[1]["forum"] is False
        for methode, chemin, corps in (
                ("GET", "/forum?ex=tp2-ex3", None),
                ("POST", "/forum", {"tp": "tp2-ex3", "texte": "salut"}),
                ("DELETE", "/forum?id=" + "a" * 32, None),
                ("POST", "/forum/signalement", {"id": "a" * 32}),
                ("GET", "/forum/moderation", None),
                ("POST", "/forum/moderation",
                 {"id": "a" * 32, "action": "masquer"}),
                ("GET", "/forum/profil", None),
                ("POST", "/forum/profil", {"pseudo": "Léa"})):
            code, quoi = call(methode, chemin, corps, jeton="mod")
            assert code == 503 and "activ" in quoi["error"], (chemin, code)

        app.FORUM_MODERATORS = frozenset({"sub-mod"})
        assert call("GET", "/oidc.json")[1]["forum"] is True

        # --- SANS JETON, AUCUNE PORTE ---------------------------------------
        assert fil(None)[0] == 401
        assert call("POST", "/forum", {"tp": "tp2-ex3", "texte": "x"})[0] == 401
        assert call("POST", "/forum/signalement", {"id": "a" * 32})[0] == 401
        assert call("GET", "/forum/moderation")[0] == 401
        assert call("GET", "/forum/profil")[0] == 401
        assert call("POST", "/forum/profil", {"pseudo": "Léa"})[0] == 401
        assert call("DELETE", "/forum?id=" + "a" * 32)[0] == 401

        # --- L'EXERCICE PASSE PAR find_tp, TOUJOURS -------------------------
        assert fil("alice", "pasuntp")[0] == 400
        assert fil("alice", "../tps")[0] == 400
        assert call("POST", "/forum",
                    {"tp": "pasuntp", "texte": "salut"}, jeton="alice")[0] == 400

        # --- LES BORNES DU TEXTE --------------------------------------------
        for mauvais in ("", "   ", "x" * (app.FORUM_MAX_CHARS + 1)):
            assert call("POST", "/forum", {"tp": "tp2-ex3", "texte": mauvais},
                        jeton="alice")[0] == 400, mauvais
        # LE HTML EST ACCEPTE PAR L'API ET STOCKE TEL QUEL : c'est le rendu qui
        # l'echappe, a chaque affichage. Un serveur qui refuserait ici donnerait
        # l'illusion d'une protection dont le rendu n'aurait plus besoin.
        assert call("POST", "/forum",
                    {"tp": "tp2-ex3", "texte": "<b>x</b>"},
                    jeton="bob")[0] == 200
        assert messages[-1]["texte"] == "<b>x</b>", messages[-1]
        messages.pop()

        # --- PUBLIER, PUIS LIRE ---------------------------------------------
        assert call("POST", "/forum",
                    {"tp": "tp2-ex3", "texte": "  Pourquoi ma boucle tourne ?  "},
                    jeton="alice")[0] == 200
        vu = fil("alice")[1]
        assert vu["exercice_id"] == "tp2-ex3" and vu["moderateur"] is False
        assert vu["max"] == app.FORUM_MAX_CHARS
        assert len(vu["messages"]) == 1
        mien = vu["messages"][0]
        assert mien["auteur"] == "Vous" and mien["mien"] is True
        assert mien["texte"] == "Pourquoi ma boucle tourne ?"
        assert app.MSG_RE.match(mien["id"]), mien["id"]

        # AUCUN `sub` NE TRAVERSE, ni ici ni ailleurs.
        assert "sub-alice" not in json.dumps(vu, ensure_ascii=False)

        # --- DEUX COMPTES, DEUX POINTS DE VUE -------------------------------
        assert call("POST", "/forum",
                    {"tp": "tp2-ex3", "texte": "j'ai le meme souci"},
                    jeton="bob")[0] == 200
        cote_bob = fil("bob")[1]["messages"]
        assert [m["auteur"] for m in cote_bob] == ["Participant", "Vous"]
        # ET LE FIL EST PAR EXERCICE : rien ne fuit d'un exercice a l'autre.
        assert fil("alice", "tp2-ex0")[1]["messages"] == []

        # --- SUPPRIMER : LE SIEN, JAMAIS CELUI D'UN AUTRE -------------------
        # Le meme 404 pour « n'existe pas » et « pas a toi » : les distinguer
        # dirait a qui essaie qu'un identifiant existe.
        assert call("DELETE", "/forum?id=" + mien["id"], jeton="bob")[0] == 404
        assert call("DELETE", "/forum?id=" + "f" * 32, jeton="alice")[0] == 404
        assert call("DELETE", "/forum?id=pasunid", jeton="alice")[0] == 400
        assert len(fil("alice")[1]["messages"]) == 2

        # --- SIGNALER, ET UNE SEULE FOIS ------------------------------------
        celui_de_bob = [m for m in fil("alice")[1]["messages"] if not m["mien"]][0]
        assert call("POST", "/forum/signalement", {"id": celui_de_bob["id"]},
                    jeton="alice")[0] == 200
        # LE DOUBLON EST UN NON-EVENEMENT, pas une erreur : meme reponse, et la
        # base n'a qu'une ligne. Un second signalement du meme compte ne doit
        # pas peser deux fois dans la file de moderation.
        assert call("POST", "/forum/signalement", {"id": celui_de_bob["id"]},
                    jeton="alice")[0] == 200
        assert len(signales) == 1, signales
        # Un identifiant invente ne cree pas de ligne orpheline.
        assert call("POST", "/forum/signalement", {"id": "e" * 32},
                    jeton="alice")[0] == 200
        assert len(signales) == 1, signales
        assert call("POST", "/forum/signalement", {"id": "pasunid"},
                    jeton="alice")[0] == 400

        # --- LA MODERATION EST RESERVEE, ET LE ROLE EST CALCULE SERVEUR -----
        assert call("GET", "/forum/moderation", jeton="alice")[0] == 403
        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "masquer"},
                    jeton="alice")[0] == 403
        assert not journal, journal
        # Et il ne s'obtient pas en le demandant : rien dans le corps ni dans
        # les en-tetes ne fabrique un moderateur.
        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "masquer",
                     "moderateur": True, "utilisateur": "sub-mod"},
                    jeton="alice")[0] == 403

        file_mod = call("GET", "/forum/moderation", jeton="mod")[1]
        assert len(file_mod["signalements"]) == 1
        assert file_mod["signalements"][0]["signalements"] == 1
        assert file_mod["signalements"][0]["texte"] == "j'ai le meme souci"

        # --- MASQUER PUIS RETABLIR, LES DEUX JOURNALISEES -------------------
        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "supprimer"},
                    jeton="mod")[0] == 400            # deux actions, pas trois
        assert call("POST", "/forum/moderation",
                    {"id": "f" * 32, "action": "masquer"}, jeton="mod")[0] == 404
        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "masquer"},
                    jeton="mod")[0] == 200
        # INVISIBLE POUR LES ETUDIANTS, y compris pour son auteur, et VISIBLE
        # pour le moderateur -- qui doit pouvoir le retablir.
        assert len(fil("alice")[1]["messages"]) == 1
        assert len(fil("bob")[1]["messages"]) == 1
        cote_mod = fil("mod")[1]
        assert cote_mod["moderateur"] is True and len(cote_mod["messages"]) == 2
        assert [m["masque"] for m in cote_mod["messages"]] == [False, True]

        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "retablir"},
                    jeton="mod")[0] == 200
        assert len(fil("alice")[1]["messages"]) == 2
        assert [a[3] for a in journal] == ["masquer", "retablir"], journal
        assert all(a[2] == "sub-mod" for a in journal), journal

        # Un message de l'equipe s'annonce comme tel -- c'est la seule etiquette
        # d'identite du forum, et elle porte un ROLE, pas une personne.
        assert call("POST", "/forum",
                    {"tp": "tp2-ex3", "texte": "Pense a relire la consigne."},
                    jeton="mod")[0] == 200
        assert [m["auteur"] for m in fil("alice")[1]["messages"]] == [
            "Vous", "Participant", "Équipe du cours"]

        # --- NOM CHOISI, NUMERO DE GROUPE, ET LE DROIT DE NE RIEN DIRE -----
        # L'ANONYMAT EST L'ETAT DE DEPART. Un profil jamais posé ne rend ni nom
        # ni groupe, et surtout aucun drapeau de visibilite a vrai.
        vide = call("GET", "/forum/profil", jeton="bob")[1]
        assert vide["pseudo"] is None and vide["groupe"] is None, vide
        assert vide["pseudo_public"] is False and vide["groupe_public"] is False

        # LES BORNES : une etiquette de l'interface ne se choisit pas, un nom
        # tient sur une ligne courte, et le groupe doit etre dans la liste de
        # la session (ici les defauts, 4 et 6).
        for mauvais in ({"pseudo": "Équipe du cours"}, {"pseudo": "participant"},
                        {"pseudo": "x" * (app.FORUM_PSEUDO_MAX + 1)},
                        {"groupe": 0}, {"groupe": 100}, {"groupe": "sept"},
                        {"groupe": 7}):
            assert call("POST", "/forum/profil", mauvais,
                        jeton="bob")[0] == 400, mauvais

        assert call("POST", "/forum/profil",
                    {"pseudo": "  Bob  B  ", "groupe": 4,
                     "pseudo_public": True, "groupe_public": False},
                    jeton="bob")[0] == 200
        de_bob = [m for m in fil("alice")[1]["messages"] if m["auteur"] == "Bob B"]
        assert de_bob, fil("alice")[1]["messages"]
        # SIGNALABLE, parce que c'est un nom que quelqu'un a choisi d'afficher.
        assert de_bob[0]["nom_signalable"] is True
        # SON GROUPE, LUI, N'EST PAS AFFICHE : il ne l'a pas coche.
        assert all(m["groupe"] is None for m in fil("alice")[1]["messages"])
        # MAIS L'EQUIPE DU COURS LE VOIT EN TOUT TEMPS -- c'est la seule
        # exception, et elle est ecrite dans le formulaire.
        cote_mod = [m for m in fil("mod")[1]["messages"] if m["auteur"] == "Bob B"]
        assert cote_mod and cote_mod[0]["groupe"] == 4, cote_mod
        # ET TOUJOURS AUCUN `sub`, meme dans la vue la plus renseignee.
        assert "sub-bob" not in json.dumps(fil("mod")[1], ensure_ascii=False)

        # DECOCHER SUFFIT A REDEVENIR ANONYME, et le nom reste a soi.
        assert call("POST", "/forum/profil",
                    {"pseudo": "Bob B", "groupe": 4,
                     "pseudo_public": False, "groupe_public": True},
                    jeton="bob")[0] == 200
        autres = [m for m in fil("alice")[1]["messages"] if not m["mien"]]
        assert not [m for m in autres if m["auteur"] == "Bob B"], autres
        assert [m for m in autres if m["groupe"] == 4], autres
        assert call("GET", "/forum/profil", jeton="bob")[1]["pseudo"] == "Bob B"

        # UNE CASE COCHEE SANS NOM N'AFFICHE RIEN : sans ca, on croirait s'etre
        # nomme en voyant « Participant ».
        assert call("POST", "/forum/profil",
                    {"pseudo": "", "pseudo_public": True},
                    jeton="bob")[0] == 200
        assert call("GET", "/forum/profil",
                    jeton="bob")[1]["pseudo_public"] is False
        assert call("POST", "/forum/profil",
                    {"pseudo": "Bob B", "groupe": 4, "pseudo_public": True,
                     "groupe_public": True}, jeton="bob")[0] == 200

        # --- SIGNALER UN NOM, PUIS L'EFFACER --------------------------------
        assert call("POST", "/forum/signalement",
                    {"id": celui_de_bob["id"], "quoi": "nom"},
                    jeton="alice")[0] == 200
        assert len(noms_signales) == 1, noms_signales
        # Meme regle que pour un message : un compte ne signale qu'une fois.
        assert call("POST", "/forum/signalement",
                    {"id": celui_de_bob["id"], "quoi": "nom"},
                    jeton="alice")[0] == 200
        assert len(noms_signales) == 1, noms_signales

        file_noms = call("GET", "/forum/moderation", jeton="mod")[1]["noms"]
        assert len(file_noms) == 1 and file_noms[0]["pseudo"] == "Bob B"
        assert file_noms[0]["groupe"] == 4
        assert "sub-bob" not in json.dumps(file_noms, ensure_ascii=False)

        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "effacer-nom"},
                    jeton="alice")[0] == 403          # reserve, comme le reste
        assert call("POST", "/forum/moderation",
                    {"id": "f" * 32, "action": "effacer-nom"},
                    jeton="mod")[0] == 404
        assert call("POST", "/forum/moderation",
                    {"id": celui_de_bob["id"], "action": "effacer-nom"},
                    jeton="mod")[0] == 200
        # LE NOM PART, LE MESSAGE RESTE, ET LE GROUPE AUSSI : ce qui a ete
        # signale est le nom, pas le reste.
        efface = call("GET", "/forum/profil", jeton="bob")[1]
        assert efface["pseudo"] is None and efface["pseudo_public"] is False
        assert efface["groupe"] == 4 and efface["groupe_public"] is True
        assert [m for m in fil("alice")[1]["messages"]
                if m["id"] == celui_de_bob["id"]], "le message n'a pas bouge"

        # --- LE QUOTA FREINE LES ECRITURES, JAMAIS LA LECTURE ---------------
        app.Handler.forum_quota = app.Quota(cooldown=30, hourly=1)
        assert call("POST", "/forum", {"tp": "tp2-ex3", "texte": "encore"},
                    jeton="alice")[0] == 200
        trop = call("POST", "/forum", {"tp": "tp2-ex3", "texte": "et encore"},
                    jeton="alice")
        assert trop[0] == 429 and trop[1]["retry_after"] > 0, trop
        assert call("POST", "/forum/signalement", {"id": celui_de_bob["id"]},
                    jeton="alice")[0] == 429
        # PAR COMPTE ET PAS PAR IP : deux etudiants derriere le meme NAT
        # d'ecole ne doivent pas se gener.
        assert call("POST", "/forum", {"tp": "tp2-ex3", "texte": "moi aussi"},
                    jeton="bob")[0] == 200
        # ET LIRE RESTE POSSIBLE : un quota qui empecherait de relire un fil
        # empecherait de suivre la reponse qu'on attend.
        assert fil("alice")[0] == 200
        app.Handler.forum_quota = app.Quota(cooldown=0, hourly=1000)

        # --- UNE BASE MUETTE SE DIT, ET N'EMPORTE PAS LE RESTE --------------
        muet = BaseSimulee.forum_fil
        BaseSimulee.forum_fil = staticmethod(lambda ex, limite: None)
        assert fil("alice")[0] == 503
        BaseSimulee.forum_fil = muet

        # --- « SUPPRIMER MES DONNEES » COUVRE LE FORUM ----------------------
        # Les messages d'alice partent, ses signalements aussi, et RIEN de ce
        # qu'un autre a ecrit n'est touche.
        avant = len(messages)
        assert call("POST", "/forum/profil",
                    {"pseudo": "Alice", "groupe": 6, "pseudo_public": True},
                    jeton="alice")[0] == 200
        assert "sub-alice" in profils
        assert call("DELETE", "/moi", jeton="alice")[0] == 200
        restants = [m["utilisateur"] for m in messages]
        assert "sub-alice" not in restants, restants
        assert "sub-bob" in restants and "sub-mod" in restants, restants
        assert len(messages) < avant
        assert not signales, signales
        assert "sub-alice" not in profils, profils
        # Et son propre message se supprime aussi a l'unite, quand elle le
        # demande message par message.
        neuf = call("POST", "/forum", {"tp": "tp2-ex3", "texte": "je reviens"},
                    jeton="alice")
        assert neuf[0] == 200, neuf
        a_moi = [m for m in fil("alice")[1]["messages"] if m["mien"]][0]
        assert call("DELETE", "/forum?id=" + a_moi["id"],
                    jeton="alice")[0] == 200
        assert not [m for m in fil("alice")[1]["messages"] if m["mien"]]
    finally:
        srv.shutdown()
        srv.server_close()
        (app.etat, app.current_user, app.STATIC, app.OIDC_ISSUER,
         app.OIDC_CLIENT_ID, app.FORUM_MODERATORS,
         app.Handler.forum_quota) = garde
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
