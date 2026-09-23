import datetime as dt
import io
import re
import zipfile

import config
from services.catalog import load_catalog, validate_files

COLORS = ("#e0533d", "#2f8fd8", "#7d57c1", "#1f9d6a", "#c9821b", "#c2418f",
          "#3f7f8f", "#8a6b3d")



def assignments(now=None):
    return [entry for entry in (load_catalog() or {}).get("assignments") or ()
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            and entry.get("access") == "available"]


def published_assignment(assignment_id):
    for entry in (load_catalog() or {}).get("assignments") or ():
        if isinstance(entry, dict) and entry.get("id") == assignment_id:
            return entry
    return None


def find_assignment(assignment_id):
    for entry in assignments():
        if entry["id"] == assignment_id:
            return entry
    return None


def assignment_exercises(assignment):
    return [item for item in assignment.get("items") or []
            if isinstance(item, str)]


def is_team_assignment(assignment):
    return bool(assignment) and isinstance(assignment.get("team"), dict)


def deadline_passed(assignment, now=None):
    raw = assignment.get("deadline")
    if not isinstance(raw, str):
        return False
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        return False
    return (now or dt.datetime.now(dt.timezone.utc)) > moment


# Only the stored label, which the teacher's dashboard shows; the page words its own.
TEAM_NAME = "Équipe %d"


def team_size(assignment):
    team = assignment.get("team") or {}
    low = team.get("min") if isinstance(team.get("min"), int) else 1
    high = team.get("max") if isinstance(team.get("max"), int) else low
    count = team.get("count") if isinstance(team.get("count"), int) else 0
    return low, high, count


def team_handle(group_number, number):
    return "g%02d-e%02d" % (int(group_number), int(number))


def joinable(assignment):
    # The opening date that freezes teams is the one find_assignment() requires,
    # so joining a team and reading its document can never overlap.
    return bool(assignment) and assignment.get("access") != "available"


def available_teams(assignment, group_number, existing):
    _low, high, count = team_size(assignment)
    by_number = {row["number"]: row for row in existing}
    items = []
    for number in range(1, count + 1):
        row = by_number.get(number) or {}
        members = int(row.get("members") or 0)
        items.append({
            "number": number,
            "members": members,
            "max": high,
            "full": members >= high,
        })
    return items


def workspace(state, sub, assignment_id):
    assignment = find_assignment(assignment_id)
    if assignment is None:
        return None, None, (404, "unknown_assignment")
    if not is_team_assignment(assignment):
        return assignment, None, (400, "not_a_team_assignment")
    team = state.team_of(sub, assignment_id)
    if team is None:
        return assignment, None, (403, "not_in_team_frozen")
    return assignment, team, None


def exercise_in(assignment, exercise_id):
    return exercise_id in set(assignment_exercises(assignment))


def members_view(roster, sub, profiles):
    profiles = profiles or {}
    out = []
    for index, account in enumerate(roster):
        profile = profiles.get(account) or {}
        name = profile.get("display_name")
        chosen = bool(name) and bool(profile.get("display_name_public"))
        out.append({
            "id": "m%d" % (index + 1),
            "name": name if chosen else "",
            "color": COLORS[index % len(COLORS)],
            "you": account == sub,
        })
    return out


def member_handle(roster, sub):
    try:
        return "m%d" % (roster.index(sub) + 1)
    except ValueError:
        return ""


def handin_files(state, assignment, team_id, catalog_entry_of):
    handin = assignment.get("handin") or {}
    root = handin.get("root") or assignment["id"]
    files, missing = {}, []
    for item in handin.get("files") or []:
        exercise_id, wanted = item.get("exercise_id"), item.get("file")
        entry = catalog_entry_of(exercise_id)
        sources = state.read_team_document(team_id, exercise_id)
        if sources is None:
            return None, []
        if entry is not None:
            checked, message, _ = validate_files(entry, sources)
            sources = checked if message is None else {}
        text = sources.get(wanted, "")
        if not text.strip():
            missing.append({"name": item["name"], "exercise_id": exercise_id})
            continue
        files[root + "/" + item["name"]] = text
    return files, missing


# Fixed timestamps and attributes keep the archive byte-for-byte reproducible.
ARCHIVE_EPOCH = (1980, 1, 1, 0, 0, 0)


def build_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ARCHIVE_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def archive_name(assignment, team):
    root = (assignment.get("handin") or {}).get("root") or assignment["id"]
    return "%s-%s.zip" % (_SAFE_NAME.sub("-", str(root))[:64],
                          _SAFE_NAME.sub("-", str(team["team_id"]))[:64])


def assignment_view(assignment, now=None):
    return {
        "id": assignment["id"],
        "title": assignment.get("title", ""),
        "description": assignment.get("description", ""),
        "items": assignment_exercises(assignment),
        "team": dict(assignment.get("team") or {}),
        "deadline": assignment.get("deadline"),
        "deadline_passed": deadline_passed(assignment, now),
        "access": assignment.get("access", "archived"),
        "handin": [dict(item) for item in
                   (assignment.get("handin") or {}).get("files") or []],
    }


def revisions_view(rows, roster):
    positions = {account: index + 1 for index, account in enumerate(roster)}
    out = []
    for row in rows:
        index = positions.get(row["account"])
        out.append({"id": row["revision_id"],
                    "author": "m%d" % index if index else "",
                    "created_at": row["created_at"], "bytes": row["bytes"]})
    return out[:config.TEAM_REVISIONS_MAX]
