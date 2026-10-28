"""Copies each team's work to a private repository of the course's GitHub organization.

One way only: CTester is where the team writes, GitHub keeps the history. Commits are
pushed with the organization's token and attributed to the students through their
noreply address, so no student token is ever kept.
"""
import base64
import datetime as dt
import difflib
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import log
import state
from services import teams
from services.catalog import find_exercise, validate_files

API = "https://api.github.com"
TOKEN_URL = "https://github.com/login/oauth/access_token"
MAX_ANSWER = 4 * 1024 * 1024
LOGIN_RE = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
MESSAGE_MAX = 72
SWEEP_EVERY = 60

# Not page text: like teams.TEAM_NAME, these are written to GitHub, in the instance's language.
WORDS = {
    "en": {"changed": "Update %s", "more": "%s and %d more",
           "handin": "Hand-in: %s (%d files)"},
    "fr": {"changed": "Modifie %s", "more": "%s et %d autres",
           "handin": "Remise : %s (%d fichiers)"},
}


def enabled():
    return all((config.GITHUB_ORG, config.GITHUB_TOKEN, config.GITHUB_CLIENT_ID,
                config.GITHUB_CLIENT_SECRET))


class Unavailable(Exception):
    """GitHub, or the database, could not do its part; status is GitHub's answer if any."""

    def __init__(self, status=None):
        super().__init__(status)
        self.status = status


