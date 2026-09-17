#!/usr/bin/env python3

import contextlib
import datetime as dt
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "worker"), os.path.join(ROOT, "app"),
                os.path.join(ROOT, "admin")]

import content_catalog as content_catalogue  # noqa: E402
import journal    # noqa: E402
import publish_content  # noqa: E402
import typst_build  # noqa: E402
import config     # noqa: E402
import csp        # noqa: E402
import state      # noqa: E402
import policy as politique  # noqa: E402
import security   # noqa: E402
from services import catalog as catalogue    # noqa: E402
from services import discord      # noqa: E402
from services import forum        # noqa: E402
from services import leaderboard  # noqa: E402
from services import progress as progression  # noqa: E402
from services import quotas       # noqa: E402
from services import collab      # noqa: E402
from services import teams       # noqa: E402
from services import spool        # noqa: E402
from services import source       # noqa: E402
from services import scratch      # noqa: E402


def lire(chemin):
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


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def test_content_v2_discovery_and_public_projection():
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


def _contenu_avec_drapeau(root, valeur, drapeau="verification"):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": ["variables"]})
    exercise = os.path.join(root, "exercises", "verif-tp2")
    donnees = {"schema_version": 1, "id": "verif-tp2", "title": "Vérification",
               "skills": ["variables"], "release": {"state": "available"}}
    if valeur is not None:
        donnees[drapeau] = valeur
    _write_json(os.path.join(exercise, "exercise.json"), donnees)
    with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
        fh.write("Lis ce code.")
    _write_json(os.path.join(exercise, "assessment", "quiz.json"),
                {"questions": [{"id": "q1", "label": "?", "answer": "42"}]})


def _depot(racine, competence, *ids):
    _write_json(os.path.join(racine, "catalog.json"),
                {"schema_version": 1, "skills": [competence]})
    for exercise_id in ids:
        exercise = os.path.join(racine, "exercises", exercise_id)
        _write_json(os.path.join(exercise, "exercise.json"),
                    {"schema_version": 1, "id": exercise_id, "title": "Titre",
                     "skills": [competence], "release": {"state": "available"}})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Lis ce code.")
        _write_json(os.path.join(exercise, "assessment", "quiz.json"),
                    {"questions": [{"id": "q1", "label": "?", "answer": "42"}]})
    return racine


def _deux_depots():
    base = tempfile.mkdtemp(prefix="ctester-depots-")
    a = _depot(os.path.join(base, "cours-a", "content"), "boucles", "tp1-ex1", "tp1-ex2")
    b = _depot(os.path.join(base, "cours-b", "content"), "pointeurs", "tp9-ex1")
    return base, a, b


def test_plusieurs_depots_fusionnent_en_un_seul_catalogue():
    base, a, b = _deux_depots()
    try:
        modele = content_catalogue.discover([a, b])
        assert list(modele["exercises"]) == ["tp1-ex1", "tp1-ex2", "tp9-ex1"]
        # Le vocabulaire est l'union : un exercice peut viser une compétence déclarée ailleurs.
        assert modele["skills"] == ["boucles", "pointeurs"], modele["skills"]
        # Rien en aval ne nomme de source : la projection reste un espace de noms plat.
        public = content_catalogue.public_catalogue(modele)
        assert [e["id"] for e in public["exercises"]] == ["tp1-ex1", "tp1-ex2", "tp9-ex1"]
        assert "source" not in json.dumps(public)
    finally:
        shutil.rmtree(base)


def test_la_revision_ne_depend_pas_de_l_ordre_des_depots():
    base, a, b = _deux_depots()
    try:
        un = publish_content.revision(
            publish_content.projection(content_catalogue.discover([a, b])))
        deux = publish_content.revision(
            publish_content.projection(content_catalogue.discover([b, a])))
        assert un == deux, "reordonner CTESTER_CONTENT republierait tout le catalogue"
    finally:
        shutil.rmtree(base)


def test_un_id_partage_entre_deux_depots_bloque_la_publication():
    base, a, b = _deux_depots()
    try:
        _depot(b, "pointeurs", "tp1-ex1")
        try:
            content_catalogue.discover([a, b])
        except content_catalogue.ContentValidationError as exc:
            texte = str(exc)
            assert "duplicate exercise id: tp1-ex1" in texte, texte
            # Le message doit nommer les deux dépôts, sinon il est inutilisable.
            assert "cours-a" in texte and "cours-b" in texte, texte
        else:
            raise AssertionError("deux dépôts ont pu revendiquer le même id")
    finally:
        shutil.rmtree(base)


def test_une_seule_racine_garde_ses_messages_sans_prefixe():
    racine = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _depot(racine, "boucles", "tp1-ex1")
        os.remove(os.path.join(racine, "exercises", "tp1-ex1", "statement.md"))
        try:
            content_catalogue.discover(racine)
        except content_catalogue.ContentValidationError as exc:
            assert str(exc).startswith("exercises/tp1-ex1:"), exc
        else:
            raise AssertionError("énoncé manquant accepté")
    finally:
        shutil.rmtree(racine)


def test_content_roots_se_decoupe_comme_la_variable_d_environnement():
    assert content_catalogue.content_roots("/a") == ["/a"]
    assert content_catalogue.content_roots(["/a", "/b"]) == ["/a", "/b"]
    decoupe = content_catalogue.content_roots("/a%s%s/b%s" % (os.pathsep, os.pathsep, os.pathsep))
    assert decoupe == ["/a", "/b"], decoupe


def test_content_v2_marque_une_verification():
    for valeur, attendu in ((True, True), (False, None), (None, None)):
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _contenu_avec_drapeau(root, valeur)
            public = content_catalogue.public_catalogue(content_catalogue.discover(root))
            assert public["exercises"][0].get("verification") is attendu, valeur
            assert "answer" not in json.dumps(public)
        finally:
            shutil.rmtree(root)
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _contenu_avec_drapeau(root, "oui")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "verification" in str(exc), exc
        else:
            raise AssertionError("drapeau non booleen accepte")
    finally:
        shutil.rmtree(root)


def test_content_v2_marque_un_bonus():
    for valeur, attendu in ((True, True), (False, None), (None, None)):
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _contenu_avec_drapeau(root, valeur, "bonus")
            public = content_catalogue.public_catalogue(content_catalogue.discover(root))
            assert public["exercises"][0].get("bonus") is attendu, valeur
            assert "answer" not in json.dumps(public)
        finally:
            shutil.rmtree(root)
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _contenu_avec_drapeau(root, "oui", "bonus")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "bonus" in str(exc), exc
        else:
            raise AssertionError("drapeau non booleen accepte")
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
            assert "several modes" in message and "unknown exercise" in message, message
        else:
            raise AssertionError("contenu v2 invalide accepté")
    finally:
        shutil.rmtree(root)


def _contenu_v2(root, etat_quiz):
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
                                  "manifest.json", "staff/exercises/nombres.json",
                                  "staff/quiz/nombres.json"], sorted(publie)
        assert "answer" not in "".join(publie.values()), publie
        assert "00010111" not in "".join(publie.values()), publie
        catalogue_publie = json.loads(publie["catalog.json"])
        etats = {e["id"]: e["access"] for e in catalogue_publie["exercises"]}
        assert etats == {"surface": "available", "nombres": "scheduled"}, etats

        assert publish_content.publish(model, dest) == revision
        _write_json(os.path.join(root, "exercises", "surface", "exercise.json"), {
            "schema_version": 1, "id": "surface", "title": "Surface v2",
            "release": {"state": "available"}})
        suivante = publish_content.publish(content_catalogue.discover(root), dest)
        assert suivante != revision, suivante
        assert publish_content.current(dest) == os.path.join(dest, suivante)
        assert os.path.isdir(os.path.join(dest, revision)), "rollback impossible"

        _contenu_v2(root, {"state": "available"})
        ouvert = publish_content.publish(content_catalogue.discover(root), dest)
        quiz = json.loads(lire(os.path.join(dest, ouvert, "quiz", "nombres.json")))
        assert quiz["questions"][0]["label"] == "23" and "answer" not in str(quiz), quiz
    finally:
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_current_survives_a_broken_pointer():
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        assert publish_content.current(dest) is None
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert publish_content.current(dest) is None
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert publish_content.current(dest) is None
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "0123456789abcdef"}, fh)
        assert publish_content.current(dest) is None
    finally:
        shutil.rmtree(dest)


def test_prune_keeps_only_the_latest_releases():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        revisions = []
        for i in range(5):
            _minimal_valid_content(root)
            _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
                "schema_version": 1, "id": "ex1", "title": "Exercise %d" % i,
                "release": {"state": "available"}})
            model = content_catalogue.discover(root)
            revisions.append(publish_content.publish(model, dest, keep=3))
            for name in os.listdir(dest):
                chemin = os.path.join(dest, name)
                if os.path.isdir(chemin):
                    os.utime(chemin, (1_000_000, 1_000_000))
        assert len(set(revisions)) == 5, revisions
        remaining = {name for name in os.listdir(dest)
                    if os.path.isdir(os.path.join(dest, name))}
        assert len(remaining) == 3, remaining
        assert remaining == set(revisions[-3:]), (remaining, revisions)
        assert publish_content.current(dest) == os.path.join(dest, revisions[-1])
        orpheline = os.path.join(dest, "0" * 16)
        os.makedirs(orpheline)
        os.utime(orpheline, (1_000_000, 1_000_000))
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "Exercise 9",
            "release": {"state": "available"}})
        publish_content.publish(content_catalogue.discover(root), dest, keep=3)
        assert not os.path.isdir(orpheline), "une revision sans manifest survit"
    finally:
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_publish_content_main_publishes_and_rejects_invalid_content():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        _minimal_valid_content(root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publish_content.main([root, dest, "--keep", "3"])
        assert code == 0, out.getvalue()
        assert "published: revision" in out.getvalue()
        assert publish_content.current(dest) is not None

        before = publish_content.current(dest)
        _write_json(os.path.join(root, "catalog.json"), {"schema_version": 99})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = publish_content.main([root, dest])
        assert code == 1, err.getvalue()
        assert "publish refused" in err.getvalue()
        assert publish_content.current(dest) == before
    finally:
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_publication_refuse_un_worker_sans_contenu():
    for contenu, publie in (("", ""), ("/tmp/x", ""), ("", "/tmp/y")):
        try:
            publish_content.publish_catalogue(contenu, publie)
        except RuntimeError as exc:
            assert "CTESTER_CONTENT" in str(exc), exc
        else:
            raise AssertionError("publication silencieuse : %r %r" % (contenu, publie))


def test_publish_catalogue_really_publishes_and_says_so_in_preview():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        _contenu_v2(root, {"state": "scheduled",
                          "available_from": "2099-01-01T00:00:00-05:00"})
        exercises = publish_content.publish_catalogue(root, dest)
        assert {e["id"] for e in exercises} == {"surface", "nombres"}
        assert publish_content.current(dest) is not None
        assert not os.path.isfile(os.path.join(
            publish_content.current(dest), "exercises", "nombres.json"))

        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            publish_content.publish_catalogue(root, dest, preview=True)
        assert "PREVIEW" in capture.getvalue(), capture.getvalue()
        assert os.path.isfile(os.path.join(
            publish_content.current(dest), "exercises", "nombres.json"))
    finally:
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_content_v2_projection_refuse_une_cle_privee():
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


def _contenu_typst(root, statement=None, ouvert=True):
    _write_json(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    exercise = os.path.join(root, "exercises", "demo")
    _write_json(os.path.join(exercise, "exercise.json"), {
        "schema_version": 1, "id": "demo", "title": "Démo",
        "release": {"state": "available"} if ouvert else
                   {"state": "scheduled", "available_from": "2099-01-01T00:00:00-05:00"}})
    _write_json(os.path.join(exercise, "assessment", "io.json"),
                {"cases": [{"stdin": "1\n", "expect": [1]}]})
    _write_json(os.path.join(exercise, "public", "files.json"),
                {"files": [{"name": "submission.c", "template": ""}]})
    with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
        fh.write(statement if statement is not None else "= Titre\n\nDu texte.\n")
    return exercise


def _typst_dispo():
    try:
        typst_build._version()
        return True
    except typst_build.TypstError:
        return False


def test_typst_un_seul_format_de_statement_a_la_fois():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        exercise = _contenu_typst(root)
        modele = content_catalogue.discover(root)
        assert modele["exercises"]["demo"]["statement_format"] == "typ"
        assert modele["exercises"]["demo"]["statement"] == "", modele["exercises"]["demo"]

        os.remove(os.path.join(exercise, "statement.typ"))
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        modele = content_catalogue.discover(root)
        assert modele["exercises"]["demo"]["statement_format"] == "md"
        assert modele["exercises"]["demo"]["statement"] == "Consigne."
        assert content_catalogue.public_detail(modele, "demo") == {
            "statement": "Consigne.",
            "files": [{"name": "submission.c", "template": ""}]}, "le Markdown a bougé"

        with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
            fh.write("= x\n")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "statement.md ET statement.typ" in str(exc), exc
        else:
            raise AssertionError("les deux formats ont été acceptés")

        os.remove(os.path.join(exercise, "statement.md"))
        os.remove(os.path.join(exercise, "statement.typ"))
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "il manque statement.md ou statement.typ" in str(exc), exc
        else:
            raise AssertionError("un exercice sans consigne a été accepté")
    finally:
        shutil.rmtree(root)


def test_typst_le_detail_public_porte_un_compte_et_aucun_chemin():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _contenu_typst(root)
        modele = content_catalogue.discover(root)
        detail = content_catalogue.public_detail(modele, "demo", pages=3)
        assert detail["statement"] == "", detail
        assert detail["statement_format"] == "typst", detail
        assert detail["statement_pages"] == 3, detail
        blob = json.dumps(detail)
        for interdit in ("statements/", ".svg", "/", "typ\""):
            assert interdit not in blob.replace("\"statement_format\"", ""), (interdit, blob)
    finally:
        shutil.rmtree(root)


def test_typst_la_projection_refuse_une_source_et_un_actif_inattendu():
    modele = {"schema_version": 1, "skills": [], "collections": {}, "assignments": {},
              "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                  "skills": [], "mode": "io", "summary": "",
                                  "difficulty": None, "contexts": [], "statement": "",
                                  "statement_format": "md", "files": [], "config": {}}}}
    original = content_catalogue.public_detail
    try:
        for faux, attendu in (
                ({"x/statement.typ": {"a": 1}}, "Typst source reached"),
                ({"statements/x/dark-99.svg": b"<svg/>"}, "unexpected binary artefact"),
                ({"autre/chose.bin": b"\0\0"}, "unexpected binary artefact"),
                ({"staff/statements/x/dark-1.svg": b"<svg/>"}, None),
                ({"statements/x/light-16.svg": b"<svg/>"}, None)):
            content_catalogue.public_detail = lambda *a, **k: {"statement": ""}
            fichiers = publish_content.projection(modele)
            fichiers.update(faux)
            mauvais = [c for c, v in fichiers.items()
                       if c.endswith(".typ")
                       or (isinstance(v, bytes) and not publish_content.ACTIF_RE.match(c))]
            if attendu is None:
                assert not mauvais, (faux, mauvais)
            else:
                assert mauvais == list(faux), (faux, mauvais)
    finally:
        content_catalogue.public_detail = original


