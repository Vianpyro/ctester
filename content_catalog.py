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
ASSIGNMENT_RE = EXERCISE_RE
SKILL_RE = re.compile(r"\A[a-z][a-z0-9-]{0,47}\Z")
FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")
MODES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))
DIFFICULTIES = frozenset(("intro", "foundation", "intermediate", "advanced"))
RELEASE_STATES = frozenset(("available", "scheduled", "archived"))
# THE OUTER BOUND ON A TEAM, not the course's rule. TCH009 asks for 3 or 4;
# the assignment file says so. This only refuses a typo that would turn a
# team into a section.
TEAM_MAX = 8
# The ZIP's top directory. A PLAIN NAME, checked here rather than when the
# archive is built: an assignment file is content, and content is the one
# place where a `../` would otherwise become a path.
ARCHIVE_ROOT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


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


# --- Assignments --------------------------------------------------------------
# AN ASSIGNMENT IS NOT A COLLECTION, and the two must not be folded together.
# A collection is a PATH through the catalog: a menu heading, no deadline, no
# hand-in, and an exercise may sit in two of them. An assignment is a piece of
# ASSESSED WORK: it has a deadline, it says what the final hand-in looks like,
# and -- when it declares a `team` -- it is done by a team rather than by a
# person. Reusing `collections` for it would have made "which lab is this in"
# and "what am I handing in" the same field, and the day they diverge is the
# day someone hands in the wrong thing.
#
# IT REFERENCES EXERCISES, IT DOES NOT REDEFINE THEM. `items` is a list of
# exercise ids, exactly like a collection's, so an exercise stays defined in
# exactly one place.
#
# `team` IS THE OPT-IN, AND ITS ABSENCE IS THE DEFAULT. No `team` block means
# an ordinary individual assignment: nothing collaborative is created, no
# workspace is offered, and every existing exercise keeps behaving as it did.


def _team(value, where, errors):
    """`{"min": 3, "max": 4}` -- or None, which means "individual".

    The bounds are the ASSIGNMENT's, not the platform's: TCH009 asks for three
    or four, another course would ask for two. `TEAM_MAX` only refuses the
    typo that would turn a team into a section.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append("%s: team must be an object" % where)
        return None
    low, high = value.get("min", 1), value.get("max")
    for label, number in (("min", low), ("max", high)):
        if not isinstance(number, int) or isinstance(number, bool):
            errors.append("%s: team.%s must be an integer" % (where, label))
            return None
    if not 1 <= low <= high <= TEAM_MAX:
        errors.append("%s: team sizes must satisfy 1 <= min <= max <= %d"
                      % (where, TEAM_MAX))
        return None
    return {"min": low, "max": high}


def _handin(value, where, items, exercises, errors):
    """What the final ZIP holds -- driven by metadata, never by a file name
    this application happens to know.

    Each entry names the file IN THE ARCHIVE and where its contents come
    from: an exercise of this assignment, and one of the files that exercise
    declares. Nothing is concatenated and nothing is rewritten -- the archive
    is a copy of what the team wrote, which is the only thing that can be
    handed in honestly.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append("%s: handin must be an object" % where)
        return None
    root = value.get("root", "")
    if not isinstance(root, str) or not ARCHIVE_ROOT_RE.match(root):
        errors.append("%s: handin.root must be a plain directory name" % where)
        return None
    entries = value.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("%s: handin.files must be a non-empty list" % where)
        return None
    out, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("%s: invalid handin entry" % where)
            continue
        name, exercise_id = entry.get("name"), entry.get("exercise_id")
        source = entry.get("file", name)
        if not isinstance(name, str) or not FILE_RE.match(name) or name in seen:
            errors.append("%s: invalid or duplicate handin file name" % where)
            continue
        if exercise_id not in items:
            errors.append("%s: handin %r names an exercise outside this assignment"
                          % (where, name))
            continue
        declared = {item["name"] for item in exercises[exercise_id]["files"]}
        if not isinstance(source, str) or source not in declared:
            errors.append("%s: handin %r reads %r, which %s does not declare"
                          % (where, name, source, exercise_id))
            continue
        seen.add(name)
        out.append({"name": name, "exercise_id": exercise_id, "file": source})
    return {"root": root, "files": out} if out else None


