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

import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import time

# Les deux chemins, parce que les deux processus ne vivent pas au même endroit :
# runner.py à la racine (il tourne sur l'hôte), l'API dans app/ (elle est montée
# dans le conteneur). Le dépôt a EXACTEMENT cette forme, et le clone déployé
# aussi -- ce fichier tourne donc à l'identique sur le contrôleur et sur le Dell.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

import content_catalogue  # noqa: E402
import publish_content  # noqa: E402
import config     # noqa: E402
import csp        # noqa: E402
import etat       # noqa: E402
import politique  # noqa: E402
import runner     # noqa: E402
import security   # noqa: E402
from services import catalogue    # noqa: E402
from services import forum        # noqa: E402
from services import progression  # noqa: E402
from services import quotas       # noqa: E402
from services import spool        # noqa: E402


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
# Contenu v2 -- contrat de migration, sans toucher aux TP historiques
# --------------------------------------------------------------------------

def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def test_content_v2_discovery_and_public_projection():
    """Une collection ne définit pas l'identité, et assessment reste privé."""
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _write_json(os.path.join(root, "catalog.json"),
                    {"schema_version": 1, "skills": ["variables"]})
        exercise = os.path.join(root, "exercises", "surface-rectangle")
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": "surface-rectangle", "title": "Surface",
            "summary": "Calcule une surface.", "skills": ["variables"],
            "difficulty": "foundation", "contexts": ["mechanical"],
            "release": {"state": "scheduled", "available_from": "2026-09-18T00:00:00-04:00"},
        })
        os.makedirs(os.path.join(exercise, "assessment"))
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Calcule la surface.")
        _write_json(os.path.join(exercise, "assessment", "io.json"), {
            "cases": [{"stdin": "2\\n3\\n", "expect": [6]}],
            "note": "ne doit jamais etre publique",
        })
        _write_json(os.path.join(exercise, "public", "files.json"), {
            "files": [{"name": "submission.c", "template": "int main(void) {}"}],
        })
        _write_json(os.path.join(root, "collections", "tp2.json"), {
            "schema_version": 1, "id": "tp2", "title": "TP2",
            "items": ["surface-rectangle"], "release": {"state": "available"},
        })
        # L'ordre des fichiers ne doit pas faire remonter TP 10 avant TP 2.
        # On garde les IDs courts et stables : le catalogue compare leurs
        # portions numériques, plutôt que de demander des zéros de remplissage.
        for number in (1, 9, 10):
            _write_json(os.path.join(root, "collections", "tp%d.json" % number), {
                "schema_version": 1, "id": "tp%d" % number, "title": "TP%d" % number,
                "items": ["surface-rectangle"], "release": {"state": "available"},
            })
        model = content_catalogue.discover(root)
        public = content_catalogue.public_catalogue(model)
        detail = content_catalogue.public_detail(model, "surface-rectangle")
        assert model["exercises"]["surface-rectangle"]["mode"] == "io"
        assert public["collections"][0]["items"] == ["surface-rectangle"]
        assert [collection["id"] for collection in public["collections"]] == [
            "tp1", "tp2", "tp9", "tp10"]
        blob = json.dumps(public)
        assert "stdin" not in blob and "expect" not in blob and "note" not in blob, blob
        assert "template" not in blob and "statement" not in blob, blob
        # PAS ENCORE OUVERT : il figure au catalogue avec son cadenas, et son
        # détail ne se résout pas. Montrer n'est pas donner.
        assert public["exercises"][0]["access"] == "scheduled", public
        assert detail is None, detail
        ouvert = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        assert content_catalogue.public_detail(model, "surface-rectangle", ouvert) == {
            "statement": "Calcule la surface.",
            "files": [{"name": "submission.c", "template": "int main(void) {}"}]}
        assert content_catalogue.public_detail(model, "inconnu", ouvert) is None
        assert content_catalogue.find_exercise(model, "surface-rectangle") is None
    finally:
        shutil.rmtree(root)


def test_content_v2_rejects_conflicting_modes_and_unknown_collection_item():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _write_json(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
        exercise = os.path.join(root, "exercises", "bad")
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": "bad", "title": "Bad",
            "release": {"state": "available"},
        })
        os.makedirs(os.path.join(exercise, "assessment"))
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("x")
        _write_json(os.path.join(exercise, "assessment", "io.json"), {"cases": []})
        _write_json(os.path.join(exercise, "assessment", "quiz.json"), {"questions": []})
        _write_json(os.path.join(root, "collections", "tp2.json"), {
            "schema_version": 1, "id": "tp2", "title": "TP2", "items": ["missing"],
            "release": {"state": "available"},
        })
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            message = str(exc)
            assert "plusieurs modes" in message and "exercice inconnu" in message, message
        else:
            raise AssertionError("contenu v2 invalide accepté")
    finally:
        shutil.rmtree(root)