def test_typst_la_revision_bouge_quand_un_rendu_bouge():
    base = {"catalog.json": {"schema_version": 1},
            "statements/x/dark-1.svg": b"<svg>A</svg>"}
    autre = dict(base, **{"statements/x/dark-1.svg": b"<svg>B</svg>"})
    assert publish_content.revision(base) != publish_content.revision(autre)
    assert publish_content.revision(base) == publish_content.revision(dict(base))


def test_typst_la_cle_de_cache_porte_tout_ce_dont_le_rendu_depend():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        exercise = _contenu_typst(root)
        depart = typst_build.fingerprint(exercise, version="0.15.1")
        assert depart == typst_build.fingerprint(exercise, version="0.15.1")
        assert typst_build.fingerprint(exercise, version="0.99.0") != depart
        with open(os.path.join(exercise, "statement.typ"), "a", encoding="utf-8") as fh:
            fh.write("Une ligne de plus.\n")
        apres_texte = typst_build.fingerprint(exercise, version="0.15.1")
        assert apres_texte != depart
        os.makedirs(os.path.join(exercise, "images"), exist_ok=True)
        with open(os.path.join(exercise, "images", "x.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        apres_image = typst_build.fingerprint(exercise, version="0.15.1")
        assert apres_image != apres_texte
        _write_json(os.path.join(exercise, "assessment", "io.json"),
                    {"cases": [{"stdin": "9\n", "expect": [9]}]})
        assert typst_build.fingerprint(exercise, version="0.15.1") == apres_image
        theme = os.path.join(typst_build.LIB, "themes", "ctester-dark.tmTheme")
        garde = lire(theme)
        try:
            with open(theme, "a", encoding="utf-8", newline="") as fh:
                fh.write("\n<!-- x -->\n")
            assert typst_build.fingerprint(exercise, version="0.15.1") != apres_image
        finally:
            with open(theme, "w", encoding="utf-8", newline="") as fh:
                fh.write(garde)
        assert typst_build.fingerprint(exercise, version="0.15.1") == apres_image
    finally:
        shutil.rmtree(root)


def test_typst_le_cache_ne_vit_jamais_sous_published():
    garde = dict(os.environ)
    try:
        os.environ.pop("CTESTER_TYPST_CACHE", None)
        os.environ["CTESTER_PUBLISHED"] = "/opt/ctester/published"
        chemin = typst_build.cache_dir()
        assert not chemin.startswith("/opt/ctester/published/"), chemin
        assert chemin == "/opt/ctester/typst-cache", chemin
        os.environ["CTESTER_TYPST_CACHE"] = "/ailleurs"
        assert typst_build.cache_dir() == "/ailleurs"
    finally:
        os.environ.clear()
        os.environ.update(garde)


def test_typst_mermaid_n_a_qu_une_seule_porte():
    porte = os.path.join(typst_build.LIB, "mermaid.typ")
    assert '@preview/merman:0.3.0' in lire(porte), porte
    for racine, _, fichiers in os.walk(typst_build.LIB):
        for nom in fichiers:
            chemin = os.path.join(racine, nom)
            if chemin == porte or not nom.endswith(".typ"):
                continue
            assert "merman" not in lire(chemin), chemin
    manifeste = os.path.join(typst_build.PACKAGES, "preview", "merman", "0.3.0",
                             "typst.toml")
    assert 'version = "0.3.0"' in lire(manifeste), manifeste


def test_le_theme_typst_porte_les_couleurs_de_la_page():
    css = lire(os.path.join(ROOT, "frontend", "src", "app.css"))
    classes = ("comment", "string", "pre", "key", "num", "fn", "const")
    for theme, bloc in (("dark", css.split(":root {")[1].split("}")[0]),
                        ("light", css.split(':root[data-theme="light"] {')[1].split("}")[0])):
        attendues = {}
        for classe in classes:
            trouve = re.search(r"--syn-%s:\s*(#[0-9a-fA-F]{6})" % classe, bloc)
            assert trouve, (theme, classe)
            attendues[classe] = trouve.group(1).lower()
        tm = lire(os.path.join(typst_build.LIB, "themes", "ctester-%s.tmTheme" % theme))
        for classe, couleur in attendues.items():
            assert couleur in tm.lower(), \
                "--syn-%s (%s theme, %s) missing from the .tmTheme" % (classe, theme, couleur)
        for variable in ("--fg", "--panel"):
            trouve = re.search(r"%s:\s*(#[0-9a-fA-F]{3,6})" % variable, bloc)
            assert trouve and trouve.group(1).lower() in tm.lower(), (theme, variable)


def test_typst_root_refuse_de_sortir_du_repertoire_de_l_exercice():
    if not _typst_dispo():
        print("     (sauté : ni CTESTER_TYPST_BIN ni Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    garde = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        with open(os.path.join(root, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("SECRET-DU-BUILD")
        exercise = _contenu_typst(root)
        for attaque in ('#read("../../secret.txt")',
                        '#read("/etc/passwd")',
                        '#read("assessment/io.json")',
                        '#include "../../secret.txt"',
                        '#image("../../../etc/hostname")'):
            with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
                fh.write(attaque + "\n")
            try:
                typst_build.render(exercise, "demo")
            except typst_build.TypstError as exc:
                assert "SECRET-DU-BUILD" not in str(exc), (attaque, exc)
            else:
                raise AssertionError("une lecture hors de l'exercice a réussi : "
                                     + attaque)
    finally:
        if garde is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = garde
        shutil.rmtree(root)
        shutil.rmtree(cache)


def test_typst_la_fixture_compile_vraiment_dans_les_deux_themes():
    if not _typst_dispo():
        print("     (sauté : ni CTESTER_TYPST_BIN ni Docker)")
        return
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    garde = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        fixture = os.path.join(ROOT, "typst", "fixture")
        rendu, du_cache = typst_build.render(fixture, "fixture-typst")
        assert du_cache is False, "un cache frais ne peut pas déjà servir"
        assert sorted(rendu) == ["dark", "html", "light"], sorted(rendu)
        html = rendu["html"]
        assert b"<h2>" in html and b"plus_grand" in html, html[:200]
        assert b"#import" not in html
        assert len(rendu["dark"]) >= 2, "le #pagebreak() n'a pas produit deux pages"
        assert len(rendu["dark"]) == len(rendu["light"]), "les deux thèmes divergent"
        for theme in typst_build.THEMES:
            pages = rendu[theme]
            for numero, octets in enumerate(pages, 1):
                assert octets.startswith(b"<svg"), (theme, numero, octets[:40])
                assert b"plus_grand" not in octets, (theme, numero)
                assert b"#import" not in octets, (theme, numero)
        assert rendu["dark"][0] != rendu["light"][0]
        encore, du_cache = typst_build.render(fixture, "fixture-typst")
        assert du_cache is True and encore == rendu
    finally:
        if garde is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = garde
        shutil.rmtree(cache)


def test_typst_une_erreur_nomme_l_exercice_le_fichier_et_la_ligne():
    if not _typst_dispo():
        print("     (sauté : ni CTESTER_TYPST_BIN ni Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    garde = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        _contenu_typst(root, "= Titre\n\n#une-fonction-qui-n-existe-pas()\n")
        modele = content_catalogue.discover(root)
        try:
            typst_build.render_all(modele)
        except typst_build.TypstError as exc:
            message = str(exc)
            assert "demo" in message, message
            assert "statement.typ" in message, message
            assert ":3:" in message, ("pas de ligne dans le message", message)
        else:
            raise AssertionError("un statement.typ cassé a été rendu")
    finally:
        if garde is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = garde
        shutil.rmtree(root)
        shutil.rmtree(cache)


def test_typst_la_publication_ecrit_les_pages_et_respecte_le_cadenas():
    if not _typst_dispo():
        print("     (sauté : ni CTESTER_TYPST_BIN ni Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    garde = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        for ouvert, prefixe in ((True, ""), (False, "staff/")):
            _contenu_typst(root, ouvert=ouvert)
            modele = content_catalogue.discover(root)
            rendus, (total, _) = typst_build.render_all(modele)
            assert total == 1, total
            revision = publish_content.publish(modele, dest, renders=rendus)
            release = os.path.join(dest, revision)
            publie = sorted(
                os.path.relpath(os.path.join(d, n), release).replace(os.sep, "/")
                for d, _, noms in os.walk(release) for n in noms)
            attendus = [prefixe + "statements/demo/%s-1.svg" % t
                        for t in ("dark", "light")]
            for chemin in attendus:
                assert chemin in publie, (chemin, publie)
            assert not any(c.endswith(".typ") for c in publie), publie
            detail = json.loads(lire(os.path.join(
                release, prefixe + "exercises/demo.json")))
            assert detail["statement_format"] == "typst", detail
            assert detail["statement_pages"] == 1, detail
            assert detail["statement"] == "", detail
    finally:
        if garde is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = garde
        for chemin in (root, dest, cache):
            shutil.rmtree(chemin)


def test_public_catalogue_omits_malformed_contexts():
    model = {"schema_version": 1, "skills": [], "collections": {},
             "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                 "skills": [], "mode": "io", "summary": "",
                                 "difficulty": None, "contexts": None,
                                 "statement": "", "files": [], "config": {},
                                 "verification": False}}}
    public = content_catalogue.public_catalogue(model)
    assert "contexts" not in public["exercises"][0], public


def test_access_treats_an_invalid_state_as_archived():
    assert content_catalogue.access(None) == "archived"
    assert content_catalogue.access({}) == "archived"
    assert content_catalogue.access({"state": "whatever"}) == "archived"
    assert content_catalogue.access({"state": "available"}) == "available"
    assert content_catalogue.access({"state": "archived"}) == "archived"
    assert content_catalogue.access({"state": "scheduled"}) == "scheduled"
    assert content_catalogue.access(
        {"state": "scheduled", "available_from": "whatever"}) == "scheduled"


def test_iso_datetime_is_strict():
    assert content_catalogue._iso_datetime(123) is None
    assert content_catalogue._iso_datetime("whatever") is None
    assert content_catalogue._iso_datetime("2026-01-01T00:00:00") is None
    assert content_catalogue._iso_datetime("2026-01-01T00:00:00Z") is not None
    assert content_catalogue._iso_datetime("2026-01-01T00:00:00-05:00") is not None


def test_children_does_not_raise_without_a_directory():
    assert content_catalogue._children("/path/that/does/not/exist") == []


def test_files_validates_each_entry():
    f = content_catalogue._files
    assert f(None, "x", []) == [{"name": "submission.c", "template": ""}]

    errors = []
    assert f("not a list", "x", errors) == [] and errors
    errors = []
    assert f([], "x", errors) == [] and errors
    errors = []
    assert f(["not an object"], "x", errors) == []
    assert "invalid files entry" in errors[0]
    errors = []
    assert f([{"name": "invalid!.c"}], "x", errors) == []
    assert "invalid or duplicate" in errors[0]
    errors = []
    duplicate = [{"name": "a.c", "template": ""}, {"name": "a.c", "template": ""}]
    result = f(duplicate, "x", errors)
    assert len(result) == 1 and "invalid or duplicate" in errors[0]
    errors = []
    assert f([{"name": "a.c", "template": 42}], "x", errors) == []
    assert "template must be text" in errors[0]
    errors = []
    assert f([{"name": "a.c", "template": "x"}], "x", errors) == [
        {"name": "a.c", "template": "x"}]
    assert not errors


def _minimal_valid_content(root):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": []})
    exercise = os.path.join(root, "exercises", "ex1")
    _write_json(os.path.join(exercise, "exercise.json"), {
        "schema_version": 1, "id": "ex1", "title": "Exercise 1",
        "release": {"state": "available"},
    })
    with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
        fh.write("Instructions.")
    _write_json(os.path.join(exercise, "assessment", "io.json"),
                {"cases": [{"stdin": "1\n", "expect": [1]}]})
    _write_json(os.path.join(exercise, "public", "files.json"),
                {"files": [{"name": "submission.c", "template": ""}]})
    _write_json(os.path.join(root, "collections", "col1.json"), {
        "schema_version": 1, "id": "col1", "title": "Collection 1",
        "items": ["ex1"], "release": {"state": "available"},
    })


def _discover_error(root):
    try:
        content_catalogue.discover(root)
    except content_catalogue.ContentValidationError as exc:
        return str(exc)
    raise AssertionError("invalid content accepted")


def test_minimal_valid_content_does_not_raise():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        model = content_catalogue.discover(root)
        assert model["exercises"]["ex1"]["id"] == "ex1"
    finally:
        shutil.rmtree(root)


def test_discover_rejects_each_catalog_level_defect():
    cases = [
        (lambda r: _write_json(os.path.join(r, "catalog.json"),
                               {"schema_version": 2, "skills": []}),
         "expected schema_version"),
        (lambda r: _write_json(os.path.join(r, "catalog.json"),
                               {"schema_version": 1, "skills": [1, 2]}),
         "invalid skills"),
        (lambda r: _write_json(os.path.join(r, "catalog.json"),
                               {"schema_version": 1, "skills": ["a", "a"]}),
         "duplicate skills"),
    ]
    for mutate, expected in cases:
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _minimal_valid_content(root)
            mutate(root)
            message = _discover_error(root)
            assert expected in message, (expected, message)
        finally:
            shutil.rmtree(root)

    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        os.makedirs(root, exist_ok=True)
        _discover_error(root)
    finally:
        shutil.rmtree(root)


def test_discover_rejects_each_exercise_level_defect():
    def ex(r):
        return os.path.join(r, "exercises", "ex1")

    base = {"schema_version": 1, "id": "ex1", "title": "X",
            "release": {"state": "available"}}

    def with_(**extra):
        d = dict(base)
        d.update(extra)
        return d

    cases = [
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), "not an object"),
         "expected a JSON object"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(schema_version=2)),
         "expected schema_version"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(id="Bad Id!")),
         "invalid id"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(id="other")),
         "must be named after the id"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(title="   ")),
         "missing title"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(summary=42)),
         "summary must be text"),
        (lambda r: os.remove(os.path.join(ex(r), "statement.md")),
         "il manque statement.md ou statement.typ"),
        (lambda r: open(os.path.join(ex(r), "statement.typ"), "w").close(),
         "statement.md ET statement.typ sont présents"),
        (lambda r: os.remove(os.path.join(ex(r), "assessment", "io.json")),
         "no mode present"),
        (lambda r: _write_json(os.path.join(ex(r), "assessment", "io.json"),
                               {"cases": "not a list"}),
         "io requires cases"),
        (lambda r: (os.remove(os.path.join(ex(r), "assessment", "io.json")),
                    _write_json(os.path.join(ex(r), "assessment", "unity.json"), {})),
         "unity requires at least one test_"),
        (lambda r: (os.remove(os.path.join(ex(r), "assessment", "io.json")),
                    _write_json(os.path.join(ex(r), "assessment", "quiz.json"),
                               {"questions": "not a list"})),
         "quiz requires questions"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(skills=["a", "a"])),
         "skills must be a list"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(skills=["unknown"])),
         "unknown or invalid skill"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(difficulty="impossible")),
         "invalid difficulty"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(verification="yes")),
         "verification must be a boolean"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"), with_(contexts=[1, 2])),
         "contexts must be a list"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               with_(prerequisites=["a", "a"])),
         "prerequisites must be a list"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               with_(prerequisites=["Bad Id!"])),
         "invalid prerequisite"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               with_(prerequisites=["unknown"])),
         "unknown prerequisite"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               {"schema_version": 1, "id": "ex1", "title": "X",
                                "release": "not an object"}),
         "release must be an object"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               {"schema_version": 1, "id": "ex1", "title": "X",
                                "release": {"state": "unknown"}}),
         "invalid release.state"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               {"schema_version": 1, "id": "ex1", "title": "X",
                                "release": {"state": "scheduled"}}),
         "scheduled requires an ISO available_from"),
        (lambda r: _write_json(os.path.join(ex(r), "exercise.json"),
                               {"schema_version": 1, "id": "ex1", "title": "X",
                                "release": {"state": "available",
                                           "available_from": "2026-01-01T00:00:00-05:00"}}),
         "available_from is only allowed for scheduled"),
    ]
    for mutate, expected in cases:
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _minimal_valid_content(root)
            mutate(root)
            message = _discover_error(root)
            assert expected in message, (expected, message)
        finally:
            shutil.rmtree(root)


