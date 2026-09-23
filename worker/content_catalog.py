import datetime as dt
import json
import os
import re
import unicodedata

import typst_build


SCHEMA_VERSION = 1
EXERCISE_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,62}\Z")
COLLECTION_RE = EXERCISE_RE
ASSIGNMENT_RE = EXERCISE_RE
SKILL_RE = re.compile(r"\A[a-z][a-z0-9-]{0,47}\Z")
# Card ids are persisted against the accounts that earned them.
CARD_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
# Names one of the drawings the page ships; an unknown one draws nothing.
CARD_ART_RE = re.compile(r"\A[a-z][a-z0-9-]{0,31}\Z")
FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")
MODES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))
# The judge reads an unknown type as "int" and says so to the student, so the only
# place a typo can still be caught is here, before anything is published.
QUIZ_TYPES = frozenset(("int", "bin", "bin8", "hex8", "choice", "multi", "bool",
                        "text", "number", "match", "order", "cloze"))
QUESTION_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
GAP_RE = re.compile(r"_{3,}")
MATCH_MIN, ORDER_MIN = 2, 3
DIFFICULTIES = frozenset(("intro", "foundation", "intermediate", "advanced"))
RELEASE_STATES = frozenset(("available", "scheduled", "archived"))
TEAM_MAX = 8
TEAM_COUNT_MAX = 99
ARCHIVE_ROOT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class ContentValidationError(ValueError):
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
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in _NATURAL_PARTS_RE.split(value) if part)


_HOUR_24_RE = re.compile(r"[T ]24[:0]")


