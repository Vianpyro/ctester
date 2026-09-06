"""Validation and discovery of v2 content.

The worker, CI, and the publisher (`publish_content.py`) all go through the
same gate, `find_exercise()`, rather than each reinterpreting the metadata on
its own.

Content is private by default. ``public_catalogue`` rebuilds only the values
allowed to cross this boundary; it never strips a few keys from a copy of the
grading configuration.
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
    """One or more author errors, never an HTTP path error."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


def _json(path, errors):
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError) as exc:
        errors.append("%s: unreadable JSON (%s)" % (path, exc))
        return None
    if not isinstance(value, dict):
        errors.append("%s: expected a JSON object" % path)
        return None
    return value


def _children(path):
    try:
        return sorted(name for name in os.listdir(path)
                      if os.path.isdir(os.path.join(path, name)))
    except OSError:
        return []


_NATURAL_PARTS_RE = re.compile(r"(\d+)")


def _natural_key(value):
    """Stable key for collection ids read from files.

    Collections are the path shown in the menu. A lexical sort of their files
    would therefore place ``tp10.json`` before ``tp2.json``. Ids stay stable
    ids and are not artificially padded with zeros: their numeric portions are
    simply compared as numbers. Portions are typed so that an id starting
    with a digit stays comparable to one starting with a letter.
    """
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in _NATURAL_PARTS_RE.split(value) if part)


def _iso_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def detect_mode(assessment_dir):
    """The single mode present, or ``None`` / a list of conflicts.

    No ``mode`` field appears in exercise.json: the grading file is the
    source of truth. The validator distinguishes absence from plurality.
    """
    found = [mode for mode, filename in MODES
             if os.path.isfile(os.path.join(assessment_dir, filename))]
    return found[0] if len(found) == 1 else (found or None)


def _release(value, where, errors):
    if not isinstance(value, dict):
        errors.append("%s: release must be an object" % where)
        return {"state": "archived"}
    state = value.get("state")
    if state not in RELEASE_STATES:
        errors.append("%s: invalid release.state" % where)
        state = "archived"
    available_from = value.get("available_from")
    if state == "scheduled":
        if _iso_datetime(available_from) is None:
            errors.append("%s: scheduled requires an ISO available_from with a timezone" % where)
    elif available_from is not None:
        errors.append("%s: available_from is only allowed for scheduled" % where)
    out = {"state": state}
    if state == "scheduled" and isinstance(available_from, str):
        out["available_from"] = available_from
    return out