def _contenu_v2(root, etat_quiz):
    """Une racine v2 minimale : un io ouvert, un quiz dont l'ouverture varie."""
    _write_json(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    for name, release, config in (
            ("surface", {"state": "available"}, ("io.json", {"cases": [{"stdin": "1\n", "expect": [1]}]})),
            ("nombres", etat_quiz, ("quiz.json", {"label": "Quiz", "questions": [
                {"id": "q1", "group": "G", "label": "23", "type": "bin8", "answer": "00010111"}]})),
    ):
        exercise = os.path.join(root, "exercises", name)
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": name, "title": name.title(), "release": release})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        _write_json(os.path.join(exercise, "assessment", config[0]), config[1])
        if config[0] != "quiz.json":
            _write_json(os.path.join(exercise, "public", "files.json"),
                        {"files": [{"name": "submission.c", "template": ""}]})
    _write_json(os.path.join(root, "collections", "tp1.json"), {
        "schema_version": 1, "id": "tp1", "title": "TP1", "items": ["surface", "nombres"],
        "release": {"state": "available"}})


def test_content_v2_publication_verrouille_et_bascule():
    """La release est nommée par son contenu, le pointeur est le seul aiguillage."""
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        _contenu_v2(root, {"state": "scheduled", "available_from": "2099-01-01T00:00:00-05:00"})
        model = content_catalogue.discover(root)
        revision = publish_content.publish(model, dest)
        release = publish_content.current(dest)
        assert release == os.path.join(dest, revision), release
        publie = {}
        for dossier, _, noms in os.walk(release):
            for nom in noms:
                chemin = os.path.join(dossier, nom)
                publie[os.path.relpath(chemin, release).replace(os.sep, "/")] = lire(chemin)
        assert sorted(publie) == ["catalog.json", "exercises/surface.json",
                                  "manifest.json"], sorted(publie)
        # LE POINT DE TOUT LE FICHIER : rien du corrigé ne franchit la frontière,
        # et un exercice pas encore ouvert n'a ni détail ni quiz publiés.
        assert "answer" not in "".join(publie.values()), publie
        assert "00010111" not in "".join(publie.values()), publie
        catalogue_publie = json.loads(publie["catalog.json"])
        etats = {e["id"]: e["access"] for e in catalogue_publie["exercises"]}
        assert etats == {"surface": "available", "nombres": "scheduled"}, etats

        # Republier un contenu identique ne crée rien ; le changer bascule le
        # pointeur SANS effacer l'ancienne release -- c'est ça, le rollback.
        assert publish_content.publish(model, dest) == revision
        _write_json(os.path.join(root, "exercises", "surface", "exercise.json"), {
            "schema_version": 1, "id": "surface", "title": "Surface v2",
            "release": {"state": "available"}})
        suivante = publish_content.publish(content_catalogue.discover(root), dest)
        assert suivante != revision, suivante
        assert publish_content.current(dest) == os.path.join(dest, suivante)
        assert os.path.isdir(os.path.join(dest, revision)), "rollback impossible"

        # Le quiz ouvert est publié, sans son corrigé.
        _contenu_v2(root, {"state": "available"})
        ouvert = publish_content.publish(content_catalogue.discover(root), dest)
        quiz = json.loads(lire(os.path.join(dest, ouvert, "quiz", "nombres.json")))
        assert quiz["questions"][0]["label"] == "23" and "answer" not in str(quiz), quiz
    finally:
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_worker_v2_resout_un_exercice_et_refuse_ce_qui_est_ferme():
    """Le worker est root : il rejoue la release et relit les noms publics."""
    root = tempfile.mkdtemp(prefix="ctester-content-")
    garde = runner.CONTENT
    try:
        _contenu_v2(root, {"state": "scheduled", "available_from": "2099-01-01T00:00:00-05:00"})
        # Un module à deux fichiers : c'est ce qui prouve que le worker LIT
        # `public/files.json` au lieu de retomber sur submission.c par défaut.
        _write_json(os.path.join(root, "exercises", "surface", "public", "files.json"),
                    {"files": [{"name": "calendrier.h", "template": ""},
                               {"name": "calendrier.c", "template": ""}]})
        runner.CONTENT = root
        assessment = os.path.join(root, "exercises", "surface", "assessment")
        assert runner.tp_path("surface") == assessment
        assert runner.tp_path("nombres") is None, "un exercice fermé reste injoignable"
        assert runner.tp_path("../../etc/passwd") is None
        assert runner.unity_dir() == os.path.join(root, "shared", "unity")
        conf = runner.load_config(assessment, "io.json")
        assert [f["name"] for f in runner.declared_files(conf, assessment)] == [
            "calendrier.h", "calendrier.c"]
        # Sans répertoire, le défaut historique tient : un TP v1 ne change pas.
        assert runner.declared_files(conf) == [{"name": "submission.c", "template": ""}]
    finally:
        runner.CONTENT = garde
        shutil.rmtree(root)


def test_publication_refuse_un_worker_sans_contenu():
    """Sans les deux variables, le worker s'ARRÊTE en le disant.

    Il n'y a plus d'arborescence historique à lire depuis la phase 8 : un worker
    mal configuré qui publierait « rien » ferait disparaître le catalogue de
    tout le monde, en silence, et le repli de la page ne le rattraperait plus.
    Systemd doit voir un échec, pas un service vert devant un menu vide.
    """
    garde = (runner.CONTENT, runner.PUBLISHED)
    try:
        for contenu, publie in (("", ""), ("/tmp/x", ""), ("", "/tmp/y")):
            runner.CONTENT, runner.PUBLISHED = contenu, publie
            try:
                runner.publish_catalogue()
            except RuntimeError as exc:
                assert "CTESTER_CONTENT" in str(exc), exc
            else:
                raise AssertionError("publication silencieuse : %r %r" % (contenu, publie))
    finally:
        runner.CONTENT, runner.PUBLISHED = garde


def test_content_v2_projection_refuse_une_cle_privee():
    """La ceinture : un champ public ajouté demain ne publie pas un corrigé."""
    modele = {"schema_version": 1, "skills": [], "collections": {},
              "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                  "skills": [], "mode": "io", "summary": "",
                                  "difficulty": None, "contexts": [],
                                  "statement": "", "files": [], "config": {}}}}
    original = content_catalogue.public_detail
    content_catalogue.public_detail = lambda *a, **k: {"statement": "", "answer": "42"}
    try:
        publish_content.projection(modele)
    except content_catalogue.ContentValidationError as exc:
        assert "answer" in str(exc), exc
    else:
        raise AssertionError("projection publiée avec une clé privée")
    finally:
        content_catalogue.public_detail = original


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


def test_presence_compteur():
    p = quotas.Presence()
    assert p.touch("a", 1000) == 1
    assert p.touch("b", 1000) == 2
    assert p.touch("a", 1000) == 2          # rejouer ne double pas
    # au-delà du TTL, la fenêtre sort du total sans que personne ne l'efface
    assert p.touch("c", 1000 + config.PRESENCE_TTL + 1) == 1


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
    l'API. Un nombre d'equilibrage qui reapparait dans le service rendrait la
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
    progression = lire(os.path.join(HERE, "app", "services", "progression.py"))
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


# LA FORME DU CATALOGUE PUBLIE, celle que `exercices_ouverts()` rend :
# `skills` et `difficulty` a plat, plus de bloc `learning`.
CATALOGUE_DEMO = [
    {"id": "tp2-ex0", "skills": ["variables"], "difficulty": "intro"},
    {"id": "tp2-ex3", "skills": ["variables", "arithmetic-operators"],
     "difficulty": "foundation"},
    {"id": "tp6-ex1", "skills": ["arrays-1d"]},
    {"id": "tp1"},                                    # sans metadonnees : legal
]


def test_projection_des_competences():
    etats = [{"exercice_id": "tp2-ex0", "statut": "valide"},
             {"exercice_id": "tp2-ex3", "statut": "essaye"}]
    pratique = [{"exercice_id": "tp6-ex1", "tentatives": 2, "reussites": 0}]
    touches, reussis = progression.exercise_facts(etats, pratique)
    assert touches == {"tp2-ex0", "tp2-ex3", "tp6-ex1"}
    assert reussis == {"tp2-ex0"}
    vue = progression.skills_view(CATALOGUE_DEMO, touches, reussis)
    # L'ORDRE EST CELUI DU COURS, pas un tri par score : la premiere ligne est
    # la premiere competence rencontree, ce que l'etudiant reconnait.
    assert [c["id"] for c in vue] == ["variables", "arithmetic-operators", "arrays-1d"]
    assert vue[0] == {"id": "variables", "total": 2, "pratiques": 2, "reussis": 1}
    assert vue[2] == {"id": "arrays-1d", "total": 1, "pratiques": 1, "reussis": 0}