def _assignment(root, filename, exercises, errors):
    path = os.path.join(root, "assignments", filename)
    data = _json(path, errors)
    if data is None:
        return None
    where = "assignments/%s" % filename
    assignment_id = data.get("id")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
    if not isinstance(assignment_id, str) or not ASSIGNMENT_RE.match(assignment_id):
        errors.append("%s: invalid id" % where)
        return None
    if filename != assignment_id + ".json":
        errors.append("%s: the file must be named after the id" % where)
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errors.append("%s: missing title" % where)
    if not isinstance(data.get("description", ""), str):
        errors.append("%s: description must be text" % where)
    items = data.get("items")
    if (not isinstance(items, list) or not items
            or any(not isinstance(item, str) for item in items)
            or len(items) != len(set(items))):
        errors.append("%s: items must be a non-empty list of text with no duplicates"
                      % where)
        items = []
    kept = []
    for item in items:
        if item in exercises:
            kept.append(item)
        else:
            errors.append("%s: unknown exercise %r" % (where, item))
    deadline = data.get("deadline")
    if deadline is not None and _iso_datetime(deadline) is None:
        errors.append("%s: deadline must be an ISO date with a timezone" % where)
        deadline = None
    return {"id": assignment_id, "title": data.get("title", ""),
            "description": data.get("description", ""), "items": kept,
            "team": _team(data.get("team"), where, errors),
            "deadline": deadline if isinstance(deadline, str) else None,
            "handin": _handin(data.get("handin"), where, set(kept), exercises, errors),
            "release": _release(data.get("release", {"state": "available"}),
                                where, errors)}


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
    assignments = {}
    directory = os.path.join(root, "assignments")
    for filename in sorted((name for name in os.listdir(directory)
                            if name.endswith(".json")), key=_natural_key) \
            if os.path.isdir(directory) else ():
        entry = _assignment(root, filename, exercises, errors)
        if entry is None:
            continue
        if entry["id"] in assignments:
            errors.append("duplicate assignment id: %s" % entry["id"])
        else:
            assignments[entry["id"]] = entry
    # AN EXERCISE BELONGS TO AT MOST ONE ASSIGNMENT, unlike a collection.
    # Two assignments claiming the same exercise would mean two teams, two
    # deadlines and two hand-ins for one shared document -- there would be no
    # honest answer to "whose workspace is this".
    owner = {}
    for entry in assignments.values():
        for item in entry["items"]:
            if item in owner:
                errors.append("%s: %r already belongs to assignment %r"
                              % (entry["id"], item, owner[item]))
            else:
                owner[item] = entry["id"]
    for entry in exercises.values():
        entry["assignment"] = owner.get(entry["id"])
        for prerequisite in entry["prerequisites"]:
            if prerequisite not in exercises:
                errors.append("%s: unknown prerequisite %r" % (entry["id"], prerequisite))
    if errors:
        raise ContentValidationError(errors)
    return {"schema_version": SCHEMA_VERSION, "skills": skills, "exercises": exercises,
            "collections": collections, "assignments": assignments}


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
        # WHICH ASSIGNMENT THIS EXERCISE BELONGS TO, or nothing at all. The
        # page reads it to know it must open the assignment workspace instead
        # of the individual editor, and `_record()` reads it to keep team work
        # out of a personal XP balance. Absent for every existing exercise,
        # which is exactly the point: the feature is additive.
        if entry.get("assignment"):
            public["assignment"] = entry["assignment"]
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
                            for entry in model["collections"].values()],
            # ASSIGNMENTS TRAVEL WHOLE, and that is deliberate: `team`,
            # `deadline` and `handin` are what the workspace, the deadline
            # notice and the ZIP are built from, and rebuilding any of them
            # from a second source would make the archive disagree with the
            # page. Nothing private is in here -- an assignment file has no
            # assessment section to leak.
            "assignments": [_public_assignment(entry, now)
                            for entry in model.get("assignments", {}).values()]}


def _public_assignment(entry, now=None):
    """One assignment, field by field. Same rule as everywhere else here."""
    public = {"id": entry["id"], "title": entry["title"],
              "description": entry["description"], "items": list(entry["items"]),
              "release": entry["release"], "access": access(entry["release"], now)}
    if entry.get("team"):
        public["team"] = dict(entry["team"])
    if entry.get("deadline"):
        public["deadline"] = entry["deadline"]
    if entry.get("handin"):
        public["handin"] = {"root": entry["handin"]["root"],
                            "files": [dict(item) for item in entry["handin"]["files"]]}
    return public


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