def test_discover_rejects_each_collection_level_defect():
    def col(r):
        return os.path.join(r, "collections", "col1.json")

    base = {"schema_version": 1, "id": "col1", "title": "C", "items": ["ex1"]}

    def with_(**extra):
        d = dict(base)
        d.update(extra)
        return d

    cases = [
        (lambda r: _write_json(col(r), "not an object"), "expected a JSON object"),
        (lambda r: _write_json(col(r), with_(schema_version=2)), "expected schema_version"),
        (lambda r: _write_json(col(r), with_(id="Bad Id!")), "invalid id"),
        (lambda r: _write_json(col(r), with_(id="other")), "must be named after the id"),
        (lambda r: _write_json(col(r), with_(title="   ")), "missing title"),
        (lambda r: _write_json(col(r), with_(description=42)), "description must be text"),
        (lambda r: _write_json(col(r), with_(items="not a list")), "items must be a list"),
        (lambda r: _write_json(col(r), with_(items=["ex1", "ex1"])), "items must be a list"),
        (lambda r: _write_json(col(r), with_(items=["unknown"])), "unknown exercise"),
    ]
    for mutate, expected in cases:
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _minimal_valid_content(root)
            mutate(root)
            message = _discover_error(root)
            assert expected in message, (expected, message)
        finally:
            shutil.rmtree(root)


def test_discover_accepts_a_missing_collections_directory():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        shutil.rmtree(os.path.join(root, "collections"))
        model = content_catalogue.discover(root)
        assert model["collections"] == {}
    finally:
        shutil.rmtree(root)


def test_discover_detects_duplicate_ids():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "collections", "col2.json"), {
            "schema_version": 1, "id": "col1", "title": "Duplicate", "items": ["ex1"],
            "release": {"state": "available"}})
        assert "duplicate collection id" in _discover_error(root)
    finally:
        shutil.rmtree(root)

    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex2", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "Duplicate",
            "release": {"state": "available"}})
        with open(os.path.join(root, "exercises", "ex2", "statement.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        _write_json(os.path.join(root, "exercises", "ex2", "assessment", "io.json"),
                    {"cases": []})
        assert "duplicate exercise id" in _discover_error(root)
    finally:
        shutil.rmtree(root)


def test_valid_prerequisite_does_not_raise():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        prereq = os.path.join(root, "exercises", "ex0")
        _write_json(os.path.join(prereq, "exercise.json"), {
            "schema_version": 1, "id": "ex0", "title": "Ex0",
            "release": {"state": "available"}})
        with open(os.path.join(prereq, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("x")
        _write_json(os.path.join(prereq, "assessment", "io.json"), {"cases": []})
        _write_json(os.path.join(prereq, "public", "files.json"),
                    {"files": [{"name": "submission.c", "template": ""}]})
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "X",
            "prerequisites": ["ex0"], "release": {"state": "available"}})
        model = content_catalogue.discover(root)
        assert model["exercises"]["ex1"]["prerequisites"] == ["ex0"]
    finally:
        shutil.rmtree(root)


def test_load_exercise_is_the_worker_s_gate():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _minimal_valid_content(root)
        assert content_catalogue.load_exercise(root, "../../etc/passwd") is None
        assert content_catalogue.load_exercise(root, "UNKNOWN IN UPPERCASE") is None
        assert content_catalogue.load_exercise(root, "does-not-exist") is None
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "a-different-id", "title": "X",
            "release": {"state": "available"}})
        assert content_catalogue.load_exercise(root, "ex1") is None

        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "X",
            "release": {"state": "scheduled",
                        "available_from": "2099-01-01T00:00:00-05:00"}})
        assert content_catalogue.load_exercise(root, "ex1") is None
        opened = content_catalogue.load_exercise(root, "ex1", tout=True)
        assert opened is not None and opened["mode"] == "io"

        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "assessment", "quiz.json"),
                    {"questions": []})
        assert content_catalogue.load_exercise(root, "ex1") is None
    finally:
        shutil.rmtree(root)


def test_presence_compteur():
    p = quotas.Presence()
    assert p.touch("a", 1000) == 1
    assert p.touch("b", 1000) == 2
    assert p.touch("a", 1000) == 2
    assert p.touch("c", 1000 + config.PRESENCE_TTL + 1) == 1


def test_public_quiz_hides_answers():
    public = publish_content.public_quiz(QUIZ)
    blob = json.dumps(public, ensure_ascii=False)
    assert "answer" not in blob, blob
    for question in QUIZ["questions"]:
        assert question["answer"] not in blob, question
        assert question["label"] in blob
    assert set(public["questions"][0]) == {"id", "group", "label", "type"}

    QUIZ["questions"][0]["commentaire_prof"] = "piège classique"
    try:
        assert "piège" not in json.dumps(publish_content.public_quiz(QUIZ), ensure_ascii=False)
    finally:
        del QUIZ["questions"][0]["commentaire_prof"]


def test_politique_est_declarative():
    assert politique.VERSION
    seuils = politique.POLICY["levels"]
    assert seuils[0] == 0 and seuils == sorted(seuils) == list(dict.fromkeys(seuils))
    ids = set()
    for succes in politique.POLICY["achievements"]:
        assert succes["title"] and succes["description"]
        assert succes["on"] and succes["threshold"] >= 1
        assert succes["id"] not in ids
        ids.add(succes["id"])
    assert set(politique.ACHIEVEMENTS) == ids
    bandes = politique.POLICY["mastery"]["bands"]
    for bande in bandes:
        assert bande["title"] and bande["description"]
    assert set(politique.BANDS) == {b["id"] for b in bandes} == set(
        politique.mastery_band(r, t, n)
        for n in range(0, 4) for t in range(0, n + 1) for r in range(0, t + 1))
    progression = lire(os.path.join(ROOT, "app", "services", "progress.py"))
    for montant in set(politique.POLICY["xp"].values()):
        assert not re.search(r"%d" % montant, progression), montant
    assert not re.search(r"%d" % politique.daily_cap(), progression)


def test_niveau_derive_du_solde():
    seuils = politique.POLICY["levels"]
    assert politique.level(0)["rank"] == 1
    assert politique.level(-5)["rank"] == 1
    assert politique.level(seuils[1])["rank"] == 2
    assert politique.level(seuils[1] - 1)["rank"] == 1
    au_bout = politique.level(seuils[-1] + 1000)
    assert au_bout["rank"] == len(seuils) and au_bout["next"] is None
    assert politique.level(seuils[1] - 4)["remaining"] == 4


def test_succes_derives_de_faits():
    assert politique.achievements_reached({}) == []
    assert politique.achievements_reached({"solved": 1}) == ["premiere-reussite"]
    beaucoup = politique.achievements_reached({"solved": 10, "skills": 3,
                                               "verifications": 1})
    assert set(beaucoup) == set(politique.ACHIEVEMENTS)
    assert "premiere-verification" not in politique.achievements_reached(
        {"solved": 10, "skills": 3})
    assert politique.achievements_reached({"inconnu": 99}) == []


CATALOGUE_DEMO = [
    {"id": "tp2-ex0", "skills": ["variables"], "difficulty": "intro"},
    {"id": "tp2-ex3", "skills": ["variables", "arithmetic-operators"],
     "difficulty": "foundation"},
    {"id": "tp7-ex1", "skills": ["arrays-1d"]},
    {"id": "tp1"},
]


CATALOGUE_VERIF = CATALOGUE_DEMO + [
    {"id": "verif-a", "skills": ["variables", "arithmetic-operators"],
     "verification": True},
    {"id": "verif-b", "skills": ["variables"], "verification": True},
]


def evidence(exercice, reussi):
    return {"exercise_id": exercice, "payload": {"job": "j", "passed": reussi}}


def test_projection_des_competences():
    etats = [{"exercise_id": "tp2-ex0", "status": "solved"},
             {"exercise_id": "tp2-ex3", "status": "attempted"}]
    pratique = [{"exercise_id": "tp7-ex1", "attempts": 2, "successes": 0}]
    touches, reussis = progression.exercise_facts(etats, pratique)
    assert touches == {"tp2-ex0", "tp2-ex3", "tp7-ex1"}
    assert reussis == {"tp2-ex0"}
    degraded = progression.exercise_facts(
        etats + [{"exercise_id": "", "status": "solved"}, {"status": "solved"}],
        pratique + [{"exercise_id": None}, {}])
    assert degraded == (touches, reussis)
    vue = progression.skills_view(CATALOGUE_DEMO, touches, reussis)
    assert [c["id"] for c in vue] == ["variables", "arithmetic-operators", "arrays-1d"]
    assert vue[0] == {"id": "variables", "total": 2, "practiced": 2, "solved": 1}
    assert vue[2] == {"id": "arrays-1d", "total": 1, "practiced": 1, "solved": 0}


def test_recommandation_deterministe():
    etats = [{"exercise_id": "tp2-ex0", "status": "solved"}]
    touches, reussis = progression.exercise_facts(etats, [])
    assert progression.recommend(CATALOGUE_DEMO, touches, reussis) == {
        "exercise_id": "tp2-ex3", "skill": "variables"}
    assert progression.recommend(CATALOGUE_DEMO, set(), set()) == {
        "exercise_id": "tp2-ex0", "skill": None}
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert progression.recommend(CATALOGUE_DEMO, tout, tout) is None
    assert progression.recommend([], set(), set()) is None


def test_progression_ne_publie_rien_de_secret():
    faits = {"xp": 25, "achievements": [{"id": "premiere-reussite",
                                   "unlocked_at": "2026-09-03", "policy": "x"},
                                  {"id": "disparu", "unlocked_at": "2026-09-03",
                                   "policy": "x"}],
             "transactions": [{"exercise_id": "tp2-ex0", "amount": 10,
                               "reason": "premiere reussite",
                               "granted_at": "2026-09-03"}]}
    charge = progression.progress_payload(
        CATALOGUE_DEMO, faits,
        [{"exercise_id": "tp2-ex0", "status": "solved"}], [], [])
    assert charge["policy"] == politique.VERSION
    assert charge["xp"] == 25 and charge["level"]["rank"] >= 1
    assert charge["exercises"] == {"total": 4, "practiced": 1, "solved": 1}
    assert [s["id"] for s in charge["achievements"]] == ["premiere-reussite"]
    assert charge["achievements"][0]["title"] and charge["achievements"][0]["description"]
    assert [b["id"] for b in charge["mastery"]["bands"]] == list(politique.BANDS)
    assert charge["mastery"]["skills"] == []
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("path", "answer", "statement", "sources", "template"):
        assert interdit not in texte, interdit


def test_bandes_de_maitrise_par_couverture():
    vide = progression.mastery_view(CATALOGUE_VERIF, [])
    assert [c["id"] for c in vide] == ["variables", "arithmetic-operators"]
    assert vide[0] == {"id": "variables", "total": 2, "attempted": 0,
                       "passed": 0, "band": "non-verifie"}

    une = progression.mastery_view(CATALOGUE_VERIF, [evidence("verif-a", True)])
    par_id = {c["id"]: c for c in une}
    assert par_id["variables"]["band"] == "en-progression"
    assert par_id["arithmetic-operators"]["band"] == "verifie"

    deux = progression.mastery_view(
        CATALOGUE_VERIF, [evidence("verif-b", True), evidence("verif-a", True)])
    assert {c["id"]: c["band"] for c in deux} == {
        "variables": "verifie", "arithmetic-operators": "verifie"}

    rate = progression.mastery_view(CATALOGUE_VERIF, [evidence("verif-a", False)])
    assert {c["id"]: c["band"] for c in rate} == {
        "variables": "a-consolider", "arithmetic-operators": "a-consolider"}
    assert par_id["variables"]["attempted"] == 1


def test_maitrise_retient_la_derniere_tentative():
    journal = [evidence("verif-a", False), evidence("verif-a", True)]
    assert progression.latest_attempts(journal) == {"verif-a": False}
    vue = {c["id"]: c for c in progression.mastery_view(CATALOGUE_VERIF, journal)}
    assert vue["arithmetic-operators"]["band"] == "a-consolider"
    assert progression.solved_verifications(journal) == {"verif-a"}


def test_une_pratique_ne_fait_bouger_aucune_bande():
    tout_reussi = [{"exercise_id": e["id"], "status": "solved"}
                   for e in CATALOGUE_DEMO]
    faits = {"xp": 75, "achievements": [], "transactions": []}
    charge = progression.progress_payload(CATALOGUE_VERIF, faits, tout_reussi,
                                          [], [])
    assert charge["exercises"]["solved"] == 4
    assert all(c["band"] == "non-verifie"
               for c in charge["mastery"]["skills"])


def test_une_verification_ne_compte_pas_comme_une_pratique():
    charge = progression.progress_payload(
        CATALOGUE_VERIF, {"xp": 0, "achievements": [], "transactions": []}, [], [], [])
    assert charge["exercises"]["total"] == len(CATALOGUE_DEMO)
    assert charge["next"]["exercise_id"] == "tp2-ex0"
    par_id = {c["id"]: c for c in charge["skills"]}
    assert par_id["variables"]["total"] == 2
    assert "arrays-1d" in par_id
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert progression.recommend(
        progression.practice_exercises(CATALOGUE_VERIF), tout, tout) is None