def test_recommandation_deterministe():
    etats = [{"exercice_id": "tp2-ex0", "statut": "valide"}]
    touches, reussis = progression.exercise_facts(etats, [])
    # Deja pratique `variables` : on repart sur l'exercice non reussi qui la
    # reprend, pas sur le premier venu.
    assert progression.recommander(CATALOGUE_DEMO, touches, reussis) == {
        "exercice_id": "tp2-ex3", "competence": "variables"}
    # Aucune competence en commun : le premier non reussi, dans l'ordre du cours.
    assert progression.recommander(CATALOGUE_DEMO, set(), set()) == {
        "exercice_id": "tp2-ex0", "competence": None}
    # Tout reussi : rien a proposer, et on le dit au lieu d'inventer.
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert progression.recommander(CATALOGUE_DEMO, tout, tout) is None
    assert progression.recommander([], set(), set()) is None


def test_progression_ne_publie_rien_de_secret():
    faits = {"xp": 25, "succes": [{"id": "premiere-reussite",
                                   "obtenu_le": "2026-09-03", "politique": "x"},
                                  {"id": "disparu", "obtenu_le": "2026-09-03",
                                   "politique": "x"}],
             "transactions": [{"exercice_id": "tp2-ex0", "montant": 10,
                               "motif": "premiere reussite",
                               "accorde_le": "2026-09-03"}]}
    charge = progression.progress_payload(
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
    assert len(tables) == 12, tables
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
    # Le theme degrade comme le reste : None dit « la base n'a pas repondu »,
    # jamais « pas de theme » -- c'est ce qui laisse la page garder le sien.
    assert etat.read_theme("u") is None
    assert etat.write_theme("u", "light") is False
    assert etat.write_theme("u", "neon") is False    # refuse avant meme la base
    assert etat.forget("u") is False


# --------------------------------------------------------------------------
# File, quotas, HTTP
# --------------------------------------------------------------------------

def test_queue_position():
    jobs = [("aaa", 100.0, True), ("bbb", 101.0, False), ("ccc", 102.0, False)]
    assert spool.queue_position(jobs, "bbb") == 1   # les terminés ne comptent pas
    assert spool.queue_position(jobs, "ccc") == 2
    assert spool.queue_position(jobs, "aaa") == 0
    assert spool.queue_position(jobs, "inconnu") == 0


def test_quota():
    q = quotas.Quota(cooldown=15, hourly=3)
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
    assert security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({}, "10.0.0.1") == "10.0.0.1"


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
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS, security.etat)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.etat = type("Base", (), {"enabled": staticmethod(lambda: True)})
        config.FORUM_MODERATORS = frozenset()
        assert security.oidc_enabled() and not forum.forum_enabled()
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        assert forum.forum_enabled()
        assert security.is_moderator("sub-mod") and not security.is_moderator("sub-alice")
        # Un `sub` vide n'est pas un moderateur, meme si la liste en contient un
        # vide par accident de configuration.
        assert not security.is_moderator("") and not security.is_moderator(None)
        # La CONNEXION reste la premiere condition : un forum sans compte n'a
        # personne a qui attribuer un message ni a qui offrir la suppression.
        config.OIDC_ISSUER = ""
        assert not forum.forum_enabled()
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS,
         security.etat) = garde


def test_forum_texte_borne_et_stocke_la_source():
    """Ce qu'un message a le droit d'etre : court, non vide, et SA SOURCE.

    LE SERVEUR NE REND RIEN ET N'ASSAINIT RIEN. Ce qui est stocke est le
    Markdown tel qu'il a ete tape -- balises comprises, sous leur forme source.
    Le rendu et l'assainissement se font a CHAQUE affichage, dans `forum.js` :
    assainir a l'ecriture seulement laisserait les messages deja en base hors de
    portee d'une regle resserree ensuite.
    """
    assert forum.forum_texte("  Pourquoi mon while ne s'arrete pas ?  ") == (
        "Pourquoi mon while ne s'arrete pas ?", None)
    assert forum.forum_texte("")[0] is None
    assert forum.forum_texte("   \n  ")[0] is None
    assert forum.forum_texte(None)[0] is None
    assert forum.forum_texte(42)[0] is None
    assert forum.forum_texte("x" * (config.FORUM_MAX_CHARS + 1))[0] is None
    assert forum.forum_texte("x" * config.FORUM_MAX_CHARS)[0] is not None
    # LA SOURCE PASSE INTACTE, y compris ce qui ressemble a du HTML : c'est le
    # rendu qui l'echappe, et il le fera a chaque affichage.
    hostile = "<script>alert(1)</script> et **gras**"
    assert forum.forum_texte(hostile)[0] == hostile
    assert forum.forum_texte("[doc](https://exemple.test)")[0] \
        == "[doc](https://exemple.test)"
    # Les caracteres de controle partent : ils ne servent a rien dans du
    # Markdown et compliquent une relecture humaine pour rien.
    assert forum.forum_texte("a\x00b\x07c")[0] == "abc"
    assert forum.forum_texte("ligne 1\r\nligne 2")[0] == "ligne 1\nligne 2"


def test_forum_bibliotheques_epinglees():
    """Les deux bibliotheques du rendu sont VERSIONNEES, presentes, et servies.

    CE CONTROLE EXISTE PARCE QU'UN ASSAINISSEUR ABSENT NE SE VOIT PAS. La page
    retombe alors sur du texte brut -- c'est le bon comportement -- et personne
    ne remarque que le rendu a disparu. Ici, un nom qui ne correspond plus entre
    `VENDOR`, `forum.js` et le disque fait echouer la suite tout de suite.
    """
    assert len(config.VENDOR) == 2, config.VENDOR
    source = lire(os.path.join(HERE, "web", "forum.js"))
    for chemin in config.VENDOR:
        sur_disque = os.path.join(HERE, "web", *chemin.split("/"))
        assert os.path.exists(sur_disque), chemin
        assert '"' + chemin + '"' in source, chemin
        # Le nom PORTE la version : c'est ce qui rend l'epinglage impossible a
        # perdre, et une montee de version impossible a faire par accident.
        assert re.search(r"-\d+\.\d+\.\d+[.-]", chemin), chemin
    # `/vendor/` N'EST PAS UN REPERTOIRE OUVERT : la liste est close, comme
    # celle des `.js` de la page.
    assert "vendor/" in config.VENDOR[0] and "vendor/" in config.VENDOR[1]


