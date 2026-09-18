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
import policy as policy  # noqa: E402
import security   # noqa: E402
from services import catalog as catalogue    # noqa: E402
from services import discord      # noqa: E402
from services import forum        # noqa: E402
from services import leaderboard  # noqa: E402
from services import progress as progress  # noqa: E402
from services import quotas       # noqa: E402
from services import collab      # noqa: E402
from services import teams       # noqa: E402
from services import spool        # noqa: E402
from services import source       # noqa: E402
from services import scratch      # noqa: E402


def read_file(path):
    with open(path, encoding="utf-8") as fh:
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
    release = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(days=30)
    try:
        _write_json(os.path.join(root, "catalog.json"),
                    {"schema_version": 1, "skills": ["variables"]})
        exercise = os.path.join(root, "exercises", "surface-rectangle")
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": "surface-rectangle", "title": "Surface",
            "summary": "Calcule une surface.", "skills": ["variables"],
            "difficulty": "foundation", "contexts": ["mechanical"],
            "release": {"state": "scheduled", "available_from": release.isoformat()},
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
        assert content_catalogue.find_exercise(model, "surface-rectangle") is None
        opened = release + dt.timedelta(days=1)
        assert content_catalogue.public_detail(model, "surface-rectangle", opened) == {
            "statement": "Calcule la surface.",
            "files": [{"name": "submission.c", "template": "int main(void) {}"}]}
        assert content_catalogue.public_detail(model, "inconnu", opened) is None
        assert content_catalogue.find_exercise(model, "surface-rectangle", opened) is not None
    finally:
        shutil.rmtree(root)


def _content_with_flag(root, value, flag="verification"):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": ["variables"]})
    exercise = os.path.join(root, "exercises", "verif-tp2")
    data = {"schema_version": 1, "id": "verif-tp2", "title": "Vérification",
               "skills": ["variables"], "release": {"state": "available"}}
    if value is not None:
        data[flag] = value
    _write_json(os.path.join(exercise, "exercise.json"), data)
    with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
        fh.write("Lis ce code.")
    _write_json(os.path.join(exercise, "assessment", "quiz.json"),
                {"questions": [{"id": "q1", "label": "?", "answer": "42"}]})


def _repository(root, skill, *ids):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": [skill]})
    for exercise_id in ids:
        exercise = os.path.join(root, "exercises", exercise_id)
        _write_json(os.path.join(exercise, "exercise.json"),
                    {"schema_version": 1, "id": exercise_id, "title": "Titre",
                     "skills": [skill], "release": {"state": "available"}})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Lis ce code.")
        _write_json(os.path.join(exercise, "assessment", "quiz.json"),
                    {"questions": [{"id": "q1", "label": "?", "answer": "42"}]})
    return root


def _two_repositories():
    base = tempfile.mkdtemp(prefix="ctester-repositories-")
    a = _repository(os.path.join(base, "cours-a", "content"), "boucles", "tp1-ex1", "tp1-ex2")
    b = _repository(os.path.join(base, "cours-b", "content"), "pointeurs", "tp9-ex1")
    return base, a, b


def test_several_repositories_merge_into_one_catalogue():
    base, a, b = _two_repositories()
    try:
        model = content_catalogue.discover([a, b])
        assert list(model["exercises"]) == ["tp1-ex1", "tp1-ex2", "tp9-ex1"]
        # The vocabulary is the union: an exercise may target a skill declared elsewhere.
        assert model["skills"] == ["boucles", "pointeurs"], model["skills"]
        # Nothing downstream names a source: the projection stays one flat namespace.
        public = content_catalogue.public_catalogue(model)
        assert [e["id"] for e in public["exercises"]] == ["tp1-ex1", "tp1-ex2", "tp9-ex1"]
        assert "source" not in json.dumps(public)
    finally:
        shutil.rmtree(base)


def test_the_revision_does_not_depend_on_the_repository_order():
    base, a, b = _two_repositories()
    try:
        one = publish_content.revision(
            publish_content.projection(content_catalogue.discover([a, b])))
        two = publish_content.revision(
            publish_content.projection(content_catalogue.discover([b, a])))
        assert one == two, "reordering CTESTER_CONTENT would republish the whole catalogue"
    finally:
        shutil.rmtree(base)


def test_an_id_shared_by_two_repositories_blocks_publication():
    base, a, b = _two_repositories()
    try:
        _repository(b, "pointeurs", "tp1-ex1")
        try:
            content_catalogue.discover([a, b])
        except content_catalogue.ContentValidationError as exc:
            text = str(exc)
            assert "duplicate exercise id: tp1-ex1" in text, text
            # The message must name both repositories, or it is useless.
            assert "cours-a" in text and "cours-b" in text, text
        else:
            raise AssertionError("two repositories could claim the same id")
    finally:
        shutil.rmtree(base)


def test_a_single_root_keeps_its_messages_unprefixed():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _repository(root, "boucles", "tp1-ex1")
        os.remove(os.path.join(root, "exercises", "tp1-ex1", "statement.md"))
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert str(exc).startswith("exercises/tp1-ex1:"), exc
        else:
            raise AssertionError("missing statement accepted")
    finally:
        shutil.rmtree(root)


def test_content_roots_splits_like_the_environment_variable():
    assert content_catalogue.content_roots("/a") == ["/a"]
    assert content_catalogue.content_roots(["/a", "/b"]) == ["/a", "/b"]
    roots = content_catalogue.content_roots("/a%s%s/b%s" % (os.pathsep, os.pathsep, os.pathsep))
    assert roots == ["/a", "/b"], roots


def test_content_v2_marks_a_verification():
    for value, expected in ((True, True), (False, None), (None, None)):
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _content_with_flag(root, value)
            public = content_catalogue.public_catalogue(content_catalogue.discover(root))
            assert public["exercises"][0].get("verification") is expected, value
            assert "answer" not in json.dumps(public)
        finally:
            shutil.rmtree(root)
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _content_with_flag(root, "oui")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "verification" in str(exc), exc
        else:
            raise AssertionError("non-boolean flag accepted")
    finally:
        shutil.rmtree(root)


def test_content_v2_marks_a_bonus():
    for value, expected in ((True, True), (False, None), (None, None)):
        root = tempfile.mkdtemp(prefix="ctester-content-")
        try:
            _content_with_flag(root, value, "bonus")
            public = content_catalogue.public_catalogue(content_catalogue.discover(root))
            assert public["exercises"][0].get("bonus") is expected, value
            assert "answer" not in json.dumps(public)
        finally:
            shutil.rmtree(root)
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _content_with_flag(root, "oui", "bonus")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "bonus" in str(exc), exc
        else:
            raise AssertionError("non-boolean flag accepted")
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
            raise AssertionError("invalid v2 content accepted")
    finally:
        shutil.rmtree(root)


