#!/usr/bin/env python3
"""Construire une copie v2 du dépôt historique unittests.

Ne modifie jamais la source : le résultat est écrit dans une nouvelle racine
``content/`` (ou --output). Les IDs existants sont conservés afin que URLs,
brouillons, états et événements restent valides au moment de la bascule.
"""

import argparse
import json
import os
import re
import shutil
import sys


MODE_FILES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))
ID_RE = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
CHUNKS_RE = re.compile(r"(\d+)")


def natural_key(value):
    """Conserve l'ordre humain tp2/ex2 avant tp10/ex10 durant la migration."""
    return [(1, int(chunk)) if chunk.isdigit() else (0, chunk.lower())
            for chunk in CHUNKS_RE.split(value) if chunk]


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def detect_mode(path):
    found = [(mode, filename) for mode, filename in MODE_FILES
             if os.path.isfile(os.path.join(path, filename))]
    if len(found) != 1:
        raise ValueError("%s: %d fichiers de mode" % (path, len(found)))
    return found[0]


def legacy_entries(root):
    """La même convention que le runner historique, mais sans l'importer."""
    for parent in sorted(os.listdir(root), key=natural_key):
        parent_path = os.path.join(root, parent)
        if not os.path.isdir(parent_path) or not (ID_RE.match(parent) or parent == "bonus"):
            continue
        try:
            mode, filename = detect_mode(parent_path)
        except ValueError:
            mode = filename = None
        if mode:
            yield parent, parent_path, mode, filename, parent
            continue
        for child in sorted(os.listdir(parent_path), key=natural_key):
            path = os.path.join(parent_path, child)
            exercise_id = parent + "-" + child
            if not os.path.isdir(path) or not ID_RE.match(exercise_id):
                continue
            try:
                mode, filename = detect_mode(path)
            except ValueError:
                continue
            yield exercise_id, path, mode, filename, parent


def release(conf):
    date = conf.get("available_from")
    if isinstance(date, str) and re.match(r"\A\d{4}-\d\d-\d\d\Z", date):
        return {"state": "scheduled", "available_from": date + "T00:00:00-04:00"}
    return {"state": "available"}


def migrate(source, output):
    if os.path.exists(output):
        raise ValueError("la sortie existe déjà : " + output)
    entries = list(legacy_entries(source))
    if not entries:
        raise ValueError("aucun exercice historique trouvé dans " + source)
    skills, groups = set(), {}
    for exercise_id, path, mode, filename, parent in entries:
        conf = read_json(os.path.join(path, filename))
        learning = conf.get("learning") if isinstance(conf.get("learning"), dict) else {}
        entry_skills = learning.get("skills") if isinstance(learning.get("skills"), list) else []
        skills.update(skill for skill in entry_skills if isinstance(skill, str))
        metadata = {
            "schema_version": 1,
            "id": exercise_id,
            "title": str(conf.get("label") or exercise_id),
            "release": release(conf),
            "skills": entry_skills,
        }
        if learning.get("difficulty"):
            metadata["difficulty"] = learning["difficulty"]
        if learning.get("context"):
            metadata["contexts"] = [learning["context"]]
        target = os.path.join(output, "exercises", exercise_id)
        write_json(os.path.join(target, "exercise.json"), metadata)
        statement = conf.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            statement = ("Consultez l'énoncé du cours pour le contrat complet de cet exercice.\n")
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write(statement.rstrip() + "\n")
        private = dict(conf)
        for key in ("label", "statement", "learning", "available_from", "related_tp", "note", "files"):
            private.pop(key, None)
        write_json(os.path.join(target, "assessment", filename), private)
        if mode != "quiz":
            files = conf.get("files") or [{"name": "submission.c", "template": ""}]
            write_json(os.path.join(target, "public", "files.json"), {"files": files})
        for name in os.listdir(path):
            if name.startswith("test_") and name.endswith(".c") or name == "allowed_includes.txt":
                shutil.copy2(os.path.join(path, name), os.path.join(target, "assessment", name))
        groups.setdefault(parent, []).append(exercise_id)
    write_json(os.path.join(output, "catalog.json"), {"schema_version": 1, "skills": sorted(skills)})
    for parent, items in groups.items():
        if parent.startswith("tp") and parent[2:].isdigit():
            title = "TP " + parent[2:]
        elif parent == "bonus":
            title = "Bonus"
        elif parent == "devoir":
            title = "Devoir"
        else:
            title = parent
        write_json(os.path.join(output, "collections", parent + ".json"),
                   {"schema_version": 1, "id": parent, "title": title,
                    "items": items, "release": {"state": "available"}})
    shared = os.path.join(source, "unity")
    if os.path.isdir(shared):
        shutil.copytree(shared, os.path.join(output, "shared", "unity"))
    return len(entries), len(groups)


def main(argv=None):
    parser = argparse.ArgumentParser(description="migre unittests historique vers content v2")
    parser.add_argument("source", help="racine unittests historique")
    parser.add_argument("--output", help="nouvelle racine (défaut : SOURCE/content)")
    args = parser.parse_args(argv)
    output = args.output or os.path.join(os.path.abspath(args.source), "content")
    try:
        exercises, collections = migrate(os.path.abspath(args.source), os.path.abspath(output))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("migration refusée : " + str(exc), file=sys.stderr)
        return 1
    print("migration v2 créée : %d exercice(s), %d collection(s)" % (exercises, collections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