def test_csp_du_document():
    """La CSP de l'en-tete et celle du `<meta>` disent la MEME chose.

    ELLE N'EST PAS LA DEFENSE PRINCIPALE -- l'assainisseur et `textContent` le
    sont -- mais elle doit etre juste : une CSP qui oublie l'emetteur OIDC casse
    la connexion, une qui oublie l'API casse tout, et les deux en silence.

    DEUX COPIES DE LA POLITIQUE EXISTENT depuis que GitHub Pages sert la page :
    l'en-tete que pose `csp()` (ce serveur, et le mode local) et le `<meta>` de
    `index.html` (Pages, qui ne peut poser aucun en-tete). Ce controle est ce
    qui les empeche de diverger -- editer l'une sans l'autre echoue ici.

    C'est le remplacant du hachage recopie a la main que le plan de separation
    envisageait : plutot que de surveiller un hachage, la page n'a plus AUCUN
    script inline, et `csp()` refuse d'en hacher un.
    """
    page = lire(os.path.join(HERE, "web", "index.html")).encode()
    politique = csp.csp(page, "https://auth.exemple/auth/v1")
    assert "default-src 'none'" in politique
    # PAS DE HACHAGE, et pas de script inline pour en avoir besoin.
    assert "sha256-" not in politique, politique
    assert "script-src 'self';" in politique, politique
    assert b"<script" in page and not csp._INLINE_SCRIPT_RE.findall(page), page
    # Un inline qui reviendrait doit faire du BRUIT, pas se faire hacher.
    # ... y compris en majuscules : un nom de balise HTML est insensible a la
    # casse, donc la garde doit l'etre aussi, sinon `<SCRIPT>` passe.
    for inline in (b"<script>var t=1;</script>", b"<SCRIPT>var t=1;</SCRIPT>"):
        try:
            csp.csp(inline)
            raise AssertionError("un <script> inline est passe sans rien dire")
        except ValueError:
            pass
    # L'EMETTEUR OIDC EST DANS connect-src, en ORIGINE seulement : `compte.js`
    # y va chercher la decouverte puis le jeton.
    assert "https://auth.exemple" in politique.split("connect-src")[1]
    assert "/auth/v1" not in politique, politique
    # L'API AUSSI : sans elle, la page servie par ce serveur pendant la bascule
    # ne peut joindre `tch099` et n'affiche plus un seul TP.
    assert config.API_ORIGIN in politique.split("connect-src")[1]
    for interdit in ("frame-ancestors 'none'", "base-uri 'none'",
                     "form-action 'none'", "img-src 'self'"):
        assert interdit in politique, interdit
    # `style-src` garde 'unsafe-inline' : la page pose des attributs `style`
    # calcules (largeur de jauge, rang d'une coche). C'est un choix, il est
    # ecrit, et il ne doit pas deraper vers script-src.
    assert "style-src 'self' 'unsafe-inline'" in politique
    assert "unsafe-inline" not in politique.split("style-src")[0], politique
    assert "unsafe-eval" not in politique

    # --- ET MAINTENANT LE <meta>, directive par directive. ---
    meta = re.search(
        rb'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert meta, "le <meta> CSP a disparu de index.html"
    du_meta = {d.split()[0]: " ".join(d.split()[1:])
               for d in meta.group(1).decode().split("; ")}
    du_serveur = {d.split()[0]: " ".join(d.split()[1:])
                  for d in csp.csp(page, config.OIDC_ISSUER or
                                   "https://auth.thevhome.com/auth/v1").split("; ")}
    # `frame-ancestors` EST LA SEULE PERTE du passage en <meta> : un <meta> ne
    # peut pas le porter, et le navigateur le signale en console -- une console
    # rouge est une panne prod qu'on a deja eue. Il est donc absent du <meta>
    # EXPRES, et repose sur une Transform Rule Cloudflare (X-Frame-Options).
    assert "frame-ancestors" not in du_meta, du_meta
    assert du_serveur.pop("frame-ancestors") == "'none'"
    assert du_meta == du_serveur, (du_meta, du_serveur)


def test_forum_vue_ne_laisse_sortir_aucun_sub():
    """« Vous », « Participant », « Enseignant » -- et RIEN d'autre.

    CE CONTROLE EST LA FRONTIERE DE CONFIDENTIALITE DU FORUM. Un `sub` qui
    traverse, meme dans un champ que personne n'affiche, rend deux messages
    recollables au meme etudiant -- ce que ni un pseudonyme ni un identifiant
    stable ne doivent permettre en phase MVP.
    """
    garde = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "utilisateur": "sub-alice", "texte": "moi",
                "masque": False, "cree_le": "2026-09-03 10:00"},
               {"id": "b" * 32, "utilisateur": "sub-bob", "texte": "lui",
                "masque": False, "cree_le": "2026-09-03 10:01"},
               {"id": "c" * 32, "utilisateur": "sub-mod", "texte": "eux",
                "masque": False, "cree_le": "2026-09-03 10:02"},
               {"id": "d" * 32, "utilisateur": "sub-bob", "texte": "cache",
                "masque": True, "cree_le": "2026-09-03 10:03"}]
        vu = forum.forum_vue(fil, "sub-alice", False)
        assert [m["auteur"] for m in vu] == [
            "Vous", "Participant", "Enseignant"], vu
        assert [m["mien"] for m in vu] == [True, False, False]
        # UN MESSAGE MASQUE N'EXISTE PAS pour un etudiant ordinaire.
        assert len(vu) == 3
        texte = json.dumps(vu, ensure_ascii=False)
        for interdit in ("sub-alice", "sub-bob", "sub-mod", "utilisateur"):
            assert interdit not in texte, interdit
        # Un moderateur, LUI, voit le masque -- sinon il ne pourrait pas le
        # retablir -- et pas davantage d'identite pour autant.
        vu_mod = forum.forum_vue(fil, "sub-mod", True)
        assert len(vu_mod) == 4 and vu_mod[3]["masque"] is True
        assert vu_mod[2]["auteur"] == "Vous"      # son propre message
        assert "sub-bob" not in json.dumps(vu_mod, ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = garde


def test_forum_identite_bornes_et_visibilite():
    """Le nom choisi et le numero de groupe : ce qui est accepte, ce qui sort.

    LA REGLE TIENT EN UNE LIGNE : rien ne s'affiche que son porteur n'ait
    rendu visible -- sauf le numero de groupe pour l'enseignant, en tout
    temps, et c'est ecrit dans le formulaire.
    """
    assert forum.forum_pseudo(None) == (None, None)
    assert forum.forum_pseudo("   ") == (None, None)
    assert forum.forum_pseudo("  Lea   B ") == ("Lea B", None)
    assert forum.forum_pseudo("Lea" + chr(10) + "B")[0] == "Lea B"   # une ligne
    for reserve in ("Vous", "participant", "Enseignant", "Équipe du cours",
                    "Anonyme"):
        assert forum.forum_pseudo(reserve)[0] is None, reserve
    assert forum.forum_pseudo("x" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    # La session n'ouvre que certains groupes (CTESTER_FORUM_GROUPES) ; hors
    # liste, rien ne passe -- pas même un numero valide 1..99.
    garde_g = config.FORUM_GROUPES
    try:
        config.FORUM_GROUPES = (4, 6)
        assert forum.forum_groupe("04") == (4, None)
        for mauvais in (0, 100, -1, "sept", True, 7):
            assert forum.forum_groupe(mauvais)[0] is None, mauvais
        config.FORUM_GROUPES = ()
        assert forum.forum_groupe("07") == (7, None)
        for mauvais in (0, 100, -1, "sept", True):
            assert forum.forum_groupe(mauvais)[0] is None, mauvais
    finally:
        config.FORUM_GROUPES = garde_g

    garde = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "utilisateur": "sub-bob", "texte": "x",
                "masque": False, "cree_le": "2026-09-03T10:00Z"}]
        cache = {"sub-bob": {"pseudo": "Bob", "groupe": 7,
                             "pseudo_public": False, "groupe_public": False}}
        vu = forum.forum_vue(fil, "sub-alice", False, cache)[0]
        assert vu["auteur"] == "Participant" and vu["groupe"] is None
        assert vu["nom_signalable"] is False
        # Le modérateur voit le groupe SANS que le nom devienne public pour
        # autant : deux cases, deux effets.
        vu_mod = forum.forum_vue(fil, "sub-mod", True, cache)[0]
        assert vu_mod["auteur"] == "Participant" and vu_mod["groupe"] == 7
        montre = {"sub-bob": dict(cache["sub-bob"], pseudo_public=True)}
        vu2 = forum.forum_vue(fil, "sub-alice", False, montre)[0]
        assert vu2["auteur"] == "Bob" and vu2["nom_signalable"] is True
        # Son propre nom reste « Vous » : on ne se signale pas soi-meme.
        a_moi = forum.forum_vue(fil, "sub-bob", False, montre)[0]
        assert a_moi["auteur"] == "Vous" and a_moi["nom_signalable"] is False
        assert "sub-bob" not in json.dumps(
            [vu, vu_mod, vu2, a_moi], ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = garde


def test_verrou_perime_est_repris_puis_abandonne():
    """UN WORKER TUÉ NE DOIT PAS COÛTER DIX MINUTES DE SILENCE À UN ÉTUDIANT.

    C'est la seule chose qu'un redémarrage de worker fait vraiment perdre : la
    file, elle, est sur disque et son ordre est le mtime de job.json, que
    personne ne touche. Le job EN VOL, lui, gardait son `.lock` sans verdict,
    donc claim() le refusait pour toujours et l'étudiant regardait « en file
    d'attente » jusqu'au balayage.

    Les trois bornes du contrôle, et pas seulement le refus : un verrou frais
    appartient à un worker vivant et ne se touche pas, un verrou périmé se
    reprend, et un job qui a déjà épuisé ses reprises rend un verdict au lieu de
    tourner en boucle sur les workers qu'il tue.
    """
    tmp = tempfile.mkdtemp(prefix="ctester-verrou-")
    try:
        job = os.path.join(tmp, "job-1")
        os.makedirs(job)
        with open(os.path.join(job, "job.json"), "w", encoding="utf-8") as fh:
            json.dump({"tp": "tp2-ex0"}, fh)
        lock = os.path.join(job, ".lock")
        os.mkdir(lock)
        maintenant = time.time()

        # Verrou frais : c'est un worker vivant, on n'y touche pas.
        assert not runner.claim(job)
        assert not runner.reclaim(job, maintenant)
        assert os.path.isdir(lock)

        # Périmé : repris une fois, et le job redevient prenable.
        os.utime(lock, (maintenant - runner.LOCK_STALE - 1,) * 2)
        assert runner.reclaim(job, maintenant)
        assert runner.claim(job)
        assert runner.reprises(job) == 1

        # Périmé une seconde fois : plus de reprise, un verdict à la place.
        os.utime(lock, (maintenant - runner.LOCK_STALE - 1,) * 2)
        assert not runner.reclaim(job, maintenant)
        with open(os.path.join(job, "result.json"), encoding="utf-8") as fh:
            verdict = json.load(fh)
        assert verdict["status"] == "error", verdict
        assert verdict["state"] == "done", verdict
        # Le job porte un verdict : pending_jobs() ne le repropose plus.
        ancien_spool = runner.SPOOL
        try:
            runner.SPOOL = tmp
            assert runner.pending_jobs() == []
        finally:
            runner.SPOOL = ancien_spool
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_le_verrou_perime_ne_double_jamais_le_balayage():
    """LOCK_STALE < SWEEP_AFTER, sinon la reprise n'arrive jamais.

    Les deux échéances courent sur le même répertoire. Si le balayage passait le
    premier, tout le code de reprise serait mort sans que rien ne le signale --
    le genre de réglage qui se dérègle en changeant CTESTER_JOB_TIMEOUT, dont
    LOCK_STALE est dérivé.
    """
    assert runner.LOCK_STALE < runner.SWEEP_AFTER, (
        "LOCK_STALE (%d) doit rester sous SWEEP_AFTER (%d) : un job doit "
        "pouvoir être repris avant d'être effacé."
        % (runner.LOCK_STALE, runner.SWEEP_AFTER))
    assert runner.LOCK_STALE > runner.JOB_TIMEOUT, (
        "LOCK_STALE (%d) doit dépasser JOB_TIMEOUT (%d) : sinon un worker "
        "vivant se fait voler le job qu'il est en train de juger."
        % (runner.LOCK_STALE, runner.JOB_TIMEOUT))


def test_le_controle_de_l_hote_ne_depend_d_aucun_tiers():
    """CE FICHIER TOURNE SUR LE DELL, AVEC LE PYTHON DE L'HÔTE.

    `pull.sh` et la vérification Ansible le lancent tous les deux hors du
    conteneur, donc sans `PYTHONPATH=/deps` : ni fastapi, ni starlette, ni
    pydantic, ni uvicorn. Un import de trop ici ne casse pas un test -- il
    bloque le déploiement automatique toutes les cinq minutes, sur un
    `ImportError`, sans que rien ne soit déployé.

    C'est arrivé une fois : `csp()` vivait dans `headers.py`, qui importe
    starlette. D'où `app/csp.py`, bibliothèque standard seulement.

    `psycopg` est la seule exception tolérée -- `etat.py` le rend facultatif et
    se déclare éteint sans lui.
    """
    tiers = {"starlette", "fastapi", "pydantic", "pydantic_core", "uvicorn",
             "httpx", "httpx2", "anyio", "h11"}
    charges = sorted(tiers & {m.split(".")[0] for m in sys.modules})
    assert not charges, (
        "test_ctester.py a tire " + ", ".join(charges) + " : ces paquets vivent "
        "dans /deps, que le python de l'hote ne voit pas. Sortir ce que le "
        "module fautif utilise dans un module sans dependance, comme app/csp.py.")


def test_duree_moyenne_glissante_par_exercice():
    """Ce que le worker mesure, et ce qu'il refuse de mesurer.

    La moyenne est PAR EXERCICE (un quiz ne coûte pas ce que coûte un TP de dix
    cas) et GLISSANTE : un cas de test ajouté en cours de session doit se voir
    dans l'estimation au bout de quelques jobs, pas être noyé sous l'histoire
    du semestre.
    """
    spool = tempfile.mkdtemp(prefix="ctester-spool-")
    garde = runner.SPOOL
    try:
        runner.SPOOL = spool

        # Un job rejeté avant le conteneur (en-tête interdit) dure quelques
        # millisecondes. L'inclure tirerait la moyenne vers zéro PRÉCISÉMENT
        # parce que les étudiants se trompent souvent.
        runner.enregistrer_duree("tp2-ex3", 0.01)
        runner.enregistrer_duree("", 9.0)
        assert runner.lire_durees() == {}

        runner.enregistrer_duree("tp2-ex3", 4.0)
        runner.enregistrer_duree("tp2-ex3", 6.0)
        assert runner.lire_durees()["tp2-ex3"] == [5.0, 2]
        # Un autre exercice ne contamine pas le premier.
        runner.enregistrer_duree("tp1", 1.0)
        assert runner.lire_durees()["tp2-ex3"][0] == 5.0

        # La fenêtre : après elle, chaque mesure pèse un vingtième et le poids
        # ne s'écrase plus. Sans le plafond, la moyenne du semestre gèlerait.
        for _ in range(60):
            runner.enregistrer_duree("tp1", 20.0)
        moyenne, n = runner.lire_durees()["tp1"]
        assert n == runner.DUREE_FENETRE + 1, n
        assert 19.0 < moyenne <= 20.0, moyenne

        # Un fichier corrompu repart de zéro plutôt que de faire échouer un job.
        with open(os.path.join(spool, runner.DUREES), "w", encoding="utf-8") as fh:
            fh.write("{ pas du json")
        assert runner.lire_durees() == {}
        runner.enregistrer_duree("tp1", 3.0)
        assert runner.lire_durees() == {"tp1": [3.0, 1]}
    finally:
        runner.SPOOL = garde
        shutil.rmtree(spool, ignore_errors=True)


def test_normalisation_ignore_l_habillage_mais_pas_le_code():
    """Deux fois le même code doit donner la même clé, quelle que soit sa mise
    en page. C'EST TOUT L'INTÉRÊT DU CACHE : un étudiant qui resoumet après
    avoir reformaté, ou qui a ajouté trois lignes vides, ne doit pas repayer une
    compilation. Mais deux programmes DIFFÉRENTS ne doivent jamais se
    rencontrer -- un faux positif ici sert le verdict de quelqu'un d'autre."""
    n = runner.normaliser_c
    espace = ("// mon programme\n#include <stdio.h>\n\n\n"
              "int main(void) {\n\n"
              "    /* la boucle */\n"
              "    for (int i = 0; i < 3; i++)\n"
              "        printf(\"%d\\n\", i);\n\n"
              "    return 0;\n}\n")
    serre = ("#include <stdio.h>\n"
             "int main(void){for(int i=0;i<3;i++)printf(\"%d\\n\",i);return 0;}")
    assert n(espace) == n(serre), (n(espace), n(serre))

    # Les blancs SÉPARATEURS restent : sans eux `int x` deviendrait `intx`,
    # c'est-à-dire un autre programme sous la même clé.
    assert n("int x;") == "int x;"
    assert n("intx;") == "intx;"
    assert n("int x;") != n("intx;")
    # Un commentaire sépare deux jetons, exactement comme un espace.
    assert n("int/*c*/x;") == n("int x;")

    # Ce qui change le sens change la clé.
    assert n("int x = 1;") != n("int x = 2;")
    assert n("int a;") != n("int b;")

    # LES DIRECTIVES GARDENT LEUR FIN DE LIGNE. Sans elle deux #define
    # fusionneraient, et deux sources distinctes partageraient une clé.
    assert n("#define A 1\n#define B 2") != n("#define A 1 #define B 2")


def test_normalisation_ne_confond_pas_une_chaine_avec_un_commentaire():
    """Le piège classique du lexeur C, et ici il n'est pas cosmétique : avaler
    la fin d'une ligne comme un commentaire ferait disparaître du code de la
    clé, donc rapprocherait deux programmes différents."""
    n = runner.normaliser_c
    # Le `//` d'une URL est dans une chaîne, pas un commentaire.
    assert n('puts("http://a"); int x;') != n('puts("http://b"); int x;')
    assert 'http://a' in n('puts("http://a");')
    # Un `/*` dans une chaîne n'ouvre pas de bloc.
    assert n('puts("/*"); int x;').endswith("int x;")
    # Un guillemet en littéral de caractère ne démarre pas une chaîne.
    assert n("char c = '\"'; int x;").endswith("int x;")
    # Un guillemet échappé ne ferme pas la chaîne.
    assert n('char *s = "a\\"b//c"; int z;').endswith("int z;")
    # Une apostrophe dans un commentaire n'ouvre pas de littéral (le contenu
    # des exercices est en français, ce cas arrive à chaque énoncé commenté).
    assert n("int x; // n'oublie pas\nint y;") == n("int x;int y;")


def test_signature_suit_le_juge_autant_que_le_code():
    """LA RÉVISION PUBLIÉE NE SUFFIT PAS comme clé, et c'est pour ça que ce
    cache vit dans le worker : `publish_content.revision()` ne hache que la
    projection publique, donc corriger un cas de test ne la change pas. La
    signature doit voir ce changement, sinon le tick de cinq minutes corrigerait
    un test et le cache continuerait de servir l'ancien verdict."""
    racine = tempfile.mkdtemp()
    try:
        tp_dir = os.path.join(racine, "exercises", "tp2-ex1", "assessment")
        os.makedirs(tp_dir)
        io_json = os.path.join(tp_dir, "io.json")
        with open(io_json, "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]}]}, fh)
        conf = {"cases": [{"stdin": "", "expect": [1]}]}
        code = {"submission.c": "int main(void){return 0;}"}

        base = runner.signature("tp2-ex1", tp_dir, "io", conf, code)
        # Rejouée sur le même état, elle ne bouge pas.
        assert runner.signature("tp2-ex1", tp_dir, "io", conf, code) == base

        # Le même code sur un autre exercice n'est pas le même verdict.
        assert runner.signature("tp2-ex2", tp_dir, "io", conf, code) != base

        # Un cas de test ajouté -- ce que fait le tick de cinq minutes.
        with open(io_json, "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]},
                                 {"stdin": "2", "expect": [2]}]}, fh)
        assert runner.signature("tp2-ex1", tp_dir, "io", conf, code) != base

        # Un fichier de test ajouté au répertoire compte aussi.
        apres = runner.signature("tp2-ex1", tp_dir, "io", conf, code)
        with open(os.path.join(tp_dir, "test_ajoute.c"), "w",
                  encoding="utf-8") as fh:
            fh.write("void test_x(void){}")
        assert runner.signature("tp2-ex1", tp_dir, "io", conf, code) != apres

        # Et le code, évidemment -- mais pas sa mise en page.
        stable = runner.signature("tp2-ex1", tp_dir, "io", conf, code)
        aere = {"submission.c": "int main(void)\n{\n\n    return 0;\n}\n"}
        assert runner.signature("tp2-ex1", tp_dir, "io", conf, aere) == stable
        autre = {"submission.c": "int main(void){return 1;}"}
        assert runner.signature("tp2-ex1", tp_dir, "io", conf, autre) != stable
    finally:
        shutil.rmtree(racine, ignore_errors=True)