def _content_v2(root, quiz_state):
    _write_json(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    for name, release, config in (
            ("surface", {"state": "available"}, ("io.json", {"cases": [{"stdin": "1\n", "expect": [1]}]})),
            ("nombres", quiz_state, ("quiz.json", {"label": "Quiz", "questions": [
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


def test_content_v2_publication_locks_and_switches():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        _content_v2(root, {"state": "scheduled", "available_from": "2099-01-01T00:00:00-05:00"})
        model = content_catalogue.discover(root)
        revision = publish_content.publish(model, dest)
        release = publish_content.current(dest)
        assert release == os.path.join(dest, revision), release
        published = {}
        for directory, _, names in os.walk(release):
            for name in names:
                path = os.path.join(directory, name)
                published[os.path.relpath(path, release).replace(os.sep, "/")] = read_file(path)
        assert sorted(published) == ["catalog.json", "exercises/surface.json",
                                  "manifest.json", "staff/exercises/nombres.json",
                                  "staff/quiz/nombres.json"], sorted(published)
        assert "answer" not in "".join(published.values()), published
        assert "00010111" not in "".join(published.values()), published
        published_catalogue = json.loads(published["catalog.json"])
        states = {e["id"]: e["access"] for e in published_catalogue["exercises"]}
        assert states == {"surface": "available", "nombres": "scheduled"}, states

        assert publish_content.publish(model, dest) == revision
        _write_json(os.path.join(root, "exercises", "surface", "exercise.json"), {
            "schema_version": 1, "id": "surface", "title": "Surface v2",
            "release": {"state": "available"}})
        following = publish_content.publish(content_catalogue.discover(root), dest)
        assert following != revision, following
        assert publish_content.current(dest) == os.path.join(dest, following)
        assert os.path.isdir(os.path.join(dest, revision)), "rollback impossible"

        _content_v2(root, {"state": "available"})
        opened = publish_content.publish(content_catalogue.discover(root), dest)
        quiz = json.loads(read_file(os.path.join(dest, opened, "quiz", "nombres.json")))
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
                path = os.path.join(dest, name)
                if os.path.isdir(path):
                    os.utime(path, (1_000_000, 1_000_000))
        assert len(set(revisions)) == 5, revisions
        remaining = {name for name in os.listdir(dest)
                    if os.path.isdir(os.path.join(dest, name))}
        assert len(remaining) == 3, remaining
        assert remaining == set(revisions[-3:]), (remaining, revisions)
        assert publish_content.current(dest) == os.path.join(dest, revisions[-1])
        orphan = os.path.join(dest, "0" * 16)
        os.makedirs(orphan)
        os.utime(orphan, (1_000_000, 1_000_000))
        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "exercise.json"), {
            "schema_version": 1, "id": "ex1", "title": "Exercise 9",
            "release": {"state": "available"}})
        publish_content.publish(content_catalogue.discover(root), dest, keep=3)
        assert not os.path.isdir(orphan), "a revision without a manifest survives"
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


def test_publication_refuses_a_worker_without_content():
    for content, published in (("", ""), ("/tmp/x", ""), ("", "/tmp/y")):
        try:
            publish_content.publish_catalogue(content, published)
        except RuntimeError as exc:
            assert "CTESTER_CONTENT" in str(exc), exc
        else:
            raise AssertionError("silent publication: %r %r" % (content, published))


def test_publish_catalogue_really_publishes_and_says_so_in_preview():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        _content_v2(root, {"state": "scheduled",
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


def test_content_v2_projection_refuses_a_private_key():
    model = {"schema_version": 1, "skills": [], "collections": {},
              "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                  "skills": [], "mode": "io", "summary": "",
                                  "difficulty": None, "contexts": [],
                                  "statement": "", "files": [], "config": {}}}}
    original = content_catalogue.public_detail
    content_catalogue.public_detail = lambda *a, **k: {"statement": "", "answer": "42"}
    try:
        publish_content.projection(model)
    except content_catalogue.ContentValidationError as exc:
        assert "answer" in str(exc), exc
    else:
        raise AssertionError("projection published with a private key")
    finally:
        content_catalogue.public_detail = original


def _typst_content(root, statement=None, released=True):
    _write_json(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    exercise = os.path.join(root, "exercises", "demo")
    _write_json(os.path.join(exercise, "exercise.json"), {
        "schema_version": 1, "id": "demo", "title": "Démo",
        "release": {"state": "available"} if released else
                   {"state": "scheduled", "available_from": "2099-01-01T00:00:00-05:00"}})
    _write_json(os.path.join(exercise, "assessment", "io.json"),
                {"cases": [{"stdin": "1\n", "expect": [1]}]})
    _write_json(os.path.join(exercise, "public", "files.json"),
                {"files": [{"name": "submission.c", "template": ""}]})
    with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
        fh.write(statement if statement is not None else "= Titre\n\nDu texte.\n")
    return exercise


def _typst_available():
    try:
        typst_build._version()
        return True
    except typst_build.TypstError:
        return False


def test_typst_one_statement_format_at_a_time():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        exercise = _typst_content(root)
        model = content_catalogue.discover(root)
        assert model["exercises"]["demo"]["statement_format"] == "typ"
        assert model["exercises"]["demo"]["statement"] == "", model["exercises"]["demo"]

        os.remove(os.path.join(exercise, "statement.typ"))
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        model = content_catalogue.discover(root)
        assert model["exercises"]["demo"]["statement_format"] == "md"
        assert model["exercises"]["demo"]["statement"] == "Consigne."
        assert content_catalogue.public_detail(model, "demo") == {
            "statement": "Consigne.",
            "files": [{"name": "submission.c", "template": ""}]}, "the Markdown changed"

        with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
            fh.write("= x\n")
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "statement.md AND statement.typ" in str(exc), exc
        else:
            raise AssertionError("both formats were accepted")

        os.remove(os.path.join(exercise, "statement.md"))
        os.remove(os.path.join(exercise, "statement.typ"))
        try:
            content_catalogue.discover(root)
        except content_catalogue.ContentValidationError as exc:
            assert "statement.md or statement.typ is missing" in str(exc), exc
        else:
            raise AssertionError("an exercise without a statement was accepted")
    finally:
        shutil.rmtree(root)


def test_typst_the_public_detail_carries_a_count_and_no_path():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        _typst_content(root)
        model = content_catalogue.discover(root)
        detail = content_catalogue.public_detail(model, "demo", pages=3)
        assert detail["statement"] == "", detail
        assert detail["statement_format"] == "typst", detail
        assert detail["statement_pages"] == 3, detail
        blob = json.dumps(detail)
        for forbidden in ("statements/", ".svg", "/", "typ\""):
            assert forbidden not in blob.replace("\"statement_format\"", ""), (forbidden, blob)
    finally:
        shutil.rmtree(root)


def test_typst_the_projection_refuses_an_unexpected_source_or_asset():
    model = {"schema_version": 1, "skills": [], "collections": {}, "assignments": {},
              "exercises": {"x": {"id": "x", "title": "X", "release": {"state": "available"},
                                  "skills": [], "mode": "io", "summary": "",
                                  "difficulty": None, "contexts": [], "statement": "",
                                  "statement_format": "md", "files": [], "config": {}}}}
    original = content_catalogue.public_detail
    try:
        for wrong, expected in (
                ({"x/statement.typ": {"a": 1}}, "Typst source reached"),
                ({"statements/x/dark-99.svg": b"<svg/>"}, "unexpected binary artefact"),
                ({"autre/chose.bin": b"\0\0"}, "unexpected binary artefact"),
                ({"staff/statements/x/dark-1.svg": b"<svg/>"}, None),
                ({"statements/x/light-16.svg": b"<svg/>"}, None)):
            content_catalogue.public_detail = lambda *a, **k: {"statement": ""}
            files = publish_content.projection(model)
            files.update(wrong)
            bad = [c for c, v in files.items()
                       if c.endswith(".typ")
                       or (isinstance(v, bytes) and not publish_content.ACTIVE_RE.match(c))]
            if expected is None:
                assert not bad, (wrong, bad)
            else:
                assert bad == list(wrong), (wrong, bad)
    finally:
        content_catalogue.public_detail = original


def test_typst_the_revision_moves_when_a_render_moves():
    base = {"catalog.json": {"schema_version": 1},
            "statements/x/dark-1.svg": b"<svg>A</svg>"}
    other = dict(base, **{"statements/x/dark-1.svg": b"<svg>B</svg>"})
    assert publish_content.revision(base) != publish_content.revision(other)
    assert publish_content.revision(base) == publish_content.revision(dict(base))


def test_typst_the_cache_key_covers_everything_the_render_depends_on():
    root = tempfile.mkdtemp(prefix="ctester-content-")
    try:
        exercise = _typst_content(root)
        initial = typst_build.fingerprint(exercise, version="0.15.1")
        assert initial == typst_build.fingerprint(exercise, version="0.15.1")
        assert typst_build.fingerprint(exercise, version="0.99.0") != initial
        with open(os.path.join(exercise, "statement.typ"), "a", encoding="utf-8") as fh:
            fh.write("Une ligne de plus.\n")
        after_text = typst_build.fingerprint(exercise, version="0.15.1")
        assert after_text != initial
        os.makedirs(os.path.join(exercise, "images"), exist_ok=True)
        with open(os.path.join(exercise, "images", "x.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        after_image = typst_build.fingerprint(exercise, version="0.15.1")
        assert after_image != after_text
        _write_json(os.path.join(exercise, "assessment", "io.json"),
                    {"cases": [{"stdin": "9\n", "expect": [9]}]})
        assert typst_build.fingerprint(exercise, version="0.15.1") == after_image
        theme = os.path.join(typst_build.LIB, "themes", "ctester-dark.tmTheme")
        saved = read_file(theme)
        try:
            with open(theme, "a", encoding="utf-8", newline="") as fh:
                fh.write("\n<!-- x -->\n")
            assert typst_build.fingerprint(exercise, version="0.15.1") != after_image
        finally:
            with open(theme, "w", encoding="utf-8", newline="") as fh:
                fh.write(saved)
        assert typst_build.fingerprint(exercise, version="0.15.1") == after_image
    finally:
        shutil.rmtree(root)


def test_typst_the_cache_never_lives_under_published():
    saved = dict(os.environ)
    try:
        os.environ.pop("CTESTER_TYPST_CACHE", None)
        os.environ["CTESTER_PUBLISHED"] = "/opt/ctester/published"
        path = typst_build.cache_dir()
        assert not path.startswith("/opt/ctester/published/"), path
        assert path == "/opt/ctester/typst-cache", path
        os.environ["CTESTER_TYPST_CACHE"] = "/ailleurs"
        assert typst_build.cache_dir() == "/ailleurs"
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_typst_mermaid_has_a_single_gate():
    gate = os.path.join(typst_build.LIB, "mermaid.typ")
    assert '@preview/merman:0.3.0' in read_file(gate), gate
    for root, _, files in os.walk(typst_build.LIB):
        for name in files:
            path = os.path.join(root, name)
            if path == gate or not name.endswith(".typ"):
                continue
            assert "merman" not in read_file(path), path
    manifest = os.path.join(typst_build.PACKAGES, "preview", "merman", "0.3.0",
                             "typst.toml")
    assert 'version = "0.3.0"' in read_file(manifest), manifest


def test_the_typst_theme_carries_the_page_colors():
    css = read_file(os.path.join(ROOT, "frontend", "src", "app.css"))
    css_classes = ("comment", "string", "pre", "key", "num", "fn", "const")
    for theme, block in (("dark", css.split(":root {")[1].split("}")[0]),
                        ("light", css.split(':root[data-theme="light"] {')[1].split("}")[0])):
        expected_colors = {}
        for css_class in css_classes:
            found = re.search(r"--syn-%s:\s*(#[0-9a-fA-F]{6})" % css_class, block)
            assert found, (theme, css_class)
            expected_colors[css_class] = found.group(1).lower()
        tm = read_file(os.path.join(typst_build.LIB, "themes", "ctester-%s.tmTheme" % theme))
        for css_class, color in expected_colors.items():
            assert color in tm.lower(), \
                "--syn-%s (%s theme, %s) missing from the .tmTheme" % (css_class, theme, color)
        for variable in ("--fg", "--panel"):
            found = re.search(r"%s:\s*(#[0-9a-fA-F]{3,6})" % variable, block)
            assert found and found.group(1).lower() in tm.lower(), (theme, variable)


def test_typst_root_refuses_to_leave_the_exercise_directory():
    if not _typst_available():
        print("     (skipped: neither CTESTER_TYPST_BIN nor Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    saved = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        with open(os.path.join(root, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("SECRET-DU-BUILD")
        exercise = _typst_content(root)
        for attack in ('#read("../../secret.txt")',
                        '#read("/etc/passwd")',
                        '#read("assessment/io.json")',
                        '#include "../../secret.txt"',
                        '#image("../../../etc/hostname")'):
            with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
                fh.write(attack + "\n")
            try:
                typst_build.render(exercise, "demo")
            except typst_build.TypstError as exc:
                assert "SECRET-DU-BUILD" not in str(exc), (attack, exc)
            else:
                raise AssertionError("a read outside the exercise succeeded: "
                                     + attack)
    finally:
        if saved is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = saved
        shutil.rmtree(root)
        shutil.rmtree(cache)


def test_typst_the_fixture_really_compiles_in_both_themes():
    if not _typst_available():
        print("     (skipped: neither CTESTER_TYPST_BIN nor Docker)")
        return
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    saved = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        fixture = os.path.join(ROOT, "typst", "fixture")
        rendered, cached = typst_build.render(fixture, "fixture-typst")
        assert cached is False, "a fresh cache cannot already serve"
        assert sorted(rendered) == ["dark", "html", "light"], sorted(rendered)
        html = rendered["html"]
        assert b"<h2>" in html and b"plus_grand" in html, html[:200]
        assert b"#import" not in html
        assert len(rendered["dark"]) >= 2, "#pagebreak() did not produce two pages"
        assert len(rendered["dark"]) == len(rendered["light"]), "the two themes diverge"
        for theme in typst_build.THEMES:
            pages = rendered[theme]
            for number, data in enumerate(pages, 1):
                assert data.startswith(b"<svg"), (theme, number, data[:40])
                assert b"plus_grand" not in data, (theme, number)
                assert b"#import" not in data, (theme, number)
        assert rendered["dark"][0] != rendered["light"][0]
        again, cached = typst_build.render(fixture, "fixture-typst")
        assert cached is True and again == rendered
    finally:
        if saved is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = saved
        shutil.rmtree(cache)


def test_typst_an_error_names_the_exercise_the_file_and_the_line():
    if not _typst_available():
        print("     (skipped: neither CTESTER_TYPST_BIN nor Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    saved = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        _typst_content(root, "= Titre\n\n#une-fonction-qui-n-existe-pas()\n")
        model = content_catalogue.discover(root)
        try:
            typst_build.render_all(model)
        except typst_build.TypstError as exc:
            message = str(exc)
            assert "demo" in message, message
            assert "statement.typ" in message, message
            assert ":3:" in message, ("no line in the message", message)
        else:
            raise AssertionError("a broken statement.typ was rendered")
    finally:
        if saved is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = saved
        shutil.rmtree(root)
        shutil.rmtree(cache)


def test_typst_publication_writes_the_pages_and_respects_the_lock():
    if not _typst_available():
        print("     (skipped: neither CTESTER_TYPST_BIN nor Docker)")
        return
    root = tempfile.mkdtemp(prefix="ctester-content-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    cache = tempfile.mkdtemp(prefix="ctester-typst-cache-")
    saved = os.environ.get("CTESTER_TYPST_CACHE")
    try:
        os.environ["CTESTER_TYPST_CACHE"] = cache
        for released, prefix in ((True, ""), (False, "staff/")):
            _typst_content(root, released=released)
            model = content_catalogue.discover(root)
            renders, (total, _) = typst_build.render_all(model)
            assert total == 1, total
            revision = publish_content.publish(model, dest, renders=renders)
            release = os.path.join(dest, revision)
            published = sorted(
                os.path.relpath(os.path.join(d, n), release).replace(os.sep, "/")
                for d, _, names in os.walk(release) for n in names)
            expected_paths = [prefix + "statements/demo/%s-1.svg" % t
                        for t in ("dark", "light")]
            for path in expected_paths:
                assert path in published, (path, published)
            assert not any(c.endswith(".typ") for c in published), published
            detail = json.loads(read_file(os.path.join(
                release, prefix + "exercises/demo.json")))
            assert detail["statement_format"] == "typst", detail
            assert detail["statement_pages"] == 1, detail
            assert detail["statement"] == "", detail
    finally:
        if saved is None:
            os.environ.pop("CTESTER_TYPST_CACHE", None)
        else:
            os.environ["CTESTER_TYPST_CACHE"] = saved
        for path in (root, dest, cache):
            shutil.rmtree(path)


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
         "statement.md or statement.typ is missing"),
        (lambda r: open(os.path.join(ex(r), "statement.typ"), "w").close(),
         "statement.md AND statement.typ are both present"),
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
        opened = content_catalogue.load_exercise(root, "ex1", unreleased=True)
        assert opened is not None and opened["mode"] == "io"

        _minimal_valid_content(root)
        _write_json(os.path.join(root, "exercises", "ex1", "assessment", "quiz.json"),
                    {"questions": []})
        assert content_catalogue.load_exercise(root, "ex1") is None
    finally:
        shutil.rmtree(root)


def test_presence_counter():
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


def test_policy_is_declarative():
    assert policy.VERSION
    thresholds = policy.POLICY["levels"]
    assert thresholds[0] == 0 and thresholds == sorted(thresholds) == list(dict.fromkeys(thresholds))
    ids = set()
    for achievement in policy.POLICY["achievements"]:
        assert achievement["title"] and achievement["description"]
        assert achievement["on"] and achievement["threshold"] >= 1
        assert achievement["id"] not in ids
        ids.add(achievement["id"])
    assert set(policy.ACHIEVEMENTS) == ids
    bands = policy.POLICY["mastery"]["bands"]
    for band in bands:
        assert band["title"] and band["description"]
    assert set(policy.BANDS) == {b["id"] for b in bands} == set(
        policy.mastery_band(r, t, n)
        for n in range(0, 4) for t in range(0, n + 1) for r in range(0, t + 1))
    progress = read_file(os.path.join(ROOT, "app", "services", "progress.py"))
    for amount in set(policy.POLICY["xp"].values()):
        assert not re.search(r"%d" % amount, progress), amount
    assert not re.search(r"%d" % policy.daily_cap(), progress)


def test_level_derives_from_the_balance():
    thresholds = policy.POLICY["levels"]
    assert policy.level(0)["rank"] == 1
    assert policy.level(-5)["rank"] == 1
    assert policy.level(thresholds[1])["rank"] == 2
    assert policy.level(thresholds[1] - 1)["rank"] == 1
    at_the_top = policy.level(thresholds[-1] + 1000)
    assert at_the_top["rank"] == len(thresholds) and at_the_top["next"] is None
    assert policy.level(thresholds[1] - 4)["remaining"] == 4


def test_achievements_derive_from_facts():
    assert policy.achievements_reached({}) == []
    assert policy.achievements_reached({"solved": 1}) == ["premiere-reussite"]
    many = policy.achievements_reached({"solved": 10, "skills": 3,
                                               "verifications": 1})
    assert set(many) == set(policy.ACHIEVEMENTS)
    assert "premiere-verification" not in policy.achievements_reached(
        {"solved": 10, "skills": 3})
    assert policy.achievements_reached({"inconnu": 99}) == []


CATALOGUE_DEMO = [
    {"id": "tp2-ex0", "skills": ["variables"], "difficulty": "intro"},
    {"id": "tp2-ex3", "skills": ["variables", "arithmetic-operators"],
     "difficulty": "foundation"},
    {"id": "tp7-ex1", "skills": ["arrays-1d"]},
    {"id": "tp1"},
]


CATALOGUE_VERIFICATION = CATALOGUE_DEMO + [
    {"id": "verif-a", "skills": ["variables", "arithmetic-operators"],
     "verification": True},
    {"id": "verif-b", "skills": ["variables"], "verification": True},
]


def evidence(exercise, solved):
    return {"exercise_id": exercise, "payload": {"job": "j", "passed": solved}}


def test_skills_projection():
    states = [{"exercise_id": "tp2-ex0", "status": "solved"},
             {"exercise_id": "tp2-ex3", "status": "attempted"}]
    practice = [{"exercise_id": "tp7-ex1", "attempts": 2, "successes": 0}]
    touched, solved = progress.exercise_facts(states, practice)
    assert touched == {"tp2-ex0", "tp2-ex3", "tp7-ex1"}
    assert solved == {"tp2-ex0"}
    degraded = progress.exercise_facts(
        states + [{"exercise_id": "", "status": "solved"}, {"status": "solved"}],
        practice + [{"exercise_id": None}, {}])
    assert degraded == (touched, solved)
    view = progress.skills_view(CATALOGUE_DEMO, touched, solved)
    assert [c["id"] for c in view] == ["variables", "arithmetic-operators", "arrays-1d"]
    assert view[0] == {"id": "variables", "total": 2, "practiced": 2, "solved": 1}
    assert view[2] == {"id": "arrays-1d", "total": 1, "practiced": 1, "solved": 0}


def test_deterministic_recommendation():
    states = [{"exercise_id": "tp2-ex0", "status": "solved"}]
    touched, solved = progress.exercise_facts(states, [])
    assert progress.recommend(CATALOGUE_DEMO, touched, solved) == {
        "exercise_id": "tp2-ex3", "skill": "variables"}
    assert progress.recommend(CATALOGUE_DEMO, set(), set()) == {
        "exercise_id": "tp2-ex0", "skill": None}
    all_ids = {e["id"] for e in CATALOGUE_DEMO}
    assert progress.recommend(CATALOGUE_DEMO, all_ids, all_ids) is None
    assert progress.recommend([], set(), set()) is None


def test_progress_publishes_nothing_secret():
    facts = {"xp": 25, "achievements": [{"id": "premiere-reussite",
                                   "unlocked_at": "2026-09-03", "policy": "x"},
                                  {"id": "disparu", "unlocked_at": "2026-09-03",
                                   "policy": "x"}],
             "transactions": [{"exercise_id": "tp2-ex0", "amount": 10,
                               "reason": "premiere reussite",
                               "granted_at": "2026-09-03"}]}
    payload = progress.progress_payload(
        CATALOGUE_DEMO, facts,
        [{"exercise_id": "tp2-ex0", "status": "solved"}], [], [])
    assert payload["policy"] == policy.VERSION
    assert payload["xp"] == 25 and payload["level"]["rank"] >= 1
    assert payload["exercises"] == {"total": 4, "practiced": 1, "solved": 1}
    assert [s["id"] for s in payload["achievements"]] == ["premiere-reussite"]
    assert payload["achievements"][0]["title"] and payload["achievements"][0]["description"]
    assert [b["id"] for b in payload["mastery"]["bands"]] == list(policy.BANDS)
    assert payload["mastery"]["skills"] == []
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("path", "answer", "statement", "sources", "template"):
        assert forbidden not in text, forbidden


def test_mastery_bands_by_coverage():
    empty = progress.mastery_view(CATALOGUE_VERIFICATION, [])
    assert [c["id"] for c in empty] == ["variables", "arithmetic-operators"]
    assert empty[0] == {"id": "variables", "total": 2, "attempted": 0,
                       "passed": 0, "band": "non-verifie"}

    one = progress.mastery_view(CATALOGUE_VERIFICATION, [evidence("verif-a", True)])
    by_id = {c["id"]: c for c in one}
    assert by_id["variables"]["band"] == "en-progression"
    assert by_id["arithmetic-operators"]["band"] == "verifie"

    two = progress.mastery_view(
        CATALOGUE_VERIFICATION, [evidence("verif-b", True), evidence("verif-a", True)])
    assert {c["id"]: c["band"] for c in two} == {
        "variables": "verifie", "arithmetic-operators": "verifie"}

    rate = progress.mastery_view(CATALOGUE_VERIFICATION, [evidence("verif-a", False)])
    assert {c["id"]: c["band"] for c in rate} == {
        "variables": "a-consolider", "arithmetic-operators": "a-consolider"}
    assert by_id["variables"]["attempted"] == 1


def test_mastery_keeps_the_last_attempt():
    journal = [evidence("verif-a", False), evidence("verif-a", True)]
    assert progress.latest_attempts(journal) == {"verif-a": False}
    view = {c["id"]: c for c in progress.mastery_view(CATALOGUE_VERIFICATION, journal)}
    assert view["arithmetic-operators"]["band"] == "a-consolider"
    assert progress.solved_verifications(journal) == {"verif-a"}


def test_a_practice_moves_no_band():
    all_solved = [{"exercise_id": e["id"], "status": "solved"}
                   for e in CATALOGUE_DEMO]
    facts = {"xp": 75, "achievements": [], "transactions": []}
    payload = progress.progress_payload(CATALOGUE_VERIFICATION, facts, all_solved,
                                          [], [])
    assert payload["exercises"]["solved"] == 4
    assert all(c["band"] == "non-verifie"
               for c in payload["mastery"]["skills"])


def test_a_verification_does_not_count_as_a_practice():
    payload = progress.progress_payload(
        CATALOGUE_VERIFICATION, {"xp": 0, "achievements": [], "transactions": []}, [], [], [])
    assert payload["exercises"]["total"] == len(CATALOGUE_DEMO)
    assert payload["next"]["exercise_id"] == "tp2-ex0"
    by_id = {c["id"]: c for c in payload["skills"]}
    assert by_id["variables"]["total"] == 2
    assert "arrays-1d" in by_id
    all_ids = {e["id"] for e in CATALOGUE_DEMO}
    assert progress.recommend(
        progress.practice_exercises(CATALOGUE_VERIFICATION), all_ids, all_ids) is None


def test_no_index_precedes_the_column_it_indexes():
    schema = read_file(os.path.join(ROOT, "app", "schema.sql"))
    instructions = re.sub(r"--[^\n]*", "", schema)
    additions = re.findall(
        r"ALTER TABLE\s+(\w+)\s+ADD COLUMN IF NOT EXISTS\s+(\w+)", instructions)
    assert additions, "no ALTER ... ADD COLUMN: this check no longer proves anything"
    first_alter = min(
        instructions.index(m.group(0))
        for m in re.finditer(r"ALTER TABLE\s+\w+\s+ADD COLUMN IF NOT EXISTS",
                             instructions))
    by_table = {}
    for table, column in additions:
        by_table.setdefault(table, set()).add(column)

    faults = []
    for index in re.finditer(
            r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+(\w+)"
            r"\s+ON\s+(\w+)\s*\(([^)]*)\)", instructions):
        if index.start() > first_alter:
            continue
        columns = {c.strip().split()[0] for c in index.group(3).split(",")
                    if c.strip()}
        late = columns & by_table.get(index.group(2), set())
        if late:
            faults.append("%s indexes %s, which the ALTER adds further down"
                          % (index.group(1), ", ".join(sorted(late))))
    assert not faults, "indexes declared before their column: " + " ; ".join(faults)


def test_every_table_has_its_grants():
    schema = read_file(os.path.join(ROOT, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    instructions = re.sub(r"--[^\n]*", "", schema)
    block = instructions[instructions.index("DO $$"):]
    block = re.sub(r"'\s*\n\s*'", " ", block)
    granted = set()
    for target in re.findall(r"\bON\s+(.+?)\s+TO ctester_app", block):
        target = re.sub(r"\([^)]*\)", "", target)
        granted |= {name.strip() for name in target.split(",") if name.strip()}
    missing = tables - granted
    assert not missing, "tables missing from every GRANT: " + ", ".join(sorted(missing))
    assert not granted - tables, sorted(granted - tables)
    assert "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctester_app')" \
        in block
    assert "CREATE ROLE" not in instructions, \
        "the role's password comes from the vault: it does not belong here"
    assert "ALL TABLES IN SCHEMA" not in instructions, instructions


def test_the_journal_consumes_only_whole_lines():
    whole = json.dumps({"job_id": "a" * 32, "exercise_id": "tp1", "status": "ok",
                         "kind": "io", "duration_s": 1.5, "queue_wait_s": 0.25,
                         "worker_id": "2", "cache_hit": False, "reprises": 0,
                         "finished_at": 1_700_000_000}).encode()
    truncated = b'{"job_id": "b", "status": "ok"'
    lines, consumed = journal.parse_journal(whole + b"\n" + truncated)
    assert consumed == len(whole) + 1, "the truncated line was consumed"
    assert [line["job_id"] for line in lines] == ["a" * 32]
    assert lines[0]["duration_s"] == 1.5 and lines[0]["reprises"] == 0
    # The rest is read again from the offset once the line is complete.
    rest = truncated + b"}\n"
    lines, consumed = journal.parse_journal(rest)
    assert consumed == len(rest)
    assert [line["job_id"] for line in lines] == ["b"]


def test_the_journal_skips_an_unreadable_line_without_blocking_the_cursor():
    good = json.dumps({"job_id": "c"}).encode()
    blob = b"pas du json\n" + b'{"job_id": 7}\n' + b"[]\n" + good + b"\n"
    lines, consumed = journal.parse_journal(blob)
    assert consumed == len(blob), "an unreadable line would block the journal"
    assert [line["job_id"] for line in lines] == ["c"]


def test_the_journal_stops_at_its_limit():
    blob = b"".join(json.dumps({"job_id": str(n)}).encode() + b"\n" for n in range(10))
    lines, consumed = journal.parse_journal(blob, limit=4)
    assert len(lines) == 4
    assert consumed < len(blob), "the limit must leave the rest for the next pass"
    rest, _ = journal.parse_journal(blob[consumed:], limit=100)
    assert [line["job_id"] for line in rest] == [str(n) for n in range(4, 10)]


def test_the_judge_journal_and_its_reader_share_the_same_fields():
    """The judge writes the line in Rust and the admin reads it in Python: a field renamed
    on one side only would go unnoticed until production."""
    rust = read_file(os.path.join(ROOT, "judge", "src", "results.rs"))
    block = rust[rust.index("let record = json!({"):]
    block = block[:block.index("});")]
    written = re.findall(r'"(\w+)":', block)
    assert written == list(journal.FIELDS), (written, list(journal.FIELDS))
    # state.py stores exactly these fields, in this order.
    assert tuple(written) == state.RUN_COLUMNS, (written, state.RUN_COLUMNS)


def test_the_journal_name_is_the_same_on_both_sides():
    rust = read_file(os.path.join(ROOT, "judge", "src", "results.rs"))
    assert 'format!("runs-{}.jsonl"' in rust, "the judge renamed the journal"
    reader = read_file(os.path.join(ROOT, "admin", "drain.py"))
    assert 'PATTERN = "runs-*.jsonl"' in reader, "the admin looks for another name"


def test_the_journal_is_standard_library_only():
    text = read_file(os.path.join(ROOT, "admin", "journal.py"))
    imported = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", text, re.M))
    assert imported <= {"json"}, sorted(imported)


def test_forget_covers_every_table():
    schema = read_file(os.path.join(ROOT, "app", "schema.sql"))
    tables = set(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)", schema))
    assert len(tables) == 21, tables
    blocks = dict(re.findall(
        r"CREATE (?:UNLOGGED )?TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);",
        schema, re.S))
    assert set(blocks) == tables, sorted(set(blocks) ^ tables)
    # judge_journal_cursor carries no account: it tracks files, not people.
    # judge_run does carry one, so forget() must clear it like any other.
    with_account = {name for name, body in blocks.items()
                   if re.search(r"^\s*account\s+TEXT", body, re.M)}
    assert with_account == tables - {"team", "team_document", "team_submission",
                                    "judge_journal_cursor"}, \
        sorted(with_account)
    state_py = read_file(os.path.join(ROOT, "app", "state.py"))
    state_py = state_py[state_py.index("def forget(user):"):]
    assert set(re.findall(r"DELETE FROM (\w+)", state_py)) == with_account
    assert state_py.count("_query(") == 1


def test_progress_degrades_without_a_database():
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
    assert progress.progression_facts("u") is None
    assert progress.cards_to_grant("u") == []


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


def test_forum_moderate_and_profiles_refuse_without_touching_the_database():
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


def test_reward_and_verification_survive_an_outage_between_write_and_reread():
    guard = progress.state
    try:
        progress.state = _PartialOutage()
        entry = {"id": "tp2-ex0", "difficulty": "foundation"}
        progress.reward("u", entry, "job1")
        progress.record_verification("u", entry, "job2", True)
    finally:
        progress.state = guard


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


def test_average_durations_ignores_a_file_that_is_not_an_object():
    guard = config.RESULTS
    try:
        config.RESULTS = tempfile.mkdtemp(prefix="ctester-results-")
        with open(os.path.join(config.RESULTS, spool.DURATIONS), "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        assert spool.average_durations() == {}
    finally:
        shutil.rmtree(config.RESULTS, ignore_errors=True)
        config.RESULTS = guard


def test_the_api_can_neither_write_nor_prepare_a_verdict():
    # The judge alone creates results/<id>: a web tier that could pre-create it would be back to
    # handing root a tree it controls.
    compose = read_file(os.path.join(ROOT, "deploy", "compose.yml"))
    web = compose.split("\n  web:\n", 1)[1].split("\n\n", 1)[0]
    assert "- ../../results:/results:ro" in web, "results must be mounted read-only into web"
    assert "CTESTER_RESULTS: /results" in web
    for path in ("routers/submission.py", "services/spool.py", "services/scratch.py"):
        source = read_file(os.path.join(ROOT, "app", path))
        for write_call in re.findall(r"open\(os\.path\.join\(config\.RESULTS[^)]*\)[^)]*\)", source):
            assert '"w' not in write_call and '"a' not in write_call, (path, write_call)


def test_eta_seconds_returns_zero_for_an_already_finished_or_unknown_job():
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
    saved = security.current_user
    try:
        security.current_user = lambda headers: "sub-" + "x" * 100
        identifier = security.client_id({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1")
        assert identifier.startswith("u:") and len(identifier) == 2 + 62
    finally:
        security.current_user = saved


def test_client_id_station_suffix_and_the_two_truncation_bounds():
    assert security.client_id({}, "10.0.0.1", station="poste-3") == "10.0.0.1/poste-3"
    identifier = security.client_id({}, "x" * 200, station="poste-3")
    assert len(identifier) == 128
    identifier = security.client_id({"CF-Connecting-IP": "y" * 200}, "10.0.0.1")
    assert identifier == "y" * 64


def test_no_redirect_refuses_to_hand_a_bearer_token_to_a_redirect_target():
    assert security._NoRedirect().redirect_request(
        None, None, 302, "Found", {}, "https://evil.exemple") is None


def test_oidc_enabled_requires_all_three_conditions_independently():
    saved = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state)
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
        config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state = saved


def test_userinfo_url_refuses_an_endpoint_outside_the_issuer():
    saved_issuer = config.OIDC_ISSUER
    saved_get_json = security._get_json
    saved_discovery = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")
        security._get_json = lambda url, headers=None: {
            "userinfo_endpoint": "https://evil.exemple/steal"}
        assert security.userinfo_url() == ""
        def forbidden(url, headers=None):
            raise AssertionError("must not be called under the negative cache")
        security._get_json = forbidden
        assert security.userinfo_url() == ""
    finally:
        config.OIDC_ISSUER = saved_issuer
        security._get_json = saved_get_json
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_userinfo_url_accepts_an_endpoint_under_the_issuer_and_caches_it():
    saved_issuer = config.OIDC_ISSUER
    saved_get_json = security._get_json
    saved_discovery = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")
        calls = []

        def answer(url, headers=None):
            calls.append(url)
            return {"userinfo_endpoint": "https://auth.exemple/userinfo"}
        security._get_json = answer
        assert security.userinfo_url() == "https://auth.exemple/userinfo"
        assert security.userinfo_url() == "https://auth.exemple/userinfo"
        assert len(calls) == 1
    finally:
        config.OIDC_ISSUER = saved_issuer
        security._get_json = saved_get_json
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_userinfo_url_survives_a_broken_discovery_document():
    saved_issuer = config.OIDC_ISSUER
    saved_get_json = security._get_json
    saved_discovery = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(until=0.0, userinfo="")

        def fail(url, headers=None):
            raise OSError("network failure")
        security._get_json = fail
        assert security.userinfo_url() == ""
    finally:
        config.OIDC_ISSUER = saved_issuer
        security._get_json = saved_get_json
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_ask_userinfo_bounds_the_sub_and_sanitizes_the_suggested_name():
    saved_issuer = config.OIDC_ISSUER
    saved_get_json = security._get_json
    saved_discovery = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")

        security._get_json = lambda url, headers=None: {
            "sub": "abc123", "preferred_username": "Léa"}
        sub, name = security._ask_userinfo("tok")
        assert sub == "abc123" and name

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
        config.OIDC_ISSUER = saved_issuer
        security._get_json = saved_get_json
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_current_user_bounds_the_bearer_token_and_caches_the_lookup():
    saved = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state, security._get_json)
    saved_tokens = dict(security._tokens)
    saved_discovery = dict(security._discovery)
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
        too_long = "Bearer " + "x" * 4097
        assert security.current_user({"Authorization": too_long}) is None

        calls = []

        def answer(url, headers=None):
            calls.append(1)
            return {"sub": "etu-1"}
        security._get_json = answer
        exact = "Bearer " + "x" * 4096
        assert security.current_user({"Authorization": exact}) == "etu-1"
        assert len(calls) == 1
        assert security.current_user({"Authorization": exact}) == "etu-1"
        assert len(calls) == 1
    finally:
        (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state,
         security._get_json) = saved
        security._tokens.clear()
        security._tokens.update(saved_tokens)
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_token_cache_flushes_fully_once_it_reaches_its_cap():
    saved = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, security.state, security._get_json)
    saved_tokens = dict(security._tokens)
    saved_discovery = dict(security._discovery)
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
         security._get_json) = saved
        security._tokens.clear()
        security._tokens.update(saved_tokens)
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_current_name_only_reads_the_cache_it_never_calls_out():
    saved_tokens = dict(security._tokens)
    try:
        security._tokens.clear()
        token = "abc"
        digest = hashlib.sha256(token.encode()).hexdigest()
        assert security.current_name({"Authorization": "Bearer " + token}) == ""
        assert security.current_name({}) == ""

        security._tokens[digest] = ("sub-1", "Lea", time.time() + 60)
        assert security.current_name({"Authorization": "Bearer " + token}) == "Lea"

        security._tokens[digest] = ("sub-1", "Lea", time.time() - 1)
        assert security.current_name({"Authorization": "Bearer " + token}) == ""
    finally:
        security._tokens.clear()
        security._tokens.update(saved_tokens)


def test_ask_userinfo_swallows_a_broken_lookup():
    saved_issuer = config.OIDC_ISSUER
    saved_get_json = security._get_json
    saved_discovery = dict(security._discovery)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        security._discovery.update(
            until=time.time() + 600, userinfo="https://auth.exemple/userinfo")
        security._get_json = lambda url, headers=None: (_ for _ in ()).throw(
            OSError("network failure"))
        assert security._ask_userinfo("tok") == (None, "")
    finally:
        config.OIDC_ISSUER = saved_issuer
        security._get_json = saved_get_json
        security._discovery.clear()
        security._discovery.update(saved_discovery)


def test_get_json_reads_a_bounded_response_and_never_follows_a_redirect():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/ok":
                body = b'{"hello": "world"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(302)
                self.send_header("Location", "http://exemple-interdit.invalid/vole")
                self.end_headers()

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        port = server.server_port
        assert security._get_json(f"http://127.0.0.1:{port}/ok") == {"hello": "world"}
        try:
            security._get_json(f"http://127.0.0.1:{port}/redirige")
            assert False, "a redirect must not resolve silently"
        except Exception:
            pass
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_forum_is_off_by_default():
    saved = (config.OIDC_ISSUER, config.OIDC_CLIENT_ID, config.FORUM_MODERATORS, security.state)
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
         security.state) = saved


def test_forum_text_is_bounded_and_stores_the_source():
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


def test_forum_libraries_are_pinned():
    manifest = json.loads(read_file(os.path.join(ROOT, "package.json")))
    pinned = manifest.get("dependencies") or {}
    loaded_by = {
        "marked": {"frontend/src/lib/domain/markdown.ts"},
        "dompurify": {"frontend/src/lib/domain/markdown.ts"},
        "yjs": {"frontend/src/lib/collab/document.ts",
                "frontend/src/lib/collab/room.svelte.ts"},
    }
    assert set(pinned) == set(loaded_by), pinned
    for package, modules in loaded_by.items():
        version = pinned[package]
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), (package, version)
        for module in modules:
            assert '"' + package + '"' in read_file(
                os.path.join(ROOT, *module.split("/"))), (package, module)
    for root, _, files in os.walk(os.path.join(ROOT, "frontend", "src")):
        for name in files:
            if not name.endswith((".ts", ".svelte")):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, ROOT).replace(os.sep, "/")
            source = read_file(path)
            for package, modules in loaded_by.items():
                if relative in modules:
                    continue
                assert 'from "' + package + '"' not in source, (relative, package)


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


def test_document_csp():
    pages = [read_file(os.path.join(ROOT, "frontend", "index.html")).encode()]
    built = os.path.join(ROOT, "frontend", "dist", "index.html")
    if os.path.exists(built):
        pages.append(read_file(built).encode())
    for page in pages:
        assert b"<script" in page and not csp._INLINE_SCRIPT_RE.findall(page), page
    page = pages[0]
    policy = csp.csp(page, "https://auth.exemple/auth/v1")
    assert "default-src 'none'" in policy
    assert "sha256-" not in policy, policy
    assert "script-src 'self';" in policy, policy
    assert b"<script" in page and not csp._INLINE_SCRIPT_RE.findall(page), page
    for inline in (b"<script>var t=1;</script>", b"<SCRIPT>var t=1;</SCRIPT>"):
        try:
            csp.csp(inline)
            raise AssertionError("an inline <script> slipped through silently")
        except ValueError:
            pass
    assert "https://auth.exemple" in policy.split("connect-src")[1]
    assert "/auth/v1" not in policy, policy
    assert config.API_ORIGIN in policy.split("connect-src")[1]
    for forbidden in ("frame-ancestors 'none'", "base-uri 'none'",
                     "form-action 'none'", "img-src 'self'"):
        assert forbidden in policy, forbidden
    assert "style-src 'self' 'unsafe-inline'" in policy
    assert "unsafe-inline" not in policy.split("style-src")[0], policy
    assert "unsafe-eval" not in policy

    meta = re.search(
        rb'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert meta, "the CSP <meta> is gone from index.html"
    from_meta = {d.split()[0]: " ".join(d.split()[1:])
               for d in meta.group(1).decode().split("; ")}
    from_server = {d.split()[0]: " ".join(d.split()[1:])
                  for d in csp.csp(page, config.OIDC_ISSUER or
                                   "https://auth.thevhome.com/auth/v1").split("; ")}
    assert "frame-ancestors" not in from_meta, from_meta
    assert from_server.pop("frame-ancestors") == "'none'"
    assert from_meta == from_server, (from_meta, from_server)


def test_forum_view_leaks_no_sub():
    saved = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        thread = [{"id": "a" * 32, "account": "sub-alice", "text": "moi",
                "hidden": False, "created_at": "2026-09-03 10:00"},
               {"id": "b" * 32, "account": "sub-bob", "text": "lui",
                "hidden": False, "created_at": "2026-09-03 10:01"},
               {"id": "c" * 32, "account": "sub-mod", "text": "eux",
                "hidden": False, "created_at": "2026-09-03 10:02"},
               {"id": "d" * 32, "account": "sub-bob", "text": "cache",
                "hidden": True, "created_at": "2026-09-03 10:03"}]
        seen = forum.forum_view(thread, "sub-alice", False)
        assert [m["author"] for m in seen] == [
            "Vous", "Participant", "Enseignant"], seen
        assert [m["mine"] for m in seen] == [True, False, False]
        assert len(seen) == 3
        text = json.dumps(seen, ensure_ascii=False)
        for forbidden in ("sub-alice", "sub-bob", "sub-mod", "account"):
            assert forbidden not in text, forbidden
        seen_by_moderator = forum.forum_view(thread, "sub-mod", True)
        assert len(seen_by_moderator) == 4 and seen_by_moderator[3]["hidden"] is True
        assert seen_by_moderator[2]["author"] == "Vous"
        assert "sub-bob" not in json.dumps(seen_by_moderator, ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = saved


def test_forum_identity_bounds_and_visibility():
    assert forum.forum_display_name(None) == (None, None)
    assert forum.forum_display_name(42) == (None, "nom invalide")
    assert forum.forum_display_name("   ") == (None, None)
    assert forum.forum_display_name("  Lea   B ") == ("Lea B", None)
    assert forum.forum_display_name("Lea" + chr(10) + "B")[0] == "Lea B"
    for reserved in ("Vous", "participant", "Enseignant", "Équipe du cours",
                    "Anonyme"):
        assert forum.forum_display_name(reserved)[0] is None, reserved
    assert forum.forum_display_name("x" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    saved_groups = config.FORUM_GROUPS
    try:
        config.FORUM_GROUPS = (4, 6)
        assert forum.forum_group("04") == (4, None)
        for bad in (0, 100, -1, "sept", True, 7):
            assert forum.forum_group(bad)[0] is None, bad
        config.FORUM_GROUPS = ()
        assert forum.forum_group("07") == (7, None)
        for bad in (0, 100, -1, "sept", True):
            assert forum.forum_group(bad)[0] is None, bad
    finally:
        config.FORUM_GROUPS = saved_groups

    saved = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        thread = [{"id": "a" * 32, "account": "sub-bob", "text": "x",
                "hidden": False, "created_at": "2026-09-03T10:00Z"}]
        cache = {"sub-bob": {"display_name": "Bob", "group_number": 7,
                             "display_name_public": False, "group_number_public": False}}
        seen = forum.forum_view(thread, "sub-alice", False, cache)[0]
        assert seen["author"] == "Participant" and seen["group"] is None
        assert seen["reportable_name"] is False
        seen_by_moderator = forum.forum_view(thread, "sub-mod", True, cache)[0]
        assert seen_by_moderator["author"] == "Participant" and seen_by_moderator["group"] == 7
        shown = {"sub-bob": dict(cache["sub-bob"], display_name_public=True)}
        seen2 = forum.forum_view(thread, "sub-alice", False, shown)[0]
        assert seen2["author"] == "Bob" and seen2["reportable_name"] is True
        mine = forum.forum_view(thread, "sub-bob", False, shown)[0]
        assert mine["author"] == "Vous" and mine["reportable_name"] is False
        assert "sub-bob" not in json.dumps(
            [seen, seen_by_moderator, seen2, mine], ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = saved


def test_the_host_check_depends_on_no_third_party():
    third_party = {"starlette", "fastapi", "pydantic", "pydantic_core", "uvicorn",
             "httpx", "httpx2", "anyio", "h11"}
    loaded = sorted(third_party & {m.split(".")[0] for m in sys.modules})
    assert not loaded, "host-side imports pulled third-party packages: " + ", ".join(loaded)


def test_both_lock_probes_open_READ_ONLY():
    source = read_file(os.path.join(ROOT, "app", "services", "scratch.py"))
    body = source[source.index("def _lock_held("):]
    body = body[:body.index("os.close(fd)")]
    assert "os.O_RDONLY" in body and "os.O_RDWR" not in body, "_lock_held must probe read-only"
    # The judge only reads the API's spool, locks included: nothing there is opened to write.
    source = read_file(os.path.join(ROOT, "judge", "src", "spool.rs"))
    assert "OFlags::RDONLY" in source
    for write_call in ("RDWR", "WRONLY", "CREATE", "APPEND", "TRUNC"):
        assert write_call not in source, "spool.rs opens the spool with " + write_call


def test_every_console_reason_has_a_message():
    judge = "".join(read_file(os.path.join(ROOT, "judge", "src", name)) for name in ("console.rs", "main.rs"))
    page = read_file(os.path.join(ROOT, "frontend", "src", "features", "scratch",
                             "session.svelte.ts"))
    block = page.split("const REASONS: Record<string, string> = {")[1].split("};")[0]
    known = set(re.findall("^\\s*(\\w+):", block, re.M)) | {"exited"}
    pattern = r'(?:break |exited\([^)]*, |(?:== 12|else) \{\s*|"reason": )"([a-z_]+)"'
    emitted = set(re.findall(pattern, judge))
    assert len(emitted) >= 9, emitted
    orphans = sorted(emitted - known)
    assert not orphans, "console reasons with no message: " + ", ".join(orphans)


def test_websockets_have_a_pinned_implementation():
    requirements = read_file(os.path.join(ROOT, "requirements.txt"))
    lines = [l.split("#")[0].strip() for l in requirements.splitlines()]
    packages = {l.split("==")[0].strip().lower() for l in lines if "==" in l}
    assert packages & {"wsproto", "websockets"}, "requirements.txt pins no WebSocket implementation"


def test_the_web_container_imports_only_what_it_mounts():
    root = {name[:-3] for name in os.listdir(os.path.join(ROOT, "worker"))
              if name.endswith(".py")}
    in_app = {name[:-3] for name in os.listdir(os.path.join(ROOT, "app"))
                if name.endswith(".py")}
    forbidden = root - in_app
    assert "content_catalog" in forbidden, forbidden
    pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                       re.M)
    faults = []
    for directory, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        if "__pycache__" in directory:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(directory, name)
            for module in pattern.findall(read_file(path)):
                if module in forbidden:
                    faults.append(os.path.relpath(path, ROOT) + " -> " + module)
    assert not faults, (
        "these root modules are not mounted in the web container: "
        + ", ".join(faults))


def _canonical_cases():
    path = os.path.join(ROOT, "frontend", "tests", "fixtures", "source.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_canonical_form_fixture_is_there():
    cases = _canonical_cases()
    assert len(cases["encodage"]) >= 6, cases
    assert len(cases["espaces_morts"]) >= 5, cases
    assert len(cases["silences"]) >= 7, cases


def test_the_canonical_form_removes_what_cannot_be_seen():
    cases = _canonical_cases()
    for group in ("encodage", "espaces_morts"):
        for c in cases[group]:
            assert source.canonicalize(c["in"]) == c["out"], (group, c["why"])


def test_the_canonical_form_leaves_everything_else_alone():
    cases = _canonical_cases()
    for c in cases["silences"]:
        assert c["out"] == c["in"], ("this case must be a fixed point", c["why"])
        assert source.canonicalize(c["in"]) == c["in"], c["why"]


def test_the_canonical_form_spares_a_line_continuation():
    assert source.canonicalize("#define F(a) \\   \n") == "#define F(a) \\   \n"
    assert source.canonicalize("#define F(a)     \n") == "#define F(a)\n"


def test_the_canonical_form_never_changes_the_line_count():
    cases = _canonical_cases()
    everything = cases["encodage"] + cases["espaces_morts"] + cases["silences"]
    for c in everything + [{"in": x, "why": x} for x in
                     ("", "x", "x\n", "x\n\n\n", "\n\n", "   ", "a\n   ")]:
        before = c["in"]
        after = source.canonicalize(before)
        if "\r" not in before:
            assert after.count("\n") == before.count("\n"), c["why"]
        assert len(after) <= len(before), c["why"]
        assert source.canonicalize(after) == after, c["why"]


def test_the_allowlist_returns_a_canonical_form():
    entry = {"id": "tp2-ex3", "files": [{"name": "submission.c"}]}
    files, message, code = catalogue.validate_files(
        entry, {"submission.c": "\ufeffint main(void){\r\n    return 0;   \r\n}\r\n"})
    assert message is None, message
    assert files == {"submission.c": "int main(void){\n    return 0;\n}\n"}, files
    envelope = len(json.dumps({"submission.c": ""}).encode())
    exact = "a" * (config.MAX_CODE - envelope - 4) + "\n" + "   "
    files, message, code = catalogue.validate_files(entry, {"submission.c": exact})
    assert message is None, (message, code)
    assert len(json.dumps(files).encode()) <= config.MAX_CODE


def test_the_console_canonicalizes_through_the_same_gate():
    code, message, status = scratch.validate_scratch("int x;   \r\n")
    assert (code, message, status) == ("int x;\n", None, 200)
    _, message, status = scratch.validate_scratch("x" * (config.MAX_CODE + 1))
    assert status == 413 and message, (status, message)
    code, message, _ = scratch.validate_scratch("x" * config.MAX_CODE + "   ")
    assert message is None and len(code) == config.MAX_CODE, message


def test_the_console_header_follows_the_file_name_rule():
    assert scratch.validate_header("", "") == ("", "", None, 200)
    assert scratch.validate_header("pile_2.h", "#define N 3  \r\n") \
        == ("pile_2.h", "#define N 3\n", None, 200)
    assert scratch.validate_header("a" * 32 + ".h", "")[2] is None
    for name in ("a" * 33 + ".h", ".h", "pile.c", "pile.H", "../pile.h", "a/b.h",
                "pile.h\n", "pi le.h", "é.h", None, 3):
        _, _, message, status = scratch.validate_header(name, "")
        assert status == 400 and message, name
    _, _, message, status = scratch.validate_header("", "int x;")
    assert status == 400 and message
    _, _, message, status = scratch.validate_header("pile.h", "x" * (config.MAX_CODE + 1))
    assert status == 413 and message
    _, _, message, status = scratch.validate_header("pile.h", None)
    assert status == 400 and message


def test_the_forum_canonicalizes_nothing():
    text = "regarde ici  \net puis là  \n"
    assert source.canonicalize(text) != text, "the case would prove nothing"
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

    small = rows[:policy.minimum_cohort() - 1]
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
    every_alias = policy.possible_aliases()
    assert len(every_alias) > 100 and len(set(every_alias)) == len(every_alias)
    assert leaderboard.draw_alias(set(), 0) == every_alias[0]
    assert leaderboard.draw_alias({every_alias[0]}, 0) == every_alias[1]
    assert leaderboard.draw_alias(set(every_alias), 0) is None


def test_divisions_only_go_up_never_down():
    assert policy.division(0)["id"] == "atelier"
    assert policy.division(8)["id"] == "machiniste"
    assert policy.division(1000)["id"] == "ingenierie"
    rows = [{"account": "u1", "alias": "A", "recent": 0, "lifetime": 25}]
    assert leaderboard.leaderboard_view(rows, "u1", 4)["division"]["id"] == "ingenierie"
    view = leaderboard.divisions_view(rows)
    assert [d["accounts"] for d in view] == [0, 0, 1]


def test_a_card_drops_on_a_whole_family_and_its_rarity_is_measured():
    assert policy.cards_earned({"tp2-ex0", "tp2-ex1"}) == []
    assert policy.cards_earned({"tp2-ex3"}) == ["card:E-01"]
    complete_set = {"tp2-ex0", "tp2-ex1", "tp2-ex2", "tp2-ex3", "tp2-ex4"}
    assert set(policy.cards_earned(complete_set)) == {"card:E-01", "card:M-04"}

    for card in policy.POLICY["cards"]:
        assert card["name"] and card["condition"] and card["exercises"]
    assert not set(policy.CARDS) & set(policy.ACHIEVEMENTS)

    views = {c["id"]: c for c in progress.collection_view(
        [{"id": "card:E-01"}], {"card:E-01": 6}, 10)}
    assert views["E-01"]["held"] and views["E-01"]["rarity"] == 60
    assert views["M-04"]["held"] is False
    assert views["M-04"]["condition"]
    muted = progress.collection_view([], {"card:E-01": 1}, 2)
    assert all(c["rarity"] is None for c in muted), muted


def _assignment_content(root, team=True, handin=True, items=None, deadline=None):
    _write_json(os.path.join(root, "catalog.json"),
                {"schema_version": 1, "skills": []})
    for identifier, files in (("dev-a", ["main.c"]),
                                  ("dev-b", ["lib.h", "lib.c"]),
                                  ("solo", ["submission.c"])):
        exercise = os.path.join(root, "exercises", identifier)
        _write_json(os.path.join(exercise, "exercise.json"), {
            "schema_version": 1, "id": identifier, "title": identifier.upper(),
            "release": {"state": "available"}})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        _write_json(os.path.join(exercise, "assessment", "io.json"),
                    {"cases": [{"stdin": "1\n", "expect": [1]}]})
        _write_json(os.path.join(exercise, "public", "files.json"),
                    {"files": [{"name": name, "template": ""} for name in files]})
    assignment = {"schema_version": 1, "id": "devoir", "title": "Le devoir",
              "items": items if items is not None else ["dev-a", "dev-b"],
              "release": {"state": "available"}}
    if team:
        assignment["team"] = {"min": 3, "max": 4, "count": 6}
    if deadline:
        assignment["deadline"] = deadline
    if handin:
        assignment["handin"] = {"root": "Devoir", "files": [
            {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
            {"name": "lib.c", "exercise_id": "dev-b", "file": "lib.c"}]}
    _write_json(os.path.join(root, "assignments", "devoir.json"), assignment)
    return root


def test_an_assignment_is_validated_projected_and_marks_its_exercises():
    root = tempfile.mkdtemp(prefix="ctester-assignment-")
    try:
        _assignment_content(root, deadline="2026-12-05T23:59:00-05:00")
        model = content_catalogue.discover(root)
        assert set(model["assignments"]) == {"devoir"}
        assignment = model["assignments"]["devoir"]
        assert assignment["team"] == {"min": 3, "max": 4, "count": 6}
        assert assignment["items"] == ["dev-a", "dev-b"]
        assert assignment["handin"]["root"] == "Devoir"
        public = content_catalogue.public_catalogue(model)
        marks = {e["id"]: e.get("assignment") for e in public["exercises"]}
        assert marks == {"dev-a": "devoir", "dev-b": "devoir", "solo": None}
        solo = [e for e in public["exercises"] if e["id"] == "solo"][0]
        assert "assignment" not in solo
        [projected] = public["assignments"]
        assert projected["deadline"] == "2026-12-05T23:59:00-05:00"
        assert projected["access"] == "available"
        files = publish_content.projection(model)
        assert "catalog.json" in files
    finally:
        shutil.rmtree(root)


def test_discover_rejects_each_assignment_defect():
    def assignment_path(r):
        return os.path.join(r, "assignments", "devoir.json")

    base = {"schema_version": 1, "id": "devoir", "title": "D",
            "items": ["dev-a"], "release": {"state": "available"}}

    def with_fields(**extra):
        d = dict(base)
        d.update(extra)
        return d

    cases = [
        (lambda r: _write_json(assignment_path(r), with_fields(schema_version=2)),
         "expected schema_version"),
        (lambda r: _write_json(assignment_path(r), with_fields(id="Pas Bon!")), "invalid id"),
        (lambda r: _write_json(assignment_path(r), with_fields(id="autre")), "must be named after the id"),
        (lambda r: _write_json(assignment_path(r), with_fields(title="  ")), "missing title"),
        (lambda r: _write_json(assignment_path(r), with_fields(items=[])), "non-empty list"),
        (lambda r: _write_json(assignment_path(r), with_fields(items=["inconnu"])), "unknown exercise"),
        (lambda r: _write_json(assignment_path(r), with_fields(deadline="pas une date")),
         "deadline must be an ISO date"),
        (lambda r: _write_json(assignment_path(r), with_fields(deadline="2026-12-05T23:59:00")),
         "deadline must be an ISO date"),
        (lambda r: _write_json(assignment_path(r), with_fields(team={"min": 4, "max": 3, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(assignment_path(r), with_fields(team={"min": 1, "max": 99, "count": 6})),
         "team sizes must satisfy"),
        (lambda r: _write_json(assignment_path(r), with_fields(team={"min": "trois", "max": 4, "count": 6})),
         "team.min must be an integer"),
        (lambda r: _write_json(assignment_path(r), with_fields(team={"min": 3, "max": 4})),
         "team.count must be an integer"),
        (lambda r: _write_json(assignment_path(r), with_fields(team={"min": 3, "max": 4, "count": 0})),
         "team.count must satisfy"),
        (lambda r: _write_json(assignment_path(r), with_fields(handin={"root": "../etc", "files": []})),
         "handin.root must be a plain directory name"),
        (lambda r: _write_json(assignment_path(r), with_fields(
            handin={"root": "D", "files": [
                {"name": "main.c", "exercise_id": "solo", "file": "submission.c"}]})),
         "names an exercise outside this assignment"),
        (lambda r: _write_json(assignment_path(r), with_fields(
            handin={"root": "D", "files": [
                {"name": "main.c", "exercise_id": "dev-a", "file": "secret.c"}]})),
         "does not declare"),
    ]
    for mutate, expected in cases:
        root = tempfile.mkdtemp(prefix="ctester-assignment-")
        try:
            _assignment_content(root)
            mutate(root)
            message = _discover_error(root)
            assert expected in message, (expected, message)
        finally:
            shutil.rmtree(root)


def test_an_exercise_belongs_to_a_single_assignment():
    root = tempfile.mkdtemp(prefix="ctester-assignment-")
    try:
        _assignment_content(root)
        _write_json(os.path.join(root, "assignments", "autre.json"),
                    {"schema_version": 1, "id": "autre", "title": "A",
                     "items": ["dev-a"], "release": {"state": "available"}})
        assert "already belongs to assignment" in _discover_error(root)
    finally:
        shutil.rmtree(root)


def test_an_assignment_without_a_team_block_stays_individual():
    root = tempfile.mkdtemp(prefix="ctester-assignment-")
    try:
        _assignment_content(root, team=False)
        model = content_catalogue.discover(root)
        assert model["assignments"]["devoir"]["team"] is None
        public = content_catalogue.public_catalogue(model)
        [projected] = public["assignments"]
        assert "team" not in projected
        assert teams.is_team_assignment(projected) is False
    finally:
        shutil.rmtree(root)


class _TeamStore:
    def __init__(self, members):
        self.members = members

    def team_of(self, user, assignment_id):
        team_id = self.members.get((assignment_id, user))
        if team_id is None:
            return None
        return {"team_id": team_id, "assignment_id": assignment_id,
                "group_number": 4, "number": 1, "label": "Équipe 1"}


def _publish_assignment(root, dest):
    publish_content.publish(content_catalogue.discover(root), dest)


def test_the_assignment_gate_distinguishes_three_refusals():
    root = tempfile.mkdtemp(prefix="ctester-assignment-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    previous = config.PUBLISHED
    try:
        _assignment_content(root)
        _publish_assignment(root, dest)
        config.PUBLISHED = dest
        base = _TeamStore({("devoir", "sub-alice"): "e1"})
        _, _, refusal = teams.workspace(base, "sub-alice", "inconnu")
        assert refusal[0] == 404
        _, team, refusal = teams.workspace(base, "sub-alice", "devoir")
        assert refusal is None and team["team_id"] == "e1"
        _, team, refusal = teams.workspace(base, "sub-bob", "devoir")
        assert team is None and refusal[0] == 403
        assert "figées" in refusal[1] and "enseignant" in refusal[1], refusal
        assignment, _, _ = teams.workspace(base, "sub-alice", "devoir")
        assert teams.exercise_in(assignment, "dev-a") is True
        assert teams.exercise_in(assignment, "solo") is False
        assert teams.exercise_in(assignment, "../catalog") is False
    finally:
        config.PUBLISHED = previous
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_an_assignment_without_a_team_is_refused_with_a_reason():
    root = tempfile.mkdtemp(prefix="ctester-assignment-")
    dest = tempfile.mkdtemp(prefix="ctester-published-")
    previous = config.PUBLISHED
    try:
        _assignment_content(root, team=False)
        _publish_assignment(root, dest)
        config.PUBLISHED = dest
        _, team, refusal = teams.workspace(_TeamStore({}), "sub-alice", "devoir")
        assert team is None and refusal[0] == 400
        assert "équipe" in refusal[1]
    finally:
        config.PUBLISHED = previous
        shutil.rmtree(root)
        shutil.rmtree(dest)


def test_the_team_view_leaks_no_sub():
    roster = ["sub-alice", "sub-bob", "sub-cleo"]
    profiles = {"sub-bob": {"display_name": "Bob B", "display_name_public": True},
               "sub-cleo": {"display_name": "Cleo", "display_name_public": False}}
    view = teams.members_view(roster, "sub-alice", profiles)
    payload = json.dumps(view, ensure_ascii=False)
    assert "sub-" not in payload, payload
    assert [m["id"] for m in view] == ["m1", "m2", "m3"]
    assert [m["you"] for m in view] == [True, False, False]
    assert view[1]["name"] == "Bob B"
    assert view[2]["name"] == "Coéquipier 3"
    assert len({m["color"] for m in view}) == 3
    assert teams.member_handle(roster, "sub-cleo") == "m3"
    assert teams.member_handle(roster, "sub-etranger") == ""


def test_the_history_names_a_position_and_quantifies_no_contribution():
    roster = ["sub-alice", "sub-bob"]
    lines = [{"revision_id": "r2", "account": "sub-bob",
               "created_at": "2026-09-07T14:32Z", "bytes": 812},
              {"revision_id": "r1", "account": "sub-alice",
               "created_at": "2026-09-07T14:02Z", "bytes": 640},
              {"revision_id": "r0", "account": "sub-parti",
               "created_at": "2026-09-06T10:00Z", "bytes": 12}]
    view = teams.revisions_view(lines, roster)
    payload = json.dumps(view)
    assert "sub-" not in payload, payload
    assert "%" not in payload and "percent" not in payload
    assert [r["author"] for r in view] == ["m2", "m1", ""]
    assert view[0]["id"] == "r2" and view[0]["bytes"] == 812


class _DocumentStore:
    def __init__(self, documents, outage=False):
        self.documents = documents
        self.outage = outage

    def read_team_document(self, team_id, exercise_id):
        if self.outage:
            return None
        return self.documents.get((team_id, exercise_id), {})


def _entry(exercise_id):
    files = {"dev-a": ["main.c"], "dev-b": ["lib.h", "lib.c"]}
    return {"id": exercise_id,
            "files": [{"name": n} for n in files[exercise_id]]}


PUBLIC_ASSIGNMENT = {
    "id": "devoir", "title": "Le devoir", "items": ["dev-a", "dev-b"],
    "team": {"min": 3, "max": 4}, "release": {"state": "available"},
    "handin": {"root": "Devoir", "files": [
        {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
        {"name": "matrac_lib.c", "exercise_id": "dev-b", "file": "lib.c"}]}}


def test_the_archive_follows_the_assignment_and_reports_what_is_missing():
    base = _DocumentStore({("e1", "dev-a"): {"main.c": "int main(void){}\n"},
                           ("e1", "dev-b"): {"lib.h": "#pragma once\n",
                                             "lib.c": "int f(void){return 1;}\n"}})
    files, missing = teams.handin_files(base, PUBLIC_ASSIGNMENT, "e1", _entry)
    assert missing == []
    assert sorted(files) == ["Devoir/main.c", "Devoir/matrac_lib.c"]
    assert files["Devoir/matrac_lib.c"] == "int f(void){return 1;}\n"
    assert not any(name.endswith("lib.h") for name in files)

    empty = _DocumentStore({("e1", "dev-a"): {"main.c": "   \n"}})
    files, missing = teams.handin_files(empty, PUBLIC_ASSIGNMENT, "e1", _entry)
    assert [m["name"] for m in missing] == ["main.c", "matrac_lib.c"]
    assert files == {}

    assert teams.handin_files(_DocumentStore({}, outage=True),
                              PUBLIC_ASSIGNMENT, "e1", _entry) == (None, [])


def test_the_archive_is_deterministic_and_readable():
    import io as _io
    import zipfile as _zipfile

    files = {"Devoir/main.c": "int main(void){return 0;}\n",
                "Devoir/matrac_lib.c": "double f(void){return 1.0;}\n"}
    first = teams.build_zip(files)
    second = teams.build_zip(dict(reversed(list(files.items()))))
    assert first == second
    with _zipfile.ZipFile(_io.BytesIO(first)) as archive:
        assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
        assert archive.read("Devoir/main.c").decode() == files["Devoir/main.c"]
        for info in archive.infolist():
            assert info.date_time == teams.ARCHIVE_EPOCH, info.date_time
            assert info.create_system == 0
    exotic = {"Devoir/main.c": "/* accentué : é\r\n*/\nint main(){}\n"}
    with _zipfile.ZipFile(_io.BytesIO(teams.build_zip(exotic))) as archive:
        assert archive.read("Devoir/main.c").decode("utf-8") \
            == exotic["Devoir/main.c"]


def test_the_deadline_is_data_not_a_task():
    past = dict(PUBLIC_ASSIGNMENT, deadline="2020-01-01T00:00:00-05:00")
    future = dict(PUBLIC_ASSIGNMENT, deadline="2099-01-01T00:00:00-05:00")
    assert teams.deadline_passed(past) is True
    assert teams.deadline_passed(future) is False
    assert teams.deadline_passed(PUBLIC_ASSIGNMENT) is False
    assert teams.deadline_passed(dict(PUBLIC_ASSIGNMENT, deadline="demain")) is False


class _FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def _sync(coro):
    import asyncio
    return asyncio.run(coro)


def test_two_teams_on_the_same_exercise_are_two_rooms():
    collab.reset()
    try:
        a1 = collab.Connection(_FakeSocket(),
                               collab.room_key("e1", "dev-a"), "m1", "sub-a")
        a2 = collab.Connection(_FakeSocket(),
                               collab.room_key("e1", "dev-a"), "m2", "sub-b")
        b1 = collab.Connection(_FakeSocket(),
                               collab.room_key("e2", "dev-a"), "m1", "sub-c")
        assert a1.key != b1.key
        epoch, pairs = collab.join(a1)
        assert pairs == 0 and epoch
        assert collab.join(a2)[1] == 1
        epoch_b, pairs_b = collab.join(b1)
        assert pairs_b == 0 and epoch_b != epoch

        _sync(collab.broadcast(a1, {"t": "update", "d": "xx"}))
        assert a2.socket.sent == [{"t": "update", "d": "xx"}]
        assert a1.socket.sent == []
        assert b1.socket.sent == []

        _sync(collab.announce(a1.key))
        assert a2.socket.sent[-1] == {"t": "presence", "online": ["m1", "m2"]}
        assert b1.socket.sent == []
    finally:
        collab.reset()


def test_an_emptied_room_changes_epoch_and_the_client_restarts_from_the_server():
    collab.reset()
    try:
        room = collab.room_key("e1", "dev-a")
        one = collab.Connection(_FakeSocket(), room, "m1", "sub-a")
        epoch, _ = collab.join(one)
        collab.leave(one)
        assert collab.members(room) == []
        two = collab.Connection(_FakeSocket(), room, "m2", "sub-b")
        fresh, pairs = collab.join(two)
        assert pairs == 0, "the emptied room must be rebuilt"
        assert fresh != epoch, "and the client must be able to see it"
    finally:
        collab.reset()


def test_a_room_deduplicates_tabs_and_is_bounded():
    collab.reset()
    previous = config.TEAM_LIVE_MAX
    try:
        room = collab.room_key("e1", "dev-a")
        for _ in range(2):
            collab.join(collab.Connection(_FakeSocket(), room, "m1", "sub-a"))
        collab.join(collab.Connection(_FakeSocket(), room, "m2", "sub-b"))
        assert collab.members(room) == ["m1", "m2"]
        config.TEAM_LIVE_MAX = 3
        assert collab.full(room) is True
        config.TEAM_LIVE_MAX = 4
        assert collab.full(room) is False
    finally:
        config.TEAM_LIVE_MAX = previous
        collab.reset()


def test_an_assignment_exercise_counts_in_no_practice():
    entries = [{"id": "solo", "skills": ["variables"]},
               {"id": "dev-a", "skills": ["variables"], "assignment": "devoir"},
               {"id": "verif", "skills": ["variables"], "verification": True}]
    assert [e["id"] for e in progress.practice_exercises(entries)] == ["solo"]
    source = read_file(os.path.join(ROOT, "app", "routers", "submission.py"))
    assert 'entry.get("assignment")' in source
    page = read_file(os.path.join(ROOT, "frontend", "src", "lib", "domain",
                             "catalog.ts"))
    assert "!t.assignment" in page


def test_the_roster_refuses_before_writing_anything():
    import importlib.util

    path = os.path.join(ROOT, "scripts", "import_teams.py")
    spec = importlib.util.spec_from_file_location("import_teams", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.team_handle(4, 7) == teams.team_handle(4, 7) == "g04-e07"
    assert module.team_handle(6, 1) == teams.team_handle(6, 1) == "g06-e01"
    assert module.TEAM_NAME % 7 == teams.TEAM_NAME % 7 == "Équipe 7"

    header = "group_number,number,account\n"
    directory = tempfile.mkdtemp(prefix="ctester-roster-")
    try:
        def write(text):
            csv_path = os.path.join(directory, "r.csv")
            with open(csv_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return csv_path

        good = write(header + "4,1,sub-alice\n4,1,sub-bob\n6,3,sub-cleo\n")
        lines = module.read_roster(good)
        assert lines == [(4, 1, "sub-alice"), (4, 1, "sub-bob"),
                          (6, 3, "sub-cleo")], lines
        assert module.sizes(lines) == {"g04-e01": 2, "g06-e03": 1}

        for text, expected in (
                (header + ",1,sub-a\n", "group_number must be 1..99"),
                (header + "4,,sub-a\n", "number must be 1..99"),
                (header + "0,1,sub-a\n", "group_number must be 1..99"),
                (header + "4,100,sub-a\n", "number must be 1..99"),
                (header + "4,1,\n", "account is required"),
                (header, "empty"),
                (header + "4,1,sub-a\n6,2,sub-a\n", "two teams")):
            try:
                module.read_roster(write(text))
            except SystemExit as exc:
                assert expected in str(exc), (expected, str(exc))
            else:
                raise AssertionError("invalid roster accepted: " + repr(text))

        script = module.to_sql(lines, "devoir")
        assert script.startswith("BEGIN;") and script.rstrip().endswith("COMMIT;")
        assert "'g04-e01'" in script and "'g06-e03'" in script, script
        assert len(module.statements(lines, "devoir")) == script.count(";") - 2
        hostile = module.read_roster(write(header + "4,1,sub-o'brien\n"))
        assert "'sub-o''brien'" in module.to_sql(hostile, "devoir")
        try:
            module.to_sql(module.read_roster(write(header + "4,0,sub-a\n")),
                          "devoir")
        except SystemExit as exc:
            assert "number must be" in str(exc)
        else:
            raise AssertionError("a refused roster still produced SQL")
    finally:
        shutil.rmtree(directory)


def test_console_the_job_carries_no_identity():
    if fcntl is None:
        print("  (skipped: no flock outside POSIX)")
        return

    directory = tempfile.mkdtemp()
    saved = config.SPOOL
    try:
        config.SPOOL = directory
        session = scratch.open_session("int main(void){return 0;}")
        job = json.loads(read_file(os.path.join(session.path, "job.json")))
        assert job == {"kind": "console"}, job
        for forbidden in ("owner", "sub", "account", "exercise_id", "utilisateur"):
            assert forbidden not in job
        assert read_file(os.path.join(session.path, "src", "main.c")) \
            == "int main(void){return 0;}"
        assert os.listdir(os.path.join(session.path, "src")) == ["main.c"]
        assert session.worker_alive() is False
        assert scratch._lock_held(os.path.join(session.path, "alive")) is True
        session.close()
        assert scratch._lock_held(os.path.join(session.path, "alive")) is False

        with_header = scratch.open_session('#include "pile.h"\n', "pile.h", "#define N 3\n")
        job = json.loads(read_file(os.path.join(with_header.path, "job.json")))
        assert job == {"kind": "console", "header": "pile.h"}, job
        assert sorted(os.listdir(os.path.join(with_header.path, "src"))) == ["main.c", "pile.h"]
        assert read_file(os.path.join(with_header.path, "src", "pile.h")) == "#define N 3\n"
        with_header.close()
    finally:
        config.SPOOL = saved
        shutil.rmtree(directory)


def test_console_has_no_include_list():
    source = read_file(os.path.join(ROOT, "judge", "src", "console.rs"))
    assert "read_allowed" not in source
    assert "forbidden_includes" not in source


def test_the_bridge_bot_runs_without_third_parties_and_skips_its_own_messages():
    path = os.path.join(ROOT, "bot", "bridge.py")
    assert os.path.exists(path), path
    output = subprocess.run([sys.executable, path, "--autotest"],
                            capture_output=True, text=True)
    assert output.returncode == 0, output.stdout + output.stderr
    assert "autotest ok" in output.stdout, output.stdout


def test_the_discord_bridge_only_lets_out_the_public_chat():
    saved = (config.DISCORD_WEBHOOK, config.DISCORD_TIMEOUT)
    sent = []
    real_post = discord._post
    try:
        config.DISCORD_WEBHOOK = "https://discord.invalide/webhook"
        discord._post = sent.append

        config.DISCORD_WEBHOOK = ""
        assert discord.enabled() is False
        assert discord.announce("@chat:general", "sub-a", "X", "salut") is False
        config.DISCORD_WEBHOOK = "https://discord.invalide/webhook"

        assert discord.announce("@chat:general", "sub-a", "Arbre", "salut") is True
        assert discord.announce("@chat:tp2-ex3", "sub-a", "Arbre", "salut") is True

        for thread in ("tp2-ex3", "tp1", "", None):
            assert discord.announce(thread, "sub-a", "Arbre", "salut") is False, thread

        assert discord.announce("@chat:general", "@discord:4711",
                                "Vianney", "salut") is False
        assert discord.announce("@chat:general", "sub-a", "Arbre", "   ") is False

        body = discord.payload("Arbre", "@everyone @here salut", "# ex.3")
        assert body["allowed_mentions"] == {"parse": []}, body
        assert body["content"] == "@everyone @here salut"
        assert body["username"] == "Arbre — # ex.3"
        long = discord.payload("n" * 400, "t" * 5000, "")
        assert len(long["username"]) <= 80 and len(long["content"]) <= 1900

        body = discord.payload("Arbre hélicoïdal", "ma question", "# ex.3")
        assert "sub-" not in json.dumps(body), body
    finally:
        discord._post = real_post
        config.DISCORD_WEBHOOK, config.DISCORD_TIMEOUT = saved


def test_the_chat_forces_public_and_the_prefix_is_the_whole_distinction():
    channel = forum.CHAT_GENERAL
    assert forum.is_chat(channel) and forum.is_chat("@chat:tp2-ex3")
    assert not forum.is_chat("tp2-ex3")
    assert not forum.is_chat("") and not forum.is_chat(None)

    assert forum.forum_visibility(None, False, channel) == ("thread", None)
    assert forum.forum_visibility("", True, channel) == ("thread", None)
    assert forum.forum_visibility("thread", True, channel) == ("thread", None)
    for forbidden in ("private", "group"):
        value, message = forum.forum_visibility(forbidden, True, channel)
        assert value is None and "publics" in message, forbidden

    assert forum.forum_visibility(None, True) == ("private", None)
    assert forum.forum_visibility(None, False) == ("thread", None)
    assert forum.forum_visibility("thread", True)[0] is None

    assert "@" in forum.CHAT_PREFIX


def test_a_hidden_author_stays_followable():
    saved = config.FORUM_MODERATORS
    try:
        config.FORUM_MODERATORS = frozenset({"sub-mod"})
        thread = [{"id": "a" * 32, "account": "sub-bob", "text": "x",
                "hidden": False, "created_at": "2026-09-03T10:00Z"},
               {"id": "b" * 32, "account": "sub-carl", "text": "y",
                "hidden": False, "created_at": "2026-09-03T10:01Z"},
               {"id": "c" * 32, "account": "sub-mod", "text": "z",
                "hidden": False, "created_at": "2026-09-03T10:02Z"}]
        profiles = {"sub-bob": {"alias": "Rotor cuivré"},
                   "sub-carl": {"alias": "Piston lisse"},
                   "sub-mod": {"alias": "Came trempée"}}
        views = forum.forum_view(thread, "sub-alice", False, profiles)
        names = [v["author"] for v in views]
        assert names[0] == "Rotor cuivré" and names[1] == "Piston lisse"
        assert names[0] != names[1]
        assert names[2] == "Enseignant"
        assert all(v["reportable_name"] is False for v in views)

        chosen = dict(profiles, **{"sub-bob": {"alias": "Rotor cuivré",
                                              "display_name": "Bob",
                                              "display_name_public": True}})
        seen = forum.forum_view(thread, "sub-alice", False, chosen)[0]
        assert seen["author"] == "Bob" and seen["reportable_name"] is True

        mine = forum.forum_view(thread, "sub-bob", False, profiles)[0]
        assert mine["author"] == "Vous (Rotor cuivré)"

        assert forum.forum_view(thread, "sub-alice", False, {})[0]["author"] == "Participant"

        assert "sub-bob" not in json.dumps(views + [seen, mine], ensure_ascii=False)
    finally:
        config.FORUM_MODERATORS = saved


def test_a_reply_travels_with_its_link_and_both_counters():
    thread = [{"id": "a" * 32, "account": "sub-bob", "text": "q", "hidden": False,
            "created_at": "2026-09-03T10:00Z", "reply_to": None,
            "upvotes": 3, "downvotes": 0, "my_vote": 1},
           {"id": "b" * 32, "account": "sub-carl", "text": "r", "hidden": False,
            "created_at": "2026-09-03T10:01Z", "reply_to": "a" * 32,
            "upvotes": 1, "downvotes": 2, "my_vote": -1}]
    views = forum.forum_view(thread, "sub-alice", False, {})
    assert views[0]["reply_to"] is None and views[1]["reply_to"] == "a" * 32
    assert views[0]["upvotes"] == 3 and views[0]["my_vote"] == 1
    assert views[1]["downvotes"] == 2 and views[1]["my_vote"] == -1


def test_the_python_gate_reads_dates_like_the_rust_gate():
    # judge/src/gate.rs replays the same file: the two gates must not diverge.
    vectors = json.loads(read_file(os.path.join(ROOT, "tests", "vectors", "release_access.json")))
    for v in vectors:
        now = dt.datetime.fromisoformat(v["now"].replace("Z", "+00:00"))
        assert content_catalogue.access(v["release"], now) == v["access"], v


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d checks passed." % len(tests))