def test_aucun_index_ne_precede_la_colonne_qu_il_indexe():
    schema = lire(os.path.join(ROOT, "app", "schema.sql"))
    instructions = re.sub(r"--[^\n]*", "", schema)
    ajouts = re.findall(
        r"ALTER TABLE\s+(\w+)\s+ADD COLUMN IF NOT EXISTS\s+(\w+)", instructions)
    assert ajouts, "aucun ALTER ... ADD COLUMN : ce controle ne prouve plus rien"
    premier_alter = min(
        instructions.index(m.group(0))
        for m in re.finditer(r"ALTER TABLE\s+\w+\s+ADD COLUMN IF NOT EXISTS",
                             instructions))
    par_table = {}
    for table, colonne in ajouts:
        par_table.setdefault(table, set()).add(colonne)

    fautes = []
    for index in re.finditer(
            r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+(\w+)"
            r"\s+ON\s+(\w+)\s*\(([^)]*)\)", instructions):
        if index.start() > premier_alter:
            continue
        colonnes = {c.strip().split()[0] for c in index.group(3).split(",")
                    if c.strip()}
        tardives = colonnes & par_table.get(index.group(2), set())
        if tardives:
            fautes.append("%s indexe %s, que l'ALTER ajoute plus bas"
                          % (index.group(1), ", ".join(sorted(tardives))))
    assert not fautes, "indexes declared before their column: " + " ; ".join(fautes)


def test_chaque_table_a_ses_droits():
    schema = lire(os.path.join(ROOT, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    instructions = re.sub(r"--[^\n]*", "", schema)
    bloc = instructions[instructions.index("DO $$"):]
    bloc = re.sub(r"'\s*\n\s*'", " ", bloc)
    accordees = set()
    for cible in re.findall(r"\bON\s+(.+?)\s+TO ctester_app", bloc):
        cible = re.sub(r"\([^)]*\)", "", cible)
        accordees |= {nom.strip() for nom in cible.split(",") if nom.strip()}
    manquantes = tables - accordees
    assert not manquantes, "tables missing from every GRANT: " + ", ".join(sorted(manquantes))
    assert not accordees - tables, sorted(accordees - tables)
    assert "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctester_app')" \
        in bloc
    assert "CREATE ROLE" not in instructions, \
        "le mot de passe du role vient du vault : il ne descend pas ici"
    assert "ALL TABLES IN SCHEMA" not in instructions, instructions


def test_le_journal_ne_consomme_que_des_lignes_entieres():
    entier = json.dumps({"job_id": "a" * 32, "exercise_id": "tp1", "status": "ok",
                         "kind": "io", "duration_s": 1.5, "queue_wait_s": 0.25,
                         "worker_id": "2", "cache_hit": False, "reprises": 0,
                         "finished_at": 1_700_000_000}).encode()
    tronque = b'{"job_id": "b", "status": "ok"'
    lignes, mange = journal.parse_journal(entier + b"\n" + tronque)
    assert mange == len(entier) + 1, "la ligne tronquee a ete consommee"
    assert [ligne["job_id"] for ligne in lignes] == ["a" * 32]
    assert lignes[0]["duration_s"] == 1.5 and lignes[0]["reprises"] == 0
    # Le reste se relit depuis l'offset, une fois la ligne enfin complete.
    reste = tronque + b"}\n"
    lignes, mange = journal.parse_journal(reste)
    assert mange == len(reste)
    assert [ligne["job_id"] for ligne in lignes] == ["b"]


def test_le_journal_saute_une_ligne_illisible_sans_bloquer_le_curseur():
    bon = json.dumps({"job_id": "c"}).encode()
    blob = b"pas du json\n" + b'{"job_id": 7}\n' + b"[]\n" + bon + b"\n"
    lignes, mange = journal.parse_journal(blob)
    assert mange == len(blob), "une ligne illisible bloquerait le journal"
    assert [ligne["job_id"] for ligne in lignes] == ["c"]


def test_le_journal_s_arrete_a_sa_borne():
    blob = b"".join(json.dumps({"job_id": str(n)}).encode() + b"\n" for n in range(10))
    lignes, mange = journal.parse_journal(blob, limit=4)
    assert len(lignes) == 4
    assert mange < len(blob), "la borne doit laisser le reste pour le prochain passage"
    suite, _ = journal.parse_journal(blob[mange:], limit=100)
    assert [ligne["job_id"] for ligne in suite] == [str(n) for n in range(4, 10)]


def test_le_journal_du_juge_et_son_lecteur_parlent_des_memes_champs():
    """Le juge ecrit la ligne en Rust, l'admin la relit en Python : un champ renomme
    d'un cote seulement passerait inapercu jusqu'en production."""
    rust = lire(os.path.join(ROOT, "judge", "src", "results.rs"))
    bloc = rust[rust.index("let record = json!({"):]
    bloc = bloc[:bloc.index("});")]
    ecrits = re.findall(r'"(\w+)":', bloc)
    assert ecrits == list(journal.FIELDS), (ecrits, list(journal.FIELDS))
    # state.py stocke exactement ces champs, dans cet ordre.
    assert tuple(ecrits) == state.RUN_COLUMNS, (ecrits, state.RUN_COLUMNS)


def test_le_nom_du_journal_est_le_meme_des_deux_cotes():
    rust = lire(os.path.join(ROOT, "judge", "src", "results.rs"))
    assert 'format!("runs-{}.jsonl"' in rust, "le juge a renomme le journal"
    lecteur = lire(os.path.join(ROOT, "admin", "drain.py"))
    assert 'PATTERN = "runs-*.jsonl"' in lecteur, "l'admin cherche un autre nom"


def test_le_journal_n_est_que_de_la_bibliotheque_standard():
    texte = lire(os.path.join(ROOT, "admin", "journal.py"))
    importes = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", texte, re.M))
    assert importes <= {"json"}, sorted(importes)


def test_suppression_couvre_toutes_les_tables():
    schema = lire(os.path.join(ROOT, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    assert len(tables) == 21, tables
    blocs = dict(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);",
        schema, re.S))
    assert set(blocs) == tables, sorted(set(blocs) ^ tables)
    # judge_journal_cursor carries no account: it tracks files, not people.
    # judge_run does carry one, so forget() must clear it like any other.
    avec_compte = {nom for nom, corps in blocs.items()
                   if re.search(r"^\s*account\s+TEXT", corps, re.M)}
    assert avec_compte == tables - {"team", "team_document", "team_submission",
                                    "judge_journal_cursor"}, \
        sorted(avec_compte)
    efface = lire(os.path.join(ROOT, "app", "state.py"))
    efface = efface[efface.index("def forget(user):"):]
    assert set(re.findall(r"DELETE FROM (\w+)", efface)) == avec_compte
    assert efface.count("_query(") == 1


def test_progression_degradee_sans_base():
    assert not state.enabled()
    assert state.grant_first_solve("u", "tp", "e", 10, "m", "v", {}, 100) is None
    assert state.unlock("u", ["premiere-reussite"], "e", "v") is False
    assert state.unlock("u", [], "e", "v") is True
    assert state.read_progress("u") is None
    assert state.record_event("u", "e", "T", "tp", "v", {}) is None
    assert state.read_events("u", "T") is None
    assert state.read_theme("u") is None
    assert state.write_theme("u", "light") is False
    assert state.write_theme("u", "neon") is False
    assert state.forget("u") is False
    assert progression.progression_facts("u") is None
    assert progression.cards_to_grant("u") == []


def test_every_persistence_function_degrades_without_a_database():
    assert not state.enabled()
    cases = [
        (state.read_resume, ("u", "ex"), None),
        (state.write_draft, ("u", "ex", {}), False),
        (state.write_state, ("u", "ex", "solved", {}), False),
        (state.read_states, ("u",), None),
        (state.write_practice_attempt,
         ("u", "j", "ex", {"status": "ok", "total": "three", "passed": "two"}), False),
        (state.read_practice_summary, ("u",), None),
        (state.read_practice_days, ("u", 30), None),
        (state.read_unlock_rates, (), None),
        (state.leaderboard_rows, (None, 7), None),
        (state.forum_thread, ("ex", 10), None),
        (state.forum_post, ("m", "ex", "u", "x"), False),
        (state.forum_open_to_group, ("m", "u"), None),
        (state.forum_vote, ("m", "u", 1), None),
        (state.forum_unvote, ("m", "u"), None),
        (state.forum_reply, ("m", "ex", "u", "x", "r"), None),
        (state.forum_search, ("quoi", "u", 5), None),
        (state.forum_top, (8, 10), None),
        (state.forum_delete, ("m", "u"), None),
        (state.forum_report, ("m", "u"), None),
        (state.forum_reports, (10,), None),
        (state.forum_moderate, ("a", "m", "u", "hide"), None),
        (state.forum_profiles, (["u"],), None),
        (state.forum_profile, ("u",), None),
        (state.forum_write_profile, ("p", "u", None, None, False, False), False),
        (state.forum_taken_aliases, (), None),
        (state.forum_report_name, ("m", "u"), None),
        (state.forum_reported_names, (10,), None),
        (state.forum_help_rows, (10, 8), None),
        (state.forum_author, ("m",), None),
    ]
    for function, args, expected in cases:
        assert function(*args) == expected, function.__name__


def test_close_is_idempotent_and_absorbs_a_failed_shutdown():
    guard = state._conn
    try:
        state._conn = None
        state._close()
        assert state._conn is None

        class FailingConnection:
            def close(self):
                raise RuntimeError("connection already dead")
        state._conn = FailingConnection()
        state._close()
        assert state._conn is None
    finally:
        state._conn = guard


def test_forum_moderer_and_profils_refuse_without_touching_the_database():
    assert state.forum_moderate("a", "m", "u", "bogus") == []
    assert state.forum_profiles([]) == {}
    assert state.forum_profiles([None, ""]) == {}


def test_minute_falls_back_to_a_string_for_what_is_not_a_date():
    assert state._minute("2026-09-04 12:00") == "2026-09-04 12:00"[:16]


def test_sources_refuses_what_is_not_a_json_object():
    assert state._sources([]) is None
    assert state._sources(None) is None
    assert state._sources([("not json",)]) is None
    assert state._sources([("[1, 2, 3]",)]) is None
    assert state._sources([('{"a": 1}',)]) == {"a": "1"}


class _PartialOutage:
    def grant_first_solve(self, *a, **k):
        return 10

    def record_event(self, *a, **k):
        return "an-id"

    def read_states(self, *a, **k):
        return None

    def read_practice_summary(self, *a, **k):
        return None

    def read_events(self, *a, **k):
        return None

    def unlock(self, *a, **k):
        raise AssertionError("unlock() must never be called without the facts")


def test_recompenser_and_verification_survive_an_outage_between_write_and_reread():
    guard = progression.state
    try:
        progression.state = _PartialOutage()
        entry = {"id": "tp2-ex0", "difficulty": "foundation"}
        progression.reward("u", entry, "job1")
        progression.record_verification("u", entry, "job2", True)
    finally:
        progression.state = guard


def test_scan_jobs_survives_a_missing_spool_and_a_directory_still_being_written():
    guard = config.SPOOL
    try:
        config.SPOOL = os.path.join(tempfile.mkdtemp(prefix="ctester-spool-"), "does-not-exist")
        assert spool.scan_jobs() == []

        config.SPOOL = os.path.dirname(config.SPOOL)
        os.makedirs(config.SPOOL, exist_ok=True)
        os.makedirs(os.path.join(config.SPOOL, "in-progress"))
        assert spool.scan_jobs() == []
    finally:
        config.SPOOL = guard


def test_durees_moyennes_ignores_a_file_that_is_not_an_object():
    guard = config.RESULTS
    try:
        config.RESULTS = tempfile.mkdtemp(prefix="ctester-results-")
        with open(os.path.join(config.RESULTS, spool.DURATIONS), "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        assert spool.average_durations() == {}
    finally:
        shutil.rmtree(config.RESULTS, ignore_errors=True)
        config.RESULTS = guard


def test_l_api_ne_peut_ni_ecrire_ni_preparer_un_verdict():
    # The judge alone creates results/<id>: a web tier that could pre-create it would be back to
    # handing root a tree it controls.
    compose = lire(os.path.join(ROOT, "deploy", "compose.yml"))
    web = compose.split("\n  web:\n", 1)[1].split("\n\n", 1)[0]
    assert "- ../../results:/results:ro" in web, "results must be mounted read-only into web"
    assert "CTESTER_RESULTS: /results" in web
    for chemin in ("routers/submission.py", "services/spool.py", "services/scratch.py"):
        source = lire(os.path.join(ROOT, "app", chemin))
        for ecriture in re.findall(r"open\(os\.path\.join\(config\.RESULTS[^)]*\)[^)]*\)", source):
            assert '"w' not in ecriture and '"a' not in ecriture, (chemin, ecriture)


def test_eta_secondes_returns_zero_for_an_already_finished_or_unknown_job():
    jobs = [("aaa", 100.0, False), ("bbb", 101.0, True)]
    assert spool.eta_seconds(jobs, "bbb") == 0
    assert spool.eta_seconds(jobs, "unknown") == 0


def test_job_metadata_refuses_a_job_json_that_is_not_an_object():
    guard = config.SPOOL
    try:
        config.SPOOL = tempfile.mkdtemp(prefix="ctester-spool-")
        job = "a" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        assert spool.job_metadata(job) == ("", None)
    finally:
        shutil.rmtree(config.SPOOL, ignore_errors=True)
        config.SPOOL = guard


def test_job_sources_ignores_an_unreadable_submission_file():
    guard = config.SPOOL
    try:
        config.SPOOL = tempfile.mkdtemp(prefix="ctester-spool-")
        job = "b" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        entry = {"id": "ex1", "mode": "io", "files": [{"name": "submission.c"}]}
        assert spool.job_sources(job, entry) == {}
        with open(os.path.join(config.SPOOL, job, "files.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert spool.job_sources(job, entry) == {}
        assert spool.job_sources(job, {"mode": "quiz"}) == {}
        with open(os.path.join(config.SPOOL, job, "files.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"an-unexpected-name.c": "x"}, fh)
        assert spool.job_sources(job, entry) == {}
    finally:
        shutil.rmtree(config.SPOOL, ignore_errors=True)
        config.SPOOL = guard


def test_queue_position():
    jobs = [("aaa", 100.0, True), ("bbb", 101.0, False), ("ccc", 102.0, False)]
    assert spool.queue_position(jobs, "bbb") == 1
    assert spool.queue_position(jobs, "ccc") == 2
    assert spool.queue_position(jobs, "aaa") == 0
    assert spool.queue_position(jobs, "inconnu") == 0


def test_quota():
    q = quotas.Quota(cooldown=15, hourly=3)
    now = time.time()
    assert q.check("ip", now) == 0
    wait = q.check("ip", now + 1)
    assert 0 < wait <= 15, wait
    assert q.check("ip", now + 16) == 0
    assert q.check("ip", now + 40) == 0
    assert q.check("ip", now + 60) > 0
    assert q.check("autre", now + 60) == 0
    assert q.check("ip", now + 3700) == 0


def test_quota_prunes_its_inactive_clients_past_five_thousand():
    q = quotas.Quota(cooldown=0, hourly=100)
    now = time.time()
    for i in range(5000):
        assert q.check("client-%d" % i, now) == 0
    assert len(q.seen) == 5000
    q.check("expired-client", now - 7200)
    assert "expired-client" in q.seen
    q.check("fresh-client", now)
    assert len(q.seen) < 5002
    assert "expired-client" not in q.seen, "an expired window should have left"
    assert "fresh-client" in q.seen and "client-0" in q.seen


def test_presence_prunes_its_expired_windows_past_five_thousand():
    p = quotas.Presence()
    now = time.time()
    for i in range(5000):
        p.touch("window-%d" % i, now)
    assert len(p.seen) == 5000
    p.touch("expired", now - config.PRESENCE_TTL - 1)
    p.touch("fresh", now)
    assert len(p.seen) < 5002
    assert "expired" not in p.seen
    assert "fresh" in p.seen


def test_client_id():
    assert security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({}, "10.0.0.1") == "10.0.0.1"


def test_client_id_prefers_the_authenticated_account_over_any_ip():
    garde = security.current_user
    try:
        security.current_user = lambda entetes: "sub-" + "x" * 100
        identifiant = security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1")
        assert identifiant.startswith("u:") and len(identifiant) == 2 + 62
    finally:
        security.current_user = garde


def test_client_id_station_suffix_and_the_two_truncation_bounds():
    assert security.client_id({}, "10.0.0.1", station="poste-3") == "10.0.0.1/poste-3"
    identifiant = security.client_id({}, "x" * 200, station="poste-3")
    assert len(identifiant) == 128
    identifiant = security.client_id({"CF-Connecting-IP": "y" * 200}, "10.0.0.1")
    assert identifiant == "y" * 64


def test_no_redirect_refuses_to_hand_a_bearer_token_to_a_redirect_target():
    assert security._NoRedirect().redirect_request(
        None, None, 302, "Found", {}, "https://evil.exemple") is None


def test_oidc_enabled_requires_all_three_conditions_independently():
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.state = type("Base", (), {"enabled": staticmethod(lambda: True)})
        assert security.oidc_enabled()

        config.OIDC_ISSUER = "http://auth.exemple"
        assert not security.oidc_enabled()
        config.OIDC_ISSUER = "https://auth.exemple"

        config.OIDC_CLIENT_ID = ""
        assert not security.oidc_enabled()
        config.OIDC_CLIENT_ID = "ctester"

        security.state = type("Base", (), {"enabled": staticmethod(lambda: False)})
        assert not security.oidc_enabled()
    finally:
        config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state = garde


def test_userinfo_url_refuses_an_endpoint_outside_the_issuer():
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")
        security._get_json = lambda url, headers=None: {
            "userinfo_endpoint": "https://evil.exemple/steal"}
        assert security.userinfo_url() == ""
        def interdit(url, headers=None):
            raise AssertionError("must not be called under the negative cache")
        security._get_json = interdit
        assert security.userinfo_url() == ""
    finally:
        config.OIDC_ISSUER = garde_issuer
        security._get_json = garde_json
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_userinfo_url_accepts_an_endpoint_under_the_issuer_and_caches_it():
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")
        appels = []

        def repond(url, headers=None):
            appels.append(url)
            return {"userinfo_endpoint": "https://auth.exemple/userinfo"}
        security._get_json = repond
        assert security.userinfo_url() == "https://auth.exemple/userinfo"
        assert security.userinfo_url() == "https://auth.exemple/userinfo"
        assert len(appels) == 1
    finally:
        config.OIDC_ISSUER = garde_issuer
        security._get_json = garde_json
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_userinfo_url_survives_a_broken_discovery_document():
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")

        def echoue(url, headers=None):
            raise OSError("network failure")
        security._get_json = echoue
        assert security.userinfo_url() == ""
    finally:
        config.OIDC_ISSUER = garde_issuer
        security._get_json = garde_json
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_ask_userinfo_bounds_the_sub_and_sanitizes_the_suggested_name():
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")

        security._get_json = lambda url, headers=None: {
            "sub": "abc123", "preferred_username": "Léa"}
        sub, nom = security._ask_userinfo("tok")
        assert sub == "abc123" and nom

        security._get_json = lambda url, headers=None: {"sub": "a" * 128}
        assert security._ask_userinfo("tok")[0] == "a" * 128
        security._get_json = lambda url, headers=None: {"sub": "a" * 129}
        assert security._ask_userinfo("tok")[0] is None

        security._get_json = lambda url, headers=None: {"sub": ""}
        assert security._ask_userinfo("tok")[0] is None
        security._get_json = lambda url, headers=None: {"sub": 12345}
        assert security._ask_userinfo("tok")[0] is None

        security._discovery.update(until=0.0, userinfo="")
        config.OIDC_ISSUER = ""
        assert security._ask_userinfo("tok") == (None, "")
    finally:
        config.OIDC_ISSUER = garde_issuer
        security._get_json = garde_json
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_current_user_bounds_the_bearer_token_and_caches_the_lookup():
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state, security._get_json)
    garde_tokens = dict(security._tokens)
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.state = type("Base", (), {"enabled": staticmethod(lambda: True)})
        security._tokens.clear()
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")

        assert security.current_user({}) is None
        assert security.current_user({"Authorization": "Basic xx"}) is None
        assert security.current_user({"Authorization": "Bearer "}) is None
        trop_long = "Bearer " + "x" * 4097
        assert security.current_user({"Authorization": trop_long}) is None

        appels = []

        def repond(url, headers=None):
            appels.append(1)
            return {"sub": "etu-1"}
        security._get_json = repond
        pile = "Bearer " + "x" * 4096
        assert security.current_user({"Authorization": pile}) == "etu-1"
        assert len(appels) == 1
        assert security.current_user({"Authorization": pile}) == "etu-1"
        assert len(appels) == 1
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state,
         security._get_json) = garde
        security._tokens.clear()
        security._tokens.update(garde_tokens)
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_token_cache_flushes_fully_once_it_reaches_its_cap():
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state, security._get_json)
    garde_tokens = dict(security._tokens)
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.state = type("Base", (), {"enabled": staticmethod(lambda: True)})
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")
        security._get_json = lambda url, headers=None: {"sub": "etu"}

        security._tokens.clear()
        for i in range(security.TOKENS_MAX - 1):
            security._tokens["f%d" % i] = ("s", "", time.time() + 300)
        assert len(security._tokens) == security.TOKENS_MAX - 1

        security.current_user({"Authorization": "Bearer tokenA"})
        assert len(security._tokens) == security.TOKENS_MAX

        security.current_user({"Authorization": "Bearer tokenB"})
        assert len(security._tokens) == 1
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state,
         security._get_json) = garde
        security._tokens.clear()
        security._tokens.update(garde_tokens)
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_current_name_only_reads_the_cache_it_never_calls_out():
    garde_tokens = dict(security._tokens)
    try:
        security._tokens.clear()
        jeton = "abc"
        empreinte = hashlib.sha256(jeton.encode()).hexdigest()
        assert security.current_name({"Authorization": "Bearer " + jeton}) == ""
        assert security.current_name({}) == ""

        security._tokens[empreinte] = ("sub-1", "Lea", time.time() + 60)
        assert security.current_name({"Authorization": "Bearer " + jeton}) == "Lea"

        security._tokens[empreinte] = ("sub-1", "Lea", time.time() - 1)
        assert security.current_name({"Authorization": "Bearer " + jeton}) == ""
    finally:
        security._tokens.clear()
        security._tokens.update(garde_tokens)


def test_ask_userinfo_swallows_a_broken_lookup():
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")
        security._get_json = lambda url, headers=None: (_ for _ in ()).throw(
            OSError("network failure"))
        assert security._ask_userinfo("tok") == (None, "")
    finally:
        config.OIDC_ISSUER = garde_issuer
        security._get_json = garde_json
        security._discovery.clear()
        security._discovery.update(garde_disc)


def test_get_json_reads_a_bounded_response_and_never_follows_a_redirect():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/ok":
                corps = b'{"hello": "world"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)
            else:
                self.send_response(302)
                self.send_header("Location", "http://exemple-interdit.invalid/vole")
                self.end_headers()

    serveur = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    try:
        port = serveur.server_port
        assert security._get_json(f"http://127.0.0.1:{port}/ok") == {"hello": "world"}
        try:
            security._get_json(f"http://127.0.0.1:{port}/redirige")
            assert False, "a redirect must not resolve silently"
        except Exception:
            pass
    finally:
        serveur.shutdown()
        fil.join(timeout=2)


def test_forum_eteint_par_defaut():
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS, security.state)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.state = type("Base", (), {"enabled": staticmethod(lambda: True)})
        config.FORUM_MODERATORS = frozenset()
        assert security.oidc_enabled() and not forum.forum_enabled()
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        assert forum.forum_enabled()
        assert security.is_moderator("sub-mod") and not security.is_moderator("sub-alice")
        assert not security.is_moderator("") and not security.is_moderator(None)
        config.OIDC_ISSUER = ""
        assert not forum.forum_enabled()
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS,
         security.state) = garde


def test_forum_texte_borne_et_stocke_la_source():
    assert forum.forum_text("  Pourquoi mon while ne s'arrete pas ?  ") == (
        "Pourquoi mon while ne s'arrete pas ?", None)
    assert forum.forum_text("")[0] is None
    assert forum.forum_text("   \n  ")[0] is None
    assert forum.forum_text(None)[0] is None
    assert forum.forum_text(42)[0] is None
    assert forum.forum_text("x" * (config.FORUM_MAX_CHARS + 1))[0] is None
    assert forum.forum_text("x" * config.FORUM_MAX_CHARS)[0] is not None
    hostile = "<script>alert(1)</script> et **gras**"
    assert forum.forum_text(hostile)[0] == hostile
    assert forum.forum_text("[doc](https://exemple.test)")[0] \
        == "[doc](https://exemple.test)"
    assert forum.forum_text("a\x00b\x07c")[0] == "abc"
    assert forum.forum_text("ligne 1\r\nligne 2")[0] == "ligne 1\nligne 2"


def test_forum_bibliotheques_epinglees():
    manifeste = json.loads(lire(os.path.join(ROOT, "package.json")))
    epingles = manifeste.get("dependencies") or {}
    charge_par = {
        "marked": {"frontend/src/lib/domain/markdown.ts"},
        "dompurify": {"frontend/src/lib/domain/markdown.ts"},
        "yjs": {"frontend/src/lib/collab/document.ts",
                "frontend/src/lib/collab/room.svelte.ts"},
    }
    assert set(epingles) == set(charge_par), epingles
    for paquet, modules in charge_par.items():
        version = epingles[paquet]
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), (paquet, version)
        for module in modules:
            assert '"' + paquet + '"' in lire(
                os.path.join(ROOT, *module.split("/"))), (paquet, module)
    for racine, _, fichiers in os.walk(os.path.join(ROOT, "frontend", "src")):
        for nom in fichiers:
            if not nom.endswith((".ts", ".svelte")):
                continue
            chemin = os.path.join(racine, nom)
            relatif = os.path.relpath(chemin, ROOT).replace(os.sep, "/")
            source = lire(chemin)
            for paquet, modules in charge_par.items():
                if relatif in modules:
                    continue
                assert 'from "' + paquet + '"' not in source, (relatif, paquet)