def test_cache_de_verdicts():
    """Ce qui entre dans le magasin, ce qui n'y entre jamais, et ce que
    `run_job` en fait. LE CAS QUI COMPTE EST L'EXCLUSION : geler un `timeout`
    ou l'échec d'un exercice aléatoire enfermerait un étudiant dans un verdict
    qu'il ne pourrait plus jamais faire changer."""
    ok = {"status": "ok", "kind": "io", "total": 3, "passed": 3}
    rate = {"status": "ok", "kind": "io", "total": 3, "passed": 1}
    # Ni le temps mural, ni une panne du juge : ce ne sont pas des fonctions
    # du code soumis.
    assert not runner.cachable({}, {"status": "timeout"})
    assert not runner.cachable({}, {"status": "compile_timeout"})
    assert not runner.cachable({}, {"status": "error", "message": "x"})
    # Une erreur de compilation, elle, est une pure fonction du code -- et
    # c'est le verdict le plus souvent répété pendant un TP.
    assert runner.cachable({}, {"status": "compile_error", "gcc": "..."})
    assert runner.cachable({}, ok)
    assert runner.cachable({}, rate)
    # `"cache": false` -- tp4-ex1 tire des dés, tp4-ex2 est un test statistique.
    assert not runner.cachable({"cache": False}, ok)
    assert not runner.cachable({"cache": False}, rate)

    spool = tempfile.mkdtemp()
    garde_spool, garde_max = runner.SPOOL, runner.CACHE_MAX
    try:
        runner.SPOOL = spool
        runner.cache_ecrire("a" * 64, ok)
        assert runner.cache_lire("a" * 64) == ok
        assert runner.cache_lire("b" * 64) is None

        # CTESTER_CACHE_MAX=0 l'éteint : le rollback ne demande pas de déployer.
        runner.CACHE_MAX = 0
        assert runner.cache_lire("a" * 64) is None
        runner.cache_ecrire("c" * 64, ok)
        runner.CACHE_MAX = garde_max
        assert runner.cache_lire("c" * 64) is None

        # ponytail: purge complète quand plein. Ce qui compte est la BORNE --
        # un magasin sans elle remplit le disque du Dell en un semestre.
        runner.CACHE_MAX = 2
        runner.cache_ecrire("d" * 64, ok)
        runner.cache_ecrire("e" * 64, ok)
        assert runner.cache_lire("d" * 64) is None, "la purge n'a pas eu lieu"
        assert runner.cache_lire("e" * 64) == ok
        runner.CACHE_MAX = garde_max

        # Un fichier corrompu est un défaut de cache, jamais une panne de juge.
        os.makedirs(os.path.join(spool, runner.CACHE_DIR), exist_ok=True)
        with open(os.path.join(spool, runner.CACHE_DIR, "f" * 64 + ".json"),
                  "w", encoding="utf-8") as fh:
            fh.write("{ pas du json")
        assert runner.cache_lire("f" * 64) is None

        # sweep() ÉPARGNE LE CACHE. Sans ça, une pause de dix minutes le
        # viderait et il ne servirait plus que pendant une rafale.
        runner.cache_ecrire("g" * 64, ok)
        vieux = os.path.join(spool, "0" * 32)
        os.mkdir(vieux)
        with open(os.path.join(vieux, "job.json"), "w", encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp1"}, fh)
        os.utime(vieux, (0, 0))
        runner.sweep(time.time())
        assert not os.path.exists(vieux), "sweep n'a pas balayé un vieux job"
        assert runner.cache_lire("g" * 64) == ok, "sweep a effacé le cache"
    finally:
        runner.SPOOL, runner.CACHE_MAX = garde_spool, garde_max
        shutil.rmtree(spool, ignore_errors=True)


def test_une_rafale_du_meme_code_ne_paie_qu_une_compilation():
    """LE CAS DU DÉBUT DE SÉANCE : vingt étudiants soumettent le gabarit non
    modifié dans la même minute. Aucun n'a fini quand les autres sont dépilés,
    donc le cache seul ne les couvre pas -- ils recompileraient tous. Celui qui
    finit le premier doit libérer les autres, et rendre leurs places à la file.

    Ce contrôle éprouve aussi les trois refus, qui comptent autant : un autre
    code n'est pas touché, un job déjà pris par un autre worker non plus, et un
    verdict qu'on ne met pas en cache n'est jamais diffusé -- geler un `timeout`
    sur vingt étudiants d'un coup serait pire que de les faire attendre."""
    racine = tempfile.mkdtemp()
    garde_spool, garde_tp = runner.SPOOL, runner.tp_path
    garde_juger, garde_max = runner._juger, runner.CACHE_MAX
    try:
        spool = os.path.join(racine, "spool")
        os.makedirs(spool)
        runner.SPOOL = spool
        runner.CACHE_MAX = 100

        tp_dir = os.path.join(racine, "exercises", "tp2-ex1", "assessment")
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, "io.json"), "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]}]}, fh)
        runner.tp_path = lambda exercise_id: tp_dir

        appels = []

        def juger_faux(job_dir, tp_dir_, mode, conf, sent):
            appels.append(sent.get("submission.c"))
            return {"status": "ok", "kind": "io", "total": 1, "passed": 1}

        runner._juger = juger_faux

        numero = [0]

        def deposer(source, exercise_id="tp2-ex1"):
            numero[0] += 1
            job_dir = os.path.join(spool, "%032x" % numero[0])
            os.mkdir(job_dir)
            with open(os.path.join(job_dir, "files.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"submission.c": source}, fh)
            with open(os.path.join(job_dir, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": exercise_id}, fh)
            return job_dir

        def fini(job_dir):
            return os.path.exists(os.path.join(job_dir, "result.json"))

        gabarit = "int main(void){\n    return 0;\n}"
        premier = deposer(gabarit)
        runner.claim(premier)  # comme main() : le worker prend son job

        # La rafale : le même code, présenté autrement par chacun.
        pareils = [deposer(gabarit),
                   deposer("// essai\nint main(void){return 0;}"),
                   deposer("int main(void)\n{\n\n\n    return 0;\n}\n")]
        autre = deposer("int main(void){return 42;}")
        ailleurs = deposer(gabarit, exercise_id="tp2-ex9")
        # Un job que l'autre worker vient de prendre : il répondra lui-même.
        pris = deposer(gabarit)
        runner.claim(pris)

        runner.write_result(premier, runner.run_job(premier))
        # La passe de priorité, celle que `main()` fait avant toute compilation.
        assert runner.servir_les_connus() == 3

        assert len(appels) == 1, appels
        for job_dir in pareils:
            assert fini(job_dir), "un doublon en file n'a pas été libéré"
            with open(os.path.join(job_dir, "result.json"),
                      encoding="utf-8") as fh:
                assert json.load(fh)["passed"] == 1
        assert not fini(autre), "un AUTRE code a reçu le verdict"
        assert not fini(ailleurs), "un autre exercice a reçu le verdict"
        assert not fini(pris), "un job déjà pris a été écrasé"

        # LA FILE S'EST VIDÉE DES DOUBLONS, et de rien d'autre. `pris` y
        # reste : un job verrouillé mais pas encore jugé est toujours en
        # attente -- c'est son worker qui le retirera.
        restants = set(runner.pending_jobs())
        assert restants == {autre, ailleurs, pris}, restants

        # LE MÉMO DE SIGNATURE NE SURVIT PAS À UNE CORRECTION DE TEST. Un job
        # est immuable une fois posé, mais l'empreinte du juge ne l'est pas :
        # sans cette invalidation, un doublon en attente recevrait le verdict
        # rendu par l'ANCIEN test, et le tick de cinq minutes ne servirait plus
        # à rien pour lui.
        tardif = deposer(gabarit)
        assert runner.servir_les_connus() == 1
        assert fini(tardif)
        with open(os.path.join(tp_dir, "io.json"), "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]},
                                 {"stdin": "", "expect": [2]}]}, fh)
        apres_correction = deposer(gabarit)
        assert runner.servir_les_connus() == 0, "verdict servi sous l'ancien test"
        assert not fini(apres_correction)

        # Le mémo ne garde que ce qui est encore en file.
        assert set(runner._SIGS) <= set(runner.pending_jobs())

        # UN VERDICT QU'ON NE MET PAS EN CACHE N'EST JAMAIS DIFFUSÉ : le
        # `timeout` d'un seul ne doit pas devenir celui de tout le monde.
        runner._juger = lambda *a: {"status": "timeout", "message": "trop long"}
        lent = deposer("while(1);")
        runner.claim(lent)
        jumeau = deposer("while (1) ;")
        runner.write_result(lent, runner.run_job(lent))
        runner.servir_les_connus()
        assert not fini(jumeau), "un timeout a été diffusé à un autre étudiant"

        # LA PASSE NE COMPILE JAMAIS : elle sert ce qui est connu, et laisse le
        # reste à la file. Sinon elle doublerait la boucle de jugement, sans
        # verrou de rang ni mesure de durée.
        runner._juger = lambda *a: (_ for _ in ()).throw(
            AssertionError("servir_les_connus a jugé"))
        runner.servir_les_connus()
    finally:
        runner.SPOOL, runner.tp_path = garde_spool, garde_tp
        runner._juger, runner.CACHE_MAX = garde_juger, garde_max
        shutil.rmtree(racine, ignore_errors=True)


def test_run_job_sert_le_cache_sans_recompiler():
    """Le contrôle de bout en bout : deux soumissions du même code ne doivent
    dépenser QU'UN conteneur. C'est la seule raison d'être de tout ce qui
    précède, et c'est ce que le juge économise pendant un TP."""
    racine = tempfile.mkdtemp()
    garde_spool, garde_tp = runner.SPOOL, runner.tp_path
    garde_juger, garde_max = runner._juger, runner.CACHE_MAX
    try:
        spool = os.path.join(racine, "spool")
        os.makedirs(spool)
        runner.SPOOL = spool
        runner.CACHE_MAX = 100

        tp_dir = os.path.join(racine, "exercises", "tp2-ex1", "assessment")
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, "io.json"), "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]}]}, fh)
        runner.tp_path = lambda exercise_id: tp_dir

        appels = []

        def juger_faux(job_dir, tp_dir_, mode, conf, sent):
            appels.append(mode)
            return {"status": "ok", "kind": "io", "total": 1, "passed": 1}

        runner._juger = juger_faux

        numero = [0]

        def soumettre(source):
            numero[0] += 1
            job_dir = os.path.join(spool, "%032x" % numero[0])
            os.mkdir(job_dir)
            with open(os.path.join(job_dir, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": "tp2-ex1"}, fh)
            with open(os.path.join(job_dir, "files.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"submission.c": source}, fh)
            return runner.run_job(job_dir)

        premier = soumettre("int main(void){return 0;}")
        assert premier["status"] == "ok"
        assert len(appels) == 1, appels

        # Le même code, autrement présenté : servi par le cache.
        second = soumettre("// essai 2\nint main(void)\n{\n\n    return 0;\n}\n")
        assert second == premier
        assert len(appels) == 1, "le juge a recompilé un code déjà jugé"

        # Un autre code : recompilé.
        soumettre("int main(void){return 1;}")
        assert len(appels) == 2, appels

        # UN CAS DE TEST CORRIGÉ INVALIDE LE CACHE. C'est le tick de cinq
        # minutes, et sans ça il servirait un verdict rendu par l'ancien test.
        with open(os.path.join(tp_dir, "io.json"), "w", encoding="utf-8") as fh:
            json.dump({"cases": [{"stdin": "", "expect": [1]},
                                 {"stdin": "", "expect": [2]}]}, fh)
        soumettre("int main(void){return 0;}")
        assert len(appels) == 3, "un test corrigé n'a pas invalidé le cache"

        # Un verdict exclu n'est jamais gardé : deux `timeout` de suite
        # dépensent deux conteneurs, et c'est voulu.
        runner._juger = lambda *a: {"status": "timeout", "message": "trop long"}
        soumettre("while(1);")
        soumettre("while(1);")
        assert runner.cache_lire(
            runner.signature("tp2-ex1", tp_dir, "io",
                             {"cases": []}, {"submission.c": "while(1);"})) is None
    finally:
        runner.SPOOL, runner.tp_path = garde_spool, garde_tp
        runner._juger, runner.CACHE_MAX = garde_juger, garde_max
        shutil.rmtree(racine, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