# The token must never follow a redirect elsewhere.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _decode(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _call(method, path, body=None, headers=None):
    """(status, decoded JSON). headers None means the organization's token."""
    url = path if path.startswith("https://") else API + path
    sent = {"Accept": "application/vnd.github+json", "User-Agent": "ctester",
            "X-GitHub-Api-Version": "2022-11-28"}
    sent.update({"Authorization": "Bearer " + config.GITHUB_TOKEN}
                if headers is None else headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    try:
        with _OPENER.open(request, timeout=config.GITHUB_TIMEOUT) as response:
            return response.status, _decode(response.read(MAX_ANSWER))
    except urllib.error.HTTPError as refused:
        return refused.code, _decode(refused.read(MAX_ANSWER))
    except (OSError, ValueError) as failure:
        raise Unavailable() from failure


def _expect(answer, *ok):
    status, body = answer
    if status not in ok:
        raise Unavailable(status)
    return body if isinstance(body, dict) else {}


def _app_auth():
    pair = "%s:%s" % (config.GITHUB_CLIENT_ID, config.GITHUB_CLIENT_SECRET)
    return {"Authorization": "Basic " + base64.b64encode(pair.encode()).decode()}


def exchange(code):
    """The student's GitHub id and login, from an OAuth code; None if GitHub refused it.
    The grant asked for no scope and its token is revoked at once: only the identity stays."""
    status, grant = _call("POST", TOKEN_URL,
                          {"client_id": config.GITHUB_CLIENT_ID,
                           "client_secret": config.GITHUB_CLIENT_SECRET, "code": code},
                          headers={"Accept": "application/json"})
    token = grant.get("access_token") if status == 200 and isinstance(grant, dict) else None
    if not isinstance(token, str) or not token:
        return None
    try:
        status, user = _call("GET", "/user", headers={"Authorization": "Bearer " + token})
    finally:
        try:
            _call("DELETE", "/applications/%s/token" % config.GITHUB_CLIENT_ID,
                  {"access_token": token}, headers=_app_auth())
        except Unavailable:
            pass
    if status != 200 or not isinstance(user, dict):
        return None
    github_id, login = user.get("id"), user.get("login")
    if not isinstance(github_id, int) or isinstance(github_id, bool) \
            or not isinstance(login, str) or not LOGIN_RE.match(login):
        return None
    return {"github_id": github_id, "login": login}


def repo_name(assignment, team_id):
    return teams._SAFE_NAME.sub("-", "%s-%s" % (assignment["id"], team_id))[:100]


def repo_url(repo):
    return "https://github.com/%s/%s" % (config.GITHUB_ORG, repo)


def repo_files(assignment, team_id):
    """The hand-in's layout when the assignment has one, else one folder per exercise."""
    if (assignment.get("handin") or {}).get("files"):
        files, _missing = teams.handin_files(state, assignment, team_id, find_exercise)
        return files
    files = {}
    for exercise_id in teams.assignment_exercises(assignment):
        sources = state.read_team_document(team_id, exercise_id)
        if sources is None:
            return None
        entry = find_exercise(exercise_id)
        if entry is not None and sources:
            checked, message, _ = validate_files(entry, sources)
            sources = checked if message is None else {}
        for name, text in sources.items():
            if text.strip():
                files[exercise_id + "/" + name] = text
    return files


def blob_sha(text):
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _counts(before, after):
    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def clean_message(text):
    return " ".join(str(text or "").split())[:MESSAGE_MAX]


def _words():
    return WORDS.get(config.LANG.split("-")[0], WORDS["en"])


def title(changed, assignment, handin, total):
    words = _words()
    if handin:
        return words["handin"] % (assignment.get("title") or assignment["id"], total)
    shown = ", ".join(changed[:3])
    if len(changed) > 3:
        shown = words["more"] % (shown, len(changed) - 3)
    return words["changed"] % shown


def _noreply(link):
    return "%d+%s@users.noreply.github.com" % (link["github_id"], link["login"])


def message(head, stats, coauthors):
    width = max((len(path) for path in stats), default=0)
    lines = [head]
    if stats:
        lines.append("")
        lines += ["%s  +%d −%d" % (path.ljust(width), added, removed)
                  for path, (added, removed) in sorted(stats.items())]
    if coauthors:
        lines.append("")
        lines += ["Co-authored-by: %s <%s>" % (link["login"], _noreply(link))
                  for link in coauthors]
    return "\n".join(lines)


def _repo(repo):
    """The default branch's head (commit, tree), creating the repository on first use."""
    path = "/repos/%s/%s" % (config.GITHUB_ORG, repo)
    status, info = _call("GET", path)
    if status == 404:
        _expect(_call("POST", "/orgs/%s/repos" % config.GITHUB_ORG,
                      {"name": repo, "private": True, "auto_init": True,
                       "has_issues": False, "has_wiki": False, "has_projects": False}),
                201)
        status, info = _call("GET", path)
    if status != 200 or not isinstance(info, dict):
        raise Unavailable(status)
    branch = info.get("default_branch") or "main"
    ref_path = path + "/git/ref/heads/" + urllib.parse.quote(branch)
    # A repository just created may answer 404 or 409 until its first commit is written.
    for _ in range(3):
        status, ref = _call("GET", ref_path)
        if status == 200:
            break
        time.sleep(1)
    ref = _expect((status, ref), 200)
    commit = (ref.get("object") or {}).get("sha")
    tree = (_expect(_call("GET", path + "/git/commits/" + str(commit)), 200)
            .get("tree") or {}).get("sha")
    if not commit or not tree:
        raise Unavailable(None)
    return path, branch, commit, tree


def _blobs(path, tree):
    listing = _expect(_call("GET", path + "/git/trees/%s?recursive=1" % tree), 200)
    return {item["path"]: item["sha"] for item in listing.get("tree") or []
            if isinstance(item, dict) and item.get("type") == "blob"}


def _old_text(path, sha):
    if not sha:
        return ""
    blob = _expect(_call("GET", path + "/git/blobs/" + sha), 200)
    try:
        return base64.b64decode(blob.get("content") or "").decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _collaborators(path, links, invited):
    """Read access for the team's linked members, and none for those who left it."""
    wanted = {str(link["github_id"]): link["login"] for link in links.values()}
    kept = {}
    for github_id, login in wanted.items():
        if github_id in invited:
            kept[github_id] = login
            continue
        status, _ = _call("PUT", path + "/collaborators/" + login, {"permission": "pull"})
        if status in (201, 204):
            kept[github_id] = login
    gone = {github_id: login for github_id, login in invited.items()
            if github_id not in wanted}
    if gone:
        for github_id, login in gone.items():
            _call("DELETE", path + "/collaborators/" + login)
        status, pending = _call("GET", path + "/invitations")
        for invitation in pending if status == 200 and isinstance(pending, list) else ():
            invitee = (invitation.get("invitee") or {}).get("id")
            if str(invitee) in gone:
                _call("DELETE", path + "/invitations/%s" % invitation.get("id"))
    return kept


_lock = threading.Lock()


def sync(assignment, team_id, note="", sender=None, handin=False):
    """Commits what changed since the last copy. Returns the new commit's sha, or "" when
    the repository already holds the team's work. Raises Unavailable."""
    # ponytail: one lock for every team; a lock per team if syncs start queueing.
    with _lock:
        try:
            return _sync(assignment, team_id, note, sender, handin)
        except Unavailable as refused:
            if refused.status == 422:
                # The branch moved while we built on it: once more from the new head.
                return _sync(assignment, team_id, note, sender, handin)
            raise


def _sync(assignment, team_id, note, sender, handin):
    started = dt.datetime.now(dt.timezone.utc)
    files = repo_files(assignment, team_id)
    record = state.read_github_repo(assignment["id"], team_id)
    roster = state.team_roster(assignment["id"], team_id)
    if files is None or record is None or roster is None:
        raise Unavailable()
    links = state.github_links(roster)
    if links is None:
        raise Unavailable()
    repo = record.get("repo") or repo_name(assignment, team_id)
    path, branch, head, tree = _repo(repo)
    blobs = _blobs(path, tree)
    changed = sorted(p for p, text in files.items() if blobs.get(p) != blob_sha(text))
    invited = _collaborators(path, links, record.get("collaborators") or {})
    sha = ""
    # A hand-in is marked by a commit even when GitHub already had every file.
    if changed or handin:
        sha = _commit(assignment, team_id, path, branch, head, tree, blobs, files, changed,
                      record.get("synced_at"), note, sender, handin)
    if not state.write_github_repo(assignment["id"], team_id, repo, started, invited):
        raise Unavailable()
    return sha


def _commit(assignment, team_id, path, branch, head, tree, blobs, files, changed,
            since, note, sender, handin):
    authors = state.github_authors(team_id, teams.assignment_exercises(assignment), since)
    if authors is None:
        raise Unavailable()
    if sender:
        authors = [sender] + [a for a in authors if a != sender]
    known = state.github_links(authors)
    if known is None:
        raise Unavailable()
    linked = [known[a] for a in authors if a in known]
    stats = {p: _counts(_old_text(path, blobs.get(p)), files[p]) for p in changed}
    head_line = clean_message(note) or title(changed, assignment, handin, len(files))
    if changed:
        tree = _expect(_call("POST", path + "/git/trees", {
            "base_tree": tree,
            "tree": [{"path": p, "mode": "100644", "type": "blob", "content": files[p]}
                     for p in changed]}), 201).get("sha")
    body = {"message": message(head_line, stats, linked[1:]),
            "tree": tree, "parents": [head]}
    if linked:
        body["author"] = {"name": linked[0]["login"], "email": _noreply(linked[0])}
    created = _expect(_call("POST", path + "/git/commits", body), 201)
    _expect(_call("PATCH", path + "/git/refs/heads/" + urllib.parse.quote(branch),
                  {"sha": created.get("sha"), "force": False}), 200)
    return created.get("sha") or ""


# Logged on the transition only: an outage would otherwise log every team every minute.
_health = {"down": False}


def _failed(failure):
    if _health["down"]:
        return
    _health["down"] = True
    log.event("github.sync_failed", log.WARN,
              "a team's work could not be copied to GitHub, it is retried every minute",
              {"http.response.status_code": getattr(failure, "status", None)}, exc=failure)


def _restored():
    if _health["down"]:
        _health["down"] = False
        log.event("github.restored", log.INFO, "team work reaches GitHub again", {})


def guarded(assignment, team_id, handin=False, sender=None):
    """sync() for the background: never raises."""
    try:
        sync(assignment, team_id, sender=sender, handin=handin)
    except Exception as failure:
        _failed(failure)
    else:
        _restored()


def later(assignment, team_id, handin=False, sender=None):
    # A slow or unavailable GitHub must never delay a hand-in.
    threading.Thread(target=guarded, args=(assignment, team_id, handin, sender),
                     daemon=True).start()


def sweep():
    for assignment in teams.assignments():
        if not teams.is_team_assignment(assignment):
            continue
        pending = state.github_pending(assignment["id"],
                                       teams.assignment_exercises(assignment),
                                       config.GITHUB_IDLE * 60)
        for team_id in pending or ():
            guarded(assignment, team_id)


def _loop():
    while True:
        time.sleep(SWEEP_EVERY)
        try:
            sweep()
        except Exception as failure:
            _failed(failure)


def start():
    if enabled():
        threading.Thread(target=_loop, daemon=True, name="github-sync").start()


def _minute(value):
    try:
        return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except AttributeError:
        return ""


def view(assignment, team_id, sub):
    """What the team band shows; None when the feature is off."""
    if not enabled():
        return None
    link = state.github_link_of(sub) or {}
    record = state.read_github_repo(assignment["id"], team_id) or {}
    return {"client_id": config.GITHUB_CLIENT_ID, "login": link.get("login", ""),
            "repo_url": repo_url(record["repo"]) if record.get("repo") else "",
            "synced_at": _minute(record.get("synced_at")), "idle": config.GITHUB_IDLE}