def test_csp_without_an_issuer_omits_the_extra_connect_src_origin():
    without_issuer = csp.csp(b"<html></html>")
    with_issuer = csp.csp(b"<html></html>", "https://auth.exemple/auth/v1")
    assert "auth.exemple" not in without_issuer, without_issuer
    assert "auth.exemple" in with_issuer, with_issuer
    without_https = csp.csp(b"<html></html>", "http://auth.exemple")
    assert "auth.exemple" not in without_https, without_https

    def directives(policy):
        return {d.split()[0]: d for d in policy.split("; ")}

    a, b = directives(without_issuer), directives(with_issuer)
    assert set(a) == set(b)
    for key in a:
        if key != "connect-src":
            assert a[key] == b[key], key


def test_csp_du_document():
    pages = [lire(os.path.join(ROOT, "frontend", "index.html")).encode()]
    construit = os.path.join(ROOT, "frontend", "dist", "index.html")
    if os.path.exists(construit):
        pages.append(lire(construit).encode())
    for page in pages:
        assert b"<script" in page and not csp._INLINE_SCRIPT_RE.findall(page), page
    page = pages[0]
    politique = csp.csp(page, "https://auth.exemple/auth/v1")
    assert "default-src 'none'" in politique
    assert "sha256-" not in politique, politique
    assert "script-src 'self';" in politique, politique
    assert b"<script" in page and not csp._INLINE_SCRIPT_RE.findall(page), page
    for inline in (b"<script>var t=1;</script>", b"<SCRIPT>var t=1;</SCRIPT>"):
        try:
            csp.csp(inline)
            raise AssertionError("un <script> inline est passe sans rien dire")
        except ValueError:
            pass
    assert "https://auth.exemple" in politique.split("connect-src")[1]
    assert "/auth/v1" not in politique, politique
    assert config.API_ORIGIN in politique.split("connect-src")[1]
    for interdit in ("frame-ancestors 'none'", "base-uri 'none'",
                     "form-action 'none'", "img-src 'self'"):
        assert interdit in politique, interdit
    assert "style-src 'self' 'unsafe-inline'" in politique
    assert "unsafe-inline" not in politique.split("style-src")[0], politique
    assert "unsafe-eval" not in politique

    meta = re.search(
        rb'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert meta, "le <meta> CSP a disparu de index.html"
    du_meta = {d.split()[0]: " ".join(d.split()[1:])
               for d in meta.group(1).decode().split("; ")}
    du_serveur = {d.split()[0]: " ".join(d.split()[1:])
                  for d in csp.csp(page, config.OIDC_ISSUER or
                                   "https://auth.thevhome.com/auth/v1").split("; ")}
    assert "frame-ancestors" not in du_meta, du_meta
    assert du_serveur.pop("frame-ancestors") == "'none'"
    assert du_meta == du_serveur, (du_meta, du_serveur)


def test_forum_vue_ne_laisse_sortir_aucun_sub():
    garde = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "account": "sub-alice", "text": "moi",
                "hidden": False, "created_at": "2026-09-03 10:00"},
               {"id": "b" * 32, "account": "sub-bob", "text": "lui",
                "hidden": False, "created_at": "2026-09-03 10:01"},
               {"id": "c" * 32, "account": "sub-mod", "text": "eux",
                "hidden": False, "created_at": "2026-09-03 10:02"},
               {"id": "d" * 32, "account": "sub-bob", "text": "cache",
                "hidden": True, "created_at": "2026-09-03 10:03"}]
        vu = forum.forum_view(fil, "sub-alice", False)
        assert [m["author"] for m in vu] == [
            "Vous", "Participant", "Enseignant"], vu
        assert [m["mine"] for m in vu] == [True, False, False]
        assert len(vu) == 3
        texte = json.dumps(vu, ensure_ascii=False)
        for interdit in ("sub-alice", "sub-bob", "sub-mod", "account"):
            assert interdit not in texte, interdit
        vu_mod = forum.forum_view(fil, "sub-mod", True)
        assert len(vu_mod) == 4 and vu_mod[3]["hidden"] is True
        assert vu_mod[2]["author"] == "Vous"
        assert "sub-bob" not in json.dumps(vu_mod, ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = garde


def test_forum_identite_bornes_et_visibilite():
    assert forum.forum_display_name(None) == (None, None)
    assert forum.forum_display_name(42) == (None, "nom invalide")
    assert forum.forum_display_name("   ") == (None, None)
    assert forum.forum_display_name("  Lea   B ") == ("Lea B", None)
    assert forum.forum_display_name("Lea" + chr(10) + "B")[0] == "Lea B"
    for reserve in ("Vous", "participant", "Enseignant", "Équipe du cours",
                    "Anonyme"):
        assert forum.forum_display_name(reserve)[0] is None, reserve
    assert forum.forum_display_name("x" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    garde_g = config.FORUM_GROUPS
    try:
        config.FORUM_GROUPS = (4, 6)
        assert forum.forum_group("04") == (4, None)
        for mauvais in (0, 100, -1, "sept", True, 7):
            assert forum.forum_group(mauvais)[0] is None, mauvais
        config.FORUM_GROUPS = ()
        assert forum.forum_group("07") == (7, None)
        for mauvais in (0, 100, -1, "sept", True):
            assert forum.forum_group(mauvais)[0] is None, mauvais
    finally:
        config.FORUM_GROUPS = garde_g

    garde = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "account": "sub-bob", "text": "x",
                "hidden": False, "created_at": "2026-09-03T10:00Z"}]
        cache = {"sub-bob": {"display_name": "Bob", "group_number": 7,
                             "display_name_public": False, "group_number_public": False}}
        vu = forum.forum_view(fil, "sub-alice", False, cache)[0]
        assert vu["author"] == "Participant" and vu["group"] is None
        assert vu["reportable_name"] is False
        vu_mod = forum.forum_view(fil, "sub-mod", True, cache)[0]
        assert vu_mod["author"] == "Participant" and vu_mod["group"] == 7
        montre = {"sub-bob": dict(cache["sub-bob"], display_name_public=True)}
        vu2 = forum.forum_view(fil, "sub-alice", False, montre)[0]
        assert vu2["author"] == "Bob" and vu2["reportable_name"] is True
        a_moi = forum.forum_view(fil, "sub-bob", False, montre)[0]
        assert a_moi["author"] == "Vous" and a_moi["reportable_name"] is False
        assert "sub-bob" not in json.dumps(
            [vu, vu_mod, vu2, a_moi], ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = garde


def test_le_controle_de_l_hote_ne_depend_d_aucun_tiers():
    tiers = {"starlette", "fastapi", "pydantic", "pydantic_core", "uvicorn",
             "httpx", "httpx2", "anyio", "h11"}
    charges = sorted(tiers & {m.split(".")[0] for m in sys.modules})
    assert not charges, "host-side imports pulled third-party packages: " + ", ".join(charges)


def test_les_deux_sondes_de_verrou_ouvrent_en_LECTURE_SEULE():
    source = lire(os.path.join(ROOT, "app", "services", "scratch.py"))
    corps = source[source.index("def _lock_held("):]
    corps = corps[:corps.index("os.close(fd)")]
    assert "os.O_RDONLY" in corps and "os.O_RDWR" not in corps, "_lock_held must probe read-only"
    # The judge only reads the API's spool, locks included: nothing there is opened to write.
    source = lire(os.path.join(ROOT, "judge", "src", "spool.rs"))
    assert "OFlags::RDONLY" in source
    for ecriture in ("RDWR", "WRONLY", "CREATE", "APPEND", "TRUNC"):
        assert ecriture not in source, "spool.rs opens the spool with " + ecriture


def test_chaque_raison_de_console_a_un_message():
    juge = "".join(lire(os.path.join(ROOT, "judge", "src", nom)) for nom in ("console.rs", "main.rs"))
    page = lire(os.path.join(ROOT, "frontend", "src", "features", "scratch",
                             "session.svelte.ts"))
    bloc = page.split("const REASONS: Record<string, string> = {")[1].split("};")[0]
    connues = set(re.findall("^\\s*(\\w+):", bloc, re.M)) | {"exited"}
    motif = r'(?:break |exited\([^)]*, |(?:== 12|else) \{\s*|"reason": )"([a-z_]+)"'
    emises = set(re.findall(motif, juge))
    assert len(emises) >= 9, emises
    orphelines = sorted(emises - connues)
    assert not orphelines, "console reasons with no message: " + ", ".join(orphelines)


def test_les_websockets_ont_une_implementation_epinglee():
    besoin = lire(os.path.join(ROOT, "requirements.txt"))
    lignes = [l.split("#")[0].strip() for l in besoin.splitlines()]
    paquets = {l.split("==")[0].strip().lower() for l in lignes if "==" in l}
    assert paquets & {"wsproto", "websockets"}, "requirements.txt pins no WebSocket implementation"


def test_le_conteneur_web_n_importe_que_ce_qu_il_monte():
    racine = {nom[:-3] for nom in os.listdir(os.path.join(ROOT, "worker"))
              if nom.endswith(".py")}
    dans_app = {nom[:-3] for nom in os.listdir(os.path.join(ROOT, "app"))
                if nom.endswith(".py")}
    interdits = racine - dans_app
    assert "content_catalog" in interdits, interdits
    motif = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                       re.M)
    fautes = []
    for dossier, _sous, fichiers in os.walk(os.path.join(ROOT, "app")):
        if "__pycache__" in dossier:
            continue
        for nom in sorted(fichiers):
            if not nom.endswith(".py"):
                continue
            chemin = os.path.join(dossier, nom)
            for module in motif.findall(lire(chemin)):
                if module in interdits:
                    fautes.append(os.path.relpath(chemin, ROOT) + " -> " + module)
    assert not fautes, (
        "ces modules de la racine ne sont pas montés dans le conteneur web : "
        + ", ".join(fautes))


