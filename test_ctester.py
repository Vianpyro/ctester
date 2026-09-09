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

import contextlib
import datetime as dt
# ponytail: `flock` est POSIX. Les deux contrôles de la Console qui l'utilisent
# ne peuvent pas tourner sur une machine de développement Windows -- mais tout
# le RESTE de ce fichier le peut, et un `import` en tête l'en empêchait. Le
# Dell, lui, l'a toujours.
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
import types

# Les deux chemins, parce que les deux processus ne vivent pas au même endroit :
# runner.py à la racine (il tourne sur l'hôte), l'API dans app/ (elle est montée
# dans le conteneur). Le dépôt a EXACTEMENT cette forme, et le clone déployé
# aussi -- ce fichier tourne donc à l'identique sur le contrôleur et sur le Dell.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

import content_catalog as content_catalogue  # noqa: E402
import publish_content  # noqa: E402
import config     # noqa: E402
import csp        # noqa: E402
import state      # noqa: E402
import policy as politique  # noqa: E402
import runner     # noqa: E402
import security   # noqa: E402
from services import catalog as catalogue    # noqa: E402
from services import forum        # noqa: E402
from services import leaderboard  # noqa: E402
from services import progress as progression  # noqa: E402
from services import quotas       # noqa: E402
from services import collab      # noqa: E402
from services import teams       # noqa: E402
from services import spool        # noqa: E402
from services import scratch      # noqa: E402


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
# Contenu v2 -- découverte, projection, publication
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


def _contenu_avec_verification(root, valeur):
    """Un contenu minimal d'un exercice, dont le drapeau `verification` varie."""
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": ["variables"]})
    exercise = os.path.join(root, "exercises", "verif-tp2")
    donnees = {"schema_version": 1, "id": "verif-tp2", "title": "Vérification",
               "skills": ["variables"], "release": {"state": "available"}}
    if valeur is not None:
        donnees["verification"] = valeur
    _write_json(os.path.join(exercise, "exercise.json"), donnees)
    with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
        fh.write("Lis ce code.")
    _write_json(os.path.join(exercise, "assessment", "quiz.json"),
                {"questions": [{"id": "q1", "label": "?", "answer": "42"}]})


def test_content_v2_marque_une_verification():
    """Le drapeau traverse la publication, et il ne depend pas du mode.

    CE QUI EST VERIFIE ICI : qu'une verification soit un exercice ORDINAIRE
    marque -- meme validation, meme projection, meme frontiere -- et que le
    drapeau soit absent quand il est faux, plutot qu'une cle par exercice qui
    ne dit rien.
    """
    for valeur, attendu in ((True, True), (False, None), (None, None)):
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _contenu_avec_verification(root, valeur)
            public = content_catalogue.public_catalogue(content_catalogue.discover(root))
            assert public["exercises"][0].get("verification") is attendu, valeur
            # La ceinture ne bronche pas : rien de assessment ne sort.
            assert "answer" not in json.dumps(public)
        finally:
            shutil.rmtree(root)
    # Un drapeau qui n'est pas un booleen est refuse a la validation, pas
    # interprete : « verification: "oui" » serait vrai en Python et faux ici.
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _contenu_avec_verification(root, "oui")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "verification" in str(exc), exc
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


def test_current_survives_a_broken_pointer():
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        assert publish_content.current(dest) is None            # nothing published
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert publish_content.current(dest) is None            # unreadable
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert publish_content.current(dest) is None            # no "revision"
        with open(os.path.join(dest, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "0123456789abcdef"}, fh)
        assert publish_content.current(dest) is None            # directory absent
    finally:
        shutil.rmtree(dest)


def test_prune_keeps_only_the_latest_releases():
    """The rollback IS the old releases: `keep` says how many.

    THE MTIMES ARE FLATTENED ON PURPOSE, and that is the whole point of this
    test now. `_elaguer` used to sort on `getmtime`, whose granularity is the
    FILESYSTEM's: on Linux that is a kernel tick, so five publications a few
    milliseconds apart share one timestamp, and the sort fell through to the
    tuple's second element -- the revision HASH. It kept an arbitrary release
    and deleted one it had promised to keep.

    IT PASSED ON WINDOWS (100 ns timestamps) AND FAILED ON THE DELL, which is
    the worst shape a bug can take: green on the machine that writes the code,
    red on the machine that runs it, and only once the hashes happened to fall
    the wrong way. Publishing an assignment changed every hash, and that is
    what finally rolled the dice badly.

    `os.utime` to a single instant reproduces the Dell here, deterministically.
    Without it, this test only fails when the hashes cooperate -- which is to
    say, one deployment out of some.
    """
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
            # LE DELL, ICI : tout le repertoire dans le meme tick d'horloge.
            for name in os.listdir(dest):
                chemin = os.path.join(dest, name)
                if os.path.isdir(chemin):
                    os.utime(chemin, (1_000_000, 1_000_000))
        assert len(set(revisions)) == 5, revisions   # five contents, five revisions
        remaining = {name for name in os.listdir(dest)
                    if os.path.isdir(os.path.join(dest, name))}
        assert len(remaining) == 3, remaining
        # The three kept are the three LATEST published, never the earliest:
        # it is the rollback that counts, not the archive.
        assert remaining == set(revisions[-3:]), (remaining, revisions)
        assert publish_content.current(dest) == os.path.join(dest, revisions[-1])
        # ET LE REPLI TIENT : une revision sans manifest -- un deploiement
        # copie a moitie, un repertoire pose a la main -- doit rester elaguable
        # plutot que de devenir immortelle et de manger la place des vraies.
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

        # Invalid content never replaces the active publication.
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
        # Sans répertoire, le défaut `submission.c` tient.
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


def test_publish_catalogue_really_publishes_and_says_so_in_preview():
    """The happy path of `publish_catalogue()` -- never exercised elsewhere,
    which calls `publish_content.publish()` for real. And `CTESTER_PREVIEW`
    is not a second filter: the date shifts to year 9999, `access()` stays
    the only read, and the worker says so in the log.
    """
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    guard = (runner.CONTENT, runner.PUBLISHED, runner.PREVIEW)
    try:
        _contenu_v2(root, {"state": "scheduled",
                          "available_from": "2099-01-01T00:00:00-05:00"})
        runner.CONTENT, runner.PUBLISHED, runner.PREVIEW = root, dest, False
        exercises = runner.publish_catalogue()
        assert {e["id"] for e in exercises} == {"surface", "nombres"}
        # Closed without PREVIEW: /tp/nombres.json was not published.
        assert publish_content.current(dest) is not None
        assert not os.path.isfile(os.path.join(
            publish_content.current(dest), "exercises", "nombres.json"))

        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            runner.PREVIEW = True
            runner.publish_catalogue()
        assert "PREVIEW" in capture.getvalue(), capture.getvalue()
        # PREVIEW opens by the date, so now published.
        assert os.path.isfile(os.path.join(
            publish_content.current(dest), "exercises", "nombres.json"))
    finally:
        runner.CONTENT, runner.PUBLISHED, runner.PREVIEW = guard
        shutil.rmtree(root)
        shutil.rmtree(dest)


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


def test_public_catalogue_omits_malformed_contexts():
    """The projection stays defensive even on a hand-built model."""
    model = {"schema_version": 1, "skills": [], "collections": {},
             "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                 "skills": [], "mode": "io", "summary": "",
                                 "difficulty": None, "contexts": None,
                                 "statement": "", "files": [], "config": {},
                                 "verification": False}}}
    public = content_catalogue.public_catalogue(model)
    assert "contexts" not in public["exercises"][0], public


def test_access_treats_an_invalid_state_as_archived():
    """`access()` is THE ONLY READ of a release: it must never raise, even on
    a state that did not survive validation.
    """
    assert content_catalogue.access(None) == "archived"
    assert content_catalogue.access({}) == "archived"
    assert content_catalogue.access({"state": "whatever"}) == "archived"
    assert content_catalogue.access({"state": "available"}) == "available"
    assert content_catalogue.access({"state": "archived"}) == "archived"
    assert content_catalogue.access({"state": "scheduled"}) == "scheduled"
    assert content_catalogue.access(
        {"state": "scheduled", "available_from": "whatever"}) == "scheduled"


def test_iso_datetime_is_strict():
    assert content_catalogue._iso_datetime(123) is None                    # not a string
    assert content_catalogue._iso_datetime("whatever") is None              # unparsable
    assert content_catalogue._iso_datetime("2026-01-01T00:00:00") is None   # no timezone
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
    assert f([], "x", errors) == [] and errors   # an empty list, not just an absent one
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
    # The correct case: a valid file passes, with no error.
    errors = []
    assert f([{"name": "a.c", "template": "x"}], "x", errors) == [
        {"name": "a.c", "template": "x"}]
    assert not errors


def _minimal_valid_content(root):
    """A minimal valid v2 root: one open io exercise, one collection.

    Every mutation test below starts here and breaks exactly ONE field, so
    the observed error message is unambiguously the mutation's own.
    """
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
    """`discover(root)` must raise; returns the joined message."""
    try:
        content_catalogue.discover(root)
    except content_catalogue.ContentValidationError as exc:
        return str(exc)
    raise AssertionError("invalid content accepted")


def test_minimal_valid_content_does_not_raise():
    """The baseline the mutation tests below build on must itself be clean."""
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

    # No catalog.json at all: this must raise, rather than silently
    # publishing an empty catalog.
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
         "missing statement.md"),
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
    """A semester that has not yet organized any collection stays publishable."""
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
    """The happy counterpart of "unknown prerequisite": it must also pass."""
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
        # An out-of-form id does not even open a path.
        assert content_catalogue.load_exercise(root, "../../etc/passwd") is None
        assert content_catalogue.load_exercise(root, "UNKNOWN IN UPPERCASE") is None
        # Well-formed but absent from disk.
        assert content_catalogue.load_exercise(root, "does-not-exist") is None
        # The file declares a different id than the one requested.
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "a-different-id", "title": "X",
            "release": {"state": "available"}})
        assert content_catalogue.load_exercise(root, "ex1") is None

        # Closed: the worker refuses without tout=True, and resolves with it.
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "X",
            "release": {"state": "scheduled",
                        "available_from": "2099-01-01T00:00:00-05:00"}})
        assert content_catalogue.load_exercise(root, "ex1") is None
        opened = content_catalogue.load_exercise(root, "ex1", tout=True)
        assert opened is not None and opened["mode"] == "io"

        # Several modes present at once: nothing to run.
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "assessment", "quiz.json"),
                    {"questions": []})
        assert content_catalogue.load_exercise(root, "ex1") is None
    finally:
        shutil.rmtree(root)


# --------------------------------------------------------------------------
# Unity
# --------------------------------------------------------------------------

def test_sandbox_force_removes_the_container_after_a_timeout():
    """`docker run --rm` is not enough: killing the docker CLIENT leaves the
    container running. Without `docker rm -f`, a pathological job would hold
    onto a Dell core until the daemon's next restart.
    """
    calls = []

    class FakeSubprocess:
        TimeoutExpired = subprocess.TimeoutExpired

        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["docker", "run"]:
                raise FakeSubprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    guard = runner.subprocess
    try:
        runner.subprocess = FakeSubprocess
        code, out = runner.sandbox("/spool/job1", "/tests/tp1", "io", "n0nce")
        assert code == 137 and out == ""
        # The forced cleanup is genuinely attempted, with the EXACT name of
        # the container that was launched -- otherwise nothing is ever freed.
        assert any(a[:3] == ["docker", "rm", "-f"] for a in calls), calls
    finally:
        runner.subprocess = guard


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
    # The expected word is missing, with no forbidden word present either --
    # the other branch of this same check, never reached by the two cases
    # above (both of which fail on `absent` first).
    manque = runner.check_case(case, "l'ecoulement est calme", tol)
    assert "ne contient pas le mot attendu" in manque, manque


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

    # An abnormal exit that is neither a timeout nor an ASan overflow (a
    # segfault, typically code 139): a THIRD message, not one of the two
    # already covered above.
    segfault = (nonce + " BEGIN 01\n" + nonce + " END 01 139\n"
               + nonce + " BEGIN 02\nSurface = 84\n" + nonce + " END 02 0\n"
               + nonce + " BEGIN 03\nSurface = 1\n" + nonce + " END 03 0\n")
    verdict = runner.verdict_io(0, segfault, cases, nonce, runner.DEFAULT_TOLERANCE)
    par_cas = {c["case"]: c for c in verdict["cases"]}
    assert "anormalement" in par_cas[1]["reason"] and "code 139" in par_cas[1]["reason"]


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

    # The block starts but never closes (the container was cut off mid-write):
    # no partial block is manufactured, the output comes back intact.
    tronque = nonce + " WARN\nsub.c:3: warning: partiel"
    assert runner.extraire_avertissements(tronque, nonce) == ("", tronque)


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

    # The settings passed into the container (dialect, sanitizers, timers)
    # are absent from the dict itself by default, not just from the command
    # line: the same policy in both modes.
    garde_env = runner.SANDBOX_ENV
    try:
        runner.SANDBOX_ENV = {"CTESTER_C_STD": "gnu23", "CTESTER_RUN_TIMEOUT": "5"}
        argv = runner.docker_argv("/spool/abc", "/tests/tp1", "c", "unity", "n")
        assert "-e" in argv and "CTESTER_C_STD=gnu23" in argv
        assert "CTESTER_RUN_TIMEOUT=5" in argv
    finally:
        runner.SANDBOX_ENV = garde_env

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


