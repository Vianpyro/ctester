"""Validation et découverte du futur dépôt de contenu ctester.

Ce module ne remplace pas encore ``runner.py`` : la production continue à lire
l'arborescence historique ``tpN/exN`` tant que sa migration n'est pas terminée.
Il définit toutefois le contrat v2 dans un endroit testable et sans dépendance
externe. Le worker, la CI et le futur publisher devront tous appeler cette même
porte, plutôt que de réinterpréter les métadonnées chacun de leur côté.

Le contenu est privé par défaut. ``public_catalogue`` reconstruit les seules
valeurs qui peuvent quitter cette frontière; il ne retire jamais quelques clés
d'une copie de la configuration de correction.
"""

import datetime as dt
import json
import os
import re


SCHEMA_VERSION = 1
EXERCISE_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,62}\Z")
COLLECTION_RE = EXERCISE_RE
SKILL_RE = re.compile(r"\A[a-z][a-z0-9-]{0,47}\Z")
FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")
MODES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))
DIFFICULTIES = frozenset(("intro", "foundation", "intermediate", "advanced"))
RELEASE_STATES = frozenset(("available", "scheduled", "archived"))


class ContentValidationError(ValueError):
    """Une ou plusieurs erreurs auteurs, jamais une erreur de chemin HTTP."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


def _json(path, errors):
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError) as exc:
        errors.append("%s: JSON illisible (%s)" % (path, exc))
        return None
    if not isinstance(value, dict):
        errors.append("%s: objet JSON attendu" % path)
        return None
    return value


def _children(path):
    try:
        return sorted(name for name in os.listdir(path)
                      if os.path.isdir(os.path.join(path, name)))
    except OSError:
        return []


def _iso_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def detect_mode(assessment_dir):
    """Le seul mode présent, ou ``None`` / une liste de conflits.

    Aucun champ ``mode`` ne figure dans exercise.json : le fichier de correction
    est la source de vérité. Le validateur distingue absence et pluralité.
    """
    found = [mode for mode, filename in MODES
             if os.path.isfile(os.path.join(assessment_dir, filename))]
    return found[0] if len(found) == 1 else (found or None)


def _release(value, where, errors):
    if not isinstance(value, dict):
        errors.append("%s: release doit être un objet" % where)
        return {"state": "archived"}
    state = value.get("state")
    if state not in RELEASE_STATES:
        errors.append("%s: release.state invalide" % where)
        state = "archived"
    available_from = value.get("available_from")
    if state == "scheduled":
        if _iso_datetime(available_from) is None:
            errors.append("%s: scheduled exige available_from ISO avec fuseau" % where)
    elif available_from is not None:
        errors.append("%s: available_from n'est permis que pour scheduled" % where)
    out = {"state": state}
    if state == "scheduled" and isinstance(available_from, str):
        out["available_from"] = available_from
    return out


def _files(value, where, errors):
    if value is None:
        return [{"name": "submission.c", "template": ""}]
    if not isinstance(value, list) or not value:
        errors.append("%s: files doit être une liste non vide" % where)
        return []
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            errors.append("%s: entrée files invalide" % where)
            continue
        name, template = item.get("name"), item.get("template", "")
        if not isinstance(name, str) or not FILE_RE.match(name) or name in seen:
            errors.append("%s: nom de fichier invalide ou dupliqué" % where)
            continue
        if not isinstance(template, str):
            errors.append("%s: template doit être du texte" % where)
            continue
        seen.add(name)
        result.append({"name": name, "template": template})
    return result


def _public_files(path, where, errors, mode):
    """Les gabarits sont publics, donc séparés de la configuration assessment."""
    if mode == "quiz":
        return []
    data = _json(os.path.join(path, "public", "files.json"), errors)
    if data is None:
        return []
    return _files(data.get("files"), where + "/public/files.json", errors)


def _exercise(root, dirname, known_skills, errors):
    path = os.path.join(root, "exercises", dirname)
    data = _json(os.path.join(path, "exercise.json"), errors)
    if data is None:
        return None
    where = "exercises/%s" % dirname
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("%s: schema_version %s attendu" % (where, SCHEMA_VERSION))
    exercise_id, title = data.get("id"), data.get("title")
    if not isinstance(exercise_id, str) or not EXERCISE_RE.match(exercise_id):
        errors.append("%s: id invalide" % where)
        return None
    if dirname != exercise_id:
        errors.append("%s: le dossier doit porter l'id" % where)
    if not isinstance(title, str) or not title.strip():
        errors.append("%s: title manquant" % where)
    if not isinstance(data.get("summary", ""), str):
        errors.append("%s: summary doit être du texte" % where)
    try:
        with open(os.path.join(path, "statement.md"), encoding="utf-8") as fh:
            statement = fh.read()
    except OSError:
        errors.append("%s: statement.md manquant" % where)
        statement = ""
    assessment = os.path.join(path, "assessment")
    mode = detect_mode(assessment)
    if isinstance(mode, list):
        errors.append("%s: plusieurs modes présents (%s)" % (where, ", ".join(mode)))
        mode = None
    elif mode is None:
        errors.append("%s: aucun mode présent" % where)
    config = _json(os.path.join(assessment, dict(MODES).get(mode, "missing.json")), errors) if mode else {}
    config = config or {}
    assessment_names = os.listdir(assessment) if os.path.isdir(assessment) else []
    if mode == "unity" and not any(name.startswith("test_") and name.endswith(".c")
                                    for name in assessment_names):
        errors.append("%s: unity exige au moins un test_*.c" % where)
    if mode == "io" and not isinstance(config.get("cases"), list):
        errors.append("%s: io exige cases" % where)
    if mode == "quiz" and not isinstance(config.get("questions"), list):
        errors.append("%s: quiz exige questions" % where)
    skills = data.get("skills", [])
    if (not isinstance(skills, list)
            or any(not isinstance(skill, str) for skill in skills)
            or len(skills) != len(set(skills))):
        errors.append("%s: skills doit être une liste de textes sans doublon" % where)
        skills = []
    for skill in skills:
        if not isinstance(skill, str) or not SKILL_RE.match(skill) or skill not in known_skills:
            errors.append("%s: skill inconnue ou invalide (%r)" % (where, skill))
    difficulty = data.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        errors.append("%s: difficulty invalide" % where)
    contexts = data.get("contexts", [])
    if not isinstance(contexts, list) or any(not isinstance(context, str) or not context
                                              for context in contexts):
        errors.append("%s: contexts doit être une liste de textes" % where)
        contexts = []
    prerequisites = data.get("prerequisites", [])
    if (not isinstance(prerequisites, list)
            or any(not isinstance(prerequisite, str) for prerequisite in prerequisites)
            or len(prerequisites) != len(set(prerequisites))):
        errors.append("%s: prerequisites doit être une liste de textes sans doublon" % where)
        prerequisites = []
    elif any(not isinstance(prerequisite, str) or not EXERCISE_RE.match(prerequisite)
             for prerequisite in prerequisites):
        errors.append("%s: prerequisite invalide" % where)
    return {
        "id": exercise_id, "path": path, "title": title, "summary": data.get("summary", ""),
        "statement": statement, "mode": mode, "release": _release(data.get("release"), where, errors),
        "skills": skills, "difficulty": difficulty, "contexts": contexts,
        "prerequisites": prerequisites, "files": _public_files(path, where, errors, mode),
    }


def discover(root):
    """Retourne le modèle privé validé du contenu v2, ou lève avec toutes les erreurs."""
    errors = []
    catalog = _json(os.path.join(root, "catalog.json"), errors)
    if catalog is None:
        raise ContentValidationError(errors)
    if catalog.get("schema_version") != SCHEMA_VERSION:
        errors.append("catalog.json: schema_version %s attendu" % SCHEMA_VERSION)
    skills = catalog.get("skills", [])
    if not isinstance(skills, list) or any(not isinstance(s, str) or not SKILL_RE.match(s) for s in skills):
        errors.append("catalog.json: skills invalides")
        skills = []
    if len(skills) != len(set(skills)):
        errors.append("catalog.json: skills dupliquées")
    exercises = {}
    for dirname in _children(os.path.join(root, "exercises")):
        entry = _exercise(root, dirname, set(skills), errors)
        if entry is None:
            continue
        if entry["id"] in exercises:
            errors.append("exercise id dupliqué: %s" % entry["id"])
        else:
            exercises[entry["id"]] = entry
    collections = {}
    for filename in sorted(name for name in os.listdir(os.path.join(root, "collections"))
                           if name.endswith(".json")) if os.path.isdir(os.path.join(root, "collections")) else ():
        data = _json(os.path.join(root, "collections", filename), errors)
        if data is None:
            continue
        where, collection_id = "collections/%s" % filename, data.get("id")
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append("%s: schema_version %s attendu" % (where, SCHEMA_VERSION))
        if not isinstance(collection_id, str) or not COLLECTION_RE.match(collection_id):
            errors.append("%s: id invalide" % where)
            continue
        if filename != collection_id + ".json":
            errors.append("%s: le fichier doit porter l'id" % where)
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            errors.append("%s: title manquant" % where)
        if not isinstance(data.get("description", ""), str):
            errors.append("%s: description doit être du texte" % where)
        items = data.get("items")
        if (not isinstance(items, list)
                or any(not isinstance(item, str) for item in items)
                or len(items) != len(set(items))):
            errors.append("%s: items doit être une liste de textes sans doublon" % where)
            items = []
        for item in items:
            if item not in exercises:
                errors.append("%s: exercice inconnu %r" % (where, item))
        if collection_id in collections:
            errors.append("collection id dupliqué: %s" % collection_id)
        collections[collection_id] = {"id": collection_id, "title": data.get("title", ""),
                                      "description": data.get("description", ""), "items": items,
                                      "release": _release(data.get("release", {"state": "available"}), where, errors)}
    for entry in exercises.values():
        for prerequisite in entry["prerequisites"]:
            if prerequisite not in exercises:
                errors.append("%s: prerequisite inconnu %r" % (entry["id"], prerequisite))
    if errors:
        raise ContentValidationError(errors)
    return {"schema_version": SCHEMA_VERSION, "skills": skills, "exercises": exercises,
            "collections": collections}


def public_catalogue(model):
    """Projection publique reconstruite champ à champ, sans contenu assessment."""
    exercises = []
    for entry in model["exercises"].values():
        public = {"id": entry["id"], "title": entry["title"], "release": entry["release"],
                  "skills": entry["skills"], "mode": entry["mode"]}
        if isinstance(entry["summary"], str) and entry["summary"]:
            public["summary"] = entry["summary"]
        if entry["difficulty"] is not None:
            public["difficulty"] = entry["difficulty"]
        if isinstance(entry["contexts"], list):
            public["contexts"] = [str(context) for context in entry["contexts"]]
        exercises.append(public)
    return {"schema_version": SCHEMA_VERSION, "skills": list(model["skills"]),
            "exercises": exercises,
            "collections": [{"id": entry["id"], "title": entry["title"],
                             "description": entry["description"], "items": list(entry["items"]),
                             "release": entry["release"]}
                            for entry in model["collections"].values()]}


def public_detail(model, exercise_id):
    """Le détail public d'un exercice, séparé du menu et de assessment.

    Les gabarits sont assez volumineux pour ne pas figurer dans catalog.json,
    mais sont publics par intention et nécessaires à l'éditeur. Un ID inconnu
    ne se résout pas en chemin : l'appelant doit déjà l'avoir trouvé dans le
    modèle validé.
    """
    entry = model["exercises"].get(exercise_id)
    if entry is None:
        return None
    return {"statement": entry["statement"], "files": [dict(item) for item in entry["files"]]}