def _iso_datetime(value):
    if not isinstance(value, str):
        return None
    if _HOUR_24_RE.search(value):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def detect_mode(assessment_dir):
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
    """The only read of a release state: a scheduled release past its date is open."""
    state = (release or {}).get("state")
    if state not in RELEASE_STATES:
        return "archived"
    if state != "scheduled":
        return state
    moment = _iso_datetime(release.get("available_from"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return "available" if moment is not None and moment <= now else "scheduled"


def find_exercise(model, exercise_id, now=None):
    entry = model["exercises"].get(exercise_id)
    if entry is None or access(entry["release"], now) != "available":
        return None
    return entry


def load_exercise(root, exercise_id, now=None, unreleased=False):
    """The worker's gate: re-checks the release instead of trusting the web tier."""
    if not isinstance(exercise_id, str) or not EXERCISE_RE.match(exercise_id):
        return None
    path = os.path.join(root, "exercises", exercise_id)
    errors = []
    data = _json(os.path.join(path, "exercise.json"), errors)
    if data is None or data.get("id") != exercise_id:
        return None
    if not unreleased and access(data.get("release"), now) != "available":
        return None
    assessment = os.path.join(path, "assessment")
    mode = detect_mode(assessment)
    if not isinstance(mode, str):
        return None
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
    if mode == "quiz":
        return []
    data = _json(os.path.join(path, "public", "files.json"), errors)
    if data is None:
        return []
    return _files(data.get("files"), where + "/public/files.json", errors)


def _exercise(root, dirname, known_skills, errors, prefix=""):
    path = os.path.join(root, "exercises", dirname)
    data = _json(os.path.join(path, "exercise.json"), errors)
    if data is None:
        return None
    where = prefix + "exercises/%s" % dirname
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
    statement_format, statement = "md", ""
    try:
        statement_format, value = typst_build.statement_of(path)
        if statement_format == "md":
            statement = value
    except typst_build.TypstError as exc:
        errors.append("%s: %s" % (where, exc))
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
    if mode == "quiz":
        _quiz(config, where, errors)
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
    verification = data.get("verification", False)
    if not isinstance(verification, bool):
        errors.append("%s: verification must be a boolean" % where)
        verification = False
    bonus = data.get("bonus", False)
    if not isinstance(bonus, bool):
        errors.append("%s: bonus must be a boolean" % where)
        bonus = False
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
        "statement": statement, "statement_format": statement_format,
        "mode": mode, "release": _release(data.get("release"), where, errors),
        "skills": skills, "difficulty": difficulty, "contexts": contexts,
        "verification": verification, "bonus": bonus,
        "prerequisites": prerequisites, "files": _public_files(path, where, errors, mode),
        "config": config,
    }


def _team(value, where, errors):
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append("%s: team must be an object" % where)
        return None
    low, high = value.get("min", 1), value.get("max")
    count = value.get("count")
    for label, number in (("min", low), ("max", high), ("count", count)):
        if not isinstance(number, int) or isinstance(number, bool):
            errors.append("%s: team.%s must be an integer" % (where, label))
            return None
    if not 1 <= low <= high <= TEAM_MAX:
        errors.append("%s: team sizes must satisfy 1 <= min <= max <= %d"
                      % (where, TEAM_MAX))
        return None
    if not 1 <= count <= TEAM_COUNT_MAX:
        errors.append("%s: team.count must satisfy 1 <= count <= %d"
                      % (where, TEAM_COUNT_MAX))
        return None
    return {"min": low, "max": high, "count": count}


def _handin(value, where, items, exercises, errors):
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


def _fold(text):
    """Case and accents dropped, the way the judge compares a lenient answer."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).lower())
                   if not unicodedata.combining(c))


def _spellings(answer, where, label, errors):
    """An accepted-spelling spec: one text, or {"accept": [...]}. [] when it is unusable."""
    if isinstance(answer, str):
        accepted = [answer]
    elif isinstance(answer, dict):
        accepted = answer.get("accept")
        if not isinstance(accepted, list) or not accepted:
            errors.append("%s %s: expects an answer or a non-empty accept list" % (where, label))
            return []
        if "strict" in answer and not isinstance(answer["strict"], bool):
            errors.append("%s %s: strict must be a boolean" % (where, label))
    else:
        errors.append("%s %s: expects an answer or a non-empty accept list" % (where, label))
        return []
    if any(not isinstance(one, str) or not one.strip() for one in accepted):
        errors.append("%s %s: every accepted spelling must be text" % (where, label))
        return []
    strict = bool(answer.get("strict")) if isinstance(answer, dict) else False
    if not strict:
        folded = [_fold(one) for one in accepted]
        if len(folded) != len(set(folded)):
            errors.append("%s %s: two accepted spellings are the same once case and "
                          "accents are dropped" % (where, label))
    return accepted


def _texts(value):
    return (value if isinstance(value, list)
            and all(isinstance(one, str) and one.strip() for one in value) else None)


def _question(question, index, seen, where, errors):
    if not isinstance(question, dict):
        errors.append("%s: question %d is not an object" % (where, index))
        return
    ident = question.get("id")
    if not isinstance(ident, str) or not QUESTION_ID_RE.match(ident):
        errors.append("%s: question %d has an invalid id" % (where, index))
        return
    label = "question %r" % ident
    if ident in seen:
        errors.append("%s: duplicate %s" % (where, label))
    seen.add(ident)
    for field in ("group", "label"):
        if not isinstance(question.get(field, ""), str):
            errors.append("%s %s: group and label must be text" % (where, label))
            break
    kind = question.get("type", "int")
    if kind not in QUIZ_TYPES:
        errors.append("%s %s: unknown question type %r" % (where, label, kind))
        return
    if "answer" not in question:
        errors.append("%s %s: no answer" % (where, label))
        return
    answer = question["answer"]
    options = question.get("options")

    if kind in ("choice", "multi"):
        chosen = _texts(options)
        if chosen is None or len(set(chosen)) < 2:
            errors.append("%s %s: %s needs at least two distinct options"
                          % (where, label, kind))
            return
        if kind == "choice":
            if answer not in chosen:
                errors.append("%s %s: the answer is not one of the options" % (where, label))
        else:
            right = _texts(answer)
            if not right or len(set(right)) != len(right) or not set(right) <= set(chosen):
                errors.append("%s %s: multi needs at least one answer, each one an option"
                              % (where, label))
            elif len(set(right)) == len(set(chosen)):
                errors.append("%s %s: multi with every option correct" % (where, label))
        return

    if options is not None and kind != "match":
        errors.append("%s %s: options are ignored for this type" % (where, label))

    if kind == "bool":
        if not isinstance(answer, bool):
            errors.append("%s %s: bool expects true or false" % (where, label))
    elif kind == "text":
        _spellings(answer, where, label, errors)
    elif kind == "number":
        value = answer.get("value") if isinstance(answer, dict) else answer
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("%s %s: number expects a value" % (where, label))
        margin = answer.get("margin", 0) if isinstance(answer, dict) else 0
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or margin < 0:
            errors.append("%s %s: margin must be a number, zero or more" % (where, label))
    elif kind == "match":
        pairs = (answer if isinstance(answer, dict) else {})
        if len(pairs) < MATCH_MIN or not all(
                isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                for k, v in pairs.items()):
            errors.append("%s %s: match needs at least %d pairs of text"
                          % (where, label, MATCH_MIN))
        # Distractors: extra right-hand entries with no prompt of their own.
        if options is not None:
            extra = _texts(options)
            if extra is None or len(set(extra)) != len(extra):
                errors.append("%s %s: the distractors must be distinct text"
                              % (where, label))
    elif kind == "order":
        items = _texts(answer)
        if not items or len(set(items)) != len(items) or len(items) < ORDER_MIN:
            errors.append("%s %s: order needs at least %d distinct items"
                          % (where, label, ORDER_MIN))
        elif items == sorted(items):
            # public_quiz publishes sorted(answer) so the file order cannot leak. When the
            # correct order IS the sorted one, that projection hands over the answer.
            errors.append("%s %s: the correct order is the alphabetical order, which is the "
                          "order the page shows -- reword an item" % (where, label))
    elif kind == "cloze":
        template = question.get("template")
        holes = len(GAP_RE.findall(template)) if isinstance(template, str) else 0
        if not holes:
            errors.append("%s %s: cloze needs a template with at least one ___ gap"
                          % (where, label))
            return
        gaps = answer if isinstance(answer, list) else []
        if len(gaps) != holes:
            errors.append("%s %s: the template has %d gap(s) and the answer has %d"
                          % (where, label, holes, len(gaps)))
            return
        for number, gap in enumerate(gaps, 1):
            accepted = _spellings(gap, where, "%s gap %d" % (label, number), errors)
            choices = gap.get("choices") if isinstance(gap, dict) else None
            if choices is None:
                continue
            listed = _texts(choices)
            if not listed or len(set(listed)) < 2:
                errors.append("%s %s gap %d: a dropdown needs at least two distinct choices"
                              % (where, label, number))
            elif not set(accepted) <= set(listed):
                errors.append("%s %s gap %d: accepts something that is not one of its choices"
                              % (where, label, number))


def _quiz(config, where, errors):
    questions = config.get("questions")
    if not isinstance(questions, list):
        errors.append("%s: quiz requires questions" % where)
        return
    seen = set()
    for index, question in enumerate(questions, 1):
        _question(question, index, seen, where, errors)


def _named_file(data, filename, pattern, where, errors):
    """The header a collection and an assignment file share. None means the id is unusable."""
    ident = data.get("id")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
    if not isinstance(ident, str) or not pattern.match(ident):
        errors.append("%s: invalid id" % where)
        return None
    if filename != ident + ".json":
        errors.append("%s: the file must be named after the id" % where)
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errors.append("%s: missing title" % where)
    if not isinstance(data.get("description", ""), str):
        errors.append("%s: description must be text" % where)
    return ident


def _assignment(root, filename, exercises, errors, prefix=""):
    path = os.path.join(root, "assignments", filename)
    data = _json(path, errors)
    if data is None:
        return None
    where = prefix + "assignments/%s" % filename
    assignment_id = _named_file(data, filename, ASSIGNMENT_RE, where, errors)
    if assignment_id is None:
        return None
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


def content_roots(value):
    """CTESTER_CONTENT is one path, or several joined by the path separator."""
    if not isinstance(value, str):
        return [one for one in value if one]
    return [part for part in value.split(os.pathsep) if part]


def _label(root):
    """Names a root in an error message: the repository, not the `content/` inside it."""
    name = os.path.basename(os.path.normpath(root))
    if name in ("content", "", os.sep):
        name = os.path.basename(os.path.dirname(os.path.normpath(root))) or name
    return name


def _cards(root, prefix, errors):
    """cards.json is optional. A card naming an unknown exercise fails the publication
    here, rather than becoming quietly unobtainable."""
    path = os.path.join(root, "cards.json")
    if not os.path.isfile(path):
        return []
    data = _json(path, errors)
    if data is None:
        return []
    where = prefix + "cards.json"
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
    entries = data.get("cards", [])
    if not isinstance(entries, list):
        errors.append("%s: cards must be a list" % where)
        return []
    cards = []
    for index, card in enumerate(entries):
        place = "%s: card %d" % (where, index + 1)
        if not isinstance(card, dict):
            errors.append("%s: must be an object" % place)
            continue
        card_id = card.get("id")
        if not isinstance(card_id, str) or not CARD_ID_RE.match(card_id):
            errors.append("%s: invalid id" % place)
            continue
        place = "%s: card %s" % (where, card_id)
        for key in ("name", "family", "condition"):
            if not isinstance(card.get(key), str) or not card[key].strip():
                errors.append("%s: missing %s" % (place, key))
        items = card.get("exercises")
        if (not isinstance(items, list) or not items
                or any(not isinstance(item, str) for item in items)
                or len(items) != len(set(items))):
            errors.append("%s: exercises must be a non-empty list of ids with no duplicates"
                          % place)
            items = []
        art = card.get("art", "")
        if art and (not isinstance(art, str) or not CARD_ART_RE.match(art)):
            errors.append("%s: invalid art" % place)
            art = ""
        cards.append({"id": card_id, "name": card.get("name", ""),
                      "family": card.get("family", ""), "art": art,
                      "condition": card.get("condition", ""), "exercises": items})
    return cards


def _catalog_skills(root, prefix, errors):
    catalog = _json(os.path.join(root, "catalog.json"), errors)
    if catalog is None:
        raise ContentValidationError(errors)
    where = prefix + "catalog.json"
    if catalog.get("schema_version") != SCHEMA_VERSION:
        errors.append("%s: expected schema_version %s" % (where, SCHEMA_VERSION))
    # A skill is an id, or an id with the words the page should show for it: the
    # vocabulary is the content base's, so its wording travels with it.
    entries = catalog.get("skills", [])
    if not isinstance(entries, list):
        errors.append("%s: invalid skills" % where)
        return [], {}
    skills, labels = [], {}
    for entry in entries:
        if isinstance(entry, dict):
            skill, label = entry.get("id"), entry.get("label", "")
        else:
            skill, label = entry, ""
        if not isinstance(skill, str) or not SKILL_RE.match(skill):
            errors.append("%s: invalid skills" % where)
            return [], {}
        if not isinstance(label, str):
            errors.append("%s: skill %s has a non-text label" % (where, skill))
            label = ""
        skills.append(skill)
        if label.strip():
            labels[skill] = label.strip()
    if len(skills) != len(set(skills)):
        errors.append("%s: duplicate skills" % where)
    return skills, labels


def discover(root):
    """One content root, or several merged into a single catalogue.

    Ids must be unique across roots; the duplicate checks below are what enforces it. Any
    error rejects the whole merge, so nothing is published half-way.
    """
    roots = [root] if isinstance(root, (str, os.PathLike)) else list(root)
    if not roots:
        raise ContentValidationError(("no content root given",))
    # A single root keeps the plain messages; the repository is only named when it is
    # needed to tell two of them apart.
    prefixes = {os.fspath(r): ("%s: " % _label(r) if len(roots) > 1 else "") for r in roots}
    errors = []

    # Every root's vocabulary, so an exercise may use a skill declared by another repository.
    skills, skill_labels = [], {}
    for one in roots:
        found, labels = _catalog_skills(one, prefixes[os.fspath(one)], errors)
        skills += found
        skill_labels.update(labels)
    skills = sorted(set(skills))

    exercises, came_from = {}, {}
    for one in roots:
        prefix = prefixes[os.fspath(one)]
        for dirname in _children(os.path.join(one, "exercises")):
            entry = _exercise(one, dirname, set(skills), errors, prefix)
            if entry is None:
                continue
            if entry["id"] in exercises:
                errors.append("%sduplicate exercise id: %s (already in %s)"
                              % (prefix, entry["id"], came_from[entry["id"]]))
            else:
                exercises[entry["id"]] = entry
                came_from[entry["id"]] = _label(one)

    collections, collection_from = {}, {}
    for one in roots:
        prefix = prefixes[os.fspath(one)]
        directory = os.path.join(one, "collections")
        names = sorted((name for name in os.listdir(directory) if name.endswith(".json")),
                       key=_natural_key) if os.path.isdir(directory) else ()
        for filename in names:
            data = _json(os.path.join(directory, filename), errors)
            if data is None:
                continue
            where = prefix + "collections/%s" % filename
            collection_id = _named_file(data, filename, COLLECTION_RE, where, errors)
            if collection_id is None:
                continue
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
                errors.append("%sduplicate collection id: %s (already in %s)"
                              % (prefix, collection_id, collection_from[collection_id]))
            collection_from[collection_id] = _label(one)
            collections[collection_id] = {
                "id": collection_id, "title": data.get("title", ""),
                "description": data.get("description", ""), "items": items,
                "release": _release(data.get("release", {"state": "available"}), where, errors)}

    assignments, assignment_from = {}, {}
    for one in roots:
        prefix = prefixes[os.fspath(one)]
        directory = os.path.join(one, "assignments")
        names = sorted((name for name in os.listdir(directory) if name.endswith(".json")),
                       key=_natural_key) if os.path.isdir(directory) else ()
        for filename in names:
            entry = _assignment(one, filename, exercises, errors, prefix)
            if entry is None:
                continue
            if entry["id"] in assignments:
                errors.append("%sduplicate assignment id: %s (already in %s)"
                              % (prefix, entry["id"], assignment_from[entry["id"]]))
            else:
                assignments[entry["id"]] = entry
                assignment_from[entry["id"]] = _label(one)

    cards, card_from = {}, {}
    for one in roots:
        prefix = prefixes[os.fspath(one)]
        for card in _cards(one, prefix, errors):
            if card["id"] in cards:
                errors.append("%sduplicate card id: %s (already in %s)"
                              % (prefix, card["id"], card_from[card["id"]]))
                continue
            for item in card["exercises"]:
                if item not in exercises:
                    errors.append("%scards.json: card %s names unknown exercise %r"
                                  % (prefix, card["id"], item))
            cards[card["id"]] = card
            card_from[card["id"]] = _label(one)

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
    # Sorted by id, so reordering CTESTER_CONTENT does not change the revision hash.
    # Collections and assignments sort naturally (tp9 before tp10).
    def _by(items, key):
        return dict(sorted(items.items(), key=lambda pair: key(pair[0])))

    return {"schema_version": SCHEMA_VERSION, "skills": skills,
            "skill_labels": dict(sorted(skill_labels.items())),
            "exercises": _by(exercises, lambda name: name),
            "collections": _by(collections, _natural_key),
            "assignments": _by(assignments, _natural_key),
            "cards": _by(cards, _natural_key)}


def public_catalogue(model, now=None):
    """Rebuilt field by field. Closed exercises are listed with their date, without detail."""
    exercises = []
    for entry in model["exercises"].values():
        public = {"id": entry["id"], "title": entry["title"], "release": entry["release"],
                  "access": access(entry["release"], now),
                  "skills": entry["skills"], "mode": entry["mode"]}
        if isinstance(entry["summary"], str) and entry["summary"]:
            public["summary"] = entry["summary"]
        if entry["difficulty"] is not None:
            public["difficulty"] = entry["difficulty"]
        if entry.get("verification"):
            public["verification"] = True
        if entry.get("bonus"):
            public["bonus"] = True
        if entry.get("assignment"):
            public["assignment"] = entry["assignment"]
        if isinstance(entry["contexts"], list):
            public["contexts"] = [str(context) for context in entry["contexts"]]
        if entry["files"]:
            public["files"] = [{"name": item["name"]} for item in entry["files"]]
        exercises.append(public)
    return {"schema_version": SCHEMA_VERSION, "skills": list(model["skills"]),
            "skill_labels": dict(model.get("skill_labels") or {}),
            "exercises": exercises,
            "collections": [{"id": entry["id"], "title": entry["title"],
                             "description": entry["description"], "items": list(entry["items"]),
                             "release": entry["release"],
                             "access": access(entry["release"], now)}
                            for entry in model["collections"].values()],
            "assignments": [_public_assignment(entry, now)
                            for entry in model.get("assignments", {}).values()],
            "cards": [dict(card) for card in model.get("cards", {}).values()]}


def _public_assignment(entry, now=None):
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


def public_detail(model, exercise_id, now=None, pages=None, html=False):
    entry = find_exercise(model, exercise_id, now)
    if entry is None:
        return None
    detail = {"statement": entry["statement"],
              "files": [dict(item) for item in entry["files"]]}
    if entry.get("statement_format") == "typ":
        detail["statement_format"] = "typst"
        detail["statement_pages"] = int(pages or 0)
        detail["statement_html"] = bool(html)
    return detail