def test_read_allowed_reads_the_file_or_disables_the_check():
    tmp = tempfile.mkdtemp(prefix="ctester-tp-")
    try:
        assert runner.read_allowed(tmp) is None    # no file: check disabled
        with open(os.path.join(tmp, "allowed_includes.txt"), "w", encoding="utf-8") as fh:
            fh.write("stdio.h\n\nstdlib.h\n  \n")
        assert runner.read_allowed(tmp) == {"stdio.h", "stdlib.h"}
    finally:
        shutil.rmtree(tmp)


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
    seuils = politique.POLICY["niveaux"]
    assert seuils[0] == 0 and seuils == sorted(seuils) == list(dict.fromkeys(seuils))
    # Chaque succes a de quoi s'afficher SANS couleur ni icone : un titre et une
    # description, plus le fait dont il derive.
    ids = set()
    for succes in politique.POLICY["succes"]:
        assert succes["title"] and succes["description"]
        assert succes["sur"] and succes["seuil"] >= 1
        assert succes["id"] not in ids
        ids.add(succes["id"])
    assert set(politique.SUCCES) == ids
    # Les bandes de maitrise s'affichent comme les succes : en toutes lettres.
    bandes = politique.POLICY["maitrise"]["bandes"]
    for bande in bandes:
        assert bande["title"] and bande["description"]
    assert set(politique.BANDES) == {b["id"] for b in bandes} == set(
        politique.bande_maitrise(r, t, n)
        for n in range(0, 4) for t in range(0, n + 1) for r in range(0, t + 1))
    # AUCUNE VALEUR D'EQUILIBRAGE NE S'ECRIT EN DUR DANS L'API. Sans ce
    # controle la politique deviendrait decorative : deux endroits ou changer un
    # montant, dont un que personne ne pense a relire.
    progression = lire(os.path.join(HERE, "app", "services", "progress.py"))
    for montant in set(politique.POLICY["xp"].values()):
        assert not re.search(r"%d" % montant, progression), montant
    assert not re.search(r"%d" % politique.plafond_quotidien(), progression)


def test_niveau_derive_du_solde():
    seuils = politique.POLICY["niveaux"]
    assert politique.niveau(0)["rank"] == 1
    assert politique.niveau(-5)["rank"] == 1          # un solde ne recule pas
    assert politique.niveau(seuils[1])["rank"] == 2
    assert politique.niveau(seuils[1] - 1)["rank"] == 1
    au_bout = politique.niveau(seuils[-1] + 1000)
    assert au_bout["rank"] == len(seuils) and au_bout["next"] is None
    # `remaining` est un nombre d'XP, pas un pourcentage : l'interface en fait
    # une phrase, et une barre sans phrase ne se lit pas a voix haute.
    assert politique.niveau(seuils[1] - 4)["remaining"] == 4


def test_succes_derives_de_faits():
    assert politique.succes_atteints({}) == []
    assert politique.succes_atteints({"solved": 1}) == ["premiere-reussite"]
    beaucoup = politique.succes_atteints({"solved": 10, "skills": 3,
                                          "verifications": 1})
    assert set(beaucoup) == set(politique.SUCCES)
    # UNE VERIFICATION N'EST PAS UNE PRATIQUE : dix exercices reussis ne
    # debloquent pas le succes de verification.
    assert "premiere-verification" not in politique.succes_atteints(
        {"solved": 10, "skills": 3})
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


# Les memes exercices, plus DEUX VERIFICATIONS. `variables` est portee par les
# deux, `arithmetic-operators` par une seule, `arrays-1d` par aucune : de quoi
# distinguer les quatre bandes sans qu'un seuil existe nulle part.
CATALOGUE_VERIF = CATALOGUE_DEMO + [
    {"id": "verif-a", "skills": ["variables", "arithmetic-operators"],
     "verification": True},
    {"id": "verif-b", "skills": ["variables"], "verification": True},
]


def evidence(exercice, reussi):
    """Une ligne telle que `state.read_events` la rend."""
    return {"exercise_id": exercice, "payload": {"job": "j", "passed": reussi}}


def test_projection_des_competences():
    etats = [{"exercise_id": "tp2-ex0", "status": "solved"},
             {"exercise_id": "tp2-ex3", "status": "attempted"}]
    pratique = [{"exercise_id": "tp6-ex1", "attempts": 2, "successes": 0}]
    touches, reussis = progression.exercise_facts(etats, pratique)
    assert touches == {"tp2-ex0", "tp2-ex3", "tp6-ex1"}
    assert reussis == {"tp2-ex0"}
    # A row with no exercise id (degraded data) breaks nothing, it simply
    # does not count -- on both sides of the merge.
    degraded = progression.exercise_facts(
        etats + [{"exercise_id": "", "status": "solved"}, {"status": "solved"}],
        pratique + [{"exercise_id": None}, {}])
    assert degraded == (touches, reussis)
    vue = progression.skills_view(CATALOGUE_DEMO, touches, reussis)
    # L'ORDRE EST CELUI DU COURS, pas un tri par score : la premiere ligne est
    # la premiere competence rencontree, ce que l'etudiant reconnait.
    assert [c["id"] for c in vue] == ["variables", "arithmetic-operators", "arrays-1d"]
    assert vue[0] == {"id": "variables", "total": 2, "practiced": 2, "solved": 1}
    assert vue[2] == {"id": "arrays-1d", "total": 1, "practiced": 1, "solved": 0}


def test_recommandation_deterministe():
    etats = [{"exercise_id": "tp2-ex0", "status": "solved"}]
    touches, reussis = progression.exercise_facts(etats, [])
    # Deja pratique `variables` : on repart sur l'exercice non reussi qui la
    # reprend, pas sur le premier venu.
    assert progression.recommander(CATALOGUE_DEMO, touches, reussis) == {
        "exercise_id": "tp2-ex3", "skill": "variables"}
    # Aucune competence en commun : le premier non reussi, dans l'ordre du cours.
    assert progression.recommander(CATALOGUE_DEMO, set(), set()) == {
        "exercise_id": "tp2-ex0", "skill": None}
    # Tout reussi : rien a proposer, et on le dit au lieu d'inventer.
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert progression.recommander(CATALOGUE_DEMO, tout, tout) is None
    assert progression.recommander([], set(), set()) is None


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
    # Un succes dont la politique ne connait plus la definition ne s'affiche
    # pas -- il reste en base, il ne devient pas une ligne vide a l'ecran.
    assert [s["id"] for s in charge["achievements"]] == ["premiere-reussite"]
    assert charge["achievements"][0]["title"] and charge["achievements"][0]["description"]
    # La legende des bandes voyage meme quand aucune competence n'est
    # verifiable : la page doit pouvoir expliquer ce qu'elle n'affiche pas
    # encore, plutot que de reecrire les libelles de son cote.
    assert [b["id"] for b in charge["mastery"]["bands"]] == list(politique.BANDES)
    assert charge["mastery"]["skills"] == []
    # RIEN DE SECRET NE TRAVERSE : ni chemin de tests, ni code soumis, ni
    # detail de verdict. Meme frontiere que publish_catalogue.
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("path", "answer", "statement", "sources", "template"):
        assert interdit not in texte, interdit


def test_bandes_de_maitrise_par_couverture():
    """La bande d'une competence, sans qu'aucun seuil existe.

    CE QUI EST VERIFIE ICI : que « verifie » veuille dire TOUTES les
    verifications ouvertes de la competence, et pas « une », sinon la phase 2
    promettrait une capacite demontree sur une seule preuve.
    """
    vide = progression.maitrise_view(CATALOGUE_VERIF, [])
    # Une competence qu'aucune verification ne porte n'y figure pas : lui
    # reprocher « pas encore verifie » serait reprocher une lacune du contenu.
    assert [c["id"] for c in vide] == ["variables", "arithmetic-operators"]
    assert vide[0] == {"id": "variables", "total": 2, "attempted": 0,
                       "passed": 0, "band": "non-verifie"}

    une = progression.maitrise_view(CATALOGUE_VERIF, [evidence("verif-a", True)])
    par_id = {c["id"]: c for c in une}
    # `variables` est portee par DEUX verifications : une seule reussie ne la
    # verifie pas. `arithmetic-operators` n'en a qu'une, donc elle est complete.
    assert par_id["variables"]["band"] == "en-progression"
    assert par_id["arithmetic-operators"]["band"] == "verifie"

    deux = progression.maitrise_view(
        CATALOGUE_VERIF, [evidence("verif-b", True), evidence("verif-a", True)])
    assert {c["id"]: c["band"] for c in deux} == {
        "variables": "verifie", "arithmetic-operators": "verifie"}

    rate = progression.maitrise_view(CATALOGUE_VERIF, [evidence("verif-a", False)])
    # Tentee sans succes : une bande a consolider, PAS le silence d'une
    # competence jamais abordee. C'est pour ca qu'un echec s'ecrit aussi.
    assert {c["id"]: c["band"] for c in rate} == {
        "variables": "a-consolider", "arithmetic-operators": "a-consolider"}
    assert par_id["variables"]["attempted"] == 1


def test_maitrise_retient_la_derniere_tentative():
    """Le dernier verdict fait foi ; les reessais restent historiques."""
    # `read_events` rend du plus recent au plus ancien : ici, un echec APRES
    # une reussite.
    journal = [evidence("verif-a", False), evidence("verif-a", True)]
    assert progression.dernieres_tentatives(journal) == {"verif-a": False}
    vue = {c["id"]: c for c in progression.maitrise_view(CATALOGUE_VERIF, journal)}
    assert vue["arithmetic-operators"]["band"] == "a-consolider"
    # MAIS UN SUCCES NE SE RETIRE PAS : ce que la bande perd, le journal le
    # garde, et le compteur des succes est monotone.
    assert progression.verifications_reussies(journal) == {"verif-a"}


def test_une_pratique_ne_fait_bouger_aucune_bande():
    """Invariant 4 : le juge en libre service ne prouve pas une maitrise."""
    tout_reussi = [{"exercise_id": e["id"], "status": "solved"}
                   for e in CATALOGUE_DEMO]
    faits = {"xp": 75, "achievements": [], "transactions": []}
    charge = progression.progress_payload(CATALOGUE_VERIF, faits, tout_reussi,
                                          [], [])
    assert charge["exercises"]["solved"] == 4
    assert all(c["band"] == "non-verifie"
               for c in charge["mastery"]["skills"])


def test_une_verification_ne_compte_pas_comme_une_pratique():
    """Deux domaines : une verification n'est ni un denominateur ni une suite.

    CE QUI EST VERIFIE ICI : que le filtre soit pose une seule fois et traverse
    les trois compteurs. Sans lui, « 4 exercices » deviendrait « 6 » et la
    recommandation enverrait pratiquer une verification.
    """
    charge = progression.progress_payload(
        CATALOGUE_VERIF, {"xp": 0, "achievements": [], "transactions": []}, [], [], [])
    assert charge["exercises"]["total"] == len(CATALOGUE_DEMO)
    assert charge["next"]["exercise_id"] == "tp2-ex0"
    # Les competences PRATIQUEES ne comptent que les exercices de pratique :
    # `variables` est portee par deux exercices, pas par les quatre.
    par_id = {c["id"]: c for c in charge["skills"]}
    assert par_id["variables"]["total"] == 2
    assert "arrays-1d" in par_id
    # Et rien ne recommande une verification, meme quand tout le reste est fait.
    tout = {e["id"] for e in CATALOGUE_DEMO}
    assert progression.recommander(
        progression.exercices_pratique(CATALOGUE_VERIF), tout, tout) is None


def test_aucun_index_ne_precede_la_colonne_qu_il_indexe():
    """UN INDEX SUR UNE COLONNE AJOUTEE PAR UN `ALTER` DOIT ETRE APRES L'ALTER.

    CE CONTROLE EXISTE PARCE QUE LA PANNE EST ARRIVEE DEUX FOIS, a l'identique,
    et les deux fois UNIQUEMENT EN PRODUCTION -- `invite_code`, puis `number`.

    Le mecanisme : sur une base ou la table existe deja, `CREATE TABLE IF NOT
    EXISTS` ne fait RIEN, donc la colonne ajoutee dans la declaration n'existe
    pas encore ; c'est l'`ALTER` de la section migration qui la pose. Un
    `CREATE INDEX` place JUSTE APRES la table echoue alors sur « column does
    not exist », et sous `ON_ERROR_STOP=1` c'est toute la convergence qui
    tombe. Sur une base neuve, tout passe -- donc rien ne se voit en
    developpement.

    CE CONTROLE EST TEXTUEL, ET C'EST VOULU : il tourne avec le python de
    l'HOTE, sans Docker et sans base, donc il part avec le tick de deploiement.
    `test_postgres.py` pose l'ancienne forme et migre pour de vrai ; celui-ci
    attrape la faute avant qu'on ait un Postgres sous la main.
    """
    schema = lire(os.path.join(HERE, "app", "schema.sql"))
    instructions = re.sub(r"--[^\n]*", "", schema)
    # Les colonnes que la section migration ajoute, et OU elle commence.
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
            continue                      # apres les ALTER : rien a dire
        colonnes = {c.strip().split()[0] for c in index.group(3).split(",")
                    if c.strip()}
        tardives = colonnes & par_table.get(index.group(2), set())
        if tardives:
            fautes.append("%s indexe %s, que l'ALTER ajoute plus bas"
                          % (index.group(1), ", ".join(sorted(tardives))))
    assert not fautes, (
        "index declares avant la colonne qu'ils indexent : " + " ; ".join(fautes)
        + " -- ils passent sur une base neuve et font tomber la convergence "
          "sur une base qui a deja la table. Les descendre avec les migrations.")