def _cas_canoniques():
    chemin = os.path.join(ROOT, "frontend", "tests", "fixtures", "source.json")
    with open(chemin, encoding="utf-8") as fh:
        return json.load(fh)


def test_le_fixture_de_la_forme_canonique_est_bien_la():
    cas = _cas_canoniques()
    assert len(cas["encodage"]) >= 6, cas
    assert len(cas["espaces_morts"]) >= 5, cas
    assert len(cas["silences"]) >= 7, cas


def test_la_forme_canonique_retire_ce_qui_ne_se_voit_pas():
    cas = _cas_canoniques()
    for groupe in ("encodage", "espaces_morts"):
        for c in cas[groupe]:
            assert source.canonicalize(c["in"]) == c["out"], (groupe, c["why"])


def test_la_forme_canonique_se_tait_sur_tout_le_reste():
    cas = _cas_canoniques()
    for c in cas["silences"]:
        assert c["out"] == c["in"], ("ce cas doit être un point fixe", c["why"])
        assert source.canonicalize(c["in"]) == c["in"], c["why"]


def test_la_forme_canonique_epargne_un_raccord_de_lignes():
    assert source.canonicalize("#define F(a) \\   \n") == "#define F(a) \\   \n"
    assert source.canonicalize("#define F(a)     \n") == "#define F(a)\n"


def test_la_forme_canonique_ne_change_jamais_le_nombre_de_lignes():
    cas = _cas_canoniques()
    tous = cas["encodage"] + cas["espaces_morts"] + cas["silences"]
    for c in tous + [{"in": x, "why": x} for x in
                     ("", "x", "x\n", "x\n\n\n", "\n\n", "   ", "a\n   ")]:
        avant = c["in"]
        apres = source.canonicalize(avant)
        if "\r" not in avant:
            assert apres.count("\n") == avant.count("\n"), c["why"]
        assert len(apres) <= len(avant), c["why"]
        assert source.canonicalize(apres) == apres, c["why"]


def test_la_liste_blanche_rend_une_forme_canonique():
    entree = {"id": "tp2-ex3", "files": [{"name": "submission.c"}]}
    fichiers, message, code = catalogue.validate_files(
        entree, {"submission.c": "\ufeffint main(void){\r\n    return 0;   \r\n}\r\n"})
    assert message is None, message
    assert fichiers == {"submission.c": "int main(void){\n    return 0;\n}\n"}, fichiers
    enveloppe = len(json.dumps({"submission.c": ""}).encode())
    pile = "a" * (config.MAX_CODE - enveloppe - 4) + "\n" + "   "
    fichiers, message, code = catalogue.validate_files(entree, {"submission.c": pile})
    assert message is None, (message, code)
    assert len(json.dumps(fichiers).encode()) <= config.MAX_CODE


def test_la_console_canonise_par_la_meme_porte():
    code, message, statut = scratch.validate_scratch("int x;   \r\n")
    assert (code, message, statut) == ("int x;\n", None, 200)
    _, message, statut = scratch.validate_scratch("x" * (config.MAX_CODE + 1))
    assert statut == 413 and message, (statut, message)
    code, message, _ = scratch.validate_scratch("x" * config.MAX_CODE + "   ")
    assert message is None and len(code) == config.MAX_CODE, message


def test_l_en_tete_de_la_console_suit_la_regle_des_noms_de_fichier():
    assert scratch.validate_header("", "") == ("", "", None, 200)
    assert scratch.validate_header("pile_2.h", "#define N 3  \r\n") \
        == ("pile_2.h", "#define N 3\n", None, 200)
    assert scratch.validate_header("a" * 32 + ".h", "")[2] is None
    for nom in ("a" * 33 + ".h", ".h", "pile.c", "pile.H", "../pile.h", "a/b.h",
                "pile.h\n", "pi le.h", "é.h", None, 3):
        _, _, message, statut = scratch.validate_header(nom, "")
        assert statut == 400 and message, nom
    _, _, message, statut = scratch.validate_header("", "int x;")
    assert statut == 400 and message
    _, _, message, statut = scratch.validate_header("pile.h", "x" * (config.MAX_CODE + 1))
    assert statut == 413 and message
    _, _, message, statut = scratch.validate_header("pile.h", None)
    assert statut == 400 and message


def test_le_forum_ne_canonise_rien():
    texte = "regarde ici  \net puis là  \n"
    assert source.canonicalize(texte) != texte, "le cas ne prouverait rien"
    with open(os.path.join(ROOT, "app", "services", "forum.py"),
              encoding="utf-8") as fh:
        assert "canonicalize" not in fh.read()


def _message(mid, account, visibility="thread", **extra):
    base = {"id": mid, "account": account, "text": "t", "hidden": False,
            "created_at": "2026-09-04T10:00Z", "step": None,
            "blocked_kind": None, "visibility": visibility,
            "retained": False, "helpful": 0, "helped_me": False}
    base.update(extra)
    return base


def test_private_question_only_reaches_its_author_and_the_moderator():
    thread = [_message("m1", "alice", "private"),
              _message("m2", "bob", "thread"),
              _message("m3", "alice", "group")]
    profiles = {"alice": {"group_number": 4}, "bob": {"group_number": 6},
               "carol": {"group_number": 4}}

    seen = lambda who, mod=False: [v["id"] for v in
                                   forum.forum_view(thread, who, mod, profiles)]
    assert seen("alice") == ["m1", "m2", "m3"]
    assert seen("bob") == ["m2"]
    assert seen("carol") == ["m2", "m3"]
    assert seen("zoe", True) == ["m1", "m2", "m3"]
    payload = json.dumps(forum.forum_view(thread, "zoe", True, profiles))
    for account in ("alice", "bob", "carol"):
        assert account not in payload, payload


def test_an_author_with_no_group_opens_to_nobody():
    thread = [_message("m1", "alice", "group")]
    profiles = {"alice": {}, "bob": {}}
    assert [v["id"] for v in forum.forum_view(thread, "bob", False, profiles)] == []
    assert [v["id"] for v in forum.forum_view(thread, "alice", False, profiles)] == ["m1"]


def test_the_closed_lists_of_stuck_here():
    assert forum.forum_step("compilation") == ("compilation", None)
    assert forum.forum_step(None) == (None, None)
    assert forum.forum_step("bogus")[1]
    assert forum.forum_blocked_kind("wrong-result") == ("wrong-result", None)
    assert forum.forum_blocked_kind("bogus")[1]

    assert forum.forum_visibility(None, True) == ("private", None)
    assert forum.forum_visibility(None, False) == ("thread", None)
    assert forum.forum_visibility("group", True) == ("group", None)
    assert forum.forum_visibility("thread", True)[1]
    assert forum.forum_visibility("private", False)[1]
    assert forum.forum_visibility("bogus", True)[1]


def test_thread_state_reads_on_what_one_can_see():
    alone = forum.forum_view([_message("m1", "alice")], "alice", False, {})
    assert forum.thread_state(alone)["unanswered"] == 1
    answered = [_message("m1", "alice"), _message("m2", "bob")]
    views = forum.forum_view(answered, "alice", False, {})
    assert forum.thread_state(views)["answered"] == 1
    resolved = forum.forum_view(
        answered[:1] + [_message("m2", "bob", retained=True)], "alice", False, {})
    assert forum.thread_state(resolved)["resolved"] == 1
    assert forum.thread_state([])["unanswered"] == 0


def test_the_leaderboard_never_names_the_last_one():
    rows = [{"account": "u%d" % i, "alias": "Piece %d" % i,
            "recent": 10 - i, "lifetime": 30 - i} for i in range(9)]
    view = leaderboard.leaderboard_view(rows, "u7", 4)
    assert [r["rank"] for r in view["rows"]] == [1, 2, 3, 4, 5, 8], view["rows"]
    assert view["me"]["rank"] == 8 and view["me"]["mine"]
    assert view["rows"][-1]["mine"]
    assert view["gap"] == {"rank": 7, "solved": 1}
    assert "u7" not in json.dumps(view), view

    small = rows[:politique.minimum_cohort() - 1]
    view = leaderboard.leaderboard_view(small, small[0]["account"], 4)
    assert view["rows"] == [] and view["me"]["rank"] == 1
    assert view["cohort"] < view["minimum"]

    assert leaderboard.leaderboard_view(rows, "staff", 4, reader=True)["rows"]
    outside = leaderboard.leaderboard_view(rows, "unknown", 4)
    assert outside["participating"] is False
    assert outside["me"] is None and outside["rows"] == []

    top = leaderboard.leaderboard_view(rows, "u1", 4)
    assert [r["rank"] for r in top["rows"]] == [1, 2, 3, 4, 5], top["rows"]
    assert sum(1 for r in top["rows"] if r["mine"]) == 1

    first = leaderboard.leaderboard_view(rows, "u0", 4)
    assert first["gap"] is None, first