def access(release, now=None):
    """``available`` / ``scheduled`` / ``archived`` -- THE ONLY READ OF A RELEASE.

    A ``scheduled`` release whose date has passed IS open: a release is data,
    not a periodic job to trigger. Without this, opening an exercise would
    require a commit the morning of class, and forgetting it would look like
    an outage. ``now`` exists only for tests and preview mode.
    """
    state = (release or {}).get("state")
    if state not in RELEASE_STATES:
        return "archived"
    if state != "scheduled":
        return state
    moment = _iso_datetime(release.get("available_from"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return "available" if moment is not None and moment <= now else "scheduled"


def find_exercise(model, exercise_id, now=None):
    """THE ONE GATE to an exercise: detail, quiz, draft, forum, submission.

    An id that is not open does not resolve to an entry, so not to a path
    either: a deep link a student shared early does not bypass anything, it
    just does not resolve. The worker calls this same function before
    running anything.
    """
    entry = model["exercises"].get(exercise_id)
    if entry is None or access(entry["release"], now) != "available":
        return None
    return entry


def load_exercise(root, exercise_id, now=None, tout=False):
    """ONE exercise resolved from the private root, without validating the whole repo.

    THIS IS THE WORKER'S GATE. It runs as root, once per job, and an exercise
    broken elsewhere in the repo must not stop the queue -- `discover()`
    validates EVERYTHING and serves CI and the publisher, not this.

    The release is re-applied: the web tier already did it, this process
    trusts nobody, including our own web container. `tout=True` is the
    instructor's preview mode, and nothing else.
    """
    if not isinstance(exercise_id, str) or not EXERCISE_RE.match(exercise_id):
        return None
    path = os.path.join(root, "exercises", exercise_id)
    errors = []
    data = _json(os.path.join(path, "exercise.json"), errors)
    if data is None or data.get("id") != exercise_id:
        return None
    if not tout and access(data.get("release"), now) != "available":
        return None
    assessment = os.path.join(path, "assessment")
    mode = detect_mode(assessment)
    if not isinstance(mode, str):
        return None  # no mode, or several: nothing to run
    files = _public_files(path, "exercises/" + exercise_id, errors, mode)
    return {"id": exercise_id, "path": assessment, "mode": mode,
            "files": files or [{"name": "submission.c", "template": ""}],
            "release": data.get("release")}


def _files(value, where, errors):
    if value is None:
        return [{"name": "submission.c", "template": ""}]
    if not isinstance(value, list) or not value:
        errors.append("%s: files must be a non-empty list" % where)
        return []
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            errors.append("%s: invalid files entry" % where)
            continue
        name, template = item.get("name"), item.get("template", "")
        if not isinstance(name, str) or not FILE_RE.match(name) or name in seen:
            errors.append("%s: invalid or duplicate file name" % where)
            continue
        if not isinstance(template, str):
            errors.append("%s: template must be text" % where)
            continue
        seen.add(name)
        result.append({"name": name, "template": template})
    return result


def _public_files(path, where, errors, mode):
    """Templates are public, so kept apart from the grading configuration."""
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
        errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
    exercise_id, title = data.get("id"), data.get("title")
    if not isinstance(exercise_id, str) or not EXERCISE_RE.match(exercise_id):
        errors.append("%s: invalid id" % where)
        return None
    if dirname != exercise_id:
        errors.append("%s: the directory must be named after the id" % where)
    if not isinstance(title, str) or not title.strip():
        errors.append("%s: missing title" % where)
    if not isinstance(data.get("summary", ""), str):
        errors.append("%s: summary must be text" % where)
    try:
        with open(os.path.join(path, "statement.md"), encoding="utf-8") as fh:
            statement = fh.read()
    except OSError:
        errors.append("%s: missing statement.md" % where)
        statement = ""
    assessment = os.path.join(path, "assessment")
    mode = detect_mode(assessment)
    if isinstance(mode, list):
        errors.append("%s: several modes present (%s)" % (where, ", ".join(mode)))
        mode = None
    elif mode is None:
        errors.append("%s: no mode present" % where)
    config = _json(os.path.join(assessment, dict(MODES).get(mode, "missing.json")), errors) if mode else {}
    config = config or {}
    assessment_names = os.listdir(assessment) if os.path.isdir(assessment) else []
    if mode == "unity" and not any(name.startswith("test_") and name.endswith(".c")
                                    for name in assessment_names):
        errors.append("%s: unity requires at least one test_*.c" % where)
    if mode == "io" and not isinstance(config.get("cases"), list):
        errors.append("%s: io requires cases" % where)
    if mode == "quiz" and not isinstance(config.get("questions"), list):
        errors.append("%s: quiz requires questions" % where)
    skills = data.get("skills", [])
    if (not isinstance(skills, list)
            or any(not isinstance(skill, str) for skill in skills)
            or len(skills) != len(set(skills))):
        errors.append("%s: skills must be a list of text with no duplicates" % where)
        skills = []
    for skill in skills:
        if not isinstance(skill, str) or not SKILL_RE.match(skill) or skill not in known_skills:
            errors.append("%s: unknown or invalid skill (%r)" % (where, skill))
    difficulty = data.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        errors.append("%s: invalid difficulty" % where)
    # A VERIFICATION IS AN ORDINARY EXERCISE, MARKED. The flag does not
    # depend on the mode: a code-reading quiz and an io debugging exercise
    # are both valid verifications (docs/gamification/mastery.md). What it
    # changes is downstream -- no XP, no counting toward practice, and a
    # piece of mastery evidence on every verdict.
    verification = data.get("verification", False)
    if not isinstance(verification, bool):
        errors.append("%s: verification must be a boolean" % where)
        verification = False
    contexts = data.get("contexts", [])
    if not isinstance(contexts, list) or any(not isinstance(context, str) or not context
                                              for context in contexts):
        errors.append("%s: contexts must be a list of text" % where)
        contexts = []
    prerequisites = data.get("prerequisites", [])
    if (not isinstance(prerequisites, list)
            or any(not isinstance(prerequisite, str) for prerequisite in prerequisites)
            or len(prerequisites) != len(set(prerequisites))):
        errors.append("%s: prerequisites must be a list of text with no duplicates" % where)
        prerequisites = []
    elif any(not isinstance(prerequisite, str) or not EXERCISE_RE.match(prerequisite)
             for prerequisite in prerequisites):
        errors.append("%s: invalid prerequisite" % where)
    return {
        "id": exercise_id, "path": path, "title": title, "summary": data.get("summary", ""),
        "statement": statement, "mode": mode, "release": _release(data.get("release"), where, errors),
        "skills": skills, "difficulty": difficulty, "contexts": contexts,
        "verification": verification,
        "prerequisites": prerequisites, "files": _public_files(path, where, errors, mode),
        # THE GRADING CONFIGURATION STAYS IN THE PRIVATE MODEL: the worker and
        # the publisher read it here rather than rebuilding a path. None of
        # this dict is exposed by public_catalogue/public_detail, which
        # rebuild field by field.
        "config": config,
    }


def discover(root):
    """Returns v2 content's validated private model, or raises with every error."""
    errors = []
    catalog = _json(os.path.join(root, "catalog.json"), errors)
    if catalog is None:
        raise ContentValidationError(errors)
    if catalog.get("schema_version") != SCHEMA_VERSION:
        errors.append("catalog.json: expected schema_version %s" % SCHEMA_VERSION)
    skills = catalog.get("skills", [])
    if not isinstance(skills, list) or any(not isinstance(s, str) or not SKILL_RE.match(s) for s in skills):
        errors.append("catalog.json: invalid skills")
        skills = []
    if len(skills) != len(set(skills)):
        errors.append("catalog.json: duplicate skills")
    exercises = {}
    for dirname in _children(os.path.join(root, "exercises")):
        entry = _exercise(root, dirname, set(skills), errors)
        if entry is None:
            continue
        if entry["id"] in exercises:
            errors.append("duplicate exercise id: %s" % entry["id"])
        else:
            exercises[entry["id"]] = entry
    collections = {}
    for filename in sorted((name for name in os.listdir(os.path.join(root, "collections"))
                            if name.endswith(".json")), key=_natural_key) \
            if os.path.isdir(os.path.join(root, "collections")) else ():
        data = _json(os.path.join(root, "collections", filename), errors)
        if data is None:
            continue
        where, collection_id = "collections/%s" % filename, data.get("id")
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
        if not isinstance(collection_id, str) or not COLLECTION_RE.match(collection_id):
            errors.append("%s: invalid id" % where)
            continue
        if filename != collection_id + ".json":
            errors.append("%s: the file must be named after the id" % where)
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            errors.append("%s: missing title" % where)
        if not isinstance(data.get("description", ""), str):
            errors.append("%s: description must be text" % where)
        items = data.get("items")
        if (not isinstance(items, list)
                or any(not isinstance(item, str) for item in items)
                or len(items) != len(set(items))):
            errors.append("%s: items must be a list of text with no duplicates" % where)
            items = []
        for item in items:
            if item not in exercises:
                errors.append("%s: unknown exercise %r" % (where, item))
        if collection_id in collections:
            errors.append("duplicate collection id: %s" % collection_id)
        collections[collection_id] = {"id": collection_id, "title": data.get("title", ""),
                                      "description": data.get("description", ""), "items": items,
                                      "release": _release(data.get("release", {"state": "available"}), where, errors)}
    for entry in exercises.values():
        for prerequisite in entry["prerequisites"]:
            if prerequisite not in exercises:
                errors.append("%s: unknown prerequisite %r" % (entry["id"], prerequisite))
    if errors:
        raise ContentValidationError(errors)
    return {"schema_version": SCHEMA_VERSION, "skills": skills, "exercises": exercises,
            "collections": collections}


def public_catalogue(model, now=None):
    """Public projection rebuilt field by field, with no assessment content.

    An exercise not yet open still APPEARS in the catalog, with its state and
    date: that is what makes the difference between "locked until the 18th"
    and "does not exist". What it lacks is a published detail (see
    ``public_detail``) -- showing is not giving.
    """
    exercises = []
    for entry in model["exercises"].values():
        public = {"id": entry["id"], "title": entry["title"], "release": entry["release"],
                  "access": access(entry["release"], now),
                  "skills": entry["skills"], "mode": entry["mode"]}
        if isinstance(entry["summary"], str) and entry["summary"]:
            public["summary"] = entry["summary"]
        if entry["difficulty"] is not None:
            public["difficulty"] = entry["difficulty"]
        # Absent when false: the catalog is re-read on every request, and one
        # key per exercise that says nothing is 73 keys saying nothing.
        if entry.get("verification"):
            public["verification"] = True
        if isinstance(entry["contexts"], list):
            public["contexts"] = [str(context) for context in entry["contexts"]]
        # NAMES STAY, TEMPLATES LEAVE. `files` is the allow-list the API
        # checks a submission against (validate_files): emptying it would
        # open a hole. The template only ever pre-fills the editor and lives
        # in the detail, loaded when the exercise opens.
        if entry["files"]:
            public["files"] = [{"name": item["name"]} for item in entry["files"]]
        exercises.append(public)
    return {"schema_version": SCHEMA_VERSION, "skills": list(model["skills"]),
            "exercises": exercises,
            "collections": [{"id": entry["id"], "title": entry["title"],
                             "description": entry["description"], "items": list(entry["items"]),
                             "release": entry["release"],
                             "access": access(entry["release"], now)}
                            for entry in model["collections"].values()]}


def public_detail(model, exercise_id, now=None):
    """An exercise's public detail, kept apart from the menu and from assessment.

    Templates are bulky enough to stay out of catalog.json, but are public by
    design and needed by the editor. An unknown id does not resolve to a
    path: the caller must already have found it in the validated model.
    """
    entry = find_exercise(model, exercise_id, now)
    if entry is None:
        return None
    return {"statement": entry["statement"], "files": [dict(item) for item in entry["files"]]}