def test_chaque_table_a_ses_droits():
    """Toute table du schema apparait dans un GRANT du MEME fichier.

    CE CONTROLE EXISTE PARCE QUE LA PANNE EST ARRIVEE TROIS FOIS, et toujours
    de la meme facon : les droits vivaient dans `VHome`, la table dans ce
    depot, et ajouter l'une sans l'autre ne se voyait qu'EN PRODUCTION -- le
    seul endroit ou le role applicatif est utilise. L'`UPDATE` du theme, la
    colonne `visibility` du forum, puis les cinq tables d'equipe.

    Les GRANT sont donc descendus dans `schema.sql`, et ce test est ce qui
    rend le rapprochement utile : une table ajoutee sans ses droits fait
    echouer la suite ici, au lieu d'etre muette dans six mois. C'est le meme
    dessin que `test_suppression_couvre_toutes_les_tables`, qui lit le schema
    plutot que d'entretenir une liste.

    IL NE JUGE PAS QUELS droits, seulement qu'il y en a : c'est `test_postgres.py`
    qui eprouve que Postgres refuse bien ce qu'il doit refuser. Ici on attrape
    l'oubli, la-bas la permission de trop.
    """
    schema = lire(os.path.join(HERE, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    # Les GRANT vivent dans un `DO $$ ... $$`, donc en chaines SQL, parfois
    # coupees sur plusieurs lignes. On recolle d'abord (`' '` accole n'est
    # qu'une concatenation), on lit ensuite.
    # LES COMMENTAIRES SORTENT D'ABORD. Ce fichier en est plein, et ils
    # NOMMENT ce qu'ils expliquent -- « ce qui reste a Ansible : CREATE ROLE
    # ... ». Un controle qui lit la prose refuse la phrase qui documente la
    # regle qu'il verifie.
    instructions = re.sub(r"--[^\n]*", "", schema)
    bloc = instructions[instructions.index("DO $$"):]
    bloc = re.sub(r"'\s*\n\s*'", " ", bloc)
    accordees = set()
    for cible in re.findall(r"\bON\s+(.+?)\s+TO ctester_app", bloc):
        cible = re.sub(r"\([^)]*\)", "", cible)       # un GRANT DE COLONNE
        accordees |= {nom.strip() for nom in cible.split(",") if nom.strip()}
    manquantes = tables - accordees
    assert not manquantes, (
        "ces tables n'apparaissent dans aucun GRANT de schema.sql : "
        + ", ".join(sorted(manquantes))
        + " -- une table sans ses droits est muette, et seulement en "
          "production.")
    # ET RIEN QUI N'EXISTE PAS : un GRANT sur une table renommee ou supprimee
    # ferait echouer TOUT le fichier sous `ON_ERROR_STOP=1`, donc toute la
    # convergence, pour une ligne que personne ne relit.
    assert not accordees - tables, sorted(accordees - tables)
    # LE ROLE EST CREE AILLEURS (Ansible porte le mot de passe, qui vient du
    # vault) : sans lui, on ne grante rien plutot que de faire tomber le
    # fichier entier.
    assert "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctester_app')" \
        in bloc
    assert "CREATE ROLE" not in instructions, \
        "le mot de passe du role vient du vault : il ne descend pas ici"
    # JAMAIS UN GRANT SUR LE SCHEMA : il couvrirait d'avance une table pas
    # encore ecrite, et c'est exactement ce que ce test ne pourrait plus voir.
    assert "ALL TABLES IN SCHEMA" not in instructions, instructions


def test_suppression_couvre_toutes_les_tables():
    """`forget` efface chaque table QUI PORTE UN COMPTE, en une seule instruction.

    C'EST LA PROMESSE DU BANDEAU DE CONSENTEMENT. Ajouter une table de
    progression sans l'ajouter la laisserait des donnees derriere quelqu'un qui
    a demande leur suppression -- et personne ne s'en apercevrait, puisque plus
    rien ne les affiche.

    LA REGLE EST LA COLONNE `account`, ET C'EST CE QUI LA REND AUTOMAINTENUE.
    Une table qui porte un compte appartient a ce compte et s'efface avec lui ;
    une table qui n'en porte pas appartient a quelqu'un d'autre. Les trois
    tables d'equipe qui restent sont exactement celles-la : `team` est le
    listage de l'enseignant, `team_document` et `team_submission` sont le
    travail note de TROIS AUTRES personnes -- effacer un membre ne doit pas
    emporter le devoir de son equipe. C'est pour ca que la colonne de
    `team_submission` s'appelle `submitted_by` : le nom porte la decision.
    """
    schema = lire(os.path.join(HERE, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    assert len(tables) == 19, tables
    # Chaque bloc `CREATE TABLE ... ( ... );`, et le fait qu'il declare ou non
    # une colonne nommee `account`.
    blocs = dict(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);",
        schema, re.S))
    assert set(blocs) == tables, sorted(set(blocs) ^ tables)
    avec_compte = {nom for nom, corps in blocs.items()
                   if re.search(r"^\s*account\s+TEXT", corps, re.M)}
    assert avec_compte == tables - {"team", "team_document", "team_submission"}, \
        sorted(avec_compte)
    efface = lire(os.path.join(HERE, "app", "state.py"))
    efface = efface[efface.index("def forget(user):"):]
    assert set(re.findall(r"DELETE FROM (\w+)", efface)) == avec_compte
    # UNE SEULE INSTRUCTION : quinze `_query` en autocommit laisseraient un
    # etudiant a moitie efface si la connexion tombe au milieu.
    assert efface.count("_query(") == 1


def test_progression_degradee_sans_base():
    """Sans DSN, tout rend None/False et rien ne leve. Le juge, lui, continue."""
    assert not state.enabled()
    assert state.grant_first_solve("u", "tp", "e", 10, "m", "v", {}, 100) is None
    assert state.unlock("u", ["premiere-reussite"], "e", "v") is False
    assert state.unlock("u", [], "e", "v") is True     # rien a faire, pas un echec
    assert state.read_progress("u") is None
    # Une evidence de maitrise degrade comme le reste : rien d'ecrit, rien de
    # lu, et surtout pas une liste vide qui se lirait « jamais verifie ».
    assert state.record_event("u", "e", "T", "tp", "v", {}) is None
    assert state.read_events("u", "T") is None
    # Le theme degrade comme le reste : None dit « la base n'a pas repondu »,
    # jamais « pas de theme » -- c'est ce qui laisse la page garder le sien.
    assert state.read_theme("u") is None
    assert state.write_theme("u", "light") is False
    assert state.write_theme("u", "neon") is False    # refuse avant meme la base
    assert state.forget("u") is False
    # `progression.py` degrades the same way, called directly rather than
    # through the HTTP boundary: no invented number when the database does
    # not answer.
    assert progression.progression_facts("u") is None
    assert progression.cards_to_grant("u") == []


def test_every_persistence_function_degrades_without_a_database():
    """The module's contract, stated in its own docstring: WITHOUT A
    DATABASE, every function returns None or False, never a value that could
    pass for a result. `test_progression_degradee_sans_base` only covered a
    hand-picked handful; this one systematically sweeps the rest, so a
    function added tomorrow without this safeguard shows up here.
    """
    assert not state.enabled()
    cases = [
        (state.read_resume, ("u", "ex"), None),
        (state.write_draft, ("u", "ex", {}), False),
        (state.write_state, ("u", "ex", "solved", {}), False),
        (state.read_states, ("u",), None),
        # The non-integer total/passed coercion runs BEFORE the query: it is
        # therefore exercised here even without a database.
        (state.write_practice_attempt,
         ("u", "j", "ex", {"status": "ok", "total": "three", "passed": "two"}), False),
        (state.read_practice_summary, ("u",), None),
        (state.read_practice_days, ("u", 30), None),
        (state.read_unlock_rates, (), None),
        (state.leaderboard_rows, (None, 7), None),
        (state.forum_fil, ("ex", 10), None),
        (state.forum_publier, ("m", "ex", "u", "x"), False),
        (state.forum_open_to_group, ("m", "u"), None),
        (state.forum_mark_helpful, ("m", "u"), None),
        (state.forum_supprimer, ("m", "u"), None),
        (state.forum_signaler, ("m", "u"), None),
        (state.forum_signalements, (10,), None),
        (state.forum_moderer, ("a", "m", "u", "hide"), None),
        (state.forum_profils, (["u"],), None),
        (state.forum_profil, ("u",), None),
        (state.forum_profil_ecrire, ("p", "u", None, None, False, False), False),
        (state.forum_taken_aliases, (), None),
        (state.forum_nom_signaler, ("m", "u"), None),
        (state.forum_noms_signales, (10,), None),
        (state.forum_help_rows, (10, 8), None),
        (state.forum_auteur, ("m",), None),
    ]
    for function, args, expected in cases:
        assert function(*args) == expected, function.__name__


def test_close_is_idempotent_and_absorbs_a_failed_shutdown():
    guard = state._conn
    try:
        state._conn = None
        state._close()          # nothing to close: must not raise
        assert state._conn is None

        class FailingConnection:
            def close(self):
                raise RuntimeError("connection already dead")
        state._conn = FailingConnection()
        state._close()           # the close failure is absorbed
        assert state._conn is None
    finally:
        state._conn = guard


def test_forum_moderer_and_profils_refuse_without_touching_the_database():
    """Two guards that short-circuit BEFORE the query, and are therefore
    testable without a database: an unknown action, an empty account list.
    """
    assert state.forum_moderer("a", "m", "u", "bogus") == []
    assert state.forum_profils([]) == {}
    assert state.forum_profils([None, ""]) == {}   # nothing usable either


def test_minute_falls_back_to_a_string_for_what_is_not_a_date():
    assert state._minute("2026-09-04 12:00") == "2026-09-04 12:00"[:16]


def test_sources_refuses_what_is_not_a_json_object():
    assert state._sources([]) is None
    assert state._sources(None) is None
    assert state._sources([("not json",)]) is None
    assert state._sources([("[1, 2, 3]",)]) is None    # JSON, but not an object
    assert state._sources([('{"a": 1}',)]) == {"a": "1"}


class _PartialOutage:
    """A write that succeeds, then a re-read that fails -- an outage BETWEEN
    the two calls, not a total one. `state.enabled()` alone cannot produce
    this combination; this double is necessary.
    """

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
    """The grant/evidence is already written when the re-read fails:
    `unlock()` must be skipped, not called with invented facts.
    """
    guard = progression.state
    try:
        progression.state = _PartialOutage()
        entry = {"id": "tp2-ex0", "difficulty": "foundation"}
        progression.recompenser("u", entry, "job1")            # must not raise
        progression.enregistrer_verification("u", entry, "job2", True)
    finally:
        progression.state = guard


# --------------------------------------------------------------------------
# File, quotas, HTTP
# --------------------------------------------------------------------------

def test_scan_jobs_survives_a_missing_spool_and_a_directory_still_being_written():
    guard = config.SPOOL
    try:
        config.SPOOL = os.path.join(tempfile.mkdtemp(prefix="ctester-spool-"), "does-not-exist")
        assert spool.scan_jobs() == []          # the directory itself is absent

        config.SPOOL = os.path.dirname(config.SPOOL)
        os.makedirs(config.SPOOL, exist_ok=True)
        # A job directory that has NOT YET received job.json (the atomic
        # write is not finished): this is not a job, not an error.
        os.makedirs(os.path.join(config.SPOOL, "in-progress"))
        assert spool.scan_jobs() == []
    finally:
        config.SPOOL = guard


def test_durees_moyennes_ignores_a_file_that_is_not_an_object():
    guard = config.SPOOL
    try:
        config.SPOOL = tempfile.mkdtemp(prefix="ctester-spool-")
        with open(os.path.join(config.SPOOL, spool.DUREES), "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)              # JSON, but not an object
        assert spool.durees_moyennes() == {}
    finally:
        shutil.rmtree(config.SPOOL, ignore_errors=True)
        config.SPOOL = guard


def test_eta_secondes_returns_zero_for_an_already_finished_or_unknown_job():
    jobs = [("aaa", 100.0, False), ("bbb", 101.0, True)]
    assert spool.eta_secondes(jobs, "bbb") == 0      # already done: no longer in the queue
    assert spool.eta_secondes(jobs, "unknown") == 0  # never existed


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
        # No files.json at all.
        assert spool.job_sources(job, entry) == {}
        with open(os.path.join(config.SPOOL, job, "files.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert spool.job_sources(job, entry) == {}
        # A quiz has no source files, whatever sits on disk.
        assert spool.job_sources(job, {"mode": "quiz"}) == {}
        # A submitted file that no longer passes the allow-list (the exercise
        # changed shape since the submission): nothing is kept.
        with open(os.path.join(config.SPOOL, job, "files.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"an-unexpected-name.c": "x"}, fh)
        assert spool.job_sources(job, entry) == {}
    finally:
        shutil.rmtree(config.SPOOL, ignore_errors=True)
        config.SPOOL = guard


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


def test_quota_prunes_its_inactive_clients_past_five_thousand():
    """A process running an entire semester must not leak: past 5000
    distinct clients, the ones whose window has expired leave -- the rest
    stay, this is not a full flush like the token cache.
    """
    q = quotas.Quota(cooldown=0, hourly=100)
    now = time.time()
    for i in range(5000):
        assert q.check("client-%d" % i, now) == 0
    assert len(q.seen) == 5000                      # right at the bound: no prune yet
    q.check("expired-client", now - 7200)            # a window already expired
    assert "expired-client" in q.seen
    q.check("fresh-client", now)                     # the 5002nd: this prunes
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
    p.touch("fresh", now)                            # the 5002nd: this prunes
    assert len(p.seen) < 5002
    assert "expired" not in p.seen
    assert "fresh" in p.seen


def test_client_id():
    assert security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "1.2.3.4"
    assert security.client_id({}, "10.0.0.1") == "10.0.0.1"


def test_client_id_prefers_the_authenticated_account_over_any_ip():
    """A validated `sub` outranks CF-Connecting-IP -- it is harder to forge."""
    garde = security.current_user
    try:
        security.current_user = lambda entetes: "sub-" + "x" * 100
        identifiant = security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1")
        assert identifiant.startswith("u:") and len(identifiant) == 2 + 62
    finally:
        security.current_user = garde


def test_client_id_station_suffix_and_the_two_truncation_bounds():
    """A station suffix separates anonymous stations behind one NAT."""
    assert security.client_id({}, "10.0.0.1", station="poste-3") == "10.0.0.1/poste-3"
    # address+station is bounded to 128 characters overall.
    identifiant = security.client_id({}, "x" * 200, station="poste-3")
    assert len(identifiant) == 128
    # CF-Connecting-IP (and X-Forwarded-For) are bounded to 64 characters
    # BEFORE any station suffix -- a forged header cannot inflate the key.
    identifiant = security.client_id({"CF-Connecting-IP": "y" * 200}, "10.0.0.1")
    assert identifiant == "y" * 64


def test_no_redirect_refuses_to_hand_a_bearer_token_to_a_redirect_target():
    """The SSRF/token-leak guard: urllib must never replay a redirect."""
    assert security._NoRedirect().redirect_request(
        None, None, 302, "Found", {}, "https://evil.exemple") is None


def test_oidc_enabled_requires_all_three_conditions_independently():
    garde = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.OIDC_CLIENT_ID = "ctester"
        security.state = type("Base", (), {"enabled": staticmethod(lambda: True)})
        assert security.oidc_enabled()

        config.OIDC_ISSUER = "http://auth.exemple"   # not HTTPS
        assert not security.oidc_enabled()
        config.OIDC_ISSUER = "https://auth.exemple"

        config.OIDC_CLIENT_ID = ""                   # no client id
        assert not security.oidc_enabled()
        config.OIDC_CLIENT_ID = "ctester"

        security.state = type("Base", (), {"enabled": staticmethod(lambda: False)})
        assert not security.oidc_enabled()            # no database
    finally:
        config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state = garde


def test_userinfo_url_refuses_an_endpoint_outside_the_issuer():
    """The SSRF guard is the only reason this function exists at all."""
    garde_issuer = config.OIDC_ISSUER
    garde_json = security._get_json
    garde_disc = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")
        security._get_json = lambda url, headers=None: {
            "userinfo_endpoint": "https://evil.exemple/steal"}
        assert security.userinfo_url() == ""
        # A refused discovery is cached too: a second call must not re-fetch.
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
        assert len(appels) == 1   # the second call is served from the cache
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
        assert sub == "abc123" and nom   # a claim, sanitized like a student's own input

        # Boundary: a 128-character sub is accepted, 129 is refused.
        security._get_json = lambda url, headers=None: {"sub": "a" * 128}
        assert security._ask_userinfo("tok")[0] == "a" * 128
        security._get_json = lambda url, headers=None: {"sub": "a" * 129}
        assert security._ask_userinfo("tok")[0] is None

        # An empty or non-string sub is refused outright, never coerced.
        security._get_json = lambda url, headers=None: {"sub": ""}
        assert security._ask_userinfo("tok")[0] is None
        security._get_json = lambda url, headers=None: {"sub": 12345}
        assert security._ask_userinfo("tok")[0] is None

        # No discovered endpoint at all: no request is even attempted.
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

        assert security.current_user({}) is None                              # no header
        assert security.current_user({"Authorization": "Basic xx"}) is None   # wrong scheme
        assert security.current_user({"Authorization": "Bearer "}) is None    # empty token
        trop_long = "Bearer " + "x" * 4097
        assert security.current_user({"Authorization": trop_long}) is None    # past MAX+1

        appels = []

        def repond(url, headers=None):
            appels.append(1)
            return {"sub": "etu-1"}
        security._get_json = repond
        pile = "Bearer " + "x" * 4096   # exactly at the bound: accepted
        assert security.current_user({"Authorization": pile}) == "etu-1"
        assert len(appels) == 1
        # Same token again: served from the cache, no second round trip.
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
    """No LRU: a full flush, so one cold token never costs more than one call."""
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
        assert len(security._tokens) == security.TOKENS_MAX   # right at the cap: no flush yet

        security.current_user({"Authorization": "Bearer tokenB"})
        assert len(security._tokens) == 1                      # one past it: flush, then insert
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
    """The one place a real socket opens. Everything else in this file mocks
    `_get_json`; this proves what it mocks actually holds against a real
    server -- in particular that `_NoRedirect` really stops urllib, not just
    that the class returns `None` in isolation.
    """
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
            pass   # exactly what current_user()/_ask_userinfo() rely on
    finally:
        serveur.shutdown()
        fil.join(timeout=2)


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
        # Un `sub` vide n'est pas un moderateur, meme si la liste en contient un
        # vide par accident de configuration.
        assert not security.is_moderator("") and not security.is_moderator(None)
        # La CONNEXION reste la premiere condition : un forum sans compte n'a
        # personne a qui attribuer un message ni a qui offrir la suppression.
        config.OIDC_ISSUER = ""
        assert not forum.forum_enabled()
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS,
         security.state) = garde


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
    """Les trois bibliotheques sont VERSIONNEES, presentes, et servies.

    CE CONTROLE EXISTE PARCE QU'UN ASSAINISSEUR ABSENT NE SE VOIT PAS. La page
    retombe alors sur du texte brut -- c'est le bon comportement -- et personne
    ne remarque que le rendu a disparu. Ici, un nom qui ne correspond plus entre
    `VENDOR`, le module qui la charge et le disque fait echouer la suite tout de
    suite.

    LE MODULE QUI CHARGE CHAQUE FICHIER EST NOMME, et c'est la moitie utile du
    controle : `marked` et DOMPurify n'existent que pour le forum, Yjs que pour
    l'espace d'equipe. Un fichier servi que plus personne ne charge est du poids
    mort dans une liste blanche, et c'est exactement ce qu'on ne veut pas y
    laisser trainer.
    """
    charge_par = {"vendor/marked-18.0.11.umd.js": "forum.js",
                  "vendor/purify-3.4.14.min.js": "forum.js",
                  "vendor/yjs-13.6.32.iife.js": "team.js"}
    assert set(config.VENDOR) == set(charge_par), config.VENDOR
    for chemin in config.VENDOR:
        sur_disque = os.path.join(HERE, "web", *chemin.split("/"))
        assert os.path.exists(sur_disque), chemin
        source = lire(os.path.join(HERE, "web", charge_par[chemin]))
        assert '"' + chemin + '"' in source, chemin
        # Le nom PORTE la version : c'est ce qui rend l'epinglage impossible a
        # perdre, et une montee de version impossible a faire par accident.
        assert re.search(r"-\d+\.\d+\.\d+[.-]", chemin), chemin
        # `/vendor/` N'EST PAS UN REPERTOIRE OUVERT : la liste est close, comme
        # celle des `.js` de la page.
        assert chemin.startswith("vendor/"), chemin


def test_csp_without_an_issuer_omits_the_extra_connect_src_origin():
    """A deployment with no OIDC configured (`issuer=""`) must add no extra
    origin to `connect-src`: the branch exists for the issuer, not for
    anything that is not one.
    """
    without_issuer = csp.csp(b"<html></html>")
    with_issuer = csp.csp(b"<html></html>", "https://auth.exemple/auth/v1")
    assert "auth.exemple" not in without_issuer, without_issuer
    assert "auth.exemple" in with_issuer, with_issuer
    # An issuer that is not https (never in production, but the guard is on
    # the prefix, not on a list of protocols) is ignored the same way.
    without_https = csp.csp(b"<html></html>", "http://auth.exemple")
    assert "auth.exemple" not in without_https, without_https

    def directives(policy):
        return {d.split()[0]: d for d in policy.split("; ")}

    # The only difference between the two policies is `connect-src`.
    a, b = directives(without_issuer), directives(with_issuer)
    assert set(a) == set(b)
    for key in a:
        if key != "connect-src":
            assert a[key] == b[key], key


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
        fil = [{"id": "a" * 32, "account": "sub-alice", "text": "moi",
                "hidden": False, "created_at": "2026-09-03 10:00"},
               {"id": "b" * 32, "account": "sub-bob", "text": "lui",
                "hidden": False, "created_at": "2026-09-03 10:01"},
               {"id": "c" * 32, "account": "sub-mod", "text": "eux",
                "hidden": False, "created_at": "2026-09-03 10:02"},
               {"id": "d" * 32, "account": "sub-bob", "text": "cache",
                "hidden": True, "created_at": "2026-09-03 10:03"}]
        vu = forum.forum_vue(fil, "sub-alice", False)
        assert [m["author"] for m in vu] == [
            "Vous", "Participant", "Enseignant"], vu
        assert [m["mine"] for m in vu] == [True, False, False]
        # UN MESSAGE MASQUE N'EXISTE PAS pour un etudiant ordinaire.
        assert len(vu) == 3
        texte = json.dumps(vu, ensure_ascii=False)
        for interdit in ("sub-alice", "sub-bob", "sub-mod", "account"):
            assert interdit not in texte, interdit
        # Un moderateur, LUI, voit le masque -- sinon il ne pourrait pas le
        # retablir -- et pas davantage d'identite pour autant.
        vu_mod = forum.forum_vue(fil, "sub-mod", True)
        assert len(vu_mod) == 4 and vu_mod[3]["hidden"] is True
        assert vu_mod[2]["author"] == "Vous"      # son propre message
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
    # Pydantic bloque déjà un non-texte à la frontière HTTP, mais la fonction
    # reste appelable directement et doit refuser plutôt que planter.
    assert forum.forum_pseudo(42) == (None, "nom invalide")
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
        fil = [{"id": "a" * 32, "account": "sub-bob", "text": "x",
                "hidden": False, "created_at": "2026-09-03T10:00Z"}]
        cache = {"sub-bob": {"display_name": "Bob", "group_number": 7,
                             "display_name_public": False, "group_number_public": False}}
        vu = forum.forum_vue(fil, "sub-alice", False, cache)[0]
        assert vu["author"] == "Participant" and vu["group"] is None
        assert vu["reportable_name"] is False
        # Le modérateur voit le groupe SANS que le nom devienne public pour
        # autant : deux cases, deux effets.
        vu_mod = forum.forum_vue(fil, "sub-mod", True, cache)[0]
        assert vu_mod["author"] == "Participant" and vu_mod["group"] == 7
        montre = {"sub-bob": dict(cache["sub-bob"], display_name_public=True)}
        vu2 = forum.forum_vue(fil, "sub-alice", False, montre)[0]
        assert vu2["author"] == "Bob" and vu2["reportable_name"] is True
        # Son propre nom reste « Vous » : on ne se signale pas soi-meme.
        a_moi = forum.forum_vue(fil, "sub-bob", False, montre)[0]
        assert a_moi["author"] == "Vous" and a_moi["reportable_name"] is False
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
            json.dump({"exercise_id": "tp2-ex0"}, fh)
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

    `psycopg` est la seule exception tolérée -- `state.py` le rend facultatif et
    se déclare éteint sans lui.
    """
    tiers = {"starlette", "fastapi", "pydantic", "pydantic_core", "uvicorn",
             "httpx", "httpx2", "anyio", "h11"}
    charges = sorted(tiers & {m.split(".")[0] for m in sys.modules})
    assert not charges, (
        "test_ctester.py a tire " + ", ".join(charges) + " : ces paquets vivent "
        "dans /deps, que le python de l'hote ne voit pas. Sortir ce que le "
        "module fautif utilise dans un module sans dependance, comme app/csp.py.")


def test_un_constructeur_absent_se_nomme_au_lieu_d_accuser_le_service():
    """`CTESTER_BUILD_SCRATCH` non pose = une CONFIGURATION qui manque.

    CE CONTROLE EXISTE PARCE QUE LA PANNE A EU LIEU, et qu'elle mentait : sans
    la variable, le worker retombait sur un defaut qui ne designe aucun
    fichier, docker bind-montait un repertoire vide sur /in/build.sh, et
    l'etudiant lisait « le service de compilation s'est interrompu ». Un
    message qui accuse le SERVICE envoie reessayer en boucle sur une panne
    qu'aucun reessai ne repare.

    IL NE DEPEND NI DE DOCKER NI DE POSIX : le refus tombe avant le premier
    verrou et avant le premier conteneur, donc ce controle tourne partout, y
    compris la ou les autres contröles de Console se sautent.
    """
    dossier = tempfile.mkdtemp()
    garde = runner.BUILD_SCRATCH
    try:
        runner.BUILD_SCRATCH = os.path.join(dossier, "absent.sh")
        verdict = runner.run_console(dossier)
        assert verdict["reason"] == "build_missing", verdict
        # L'ETAT AUSSI, sinon l'API ne verrait rien et conclurait « worker » --
        # le mot qui accuse le service, celui-la meme qu'on vient d'ecarter.
        etat = json.loads(lire(os.path.join(dossier, "state.json")))
        assert etat["state"] == "exited" and etat["reason"] == "build_missing", etat
    finally:
        runner.BUILD_SCRATCH = garde
        shutil.rmtree(dossier)


def test_chaque_raison_de_console_a_un_message():
    """Une raison que la page ne connait pas s'affiche... comme rien du tout.

    `run_console()` pose `reason` sur l'etat de la session ; `scratch.js` la
    traduit en une phrase. Une raison ajoutee cote worker sans son entree dans
    RAISONS laisse `annoncer()` retomber sur « Termine (code -1) » -- un chiffre
    la ou il fallait dire quoi faire. C'est arrive avec `build_missing`, qui
    accusait le service alors qu'il manquait une variable a l'unite systemd.

    LE CONTROLE LIT LES DEUX FICHIERS plutot que d'entretenir une liste : c'est
    le meme dessin que `forget()` et les GRANT, et c'est ce qui le rend vrai
    dans six mois.

    `exited` est la seule exception, ecrite dans le commentaire de RAISONS : un
    programme qui se termine normalement n'a rien a expliquer, on affiche son
    code de sortie.
    """
    worker = lire(os.path.join(HERE, "runner.py"))
    page = lire(os.path.join(HERE, "web", "scratch.js"))
    bloc = page.split("const RAISONS = {")[1].split("};")[0]
    connues = set(re.findall("^\\s*(\\w+):", bloc, re.M)) | {"exited"}
    motif = 'reason["\']?[=:]\\s*["\'](\\w+)["\']'
    emises = set(re.findall(motif, worker))
    orphelines = sorted(emises - connues)
    assert not orphelines, (
        "le worker peut emettre " + ", ".join(orphelines) + " mais scratch.js "
        "n'a pas de phrase pour ces raisons-la : l'etudiant lirait un code de "
        "sortie au lieu de savoir quoi faire.")


def test_les_websockets_ont_une_implementation_epinglee():
    """UVICORN SEUL NE SAIT PAS PARLER WEBSOCKET, et il ne le dit pas.

    `requirements.txt` refuse `uvicorn[standard]` -- pour de bonnes raisons,
    ecrites la-bas -- mais cet extra est aussi ce qui apportait `websockets`.
    Sans implementation, uvicorn resout son protocole a `None` et repond 501 a
    CHAQUE poignee de main : `/team/live` et `/scratch/live` ne s'ouvrent
    jamais, le navigateur ne voit qu'une connexion refusee, et TOUT LE RESTE DU
    SITE marche parfaitement -- ce qui rend la panne tres longue a trouver.

    CE CONTROLE EXISTE PARCE QUE LA PANNE A EU LIEU : la Console a ete livree,
    deployee, et n'a jamais pu ouvrir une seule session.

    Il lit le FICHIER et pas les modules charges : c'est ce fichier qui decide
    de ce qui est pose dans `/deps`, et ce test-ci tourne avec le python de
    l'hote, qui ne voit rien de ce volume.
    """
    besoin = lire(os.path.join(HERE, "requirements.txt"))
    lignes = [l.split("#")[0].strip() for l in besoin.splitlines()]
    paquets = {l.split("==")[0].strip().lower() for l in lignes if "==" in l}
    assert paquets & {"wsproto", "websockets"}, (
        "requirements.txt n'epingle aucune implementation WebSocket : uvicorn "
        "repondra 501 a /team/live et /scratch/live sans rien journaliser. "
        "Poser `wsproto` (pur Python, sa seule dependance est h11, deja epingle).")


def test_le_conteneur_web_n_importe_que_ce_qu_il_monte():
    """`app/` NE PEUT IMPORTER QUE `app/`. Les modules de la RACINE sont au worker.

    LE CONTENEUR WEB MONTE `app/`, `web/` ET `published/`, ET RIEN D'AUTRE --
    c'est ce qui fait qu'il n'a jamais accès aux tests ni aux corrigés. Un
    `import content_catalog` (ou `runner`, ou `publish_content`) dans `app/`
    passe donc parfaitement ici, où la racine est dans `sys.path`, et fait
    planter le conteneur AU DÉMARRAGE en production -- une panne totale, dans
    le seul environnement où on ne peut pas la voir venir.

    CE CONTRÔLE EXISTE PARCE QUE ÇA VIENT D'ARRIVER : `services/teams.py`
    importait `access` depuis `content_catalog` pour recalculer une valeur que
    `catalog.json` porte déjà.

    C'est le pendant de `test_le_controle_de_l_hote_ne_depend_d_aucun_tiers` :
    l'un dit ce que le python de l'HÔTE ne voit pas, l'autre ce que le
    CONTENEUR ne monte pas.
    """
    racine = {nom[:-3] for nom in os.listdir(HERE) if nom.endswith(".py")}
    # Ce qui vit dans `app/` peut évidemment s'importer entre soi.
    dans_app = {nom[:-3] for nom in os.listdir(os.path.join(HERE, "app"))
                if nom.endswith(".py")}
    interdits = racine - dans_app
    assert "content_catalog" in interdits and "runner" in interdits, interdits
    motif = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                       re.M)
    fautes = []
    for dossier, _sous, fichiers in os.walk(os.path.join(HERE, "app")):
        if "__pycache__" in dossier:
            continue
        for nom in sorted(fichiers):
            if not nom.endswith(".py"):
                continue
            chemin = os.path.join(dossier, nom)
            for module in motif.findall(lire(chemin)):
                if module in interdits:
                    fautes.append(os.path.relpath(chemin, HERE) + " -> " + module)
    assert not fautes, (
        "ces modules de la racine ne sont pas montés dans le conteneur web : "
        + ", ".join(fautes))


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
    garde_elagage = runner.CACHE_PRUNE_EVERY
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

        # L'ÉVICTION GARDE CE QUI SERT, ET C'EST LE SCÉNARIO DE L'INTRA : en
        # semaine 4 on rouvre les exercices de la semaine 1, dont les entrées
        # sont les PLUS VIEILLES à l'écriture. Les jeter pour ça ferait
        # recompiler tout le monde le jour de la révision. Ce qui compte est la
        # date de DERNIER SERVICE, que `cache_lire` repose à chaque succès.
        dossier = os.path.join(spool, runner.CACHE_DIR)
        shutil.rmtree(dossier, ignore_errors=True)  # partir d'un magasin net
        for rang, nom in enumerate(("vieux", "moyen", "recent")):
            runner.cache_ecrire(nom * 16, ok)
            os.utime(os.path.join(dossier, nom * 16 + ".json"),
                     (1000 + rang, 1000 + rang))
        # `vieux` est relu : il redevient le plus récemment servi.
        assert runner.cache_lire("vieux" * 16) == ok
        # Marge nulle : on jette exactement ce qui dépasse, pour que ce
        # contrôle porte sur le CHOIX de la victime et pas sur la marge.
        runner.CACHE_MAX, runner.CACHE_PRUNE_EVERY = 3, 0
        runner.cache_ecrire("neuf" * 16, ok)
        assert runner.cache_lire("moyen" * 16) is None, "le moins servi a survécu"
        assert runner.cache_lire("vieux" * 16) == ok, "une entrée servie a été jetée"
        assert runner.cache_lire("recent" * 16) == ok
        assert runner.cache_lire("neuf" * 16) == ok
        runner.CACHE_MAX, runner.CACHE_PRUNE_EVERY = garde_max, garde_elagage

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
        runner.CACHE_PRUNE_EVERY = garde_elagage
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


# --------------------------------------------------------------------------
# The redesign: message visibility, leaderboard, collection
# --------------------------------------------------------------------------

def _message(mid, account, visibility="thread", **extra):
    """A thread message, in the shape `state.forum_fil` renders it."""
    base = {"id": mid, "account": account, "text": "t", "hidden": False,
            "created_at": "2026-09-04T10:00Z", "step": None,
            "blocked_kind": None, "visibility": visibility,
            "retained": False, "helpful": 0, "helped_me": False}
    base.update(extra)
    return base


def test_private_question_only_reaches_its_author_and_the_moderator():
    """THE VISIBILITY RULE, AND IT IS A SECURITY BOUNDARY.

    "Only the lab instructor" is written on the student's form. If a private
    message leaked to a classmate, that would be a promise written on screen
    and broken in silence -- the worst kind of leak, the one nobody checks for.
    """
    thread = [_message("m1", "alice", "private"),
              _message("m2", "bob", "thread"),
              _message("m3", "alice", "group")]
    profiles = {"alice": {"group_number": 4}, "bob": {"group_number": 6},
               "carol": {"group_number": 4}}

    seen = lambda who, mod=False: [v["id"] for v in
                                   forum.forum_vue(thread, who, mod, profiles)]
    # Its own author sees everything they wrote, private included.
    assert seen("alice") == ["m1", "m2", "m3"]
    # Bob is NOT in group 4: neither the private one nor the group one.
    assert seen("bob") == ["m2"]
    # Carol is in group 4: she sees the group one, never the private one.
    assert seen("carol") == ["m2", "m3"]
    # The moderator sees everything: a private question IS addressed to them.
    assert seen("zoe", True) == ["m1", "m2", "m3"]
    # AND NO `sub` CROSSES THE BOUNDARY, even in the most detailed view. Same
    # check as an ordinary thread, redone here because these three fields
    # are new.
    payload = json.dumps(forum.forum_vue(thread, "zoe", True, profiles))
    for account in ("alice", "bob", "carol"):
        assert account not in payload, payload


def test_an_author_with_no_group_opens_to_nobody():
    """A `group` message with no group number publishes to nobody else.

    Without this case, "opened to my group" on an account with no chosen
    group would open to EVERYONE without one either -- that is, to most
    accounts by default.
    """
    thread = [_message("m1", "alice", "group")]
    profiles = {"alice": {}, "bob": {}}
    assert [v["id"] for v in forum.forum_vue(thread, "bob", False, profiles)] == []
    assert [v["id"] for v in forum.forum_vue(thread, "alice", False, profiles)] == ["m1"]


def test_the_closed_lists_of_stuck_here():
    """Step, blocked kind and visibility: closed lists, and a private default.

    They are closed because they are what the instructor's aggregate groups
    by: six ways of writing "compilation" would read as six different
    problems on the morning that count matters.
    """
    assert forum.forum_step("compilation") == ("compilation", None)
    assert forum.forum_step(None) == (None, None)      # an ordinary question
    assert forum.forum_step("bogus")[1]
    assert forum.forum_blocked_kind("wrong-result") == ("wrong-result", None)
    assert forum.forum_blocked_kind("bogus")[1]

    # A HELP REQUEST IS PRIVATE BY DEFAULT, an ordinary question is public:
    # asking for help must not require deciding, in the same breath, to say
    # so publicly.
    assert forum.forum_visibility(None, True) == ("private", None)
    assert forum.forum_visibility(None, False) == ("thread", None)
    assert forum.forum_visibility("group", True) == ("group", None)
    # AND THE TWO PATHS STAY DISTINCT: a help request does not become a
    # thread post, or the aggregate would count discussions.
    assert forum.forum_visibility("thread", True)[1]
    assert forum.forum_visibility("private", False)[1]
    assert forum.forum_visibility("bogus", True)[1]


def test_thread_state_reads_on_what_one_can_see():
    """Resolved / answered / unanswered, derived -- and never stored.

    ON WHAT THE READER SEES: a private message nobody else can read must not
    inflate anyone else's "unanswered".
    """
    # ON VIEWS, not on raw rows: it is `forum_vue`'s output that the state
    # counts, so it is what the reader sees.
    alone = forum.forum_vue([_message("m1", "alice")], "alice", False, {})
    assert forum.thread_state(alone)["unanswered"] == 1
    answered = [_message("m1", "alice"), _message("m2", "bob")]
    views = forum.forum_vue(answered, "alice", False, {})
    assert forum.thread_state(views)["answered"] == 1
    resolved = forum.forum_vue(
        answered[:1] + [_message("m2", "bob", retained=True)], "alice", False, {})
    assert forum.thread_state(resolved)["resolved"] == 1
    assert forum.thread_state([])["unanswered"] == 0


def test_the_leaderboard_never_names_the_last_one():
    """THREE RULES, and each one protects someone.

    Opt-in (an absent row is not a hidden row), the minimum cohort (a
    leaderboard of four names those four, last one included) and the top of
    the table alone (nobody is named last). None of the three can be relaxed
    without a student ending up singled out.
    """
    rows = [{"account": "u%d" % i, "alias": "Piece %d" % i,
            "recent": 10 - i, "lifetime": 30 - i} for i in range(9)]
    view = leaderboard.leaderboard_view(rows, "u7", 4)
    # The top of the table, plus ONE'S OWN row -- nothing in between.
    assert [r["rank"] for r in view["rows"]] == [1, 2, 3, 4, 5, 8], view["rows"]
    assert view["me"]["rank"] == 8 and view["me"]["mine"]
    assert view["rows"][-1]["mine"]
    # THE STEP IS UPWARD, never downward: "two more and you pass 7th" is
    # made, "someone is catching up" is not.
    assert view["gap"] == {"rank": 7, "solved": 1}
    # NO `sub` COMES OUT: the leaderboard reads `account` to find its own
    # row, and drops it afterward.
    assert "u7" not in json.dumps(view), view

    # UNDER THE MINIMUM COHORT, NO TABLE AT ALL -- not a truncated one, which
    # would disclose exactly the same people.
    small = rows[:politique.minimum_cohort() - 1]
    view = leaderboard.leaderboard_view(small, small[0]["account"], 4)
    assert view["rows"] == [] and view["me"]["rank"] == 1
    assert view["cohort"] < view["minimum"]

    # WHO DID NOT OPT IN IS NOT RANKED, and that is not an error: the screen
    # then offers the checkbox, rather than an empty leaderboard that would
    # look broken.
    outside = leaderboard.leaderboard_view(rows, "unknown", 4)
    assert outside["participating"] is False
    assert outside["me"] is None and outside["rows"] == []

    # ALREADY IN THE TOP OF THE TABLE: their own row appears there only
    # once, not appended a second time at the end of the list.
    top = leaderboard.leaderboard_view(rows, "u1", 4)
    assert [r["rank"] for r in top["rows"]] == [1, 2, 3, 4, 5], top["rows"]
    assert sum(1 for r in top["rows"] if r["mine"]) == 1

    # FIRST IN THE RANKING: nobody ahead, so no step is announced.
    first = leaderboard.leaderboard_view(rows, "u0", 4)
    assert first["gap"] is None, first


def test_the_alias_is_drawn_from_a_closed_list_and_avoids_taken_ones():
    """Nothing a student types can ever reach a leaderboard.

    That is what makes it possible NOT to moderate the leaderboard: the
    vocabulary is closed, so there is no name to report.
    """
    every_alias = politique.possible_aliases()
    assert len(every_alias) > 100 and len(set(every_alias)) == len(every_alias)
    assert leaderboard.draw_alias(set(), 0) == every_alias[0]
    # A taken name is skipped, never handed out twice.
    assert leaderboard.draw_alias({every_alias[0]}, 0) == every_alias[1]
    # Vocabulary exhausted: None, and the caller answers 503 rather than
    # manufacturing a duplicate.
    assert leaderboard.draw_alias(set(every_alias), 0) is None


def test_divisions_only_go_up_never_down():
    """They are read on the CUMULATIVE total, never on the week.

    A quiet week must not demote anybody (ranked.md): this is the only place
    that choice shows, and it hinges on the argument passed in.
    """
    assert politique.division(0)["id"] == "atelier"
    assert politique.division(8)["id"] == "machiniste"
    assert politique.division(1000)["id"] == "ingenierie"
    # `lifetime`, not `recent`: a week at zero keeps its division.
    rows = [{"account": "u1", "alias": "A", "recent": 0, "lifetime": 25}]
    assert leaderboard.leaderboard_view(rows, "u1", 4)["division"]["id"] == "ingenierie"
    view = leaderboard.divisions_view(rows)
    assert [d["accounts"] for d in view] == [0, 0, 1]


def test_a_card_drops_on_a_whole_family_and_its_rarity_is_measured():
    """A card is an achievement in disguise: same table, same key, same "once".

    AND NONE OF THEM IS DRAWN AT RANDOM. The condition is printed on the
    locked card, so it is readable before aiming for it -- that is the
    difference between a collection and a loot box.
    """
    # A partial family grants nothing.
    assert politique.cards_earned({"tp2-ex0", "tp2-ex1"}) == []
    assert politique.cards_earned({"tp2-ex3"}) == ["card:E-01"]
    complete = {"tp2-ex0", "tp2-ex1", "tp2-ex2", "tp2-ex3", "tp2-ex4"}
    assert set(politique.cards_earned(complete)) == {"card:E-01", "card:M-04"}

    # Every card displays with NO color and no image: a name and a condition.
    for card in politique.POLICY["cards"]:
        assert card["name"] and card["condition"] and card["exercises"]
    # And a card id can never be mistaken for an achievement's.
    assert not set(politique.CARDS) & set(politique.SUCCES)

    # RARITY IS MEASURED, and withheld under the minimum cohort: a percentage
    # over four accounts describes those four accounts.
    views = {c["id"]: c for c in progression.collection_view(
        [{"id": "card:E-01"}], {"card:E-01": 6}, 10)}
    assert views["E-01"]["held"] and views["E-01"]["rarity"] == 60
    assert views["M-04"]["held"] is False
    assert views["M-04"]["condition"]          # the condition is always stated
    muted = progression.collection_view([], {"card:E-01": 1}, 2)
    assert all(c["rarity"] is None for c in muted), muted


# ---------------------------------------------------------------------------
# Team assignments
#
# WHAT THESE CHECKS EXIST FOR: a group is not a team, and nothing in the page
# may be able to turn one into the other. The HTTP boundary is exercised in
# `test_api.py`; here we call the rules directly -- which is the only way to
# reach `collab.py`'s join ordering, and the only way to prove the archive is
# deterministic without standing a server up.


def _contenu_devoir(root, team=True, handin=True, items=None, deadline=None):
    """A v2 root with one assignment over two exercises. Returns the root."""
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
        # `count` EST OBLIGATOIRE : c'est lui qui rend la numerotation
        # comparable a celle de Moodle, donc il n'a pas de defaut sensé.
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
    """L'assignment traverse `discover` puis `public_catalogue`, entier.

    ET IL MARQUE SES EXERCICES. `assignment` sur l'entree publique est ce qui
    dit a la page d'ouvrir un espace d'equipe plutot que l'editeur individuel,
    et a `_record()` de ne pas verser d'XP -- deux decisions prises a deux
    endroits, a partir d'un seul champ.
    """
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
        # ABSENT QUAND IL N'Y EN A PAS, comme `verification` : une cle par
        # exercice qui ne dit rien est 77 cles qui ne disent rien.
        solo = [e for e in public["exercises"] if e["id"] == "solo"][0]
        assert "assignment" not in solo
        [projete] = public["assignments"]
        assert projete["deadline"] == "2026-12-05T23:59:00-05:00"
        assert projete["access"] == "available"
        # LA PROJECTION EST PUBLIABLE : le controle de fuite de
        # `publish_content` porte sur les cles, et un devoir en ajoute cinq.
        fichiers = publish_content.projection(model)
        assert "catalog.json" in fichiers
    finally:
        shutil.rmtree(root)


def test_discover_refuse_chaque_defaut_d_un_devoir():
    """Un devoir casse ne remplace jamais la publication active."""
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
        # LA DATE SANS FUSEAU EST REFUSEE, comme une ouverture : "23:59" sans
        # fuseau veut dire quatre heures de plus ou de moins selon le serveur.
        (lambda r: _write_json(devoir(r), avec(deadline="2026-12-05T23:59:00")),
         "deadline must be an ISO date"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 4, "max": 3, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(devoir(r), avec(team={"min": 1, "max": 99, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(devoir(r), avec(team={"min": "trois", "max": 4, "count": 6})),
         "team.min must be an integer"),
        # `count` EST EXIGÉ, et sa borne aussi : sans lui la liste d'équipes
        # n'a pas de longueur, donc rien à faire correspondre avec Moodle.
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
    """Deux devoirs sur le meme exercice n'ont pas de reponse honnete.

    Ce serait deux equipes, deux dates et deux remises pour UN document
    partage. Une collection peut se croiser (invariant 3) ; un devoir non.
    """
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
    """L'OPT-IN EST L'ABSENCE DE `team`, et c'est ce qui rend tout additif.

    Un devoir sans equipe se publie, s'affiche, et n'ouvre aucun espace
    partage : `workspace()` le refuse en le disant.
    """
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
    """The one team read `teams.workspace` needs, and nothing else."""

    def __init__(self, membres):
        self.membres = membres          # {(assignment, account): team_id}

    def team_of(self, user, assignment_id):
        team_id = self.membres.get((assignment_id, user))
        if team_id is None:
            return None
        return {"team_id": team_id, "assignment_id": assignment_id,
                "group_number": 4, "number": 1, "label": "Équipe 1"}


def _publier_devoir(root, dest):
    publish_content.publish(content_catalogue.discover(root), dest)


def test_la_porte_d_un_devoir_distingue_trois_refus():
    """`workspace()` est LA porte, et ses trois refus ne disent pas la meme chose.

    "ce devoir n'existe pas", "ce devoir n'est pas un travail d'equipe" et "tu
    n'es dans aucune equipe" envoient l'etudiant a trois endroits differents.
    Les fondre en un seul 403 les enverrait tous les trois chez l'enseignant --
    alors qu'un seul des trois le justifie.

    ET LE TROISIEME DIT POURQUOI C'EST TROP TARD : les equipes se choisissent
    AVANT l'ouverture du devoir, et `workspace()` n'est atteint qu'une fois
    ouvert. Renvoyer vers une liste qui ne s'ouvrira plus serait pire que de
    ne rien dire.
    """
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
        # BOB N'EST DANS AUCUNE EQUIPE : 403, et pas de document. Le message
        # dit que c'est FIGE, et renvoie vers l'enseignant -- pas vers une
        # liste d'equipes qui ne s'ouvrira plus.
        _, equipe, refus = teams.workspace(base, "sub-bob", "devoir")
        assert equipe is None and refus[0] == 403
        assert "figées" in refus[1] and "enseignant" in refus[1], refus
        # L'EXERCICE EST LA SECONDE MOITIE DE LA PORTE. Prouver l'equipe ne
        # prouve pas l'exercice : `solo` n'est pas dans ce devoir.
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
    """Le `sub` ne franchit pas la frontiere, ici comme dans le forum.

    ET L'IDENTIFIANT DE MEMBRE EST UNE POSITION : "m2" ne veut rien dire hors
    de cette equipe-la, donc il n'y a rien a recouper avec un autre exercice,
    un autre devoir ou un fil du forum.
    """
    roster = ["sub-alice", "sub-bob", "sub-cleo"]
    profils = {"sub-bob": {"display_name": "Bob B", "display_name_public": True},
               "sub-cleo": {"display_name": "Cleo", "display_name_public": False}}
    vue = teams.members_view(roster, "sub-alice", profils)
    charge = json.dumps(vue, ensure_ascii=False)
    assert "sub-" not in charge, charge
    assert [m["id"] for m in vue] == ["m1", "m2", "m3"]
    assert [m["you"] for m in vue] == [True, False, False]
    # UN NOM CHOISI ET RENDU PUBLIC SORT, un nom garde pour soi ne sort pas.
    assert vue[1]["name"] == "Bob B"
    assert vue[2]["name"] == "Coéquipier 3"
    # DES COULEURS DISTINCTES : c'est le seul lien entre un curseur et un nom.
    assert len({m["color"] for m in vue}) == 3
    # LA POIGNEE VIENT DU LISTAGE, jamais de ce que le client annonce.
    assert teams.member_handle(roster, "sub-cleo") == "m3"
    assert teams.member_handle(roster, "sub-etranger") == ""


def test_l_historique_nomme_une_position_et_ne_chiffre_aucune_contribution():
    """Recuperer, auditer, comprendre -- jamais noter.

    UN POURCENTAGE DE CONTRIBUTION DEVIENDRAIT UNE NOTE le lendemain de sa
    livraison, et il aurait tort a propos de celui qui reflechit avant de
    taper. Ce controle lit la charge entiere : aucun `sub`, aucun `%`.
    """
    roster = ["sub-alice", "sub-bob"]
    lignes = [{"revision_id": "r2", "account": "sub-bob",
               "created_at": "2026-09-07T14:32Z", "bytes": 812},
              {"revision_id": "r1", "account": "sub-alice",
               "created_at": "2026-09-07T14:02Z", "bytes": 640},
              # Un compte qui a demande l'effacement de ses donnees n'a plus
              # de ligne ; s'il en restait une, elle ne nommerait personne.
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
    """CE QUI ENTRE DANS LE ZIP VIENT DE `handin.files`, ET DE NULLE PART AILLEURS.

    Aucun nom de fichier de TCH009 n'est ecrit dans l'application : "main.c et
    matrac_lib.c" est un fait sur le contenu de ce devoir-la.

    ET UN TROU N'EST PAS REMIS EN SILENCE. Un exercice sans document ressort
    dans `missing` plutot que de produire un fichier vide -- remettre une
    archive sans `matrac_lib.c` est la panne qu'on ne decouvre qu'a la
    correction.
    """
    base = _BaseDocuments({("e1", "dev-a"): {"main.c": "int main(void){}\n"},
                           ("e1", "dev-b"): {"lib.h": "#pragma once\n",
                                             "lib.c": "int f(void){return 1;}\n"}})
    fichiers, manquants = teams.handin_files(base, DEVOIR_PUBLIC, "e1", _entree)
    assert manquants == []
    assert sorted(fichiers) == ["Devoir/main.c", "Devoir/matrac_lib.c"]
    # LE NOM DANS L'ARCHIVE EST CELUI DU DEVOIR, la source celui de l'exercice.
    assert fichiers["Devoir/matrac_lib.c"] == "int f(void){return 1;}\n"
    # LE FICHIER NON DECLARE DANS `handin` NE SORT PAS : `lib.h` reste dans
    # l'espace de travail, l'enonce ne le demande pas dans la remise.
    assert not any(nom.endswith("lib.h") for nom in fichiers)

    vide = _BaseDocuments({("e1", "dev-a"): {"main.c": "   \n"}})
    fichiers, manquants = teams.handin_files(vide, DEVOIR_PUBLIC, "e1", _entree)
    assert [m["name"] for m in manquants] == ["main.c", "matrac_lib.c"]
    assert fichiers == {}

    # UNE BASE MUETTE NE REND PAS UNE ARCHIVE VIDE : c'est la seule panne qui
    # ressemblerait a une remise reussie.
    assert teams.handin_files(_BaseDocuments({}, panne=True),
                              DEVOIR_PUBLIC, "e1", _entree) == (None, [])


def test_l_archive_est_deterministe_et_relisible():
    """MEMES DOCUMENTS, MEMES OCTETS -- sinon "deterministe" est un mot sans controle.

    L'horodatage est une constante et les entrees sont triees : une archive
    construite sur le Dell et une construite sur un portable doivent etre
    identiques, ou ce controle ne prouverait que la machine qui l'a joue.
    """
    import io as _io
    import zipfile as _zipfile

    fichiers = {"Devoir/main.c": "int main(void){return 0;}\n",
                "Devoir/matrac_lib.c": "double f(void){return 1.0;}\n"}
    premier = teams.build_zip(fichiers)
    # L'ordre d'insertion ne change rien : c'est le tri qui decide.
    second = teams.build_zip(dict(reversed(list(fichiers.items()))))
    assert premier == second
    with _zipfile.ZipFile(_io.BytesIO(premier)) as archive:
        assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
        assert archive.read("Devoir/main.c").decode() == fichiers["Devoir/main.c"]
        for info in archive.infolist():
            assert info.date_time == teams.ARCHIVE_EPOCH, info.date_time
            assert info.create_system == 0
    # LE CODE DE L'ETUDIANT N'EST PAS TOUCHE : ni reindente, ni recode, ni
    # complete d'un en-tete. Ce qui est remis est ce qui a ete ecrit.
    exotique = {"Devoir/main.c": "/* accentué : é\r\n*/\nint main(){}\n"}
    with _zipfile.ZipFile(_io.BytesIO(teams.build_zip(exotique))) as archive:
        assert archive.read("Devoir/main.c").decode("utf-8") \
            == exotique["Devoir/main.c"]


def test_la_date_de_remise_est_une_donnee_pas_une_tache():
    """Comme une date d'ouverture : lue a chaque appel, sans tache de minuit."""
    passe = dict(DEVOIR_PUBLIC, deadline="2020-01-01T00:00:00-05:00")
    futur = dict(DEVOIR_PUBLIC, deadline="2099-01-01T00:00:00-05:00")
    assert teams.deadline_passed(passe) is True
    assert teams.deadline_passed(futur) is False
    # PAS DE DATE = PAS DE FERMETURE. Un devoir sans date ne se ferme jamais
    # tout seul, ce qui est plus sur que de deviner une echeance.
    assert teams.deadline_passed(DEVOIR_PUBLIC) is False
    # Une date illisible ne ferme pas non plus : une faute de frappe dans le
    # contenu ne doit pas bloquer une remise la veille.
    assert teams.deadline_passed(dict(DEVOIR_PUBLIC, deadline="demain")) is False


class _SocketFactice:
    def __init__(self):
        self.envois = []

    async def send_text(self, texte):
        self.envois.append(json.loads(texte))


def _sync(coro):
    """Runs one coroutine. `asyncio.run` per call: these are three lines each."""
    import asyncio
    return asyncio.run(coro)


def test_deux_equipes_sur_le_meme_exercice_sont_deux_salles():
    """L'ISOLEMENT EST STRUCTUREL, PAS FILTRE. L'equipe est DANS la cle de la
    salle, et un membre n'est mis que dans la salle construite a partir de
    l'equipe que la base a rendue pour lui. Il n'y a donc rien a filtrer, et
    rien a oublier de filtrer.
    """
    collab.reset()
    try:
        a1 = collab.Connection(_SocketFactice(),
                               collab.room_key("e1", "dev-a"), "m1", "sub-a")
        a2 = collab.Connection(_SocketFactice(),
                               collab.room_key("e1", "dev-a"), "m2", "sub-b")
        b1 = collab.Connection(_SocketFactice(),
                               collab.room_key("e2", "dev-a"), "m1", "sub-c")
        assert a1.key != b1.key
        # LA PREMIERE ARRIVEE VOIT UNE SALLE VIDE, la seconde ne la voit plus :
        # c'est ce `peers` qui decide qui seme le document, et l'ordre est
        # decide ici, dans un seul processus.
        epoque, pairs = collab.join(a1)
        assert pairs == 0 and epoque
        assert collab.join(a2)[1] == 1
        # L'autre equipe repart de zero : sa salle n'existait pas.
        epoque_b, pairs_b = collab.join(b1)
        assert pairs_b == 0 and epoque_b != epoque

        _sync(collab.broadcast(a1, {"t": "update", "d": "xx"}))
        assert a2.socket.envois == [{"t": "update", "d": "xx"}]
        # NI L'EMETTEUR (il a deja son changement), NI L'AUTRE EQUIPE.
        assert a1.socket.envois == []
        assert b1.socket.envois == []

        _sync(collab.announce(a1.key))
        assert a2.socket.envois[-1] == {"t": "presence", "online": ["m1", "m2"]}
        assert b1.socket.envois == []
    finally:
        collab.reset()


def test_une_salle_videe_change_d_epoque_et_le_client_repart_du_serveur():
    """L'EPOQUE EST LA COUTURE. La salle meurt avec son dernier membre et
    renait pour le suivant : un client qui revient avec un document local
    d'avant doit le JETER, sinon Yjs fusionnerait deux histoires et le
    fichier serait ecrit deux fois.
    """
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
    """Un membre avec deux onglets est une personne, pas un cinquieme coequipier.

    Et la borne existe pour qu'un compte ne puisse pas ouvrir mille sockets
    sur un service qui n'a qu'un worker.
    """
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
    """LE FILTRE EST POSE UNE FOIS, dans `exercices_pratique()`.

    Sans lui, un exercice ecrit a quatre gonflerait "exercices publies", les
    competences pratiquees, la recommandation et le main.c d'export -- quatre
    endroits, dont trois ou personne ne l'aurait vu.
    """
    entrees = [{"id": "solo", "skills": ["variables"]},
               {"id": "dev-a", "skills": ["variables"], "assignment": "devoir"},
               {"id": "verif", "skills": ["variables"], "verification": True}]
    assert [e["id"] for e in progression.exercices_pratique(entrees)] == ["solo"]
    # ET LA REGLE EST DANS LE SERVICE, pas recopiee dans le routeur : la
    # branche qui refuse l'XP nomme le meme champ.
    source = lire(os.path.join(HERE, "app", "routers", "submission.py"))
    assert 'entree.get("assignment")' in source
    # LA PAGE PORTE LE MEME FILTRE POUR L'EXPORT.
    page = lire(os.path.join(HERE, "web", "app.js"))
    assert "!t.assignment" in page


def test_le_listage_refuse_avant_d_ecrire_quoi_que_ce_soit():
    """`import_teams.read_roster` verifie TOUT avant d'ecrire UNE ligne.

    Un listage a moitie charge parce que la ligne 30 avait une faute est pire
    qu'un listage non charge : l'enseignant lit « termine », et trois etudiants
    n'ont silencieusement pas d'equipe le matin du laboratoire.

    CE N'EST PLUS LE CHEMIN PRINCIPAL : les etudiants choisissent leur equipe
    dans une liste numerotee, comme sur Moodle. Ce script reste pour CORRIGER
    -- deplacer quelqu'un une fois les listes figees, placer celui qui n'a rien
    choisi.
    """
    import importlib.util

    chemin = os.path.join(HERE, "import_teams.py")
    spec = importlib.util.spec_from_file_location("import_teams", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # LA POIGNEE EST CONSTRUITE DES DEUX COTES, et les deux doivent dire la
    # meme chose : ce script tourne avec le python de l'HOTE, qui ne voit pas
    # `app/`, donc la fonction y est recopiee. Sans ce controle, la copie
    # deriverait et les deux chemins nommeraient deux equipes differentes avec
    # les memes mots.
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
        # DEUX GROUPES, DEUX « EQUIPE 1 » : c'est le groupe dans la poignee qui
        # les separe, et donc leurs documents.
        assert module.sizes(lignes) == {"g04-e01": 2, "g06-e03": 1}

        for texte, attendu in (
                (entete + ",1,sub-a\n", "group_number must be 1..99"),
                (entete + "4,,sub-a\n", "number must be 1..99"),
                (entete + "0,1,sub-a\n", "group_number must be 1..99"),
                (entete + "4,100,sub-a\n", "number must be 1..99"),
                (entete + "4,1,\n", "account is required"),
                (entete, "empty"),
                # UN COMPTE SUR DEUX EQUIPES est refuse ici en NOMMANT la
                # ligne, avant que la cle primaire ne le refuse en parlant
                # d'un index.
                (entete + "4,1,sub-a\n6,2,sub-a\n", "two teams")):
            try:
                module.read_roster(ecrire(texte))
            except SystemExit as exc:
                assert attendu in str(exc), (attendu, str(exc))
            else:
                raise AssertionError("listage invalide accepte : " + repr(texte))

        # `--sql` : LE MEME LISTAGE, SANS PSYCOPG. Le python de l'hote du Dell
        # n'a aucun paquet tiers (`test_le_controle_de_l_hote_ne_depend_d_aucun_tiers`),
        # et y installer psycopg pour deux chargements par session mettrait une
        # dependance sur la seule machine que le projet garde propre.
        script = module.to_sql(lignes, "devoir")
        assert script.startswith("BEGIN;") and script.rstrip().endswith("COMMIT;")
        assert "'g04-e01'" in script and "'g06-e03'" in script, script
        # UNE SEULE SOURCE POUR LES DEUX CHEMINS : `load()` execute exactement
        # ces instructions-la.
        assert len(module.statements(lignes, "devoir")) == script.count(";") - 2
        # L'APOSTROPHE EST DOUBLEE, et c'est la seule chose a echapper :
        # `standard_conforming_strings` est a `on` depuis PostgreSQL 9.1.
        hostile = module.read_roster(ecrire(entete + "4,1,sub-o'brien\n"))
        assert "'sub-o''brien'" in module.to_sql(hostile, "devoir")
        # ET RIEN N'EST IMPRIME AVANT LA VERIFICATION : un listage refuse ne
        # produit pas un script a moitie bon qu'on passerait dans psql par
        # reflexe.
        try:
            module.to_sql(module.read_roster(ecrire(entete + "4,0,sub-a\n")),
                          "devoir")
        except SystemExit as exc:
            assert "number must be" in str(exc)
        else:
            raise AssertionError("un listage refuse a quand meme produit du SQL")
    finally:
        shutil.rmtree(dossier)


# --------------------------------------------------------------------------
# La Console
# --------------------------------------------------------------------------


def test_console_ne_monte_rien_du_contenu_prive():
    """La Console ne voit NI test, NI cas, NI corrige. C'est son invariant.

    Plus fort que ce que le mode io promet deja : celui-la ne monte pas le
    repertoire de l'exercice mais recoit ses ENTREES. Ici les deux seuls
    montages sont le main.c de l'etudiant et le script de construction.
    """
    garde = runner.CONTENT
    try:
        runner.CONTENT = "/opt/ctester/content"
        argv = runner.docker_argv_console("/spool/abc", "ctester-sbx-abc", "n0nce")
    finally:
        runner.CONTENT = garde
    joint = " ".join(argv)
    for interdit in ("/opt/ctester/content", "/in/cases", "/in/tests",
                     "/in/unity", "shared/unity"):
        assert interdit not in joint, (interdit, joint)
    # TOUT MONTAGE EST EN LECTURE SEULE, sans exception. C'est ce controle qui
    # empeche qu'un montage inscriptible reapparaisse un jour « pour deboguer ».
    montages = [argv[i + 1] for i, item in enumerate(argv) if item == "-v"]
    assert len(montages) == 2, montages
    for montage in montages:
        assert montage.endswith(":ro"), montage
    assert "/spool/abc/src:/in/src:ro" in montages
    # LA SURFACE INSCRIPTIBLE TIENT EN DEUX TMPFS, et il n'y en a pas un
    # troisieme. Le reste du systeme de fichiers est immuable.
    assert "--read-only" in argv
    tmpfs = [argv[i + 1] for i, item in enumerate(argv) if item == "--tmpfs"]
    assert len(tmpfs) == 2, tmpfs
    assert all(t.startswith(("/work:", "/tmp:")) for t in tmpfs), tmpfs
    # Et le spool n'est pas monte : le programme ne peut voir ni `in`, ni
    # `out`, ni le repertoire d'un autre job.
    assert "/spool/abc:" not in joint, joint


def test_console_est_interactive_et_sans_tty():
    argv = runner.docker_argv_console("/spool/abc", "ctester-sbx-abc", "n")
    assert "-i" in argv
    # `-t` ferait allouer un pty au worker, puis un second par dockerd dans le
    # sentry gVisor. Le constructeur de build-scratch.sh fait mieux, en pur gcc.
    assert "-t" not in argv and "-it" not in argv
    # Sans ca, docker recopie chaque octet de stdout dans son journal JSON --
    # le chemin le plus rapide vers un disque plein quand un programme peut
    # imprimer pendant trois minutes.
    assert argv[argv.index("--log-driver") + 1] == "none"
    assert "--privileged" not in argv
    assert argv[argv.index("--user") + 1] == "65534:65534"


def test_console_est_plus_stricte_que_la_correction():
    """Les plafonds de la Console DOIVENT rester sous ceux de la correction.

    Ce controle compare, il ne verifie pas des litteraux : c'est ce qui fait
    echouer une future « harmonisation » au lieu de la laisser relacher les
    plafonds. La fenetre d'exposition passe de 5 s par cas a CONSOLE_SESSION_MAX,
    soit trente-six fois -- d'ou des bornes plus serrees, pas egales.
    """
    def mo(valeur):
        return int(valeur.rstrip("m"))

    assert mo(runner.CONSOLE_MEMORY) < mo(runner.MEMORY)
    assert int(runner.CONSOLE_PIDS) < int(runner.PIDS)
    assert float(runner.CONSOLE_CPUS) <= float(runner.CPUS)
    juge = runner.docker_argv("/spool/abc", "/tests/tp1", "c", "io", "n")
    console = runner.docker_argv_console("/spool/abc", "c", "n")

    def taille(argv, point):
        for i, item in enumerate(argv):
            if item == "--tmpfs" and argv[i + 1].startswith(point + ":"):
                return int(argv[i + 1].split("size=")[1].split(",")[0].rstrip("m"))
        raise AssertionError(point)

    assert taille(console, "/work") < taille(juge, "/work")
    assert taille(console, "/tmp") < taille(juge, "/tmp")
    # Et la correction gagne en cas de contention.
    assert int(console[console.index("--cpu-shares") + 1]) < 1024


def test_console_bascule_de_phase_sur_le_marqueur():
    """`build` recoit gcc, `out` recoit le programme, et la coupe est unique.

    Le marqueur peut tomber A CHEVAL sur deux lectures : sans la queue gardee
    entre deux tours, il ne serait jamais reconnu et toute la session
    s'ecrirait dans `build`.
    """
    nonce = "abcd1234"
    for coupe in (None, 3, 12):
        dossier = tempfile.mkdtemp()
        try:
            lecture, ecriture = os.pipe()
            flux = (b"warning: ceci vient de gcc\n" + nonce.encode()
                    + b" RUN\n" + b"Entrez : " + b"42\n")
            if coupe is None:
                os.write(ecriture, flux)
            else:
                # On coupe DANS le marqueur, la ou c'est le plus mechant.
                pivot = flux.index(nonce.encode()) + coupe
                os.write(ecriture, flux[:pivot])
                os.write(ecriture, flux[pivot:])
            os.close(ecriture)

            class Faux:
                def __init__(self, fd):
                    self.stdout = type("F", (), {"fileno": lambda _s: fd})()

            compteur = {"octets": 0, "trop": False, "vu": 0.0, "compile": False}
            runner._pompe_sortie(Faux(lecture), dossier, nonce, compteur)
            os.close(lecture)
            build = open(os.path.join(dossier, "build"), "rb").read()
            out = open(os.path.join(dossier, "out"), "rb").read()
            assert build == b"warning: ceci vient de gcc\n", (coupe, build)
            assert out == b"Entrez : 42\n", (coupe, out)
            assert compteur["compile"] is True
            # Le marqueur lui-meme ne franchit jamais la frontiere.
            assert nonce.encode() not in build + out
        finally:
            shutil.rmtree(dossier)


def test_console_plafond_de_sortie():
    """`while (1) puts("x");` n'est JAMAIS inactif : seul ce plafond l'arrete."""
    dossier = tempfile.mkdtemp()
    garde = runner.CONSOLE_OUT_MAX
    try:
        runner.CONSOLE_OUT_MAX = 100
        lecture, ecriture = os.pipe()
        # ALIMENTE DEPUIS UN FIL, et pas d'un `os.write` direct : 5 Ko
        # depassent le tampon d'un tube sur certaines plateformes, et une
        # ecriture sans lecteur y bloque POUR TOUJOURS -- le harnais se fige
        # avant meme d'appeler ce qu'il teste. C'est la charge utile qui
        # compte ici (bien au-dela du plafond), pas qui la pousse.
        import threading as _fils

        def _verser():
            os.write(ecriture, b"n RUN\n" + b"x" * 5000)
            os.close(ecriture)

        pousseur = _fils.Thread(target=_verser, daemon=True)
        pousseur.start()

        class Faux:
            def __init__(self, fd):
                self.stdout = type("F", (), {"fileno": lambda _s: fd})()

        compteur = {"octets": 0, "trop": False, "vu": 0.0, "compile": False}
        runner._pompe_sortie(Faux(lecture), dossier, "n", compteur)
        pousseur.join(5)
        os.close(lecture)
        assert compteur["trop"] is True
        assert len(open(os.path.join(dossier, "out"), "rb").read()) <= 100
    finally:
        runner.CONSOLE_OUT_MAX = garde
        shutil.rmtree(dossier)


def test_console_une_seule_session_sur_tout_le_service():
    """Deux workers, un seul terminal : sinon plus personne ne corrige."""
    dossier = tempfile.mkdtemp()
    garde = runner.SPOOL
    try:
        runner.SPOOL = dossier
        assert runner.console_lock() is True
        # Le second worker n'obtient rien, et doit donc SAUTER le job.
        assert runner.console_lock() is False
        runner.console_unlock()
        assert runner.console_lock() is True
        # Un verrou abandonne par un worker tue est repris, mais seulement
        # apres une session entiere plus une marge.
        vieux = time.time() - (runner.CONSOLE_SESSION_MAX + 120)
        os.utime(os.path.join(dossier, runner.CONSOLE_LOCK), (vieux, vieux))
        assert runner.console_lock() is True
    finally:
        runner.SPOOL = garde
        shutil.rmtree(dossier)


def test_console_le_job_ne_porte_aucune_identite():
    """Ni `owner`, ni `sub`, ni `exercise_id` : le worker ne sait pas qui tape.

    Deux consequences gratuites, et ce sont elles qu'on protege ici :
    `_enregistrer()` exige un owner ET un exercice, donc il est inatteignable ;
    et la passe de cache du worker ignore la session d'elle-meme.
    """
    if fcntl is None:
        print("  (saute : pas de flock hors POSIX)")
        return

    dossier = tempfile.mkdtemp()
    garde = config.SPOOL
    try:
        config.SPOOL = dossier
        session = scratch.ouvrir("int main(void){return 0;}")
        job = json.loads(lire(os.path.join(session.chemin, "job.json")))
        assert job == {"kind": "console"}, job
        for interdit in ("owner", "sub", "account", "exercise_id", "utilisateur"):
            assert interdit not in job
        # Le code de l'etudiant est bien la, sous le nom que le script attend.
        assert lire(os.path.join(session.chemin, "src", "main.c")) \
            == "int main(void){return 0;}"
        # `job.json` EST ECRIT EN DERNIER : le verrou de vivacite le precede,
        # donc un worker ne peut pas voir une session avant que l'API n'ait
        # prouve qu'elle est vivante.
        assert session.worker_vivant() is False
        assert scratch._verrou_tenu(os.path.join(session.chemin, "alive")) is True
        session.fermer()
        assert scratch._verrou_tenu(os.path.join(session.chemin, "alive")) is False
    finally:
        config.SPOOL = garde
        shutil.rmtree(dossier)


def test_console_invisible_pour_le_cache_de_verdicts():
    """Un job sans exercice ne peut pas etre servi par le cache, PAR CONSTRUCTION.

    Ce n'est pas un `if` ajoute : `_contexte("")` passe par `tp_path("")`, qui
    ne resout rien. Le controle est ici pour que ca reste vrai.
    """
    assert runner._contexte("") is False
    # Et sa duree va sous sa PROPRE cle, sinon une console de trois minutes
    # compterait pour la moyenne d'une compilation de quinze secondes.
    assert runner.CONSOLE_DUREE.startswith(":")


def test_console_le_worker_tient_son_verrou_pendant_toute_la_session():
    """L'API sonde `claim` a chaque tour : si le worker ne le TIENT pas, elle
    conclut « le service s'est interrompu » sur une session parfaitement vivante.

    CE CONTROLE EXISTE PARCE QUE LE BOGUE A ETE ECRIT. `run_console()` decrivait
    ce verrou dans sa docstring sans le prendre, et aucun test unitaire ne
    pouvait le voir : chaque cote etait eprouve seul, et il n'y a que les deux
    ensemble qui mentent. Le terminal s'ouvrait puis se refermait aussitot en
    disant « worker ».
    """
    import threading as _fils

    if fcntl is None:
        print("  (saute : pas de flock hors POSIX)")
        return

    dossier = tempfile.mkdtemp()
    job = os.path.join(dossier, "a" * 32)
    os.makedirs(os.path.join(job, "src"))
    with open(os.path.join(job, "src", "main.c"), "w") as fh:
        fh.write("int main(void){return 0;}")
    # L'API tient `alive` : sans ca, run_console repart immediatement.
    tenu = os.open(os.path.join(job, "alive"), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)

    lecture, ecriture = os.pipe()
    relacher = _fils.Event()

    class FauxProcessus:
        returncode = None

        def __init__(self):
            self.stdout = type("F", (), {"fileno": lambda _s: lecture})()
            self.stdin = type("E", (), {"write": lambda _s, d: None,
                                        "flush": lambda _s: None,
                                        "close": lambda _s: None})()

        def poll(self):
            return None if not relacher.is_set() else 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            pass

    class FauxSubprocess:
        PIPE = STDOUT = -1
        TimeoutExpired = subprocess.TimeoutExpired
        Popen = staticmethod(lambda *a, **k: FauxProcessus())
        run = staticmethod(lambda *a, **k: None)

    garde = runner.subprocess
    # LE CONSTRUCTEUR EST STUBE COMME LE PROCESSUS. `run_console()` refuse de
    # depenser un conteneur quand `CTESTER_BUILD_SCRATCH` ne designe aucun
    # fichier -- et ce harnais tourne avec le python de l'HOTE, sans les
    # variables de l'unite systemd, donc il retomberait toujours sur le defaut.
    # C'est le verrou qu'on eprouve ici, pas la configuration du Dell.
    garde_build = runner.BUILD_SCRATCH
    try:
        runner.BUILD_SCRATCH = os.path.join(HERE, "build-scratch.sh")
        runner.subprocess = FauxSubprocess
        fil = _fils.Thread(target=runner.run_console, args=(job,), daemon=True)
        fil.start()
        # PENDANT que la session tourne, le verrou doit etre TENU.
        vu = False
        for _ in range(200):
            if scratch._verrou_tenu(os.path.join(job, "claim")):
                vu = True
                break
            time.sleep(0.01)
        assert vu, "le worker ne tient pas `claim` pendant la session"
        relacher.set()
        os.close(ecriture)
        fil.join(timeout=15)
        assert not fil.is_alive()
        # ET RELACHE APRES l'etat final, pas avant : l'API lit l'etat au meme
        # tour ou elle sonde le verrou.
        etat = json.loads(lire(os.path.join(job, "state.json")))
        assert etat["state"] == "exited", etat
        assert scratch._verrou_tenu(os.path.join(job, "claim")) is False
    finally:
        runner.subprocess = garde
        runner.BUILD_SCRATCH = garde_build
        os.close(tenu)
        try:
            os.close(lecture)
        except OSError:
            pass
        shutil.rmtree(dossier)


def test_console_une_session_ne_peut_pas_survivre_a_son_propre_balayage():
    """`SESSION_MAX` DOIT rester tres en dessous de `SWEEP_AFTER`.

    `sweep()` efface un repertoire de spool sur son MTIME, et le mtime d'un
    repertoire ne bouge plus une fois ses fichiers crees -- ecrire dans `out`
    ne le rajeunit pas. Une session plus longue que SWEEP_AFTER se ferait donc
    effacer le sol sous les pieds, en pleine frappe, par l'autre worker.

    Meme classe de contrainte que LOCK_STALE, qui doit rester sous SWEEP_AFTER
    pour que reclaim() puisse encore reprendre un verrou avant que le job ne
    disparaisse. Le facteur deux est la marge : le temps de detecter, de tuer
    le conteneur et d'ecrire le resultat.
    """
    assert runner.CONSOLE_SESSION_MAX * 2 < runner.SWEEP_AFTER, (
        runner.CONSOLE_SESSION_MAX, runner.SWEEP_AFTER)
    # Et le verrou de session, lui, se reprend APRES la fin d'une session --
    # sinon un worker en reprendrait un encore vivant.
    assert runner.CONSOLE_SESSION_MAX < runner.CONSOLE_SESSION_MAX + 60


def test_console_n_a_pas_de_liste_d_includes():
    """`#include <unistd.h>` compile dans la Console, et c'est le dessin.

    La liste est PEDAGOGIQUE, pas securitaire : son message est « utilise
    seulement ce qui a ete vu en cours », et elle vit dans l'`assessment` d'un
    EXERCICE. Une console n'a pas d'exercice, donc pas de liste. Elle n'a
    jamais ete la frontiere de toute facon -- `system()` vient de <stdlib.h>,
    que tous les exercices autorisent. La frontiere est --network none,
    --cap-drop ALL, --read-only, l'uid 65534 et gVisor.

    Sans ce controle, quelqu'un rajoute la liste « par symetrie » dans six mois
    et herite de deux listes a tenir synchronisees.
    """
    source = lire(os.path.join(HERE, "runner.py"))
    corps = source[source.index("def run_console("):]
    corps = corps[:corps.index("\ndef ")]
    assert "read_allowed" not in corps
    assert "forbidden_includes" not in corps


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