def test_the_alias_is_drawn_from_a_closed_list_and_avoids_taken_ones():
    every_alias = politique.possible_aliases()
    assert len(every_alias) > 100 and len(set(every_alias)) == len(every_alias)
    assert leaderboard.draw_alias(set(), 0) == every_alias[0]
    assert leaderboard.draw_alias({every_alias[0]}, 0) == every_alias[1]
    assert leaderboard.draw_alias(set(every_alias), 0) is None


def test_divisions_only_go_up_never_down():
    assert politique.division(0)["id"] == "atelier"
    assert politique.division(8)["id"] == "machiniste"
    assert politique.division(1000)["id"] == "ingenierie"
    rows = [{"account": "u1", "alias": "A", "recent": 0, "lifetime": 25}]
    assert leaderboard.leaderboard_view(rows, "u1", 4)["division"]["id"] == "ingenierie"
    view = leaderboard.divisions_view(rows)
    assert [d["accounts"] for d in view] == [0, 0, 1]


def test_a_card_drops_on_a_whole_family_and_its_rarity_is_measured():
    assert politique.cards_earned({"tp2-ex0", "tp2-ex1"}) == []
    assert politique.cards_earned({"tp2-ex3"}) == ["card:E-01"]
    complete = {"tp2-ex0", "tp2-ex1", "tp2-ex2", "tp2-ex3", "tp2-ex4"}
    assert set(politique.cards_earned(complete)) == {"card:E-01", "card:M-04"}

    for card in politique.POLICY["cards"]:
        assert card["name"] and card["condition"] and card["exercises"]
    assert not set(politique.CARDS) & set(politique.ACHIEVEMENTS)

    views = {c["id"]: c for c in progression.collection_view(
        [{"id": "card:E-01"}], {"card:E-01": 6}, 10)}
    assert views["E-01"]["held"] and views["E-01"]["rarity"] == 60
    assert views["M-04"]["held"] is False
    assert views["M-04"]["condition"]
    muted = progression.collection_view([], {"card:E-01": 1}, 2)
    assert all(c["rarity"] is None for c in muted), muted


def _contenu_devoir(root, team=True, handin=True, items=None, deadline=None):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": []})
    for identifiant, fichiers in (("dev-a", ["main.c"]),
                                  ("dev-b", ["lib.h", "lib.c"]),
                                  ("solo", ["submission.c"])):
        exercise = os.path.join(root, "exercises", identifiant)
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": identifiant, "title": identifiant.upper(),
            "release": {"state": "available"}})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        _write_json(os.path.join(exercise, "assessment", "io.json"),
                    {"cases": [{"stdin": "1\n", "expect": [1]}]})
        _write_json(os.path.join(exercise, "public", "files.json"),
                    {"files": [{"name": nom, "template": ""} for nom in fichiers]})
    devoir = {"schema_version": 1, "id": "devoir", "title": "Le devoir",
              "items": items if items is not None else ["dev-a", "dev-b"],
              "release": {"state": "available"}}
    if team:
        devoir["team"] = {"min": 3, "max": 4, "count": 6}
    if deadline:
        devoir["deadline"] = deadline
    if handin:
        devoir["handin"] = {"root": "Devoir", "files": [
            {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
            {"name": "lib.c", "exercise_id": "dev-b", "file": "lib.c"}]}
    _write_json(os.path.join(root, "assignments", "devoir.json"), devoir)
    return root


def test_un_devoir_est_valide_projete_et_marque_ses_exercices():
    root = tempfile.mkdtemp(prefix="ctester-devoir-")
    try:
        _contenu_devoir(root, deadline="2026-12-05T23:59:00-05:00")
        model = content_catalogue.discover(root)
        assert set(model["assignments"]) == {"devoir"}
        devoir = model["assignments"]["devoir"]
        assert devoir["team"] == {"min": 3, "max": 4, "count": 6}
        assert devoir["items"] == ["dev-a", "dev-b"]
        assert devoir["handin"]["root"] == "Devoir"
        public = content_catalogue.public_catalogue(model)
        marques = {e["id"]: e.get("assignment") for e in public["exercises"]}
        assert marques == {"dev-a": "devoir", "dev-b": "devoir", "solo": None}
        solo = [e for e in public["exercises"] if e["id"] == "solo"][0]
        assert "assignment" not in solo
        [projete] = public["assignments"]
        assert projete["deadline"] == "2026-12-05T23:59:00-05:00"
        assert projete["access"] == "available"
        fichiers = publish_content.projection(model)
        assert "catalog.json" in fichiers
    finally:
        shutil.rmtree(root)


def test_discover_refuse_chaque_defaut_d_un_devoir():
    def devoir(r):
        return os.path.join(r, "assignments", "devoir.json")

    base = {"schema_version": 1, "id": "devoir", "title": "D",
            "items": ["dev-a"], "release": {"state": "available"}}

    def avec(**extra):
        d = dict(base)
        d.update(extra)
        return d

    cas = [
        (lambda r: _write_json(devoir(r), avec(schema_version=2)),
         "expected schema_version"),
        (lambda r: _write_json(devoir(r), avec(id="Pas Bon!")), "invalid id"),
        (lambda r: _write_json(devoir(r), avec(id="autre")), "must be named after the id"),
        (lambda r: _write_json(devoir(r), avec(title="  ")), "missing title"),
        (lambda r: _write_json(devoir(r), avec(items=[])), "non-empty list"),
        (lambda r: _write_json(devoir(r), avec(items=["inconnu"])), "unknown exercise"),
        (lambda r: _write_json(devoir(r), avec(deadline="pas une date")),
         "deadline must be an ISO date"),
        (lambda r: _write_json(devoir(r), avec(deadline="2026-12-05T23:59:00")),
         "deadline must be an ISO date"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 4, "max": 3, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 1, "max": 99, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(devoir(r), avec(team={"min": "trois", "max": 4, "count": 6})),
         "team.min must be an integer"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 3, "max": 4})),
         "team.count must be an integer"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 3, "max": 4, "count": 0})),
         "team.count must satisfy"),
        (lambda r: _write_json(devoir(r), avec(handin={"root": "../etc", "files": []})),
         "handin.root must be a plain directory name"),
        (lambda r: _write_json(devoir(r), avec(
            handin={"root": "D", "files": [
                {"name": "main.c", "exercise_id": "solo", "file": "submission.c"}]})),
         "names an exercise outside this assignment"),
        (lambda r: _write_json(devoir(r), avec(
            handin={"root": "D", "files": [
                {"name": "main.c", "exercise_id": "dev-a", "file": "secret.c"}]})),
         "does not declare"),
    ]
    for muter, attendu in cas:
        root = tempfile.mkdtemp(prefix="ctester-devoir-")
        try:
            _contenu_devoir(root)
            muter(root)
            message = _discover_error(root)
            assert attendu in message, (attendu, message)
        finally:
            shutil.rmtree(root)


def test_un_exercice_n_appartient_qu_a_un_seul_devoir():
    root = tempfile.mkdtemp(prefix="ctester-devoir-")
    try:
        _contenu_devoir(root)
        _write_json(os.path.join(root, "assignments", "autre.json"),
                    {"schema_version": 1, "id": "autre", "title": "A",
                     "items": ["dev-a"], "release": {"state": "available"}})
        assert "already belongs to assignment" in _discover_error(root)
    finally:
        shutil.rmtree(root)


def test_un_devoir_sans_bloc_team_reste_individuel():
    root = tempfile.mkdtemp(prefix="ctester-devoir-")
    try:
        _contenu_devoir(root, team=False)
        model = content_catalogue.discover(root)
        assert model["assignments"]["devoir"]["team"] is None
        public = content_catalogue.public_catalogue(model)
        [projete] = public["assignments"]
        assert "team" not in projete
        assert teams.is_team_assignment(projete) is False
    finally:
        shutil.rmtree(root)


class _BaseEquipe:
    def __init__(self, membres):
        self.membres = membres

    def team_of(self, user, assignment_id):
        team_id = self.membres.get((assignment_id, user))
        if team_id is None:
            return None
        return {"team_id": team_id, "assignment_id": assignment_id,
                "group_number": 4, "number": 1, "label": "Équipe 1"}


def _publier_devoir(root, dest):
    publish_content.publish(content_catalogue.discover(root), dest)


def test_la_porte_d_un_devoir_distingue_trois_refus():
    root = tempfile.mkdtemp(prefix="ctester-devoir-")
    dest = tempfile.mkdtemp(prefix="ctester-publie-")
    ancien = config.PUBLISHED
    try:
        _contenu_devoir(root)
        _publier_devoir(root, dest)
        config.PUBLISHED = dest
        base = _BaseEquipe({("devoir", "sub-alice"): "e1"})
        _, _, refus = teams.workspace(base, "sub-alice", "inconnu")
        assert refus[0] == 404
        _, equipe, refus = teams.workspace(base, "sub-alice", "devoir")
        assert refus is None and equipe["team_id"] == "e1"
        _, equipe, refus = teams.workspace(base, "sub-bob", "devoir")
        assert equipe is None and refus[0] == 403
        assert "figées" in refus[1] and "enseignant" in refus[1], refus
        devoir, _, _ = teams.workspace(base, "sub-alice", "devoir")
        assert teams.exercise_in(devoir, "dev-a") is True
        assert teams.exercise_in(devoir, "solo") is False
        assert teams.exercise_in(devoir, "../catalog") is False
    finally:
        config.PUBLISHED = ancien
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_un_devoir_sans_equipe_est_refuse_en_le_disant():
    root = tempfile.mkdtemp(prefix="ctester-devoir-")
    dest = tempfile.mkdtemp(prefix="ctester-publie-")
    ancien = config.PUBLISHED
    try:
        _contenu_devoir(root, team=False)
        _publier_devoir(root, dest)
        config.PUBLISHED = dest
        _, equipe, refus = teams.workspace(_BaseEquipe({}), "sub-alice", "devoir")
        assert equipe is None and refus[0] == 400
        assert "équipe" in refus[1]
    finally:
        config.PUBLISHED = ancien
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_la_vue_d_une_equipe_ne_laisse_sortir_aucun_sub():
    roster = ["sub-alice", "sub-bob", "sub-cleo"]
    profils = {"sub-bob": {"display_name": "Bob B", "display_name_public": True},
               "sub-cleo": {"display_name": "Cleo", "display_name_public": False}}
    vue = teams.members_view(roster, "sub-alice", profils)
    charge = json.dumps(vue, ensure_ascii=False)
    assert "sub-" not in charge, charge
    assert [m["id"] for m in vue] == ["m1", "m2", "m3"]
    assert [m["you"] for m in vue] == [True, False, False]
    assert vue[1]["name"] == "Bob B"
    assert vue[2]["name"] == "Coéquipier 3"
    assert len({m["color"] for m in vue}) == 3
    assert teams.member_handle(roster, "sub-cleo") == "m3"
    assert teams.member_handle(roster, "sub-etranger") == ""


def test_l_historique_nomme_une_position_et_ne_chiffre_aucune_contribution():
    roster = ["sub-alice", "sub-bob"]
    lignes = [{"revision_id": "r2", "account": "sub-bob",
               "created_at": "2026-09-07T14:32Z", "bytes": 812},
              {"revision_id": "r1", "account": "sub-alice",
               "created_at": "2026-09-07T14:02Z", "bytes": 640},
              {"revision_id": "r0", "account": "sub-parti",
               "created_at": "2026-09-06T10:00Z", "bytes": 12}]
    vue = teams.revisions_view(lignes, roster)
    charge = json.dumps(vue)
    assert "sub-" not in charge, charge
    assert "%" not in charge and "percent" not in charge
    assert [r["author"] for r in vue] == ["m2", "m1", ""]
    assert vue[0]["id"] == "r2" and vue[0]["bytes"] == 812


class _BaseDocuments:
    def __init__(self, documents, panne=False):
        self.documents = documents
        self.panne = panne

    def read_team_document(self, team_id, exercise_id):
        if self.panne:
            return None
        return self.documents.get((team_id, exercise_id), {})


def _entree(exercise_id):
    fichiers = {"dev-a": ["main.c"], "dev-b": ["lib.h", "lib.c"]}
    return {"id": exercise_id,
            "files": [{"name": n} for n in fichiers[exercise_id]]}


DEVOIR_PUBLIC = {
    "id": "devoir", "title": "Le devoir", "items": ["dev-a", "dev-b"],
    "team": {"min": 3, "max": 4}, "release": {"state": "available"},
    "handin": {"root": "Devoir", "files": [
        {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
        {"name": "matrac_lib.c", "exercise_id": "dev-b", "file": "lib.c"}]}}


def test_l_archive_est_pilotee_par_le_devoir_et_signale_ce_qui_manque():
    base = _BaseDocuments({("e1", "dev-a"): {"main.c": "int main(void){}\n"},
                           ("e1", "dev-b"): {"lib.h": "#pragma once\n",
                                             "lib.c": "int f(void){return 1;}\n"}})
    fichiers, manquants = teams.handin_files(base, DEVOIR_PUBLIC, "e1", _entree)
    assert manquants == []
    assert sorted(fichiers) == ["Devoir/main.c", "Devoir/matrac_lib.c"]
    assert fichiers["Devoir/matrac_lib.c"] == "int f(void){return 1;}\n"
    assert not any(nom.endswith("lib.h") for nom in fichiers)

    vide = _BaseDocuments({("e1", "dev-a"): {"main.c": "   \n"}})
    fichiers, manquants = teams.handin_files(vide, DEVOIR_PUBLIC, "e1", _entree)
    assert [m["name"] for m in manquants] == ["main.c", "matrac_lib.c"]
    assert fichiers == {}

    assert teams.handin_files(_BaseDocuments({}, panne=True),
                              DEVOIR_PUBLIC, "e1", _entree) == (None, [])


def test_l_archive_est_deterministe_et_relisible():
    import io as _io
    import zipfile as _zipfile

    fichiers = {"Devoir/main.c": "int main(void){return 0;}\n",
                "Devoir/matrac_lib.c": "double f(void){return 1.0;}\n"}
    premier = teams.build_zip(fichiers)
    second = teams.build_zip(dict(reversed(list(fichiers.items()))))
    assert premier == second
    with _zipfile.ZipFile(_io.BytesIO(premier)) as archive:
        assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
        assert archive.read("Devoir/main.c").decode() == fichiers["Devoir/main.c"]
        for info in archive.infolist():
            assert info.date_time == teams.ARCHIVE_EPOCH, info.date_time
            assert info.create_system == 0
    exotique = {"Devoir/main.c": "/* accentué : é\r\n*/\nint main(){}\n"}
    with _zipfile.ZipFile(_io.BytesIO(teams.build_zip(exotique))) as archive:
        assert archive.read("Devoir/main.c").decode("utf-8") \
            == exotique["Devoir/main.c"]


def test_la_date_de_remise_est_une_donnee_pas_une_tache():
    passe = dict(DEVOIR_PUBLIC, deadline="2020-01-01T00:00:00-05:00")
    futur = dict(DEVOIR_PUBLIC, deadline="2099-01-01T00:00:00-05:00")
    assert teams.deadline_passed(passe) is True
    assert teams.deadline_passed(futur) is False
    assert teams.deadline_passed(DEVOIR_PUBLIC) is False
    assert teams.deadline_passed(dict(DEVOIR_PUBLIC, deadline="demain")) is False


class _SocketFactice:
    def __init__(self):
        self.envois = []

    async def send_text(self, texte):
        self.envois.append(json.loads(texte))


def _sync(coro):
    import asyncio
    return asyncio.run(coro)


def test_deux_equipes_sur_le_meme_exercice_sont_deux_salles():
    collab.reset()
    try:
        a1 = collab.Connection(_SocketFactice(),
                               collab.room_key("e1", "dev-a"), "m1", "sub-a")
        a2 = collab.Connection(_SocketFactice(),
                               collab.room_key("e1", "dev-a"), "m2", "sub-b")
        b1 = collab.Connection(_SocketFactice(),
                               collab.room_key("e2", "dev-a"), "m1", "sub-c")
        assert a1.key != b1.key
        epoque, pairs = collab.join(a1)
        assert pairs == 0 and epoque
        assert collab.join(a2)[1] == 1
        epoque_b, pairs_b = collab.join(b1)
        assert pairs_b == 0 and epoque_b != epoque

        _sync(collab.broadcast(a1, {"t": "update", "d": "xx"}))
        assert a2.socket.envois == [{"t": "update", "d": "xx"}]
        assert a1.socket.envois == []
        assert b1.socket.envois == []

        _sync(collab.announce(a1.key))
        assert a2.socket.envois[-1] == {"t": "presence", "online": ["m1", "m2"]}
        assert b1.socket.envois == []
    finally:
        collab.reset()


def test_une_salle_videe_change_d_epoque_et_le_client_repart_du_serveur():
    collab.reset()
    try:
        cle = collab.room_key("e1", "dev-a")
        un = collab.Connection(_SocketFactice(), cle, "m1", "sub-a")
        epoque, _ = collab.join(un)
        collab.leave(un)
        assert collab.members(cle) == []
        deux = collab.Connection(_SocketFactice(), cle, "m2", "sub-b")
        nouvelle, pairs = collab.join(deux)
        assert pairs == 0, "la salle videe doit etre reconstruite"
        assert nouvelle != epoque, "et le client doit pouvoir le voir"
    finally:
        collab.reset()


def test_une_salle_deduplique_les_onglets_et_se_borne():
    collab.reset()
    ancien = config.TEAM_LIVE_MAX
    try:
        cle = collab.room_key("e1", "dev-a")
        for _ in range(2):
            collab.join(collab.Connection(_SocketFactice(), cle, "m1", "sub-a"))
        collab.join(collab.Connection(_SocketFactice(), cle, "m2", "sub-b"))
        assert collab.members(cle) == ["m1", "m2"]
        config.TEAM_LIVE_MAX = 3
        assert collab.full(cle) is True
        config.TEAM_LIVE_MAX = 4
        assert collab.full(cle) is False
    finally:
        config.TEAM_LIVE_MAX = ancien
        collab.reset()


def test_un_exercice_de_devoir_ne_compte_dans_aucune_pratique():
    entrees = [{"id": "solo", "skills": ["variables"]},
               {"id": "dev-a", "skills": ["variables"], "assignment": "devoir"},
               {"id": "verif", "skills": ["variables"], "verification": True}]
    assert [e["id"] for e in progression.practice_exercises(entrees)] == ["solo"]
    source = lire(os.path.join(ROOT, "app", "routers", "submission.py"))
    assert 'entry.get("assignment")' in source
    page = lire(os.path.join(ROOT, "frontend", "src", "lib", "domain",
                             "catalog.ts"))
    assert "!t.assignment" in page


def test_le_listage_refuse_avant_d_ecrire_quoi_que_ce_soit():
    import importlib.util

    chemin = os.path.join(ROOT, "scripts", "import_teams.py")
    spec = importlib.util.spec_from_file_location("import_teams", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.team_handle(4, 7) == teams.team_handle(4, 7) == "g04-e07"
    assert module.team_handle(6, 1) == teams.team_handle(6, 1) == "g06-e01"
    assert module.TEAM_NAME % 7 == teams.TEAM_NAME % 7 == "Équipe 7"

    entete = "group_number,number,account\n"
    dossier = tempfile.mkdtemp(prefix="ctester-listage-")
    try:
        def ecrire(texte):
            chemin_csv = os.path.join(dossier, "r.csv")
            with open(chemin_csv, "w", encoding="utf-8") as fh:
                fh.write(texte)
            return chemin_csv

        bon = ecrire(entete + "4,1,sub-alice\n4,1,sub-bob\n6,3,sub-cleo\n")
        lignes = module.read_roster(bon)
        assert lignes == [(4, 1, "sub-alice"), (4, 1, "sub-bob"),
                          (6, 3, "sub-cleo")], lignes
        assert module.sizes(lignes) == {"g04-e01": 2, "g06-e03": 1}

        for texte, attendu in (
                (entete + ",1,sub-a\n", "group_number must be 1..99"),
                (entete + "4,,sub-a\n", "number must be 1..99"),
                (entete + "0,1,sub-a\n", "group_number must be 1..99"),
                (entete + "4,100,sub-a\n", "number must be 1..99"),
                (entete + "4,1,\n", "account is required"),
                (entete, "empty"),
                (entete + "4,1,sub-a\n6,2,sub-a\n", "two teams")):
            try:
                module.read_roster(ecrire(texte))
            except SystemExit as exc:
                assert attendu in str(exc), (attendu, str(exc))
            else:
                raise AssertionError("listage invalide accepte : " + repr(texte))

        script = module.to_sql(lignes, "devoir")
        assert script.startswith("BEGIN;") and script.rstrip().endswith("COMMIT;")
        assert "'g04-e01'" in script and "'g06-e03'" in script, script
        assert len(module.statements(lignes, "devoir")) == script.count(";") - 2
        hostile = module.read_roster(ecrire(entete + "4,1,sub-o'brien\n"))
        assert "'sub-o''brien'" in module.to_sql(hostile, "devoir")
        try:
            module.to_sql(module.read_roster(ecrire(entete + "4,0,sub-a\n")),
                          "devoir")
        except SystemExit as exc:
            assert "number must be" in str(exc)
        else:
            raise AssertionError("un listage refuse a quand meme produit du SQL")
    finally:
        shutil.rmtree(dossier)


def test_console_le_job_ne_porte_aucune_identite():
    if fcntl is None:
        print("  (saute : pas de flock hors POSIX)")
        return

    dossier = tempfile.mkdtemp()
    garde = config.SPOOL
    try:
        config.SPOOL = dossier
        session = scratch.open_session("int main(void){return 0;}")
        job = json.loads(lire(os.path.join(session.path, "job.json")))
        assert job == {"kind": "console"}, job
        for interdit in ("owner", "sub", "account", "exercise_id", "utilisateur"):
            assert interdit not in job
        assert lire(os.path.join(session.path, "src", "main.c")) \
            == "int main(void){return 0;}"
        assert os.listdir(os.path.join(session.path, "src")) == ["main.c"]
        assert session.worker_alive() is False
        assert scratch._lock_held(os.path.join(session.path, "alive")) is True
        session.close()
        assert scratch._lock_held(os.path.join(session.path, "alive")) is False

        avec = scratch.open_session('#include "pile.h"\n', "pile.h", "#define N 3\n")
        job = json.loads(lire(os.path.join(avec.path, "job.json")))
        assert job == {"kind": "console", "header": "pile.h"}, job
        assert sorted(os.listdir(os.path.join(avec.path, "src"))) == ["main.c", "pile.h"]
        assert lire(os.path.join(avec.path, "src", "pile.h")) == "#define N 3\n"
        avec.close()
    finally:
        config.SPOOL = garde
        shutil.rmtree(dossier)


def test_console_n_a_pas_de_liste_d_includes():
    source = lire(os.path.join(ROOT, "judge", "src", "console.rs"))
    assert "read_allowed" not in source
    assert "forbidden_includes" not in source


def test_le_bot_du_pont_tourne_sans_aucun_tiers_et_saute_ses_propres_messages():
    chemin = os.path.join(ROOT, "bot", "bridge.py")
    assert os.path.exists(chemin), chemin
    sortie = subprocess.run([sys.executable, chemin, "--autotest"],
                            capture_output=True, text=True)
    assert sortie.returncode == 0, sortie.stdout + sortie.stderr
    assert "autotest ok" in sortie.stdout, sortie.stdout


def test_le_pont_discord_ne_laisse_sortir_que_le_chat_public():
    garde = (config.DISCORD_WEBHOOK, config.DISCORD_TIMEOUT)
    partis = []
    vrai_poster = discord._post
    try:
        config.DISCORD_WEBHOOK = "https://discord.invalide/webhook"
        discord._post = partis.append

        config.DISCORD_WEBHOOK = ""
        assert discord.enabled() is False
        assert discord.announce("@chat:general", "sub-a", "X", "salut") is False
        config.DISCORD_WEBHOOK = "https://discord.invalide/webhook"

        assert discord.announce("@chat:general", "sub-a", "Arbre", "salut") is True
        assert discord.announce("@chat:tp2-ex3", "sub-a", "Arbre", "salut") is True

        for fil in ("tp2-ex3", "tp1", "", None):
            assert discord.announce(fil, "sub-a", "Arbre", "salut") is False, fil

        assert discord.announce("@chat:general", "@discord:4711",
                                "Vianney", "salut") is False
        assert discord.announce("@chat:general", "sub-a", "Arbre", "   ") is False

        corps = discord.payload("Arbre", "@everyone @here salut", "# ex.3")
        assert corps["allowed_mentions"] == {"parse": []}, corps
        assert corps["content"] == "@everyone @here salut"
        assert corps["username"] == "Arbre — # ex.3"
        long = discord.payload("n" * 400, "t" * 5000, "")
        assert len(long["username"]) <= 80 and len(long["content"]) <= 1900

        corps = discord.payload("Arbre hélicoïdal", "ma question", "# ex.3")
        assert "sub-" not in json.dumps(corps), corps
    finally:
        discord._post = vrai_poster
        config.DISCORD_WEBHOOK, config.DISCORD_TIMEOUT = garde


def test_le_chat_force_le_public_et_le_prefixe_est_toute_la_distinction():
    salon = forum.CHAT_GENERAL
    assert forum.is_chat(salon) and forum.is_chat("@chat:tp2-ex3")
    assert not forum.is_chat("tp2-ex3")
    assert not forum.is_chat("") and not forum.is_chat(None)

    assert forum.forum_visibility(None, False, salon) == ("thread", None)
    assert forum.forum_visibility("", True, salon) == ("thread", None)
    assert forum.forum_visibility("thread", True, salon) == ("thread", None)
    for interdit in ("private", "group"):
        valeur, message = forum.forum_visibility(interdit, True, salon)
        assert valeur is None and "publics" in message, interdit

    assert forum.forum_visibility(None, True) == ("private", None)
    assert forum.forum_visibility(None, False) == ("thread", None)
    assert forum.forum_visibility("thread", True)[0] is None

    assert "@" in forum.CHAT_PREFIX


def test_un_auteur_masque_reste_suivable():
    garde = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        fil = [{"id": "a" * 32, "account": "sub-bob", "text": "x",
                "hidden": False, "created_at": "2026-09-03T10:00Z"},
               {"id": "b" * 32, "account": "sub-carl", "text": "y",
                "hidden": False, "created_at": "2026-09-03T10:01Z"},
               {"id": "c" * 32, "account": "sub-mod", "text": "z",
                "hidden": False, "created_at": "2026-09-03T10:02Z"}]
        profils = {"sub-bob": {"alias": "Rotor cuivré"},
                   "sub-carl": {"alias": "Piston lisse"},
                   "sub-mod": {"alias": "Came trempée"}}
        vus = forum.forum_view(fil, "sub-alice", False, profils)
        noms = [v["author"] for v in vus]
        assert noms[0] == "Rotor cuivré" and noms[1] == "Piston lisse"
        assert noms[0] != noms[1]
        assert noms[2] == "Enseignant"
        assert all(v["reportable_name"] is False for v in vus)

        choisi = dict(profils, **{"sub-bob": {"alias": "Rotor cuivré",
                                              "display_name": "Bob",
                                              "display_name_public": True}})
        vu = forum.forum_view(fil, "sub-alice", False, choisi)[0]
        assert vu["author"] == "Bob" and vu["reportable_name"] is True

        moi = forum.forum_view(fil, "sub-bob", False, profils)[0]
        assert moi["author"] == "Vous (Rotor cuivré)"

        assert forum.forum_view(fil, "sub-alice", False, {})[0]["author"] == "Participant"

        assert "sub-bob" not in json.dumps(vus + [vu, moi], ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = garde


def test_une_reponse_voyage_avec_son_lien_et_ses_deux_compteurs():
    fil = [{"id": "a" * 32, "account": "sub-bob", "text": "q", "hidden": False,
            "created_at": "2026-09-03T10:00Z", "reply_to": None,
            "upvotes": 3, "downvotes": 0, "my_vote": 1},
           {"id": "b" * 32, "account": "sub-carl", "text": "r", "hidden": False,
            "created_at": "2026-09-03T10:01Z", "reply_to": "a" * 32,
            "upvotes": 1, "downvotes": 2, "my_vote": -1}]
    vus = forum.forum_view(fil, "sub-alice", False, {})
    assert vus[0]["reply_to"] is None and vus[1]["reply_to"] == "a" * 32
    assert vus[0]["upvotes"] == 3 and vus[0]["my_vote"] == 1
    assert vus[1]["downvotes"] == 2 and vus[1]["my_vote"] == -1


def test_la_porte_python_lit_les_dates_comme_la_porte_rust():
    # judge/src/gate.rs replays the same file: the two gates must not diverge.
    vecteurs = json.loads(lire(os.path.join(ROOT, "tests", "vectors", "release_access.json")))
    for v in vecteurs:
        maintenant = dt.datetime.fromisoformat(v["now"].replace("Z", "+00:00"))
        assert content_catalogue.access(v["release"], maintenant) == v["access"], v


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
