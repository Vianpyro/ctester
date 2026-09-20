#!/usr/bin/env python3

import asyncio
import contextlib
import io
import json
import pathlib
import re
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "worker"), os.path.join(ROOT, "app")]

os.environ.setdefault("CTESTER_ORIGINS",
                      "https://tch009.thevhome.com,https://vianpyro.github.io")

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover -- message, pas trace
    sys.exit("tests/test_api.py a besoin de httpx2 : pip install -r requirements-dev.txt")

import config      # noqa: E402
import deps        # noqa: E402
import state        # noqa: E402
import main        # noqa: E402
import security    # noqa: E402
import policy as policy  # noqa: E402
from services import collab  # noqa: E402
from services import forum_live  # noqa: E402
from services import quotas  # noqa: E402

KNOWN_ORIGIN = "https://tch009.thevhome.com"
UNKNOWN_ORIGIN = "https://mechant.example"

client = TestClient(main.app)


def _stateful_modules():
    return [m for m in list(sys.modules.values())
            if getattr(m, "state", None) is state]


class FakeDatabase:
    STATUSES = ("attempted", "solved")
    THEMES = ("light", "dark")
    enabled = staticmethod(lambda: True)

    EMPTY_PROFILE = {"display_name": None, "group_number": None,
                   "display_name_public": False, "group_number_public": False,
                   "alias": None, "plate_frame": None,
                   "badges_public": False, "leaderboard_opt_in": False}

    def __init__(self):
        self.drafts, self.states, self.themes = {}, {}, {}
        self.notepads = {}
        self.messages, self.profiles = [], {}
        self.practice, self.jobs = {}, set()
        self.events, self.xp, self.achievement = {}, {}, {}
        self.facts = []
        self.useful = {}
        self.retained = {}
        self.teams = {}
        self.team_meta = {}
        self.locks = {}
        self.documents = {}
        self.revisions = []
        self.handins = {}
        self.clock = 1000.0

    def read_resume(self, user, ex):
        return self.drafts.get((user, ex))

    def write_draft(self, user, ex, sources):
        self.drafts[(user, ex)] = sources
        return True

    def read_states(self, user):
        return [{"exercise_id": ex, "status": s}
                for (u, ex), s in self.states.items() if u == user]

    def write_state(self, user, ex, status, sources):
        self.states[(user, ex)] = status
        return True

    def read_scratch(self, user):
        return self.notepads.get(user, {"code": "", "header_name": "", "header": ""})

    def write_scratch(self, user, code, header_name="", header=""):
        self.notepads[user] = {"code": code, "header_name": header_name, "header": header}
        return True

    def read_theme(self, user):
        return self.themes.get(user, "")

    def write_theme(self, user, theme):
        self.themes[user] = theme
        return True

    def forget(self, user):
        for table in (self.drafts, self.states, self.themes, self.profiles):
            for key in [k for k in table if (k[0] if isinstance(k, tuple) else k) == user]:
                del table[key]
        self.messages = [m for m in self.messages if m["account"] != user]
        for key in [k for k in self.teams if k[1] == user]:
            del self.teams[key]
        self.revisions = [r for r in self.revisions if r["account"] != user]
        return True

    def register(self, assignment_id, team_id, accounts, group_number=4,
                 label=None, number=1):
        self.team_meta[(team_id, assignment_id)] = {
            "group_number": group_number, "number": number,
            "label": label or ("Équipe %d" % number)}
        for account in accounts:
            self.teams[(assignment_id, account)] = team_id

    def _meta(self, team_id, assignment_id):
        return self.team_meta.setdefault(
            (team_id, assignment_id),
            {"group_number": 4, "number": 1, "label": "Équipe 1"})

    def _members(self, assignment_id, team_id):
        return [account for (assignment, account), team in sorted(self.teams.items())
                if assignment == assignment_id and team == team_id]

    def team_of(self, user, assignment_id):
        team_id = self.teams.get((assignment_id, user))
        if team_id is None:
            return None
        meta = self._meta(team_id, assignment_id)
        return {"team_id": team_id, "assignment_id": assignment_id,
                "group_number": meta["group_number"], "number": meta["number"],
                "label": meta["label"]}

    def team_join(self, user, assignment_id, team_id, group_number, number,
                  label, max_size):
        if (assignment_id, user) in self.teams:
            return None
        if len(self._members(assignment_id, team_id)) >= max_size:
            return None
        self.team_meta.setdefault(
            (team_id, assignment_id),
            {"group_number": group_number, "number": number, "label": label})
        self.teams[(assignment_id, user)] = team_id
        return team_id

    def team_leave(self, user, assignment_id):
        self.teams.pop((assignment_id, user), None)
        return True

    def team_counts(self, assignment_id, group_number):
        lines = [{"number": meta["number"], "team_id": team_id,
                   "label": meta["label"],
                   "members": len(self._members(assignment, team_id))}
                  for (team_id, assignment), meta in self.team_meta.items()
                  if assignment == assignment_id
                  and meta["group_number"] == group_number]
        return sorted(lines, key=lambda line: line["number"])

    def team_memberships(self, user):
        lines = []
        for (assignment, account), team in sorted(self.teams.items()):
            if account != user:
                continue
            meta = self._meta(team, assignment)
            lines.append({"assignment_id": assignment, "team_id": team,
                           "group_number": meta["group_number"],
                           "number": meta["number"], "label": meta["label"]})
        return lines

    def team_roster(self, assignment_id, team_id):
        return self._members(assignment_id, team_id)

    def read_team_document(self, team_id, exercise_id):
        return dict(self.documents.get((team_id, exercise_id), {}))

    def write_team_document(self, team_id, exercise_id, user, sources,
                            revision_id, window):
        self.documents[(team_id, exercise_id)] = dict(sources)
        payload = json.dumps(sources)
        old = [r for r in self.revisions
                     if r["team_id"] == team_id and r["exercise_id"] == exercise_id]
        recent = any(r["account"] == user and r["at"] > self.clock - window
                      for r in old)
        identical = bool(old) and old[-1]["sources"] == payload
        if not recent and not identical:
            self.revisions.append({
                "revision_id": revision_id, "team_id": team_id,
                "exercise_id": exercise_id, "account": user,
                "sources": payload, "at": self.clock})
        return True

    def read_team_revisions(self, team_id, exercise_id, limit):
        lines = [r for r in self.revisions
                  if r["team_id"] == team_id and r["exercise_id"] == exercise_id]
        return [{"revision_id": r["revision_id"], "account": r["account"],
                 "created_at": "2026-09-07T14:0%d" % (i % 10),
                 "bytes": len(r["sources"])}
                for i, r in enumerate(reversed(lines))][:limit]

    def read_team_revision(self, team_id, revision_id):
        for r in self.revisions:
            if r["revision_id"] == revision_id and r["team_id"] == team_id:
                return json.loads(r["sources"])
        return {}

    def write_team_submission(self, assignment_id, team_id, user, files):
        self.handins[(assignment_id, team_id)] = {
            "submitted_by": user, "files": files,
            "submitted_at": "2026-09-07T15:00Z"}
        return True

    def read_team_submission(self, assignment_id, team_id):
        record = self.handins.get((assignment_id, team_id))
        if record is None:
            return {}
        return {"submitted_by": record["submitted_by"],
                "submitted_at": record["submitted_at"]}

    def read_teams(self, assignment_id):
        lines = []
        for (team_id, assignment), meta in sorted(self.team_meta.items()):
            if assignment != assignment_id:
                continue
            lines.append({"team_id": team_id,
                           "group_number": meta["group_number"],
                           "label": meta["label"],
                           "members": len(self.team_roster(assignment, team_id))})
        return lines

    def read_practice_summary(self, user):
        return [{"exercise_id": ex, "attempts": n, "successes": r}
                for (u, ex), (n, r) in self.practice.items() if u == user]

    def write_practice_attempt(self, user, job_id, ex, result):
        if job_id not in self.jobs:
            self.jobs.add(job_id)
            n, r = self.practice.get((user, ex), (0, 0))
            passed = (result.get("total", 0) > 0
                     and result.get("passed") == result.get("total"))
            self.practice[(user, ex)] = (n + 1, r + int(passed))
        return True

    def grant_first_solve(self, user, ex, event_id, amount, reason, policy,
                          payload, daily_cap):
        if (user, event_id) in self.events:
            return None
        self.events[(user, event_id)] = payload
        self.facts.append({"account": user, "type": "ExerciceReussi",
                           "exercise_id": ex, "payload": payload})
        already = sum(t["amount"] for (u, _), t in self.xp.items() if u == user)
        self.xp[(user, event_id)] = {
            "exercise_id": ex, "amount": max(min(amount, daily_cap - already), 0),
            "reason": reason, "granted_at": "2026-09-04"}
        return self.xp[(user, event_id)]["amount"]

    def record_event(self, user, event_id, kind, ex, policy, payload):
        if (user, event_id) in self.events:
            return None
        self.events[(user, event_id)] = payload
        self.facts.append({"account": user, "type": kind,
                           "exercise_id": ex, "payload": payload})
        return event_id

    def read_events(self, user, kind, limit=500):
        return [{"exercise_id": event["exercise_id"], "payload": event["payload"]}
                for event in reversed(self.facts)
                if event["account"] == user and event["type"] == kind][:limit]

    def unlock(self, user, ids, event_id, policy):
        for achievement_id in ids:
            self.achievement.setdefault((user, achievement_id),
                                   {"id": achievement_id, "unlocked_at": "2026-09-04",
                                    "policy": policy})
        return True

    def read_practice_days(self, user, days):
        n = sum(a for (u, _), (a, _) in self.practice.items() if u == user)
        return [{"date": "2026-09-04", "attempts": n}] if n else []

    def read_unlock_rates(self):
        account = {}
        for (_, achievement_id) in self.achievement:
            account[achievement_id] = account.get(achievement_id, 0) + 1
        return account, len({u for (u, _) in self.practice})

    def leaderboard_rows(self, group_number, days, staff=()):
        self._staff = set(staff or ())
        rows = []
        for account, profile in self.profiles.items():
            if not profile.get("leaderboard_opt_in"):
                continue
            if group_number is not None and profile.get("group_number") != group_number:
                continue
            if account in self._staff:
                continue
            n = sum(1 for (u, _) in self.xp if u == account)
            rows.append({"account": account, "alias": profile.get("alias"),
                         "group_number": profile.get("group_number"),
                         "recent": n, "lifetime": n})
        return rows

    def forum_taken_aliases(self):
        return {p["alias"] for p in self.profiles.values() if p.get("alias")}

    def read_progress(self, user):
        mien = lambda t: [v for (u, _), v in sorted(t.items()) if u == user]  # noqa: E731
        return {"xp": sum(t["amount"] for t in mien(self.xp)),
                "achievements": mien(self.achievement), "transactions": mien(self.xp)}

    def _message_view(self, m, reader):
        return dict(m, retained=self.retained.get(m["id"], False),
                    upvotes=sum(1 for (i, _), v in self.useful.items()
                                if i == m["id"] and v == 1),
                    downvotes=sum(1 for (i, _), v in self.useful.items()
                                  if i == m["id"] and v == -1),
                    my_vote=self.useful.get((m["id"], reader or ""), 0))

    def forum_thread(self, ex, limit, reader=None):
        roots = [m["id"] for m in self.messages
                   if m["exercise_id"] == ex and not m.get("reply_to")][-limit:]
        kept = set(roots)
        return [self._message_view(m, reader) for m in self.messages
                if m["exercise_id"] == ex
                and (m["id"] in kept or m.get("reply_to") in kept)]

    def forum_activity(self, reader, moderator, days):
        seen = {}
        for m in self.messages:
            if m["hidden"]:
                continue
            if not (moderator or (m.get("visibility") or "thread") == "thread"
                    or m["account"] == reader):
                continue
            key = m["exercise_id"]
            if m["created_at"] > seen.get(key, ""):
                seen[key] = m["created_at"]
        return seen

    def forum_thread_of(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["exercise_id"]
        return ""

    def forum_conversation(self, mid, reader=None):
        target = next((m for m in self.messages if m["id"] == mid), None)
        if target is None:
            return None, []
        root = target.get("reply_to") or target["id"]
        seen = [self._message_view(m, reader) for m in self.messages
               if m["id"] == root or m.get("reply_to") == root]
        return (target["exercise_id"], seen) if seen else (None, [])

    def forum_search(self, terms, reader, limit):
        terms = (terms or "").strip().lower()
        if not terms:
            return []
        hits = []
        for m in self.messages:
            if m["hidden"] or terms not in m["text"].lower():
                continue
            if (m.get("visibility") or "thread") != "thread" and m["account"] != reader:
                continue
            root = m.get("reply_to") or m["id"]
            hits.append({"id": m["id"], "exercise_id": m["exercise_id"],
                         "excerpt": m["text"][:240],
                         "created_at": m["created_at"],
                         "upvotes": sum(1 for (i, _), v in self.useful.items()
                                        if i == m["id"] and v == 1),
                         "replies": sum(1 for r in self.messages
                                        if r.get("reply_to") == root)})
        return hits[:limit]

    def forum_top(self, hours, limit):
        roots = [m for m in self.messages
                 if not m.get("reply_to") and not m["hidden"]]
        rows = [{"id": m["id"], "exercise_id": m["exercise_id"],
                 "text": m["text"], "created_at": m["created_at"],
                 "visibility": m.get("visibility") or "thread",
                 "step": m.get("step"), "blocked_kind": m.get("blocked_kind"),
                 "upvotes": sum(1 for (i, _), v in self.useful.items()
                                if i == m["id"] and v == 1),
                 "replies": sum(1 for r in self.messages
                                if r.get("reply_to") == m["id"])}
                for m in roots]
        return sorted(rows, key=lambda r: -r["upvotes"])[:limit]

    def forum_post(self, mid, ex, user, text, step=None, blocked_kind=None,
                   visibility="thread"):
        self.messages.append({"id": mid, "exercise_id": ex, "account": user,
                              "text": text, "hidden": False,
                              "step": step, "blocked_kind": blocked_kind,
                              "visibility": visibility, "reply_to": None,
                              "created_at": "2026-09-04"})
        return True

    def forum_reply(self, mid, ex, user, text, target):
        for m in self.messages:
            if m["id"] == target and m["exercise_id"] == ex:
                self.messages.append(
                    {"id": mid, "exercise_id": ex, "account": user,
                     "text": text, "hidden": False, "step": None,
                     "blocked_kind": None, "visibility": "thread",
                     "reply_to": m.get("reply_to") or m["id"],
                     "created_at": "2026-09-04"})
                return [mid]
        return []

    def forum_open_to_group(self, mid, user):
        for m in self.messages:
            if (m["id"] == mid and m["account"] == user
                    and m.get("visibility") == "private"):
                m["visibility"] = "group"
                return [mid]
        return []

    def forum_vote(self, mid, user, value):
        value = 1 if int(value) >= 0 else -1
        for m in self.messages:
            if (m["id"] == mid and m["account"] != user
                    and (value == 1 or m.get("reply_to"))):
                self.useful[(mid, user)] = value
                return [mid]
        return []

    def forum_unvote(self, mid, user):
        return [mid] if self.useful.pop((mid, user), None) is not None else []

    def forum_help_rows(self, limit, hours):
        groups = {}
        for m in self.messages:
            if not m.get("step") or m["hidden"]:
                continue
            key = (m["exercise_id"], m["step"], m.get("blocked_kind"))
            row = groups.setdefault(key, {"exercise_id": key[0], "step": key[1],
                                          "blocked_kind": key[2], "people": 0,
                                          "opened": 0, "since": m["created_at"],
                                          "accounts": set()})
            row["accounts"].add(m["account"])
            row["people"] = len(row["accounts"])
            row["opened"] += int(m.get("visibility") == "group")
        rows = [{k: v for k, v in row.items() if k != "accounts"}
               for row in groups.values()]
        return sorted(rows, key=lambda row: -row["people"])[:limit]

    def forum_delete(self, mid, user):
        before = len(self.messages)
        self.messages = [m for m in self.messages
                         if not (m["id"] == mid and m["account"] == user)]
        return len(self.messages) < before

    def forum_report(self, mid, user):
        return True

    def forum_report_name(self, mid, user):
        return True

    def forum_reports(self, limit):
        return []

    def forum_reported_names(self, limit):
        return []

    def forum_moderate(self, aid, mid, moderator, action):
        for m in self.messages:
            if m["id"] == mid:
                if action in ("retain", "unretain"):
                    self.retained[mid] = (action == "retain")
                else:
                    m["hidden"] = (action == "hide")
                return True
        return False

    def forum_author(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["account"]
        return None

    def forum_profile(self, user):
        return self.profiles.get(user, dict(self.EMPTY_PROFILE))

    def forum_profiles(self, users):
        return {u: self.profiles[u] for u in users if u in self.profiles}

    def forum_write_profile(self, pid, user, pseudo, group, pseudo_public,
                            public_group, set_by_moderator=False, alias=None,
                            plate_frame=None, badges_public=False,
                            leaderboard_opt_in=False):
        self.profiles[user] = {"display_name": pseudo, "group_number": group,
                              "display_name_public": pseudo_public,
                              "group_number_public": public_group,
                              "alias": alias, "plate_frame": plate_frame,
                              "badges_public": badges_public,
                              "leaderboard_opt_in": leaderboard_opt_in}
        return True


CONTENT = [
    ("tp2-ex3", "TP2 ex.3", "io", ["submission.c"], ["variables"], "foundation"),
    ("tp5-mod", "TP5 module", "unity", ["calendrier.h", "calendrier.c"],
     ["structs"], "intermediate"),
    ("quiz1", "Quiz 1", "quiz", [], ["variables"], "intro"),
    ("verif-tp2", "Vérification TP2", "quiz", [], ["variables"], "foundation"),
]


ASSIGNMENT = CONTENT + [
    ("dev-a", "Devoir : partie A", "io", ["main.c"], ["variables"], "advanced"),
    ("dev-b", "Devoir : partie B", "unity", ["lib.h", "lib.c"],
     ["variables"], "advanced"),
]


def _assignment_json(deadline=None, team=True):
    assignment = {"schema_version": 1, "id": "devoir", "title": "Le devoir",
              "description": "Trois ou quatre, une seule remise.",
              "items": ["dev-a", "dev-b"], "release": {"state": "available"},
              "handin": {"root": "Devoir", "files": [
                  {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
                  {"name": "matrac_lib.c", "exercise_id": "dev-b",
                   "file": "lib.c"}]}}
    if team:
        assignment["team"] = {"min": 3, "max": 4, "count": 6}
    if deadline:
        assignment["deadline"] = deadline
    return assignment


def _write_content(root, exercises=CONTENT, release=None, assignment=None):
    def write(path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)

    skill_names = sorted({c for _, _, _, _, skills, _ in exercises for c in skills})
    write(os.path.join(root, "catalog.json"),
           {"schema_version": 1, "skills": skill_names})
    for identifier, title, mode, files, skills, difficulty in exercises:
        directory = os.path.join(root, "exercises", identifier)
        write(os.path.join(directory, "exercise.json"),
               {"schema_version": 1, "id": identifier, "title": title,
                "skills": skills, "difficulty": difficulty,
                "verification": identifier.startswith("verif-"),
                "release": release or {"state": "available"}})
        with open(os.path.join(directory, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        assessment = os.path.join(directory, "assessment")
        if mode == "io":
            write(os.path.join(assessment, "io.json"),
                   {"cases": [{"stdin": "1\n", "expect": [1]}]})
        elif mode == "unity":
            write(os.path.join(assessment, "unity.json"), {})
            with open(os.path.join(assessment, "test_x.c"), "w",
                      encoding="utf-8") as fh:
                fh.write("void test_x(void) {}\n")
        else:
            write(os.path.join(assessment, "quiz.json"),
                   {"questions": [{"id": "q1", "type": "int", "text": "2+2 ?",
                                   "answer": 4}]})
        if files:
            write(os.path.join(directory, "public", "files.json"),
                   {"files": [{"name": name, "template": ""} for name in files]})
    if assignment is not None:
        write(os.path.join(root, "assignments", "devoir.json"), assignment)


def _publish(tmp, exercises=CONTENT, assignment=None):
    import content_catalog as content_catalogue
    import publish_content
    root = os.path.join(tmp, "content")
    published = os.path.join(tmp, "published")
    _write_content(root, exercises, assignment=assignment)
    publish_content.publish(content_catalogue.discover(root), published)
    return published


@contextlib.contextmanager
def context(*, tokens=None, moderators=(), forum_enabled=True, base=None,
             groups=(4, 6), exercises=CONTENT, assignment=None, console=True,
             bridge="", webhook=""):
    tmp = tempfile.mkdtemp()
    spool, page, results = (os.path.join(tmp, n) for n in ("spool", "web", "results"))
    for path in (spool, page, results):
        os.makedirs(path)
    published = _publish(tmp, exercises, assignment)

    fake = base if base is not None else FakeDatabase()
    modules = _stateful_modules()
    saved_state = [(m, m.state) for m in modules]
    saved_config = {n: getattr(config, n) for n in
                    ("PUBLISHED", "SPOOL", "RESULTS", "PAGE", "KEY", "OIDC_ISSUER",
                     "OIDC_CLIENT_ID", "FORUM_MODERATORS", "FORUM_GROUPS",
                     "SCRATCH", "DISCORD_BRIDGE_KEY", "DISCORD_WEBHOOK")}
    saved_security = (security.current_user, security.current_name)
    saved_quotas = (deps.quota, deps.signed_in_quota, deps.state_quota,
                    deps.forum_quota, deps.presence, deps.scratch_quota)

    for m in modules:
        m.state = fake
    config.SPOOL, config.PAGE, config.RESULTS = spool, page, results
    config.PUBLISHED = published
    config.KEY = "cle-de-session"
    config.OIDC_ISSUER = "https://auth.exemple.com"
    config.OIDC_CLIENT_ID = "ctester"
    config.FORUM_MODERATORS = frozenset(moderators) if forum_enabled else frozenset()
    config.FORUM_GROUPS = tuple(groups)
    config.SCRATCH = console
    config.DISCORD_BRIDGE_KEY = bridge
    config.DISCORD_WEBHOOK = webhook
    tokens = tokens or {}
    security.current_user = lambda headers: tokens.get(
        headers.get("Authorization", "").replace("Bearer ", ""))
    security.current_name = lambda headers: ""
    deps.quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.state_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.presence = quotas.Presence()
    deps.scratch_quota = quotas.Quota(cooldown=0, hourly=100000)

    try:
        yield TestClient(main.create_app()), fake, tmp
    finally:
        for m, previous in saved_state:
            m.state = previous
        for name, value in saved_config.items():
            setattr(config, name, value)
        security.current_user, security.current_name = saved_security
        (deps.quota, deps.signed_in_quota, deps.state_quota, deps.forum_quota,
         deps.presence, deps.scratch_quota) = saved_quotas
        shutil.rmtree(tmp, ignore_errors=True)


def _content_v2(root):
    def write(path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)

    write(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    for identifier, release in (("ouvert", {"state": "available"}),
                                 ("ferme", {"state": "scheduled",
                                            "available_from": "2099-01-01T00:00:00-05:00"})):
        exercise = os.path.join(root, "exercises", identifier)
        write(os.path.join(exercise, "exercise.json"),
               {"schema_version": 1, "id": identifier, "title": identifier.title(),
                "release": release})
        with open(os.path.join(exercise, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        write(os.path.join(exercise, "assessment", "io.json"),
               {"cases": [{"stdin": "1\\n", "expect": [1]}]})
        write(os.path.join(exercise, "public", "files.json"),
               {"files": [{"name": "submission.c", "template": ""}]})
    write(os.path.join(root, "collections", "tp1.json"),
           {"schema_version": 1, "id": "tp1", "title": "TP 1",
            "items": ["ouvert", "ferme"], "release": {"state": "available"}})


def test_release_drives_the_catalogue_and_closes_the_rest():
    import content_catalog as content_catalogue
    import publish_content

    with context() as (c, _, tmp):
        root, published = os.path.join(tmp, "v2"), os.path.join(tmp, "releases")
        _content_v2(root)
        publish_content.publish(content_catalogue.discover(root), published)
        config.PUBLISHED = published

        catalog = c.get("/catalog.json").json()
        states = {e["id"]: e["access"] for e in catalog["exercises"]}
        assert states == {"ouvert": "available", "ferme": "scheduled"}, states
        assert catalog["collections"][0]["items"] == ["ouvert", "ferme"]

        assert c.get("/exercise/ouvert.json").json()["statement"] == "Consigne."
        assert c.get("/exercise/ferme.json").status_code == 404

        body = {"key": config.KEY, "files": {"submission.c": "int main(void){}"}}
        assert c.post("/submit", json=dict(body, exercise_id="ferme")).status_code == 400
        assert c.post("/submit", json=dict(body, exercise_id="ouvert")).status_code == 200

        config.PUBLISHED = ""
        assert c.get("/catalog.json").status_code == 404
        assert c.get("/exercise/ouvert.json").status_code == 404
        assert c.post("/submit", json=dict(body, exercise_id="ouvert")).status_code == 400


def _content_typst(root, pages=2, open_and_closed=True):
    def write(path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)

    write(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": []})
    states = (("ouvert", {"state": "available"}),
             ("ferme", {"state": "scheduled",
                        "available_from": "2099-01-01T00:00:00-05:00"}))
    for identifier, release in (states if open_and_closed else states[:1]):
        exercise = os.path.join(root, "exercises", identifier)
        write(os.path.join(exercise, "exercise.json"),
               {"schema_version": 1, "id": identifier, "title": identifier.title(),
                "release": release})
        with open(os.path.join(exercise, "statement.typ"), "w", encoding="utf-8") as fh:
            fh.write("= Titre\n")
        write(os.path.join(exercise, "assessment", "io.json"),
               {"cases": [{"stdin": "1\n", "expect": [1]}]})
        write(os.path.join(exercise, "public", "files.json"),
               {"files": [{"name": "submission.c", "template": ""}]})
    write(os.path.join(root, "collections", "tp1.json"),
           {"schema_version": 1, "id": "tp1", "title": "TP 1",
            "items": [i for i, _ in (states if open_and_closed else states[:1])],
            "release": {"state": "available"}})


def _publish_typst(tmp, pages=2):
    import content_catalog as content_catalogue
    import publish_content

    root, published = os.path.join(tmp, "typ"), os.path.join(tmp, "typreleases")
    _content_typst(root)
    model = content_catalogue.discover(root)
    renders = {identifier: {theme: [("<svg id='%s-%s-%d'/>" % (identifier, theme, n)).encode()
                                    for n in range(1, pages + 1)]
                            for theme in ("dark", "light")}
              for identifier in model["exercises"]}
    publish_content.publish(model, published, renders=renders)
    config.PUBLISHED = published
    return published


def test_a_typst_statement_page_is_a_cacheable_file():
    with context() as (c, _, tmp):
        _publish_typst(tmp)

        r = c.get("/statement/ouvert/dark-1.svg")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/svg+xml", dict(r.headers)
        assert r.headers["cache-control"] == "no-cache", dict(r.headers)
        assert r.headers["etag"], dict(r.headers)
        assert r.content == b"<svg id='ouvert-dark-1'/>", r.content

        light = c.get("/statement/ouvert/light-1.svg")
        assert light.status_code == 200 and light.content != r.content
        assert light.headers["etag"] != r.headers["etag"], "two bodies, one ETag"

        assert c.get("/statement/ouvert/dark-2.svg").status_code == 200
        assert c.get("/statement/ouvert/dark-3.svg").status_code == 404

        detail = c.get("/exercise/ouvert.json").json()
        assert detail["statement"] == "", detail
        assert detail["statement_format"] == "typst", detail
        assert detail["statement_pages"] == 2, detail
        assert "statements/" not in json.dumps(detail), detail


def test_a_statement_page_refuses_anything_that_is_not_a_page():
    with context() as (c, _, tmp):
        _publish_typst(tmp)
        for name in ("dark-0.svg", "dark-17.svg", "sepia-1.svg", "dark-1.png",
                    "dark-1.svg.typ", "dark-1", "", "dark--1.svg",
                    "dark-01.svg", "DARK-1.svg",
                    "index.html", "statement.htm", "dark-1.html",
                    "..%2Fcatalog.json", "%2e%2e%2fcatalog.json",
                    "%2E%2E/catalog.json", "dark-1.svg%00.typ"):
            r = c.get("/statement/ouvert/" + name)
            assert r.status_code == 404, (name, r.status_code, r.text[:120])
        r = c.get("/statement/ouvert/../../catalog.json")
        assert str(r.url).endswith("/catalog.json"), str(r.url)
        assert c.get("/statement/inconnu/dark-1.svg").status_code == 404


def test_a_closed_statement_page_is_served_only_to_the_moderator():
    with context(tokens={"alice": "sub-alice", "prof": "sub-prof"},
                  moderators=["sub-prof"]) as (c, _, tmp):
        _publish_typst(tmp)

        assert c.get("/statement/ferme/dark-1.svg").status_code == 404
        assert c.get("/statement/ferme/dark-1.svg",
                     headers=auth("alice")).status_code == 404
        r = c.get("/statement/ferme/dark-1.svg", headers=auth("prof"))
        assert r.status_code == 200, r.text
        assert r.content == b"<svg id='ferme-dark-1'/>", r.content
        assert r.headers["cache-control"] == "no-store", dict(r.headers)
        assert "etag" not in r.headers, dict(r.headers)

        page = c.get("/statement/ouvert/dark-1.svg", headers=auth("prof"))
        assert page.headers["cache-control"] == "no-cache", dict(page.headers)
        assert page.headers["etag"], dict(page.headers)


def test_a_markdown_statement_answers_exactly_what_it_did_before():
    with context() as (c, _, tmp):
        root, published = os.path.join(tmp, "md"), os.path.join(tmp, "mdreleases")
        import content_catalog as content_catalogue
        import publish_content
        _content_v2(root)
        publish_content.publish(content_catalogue.discover(root), published)
        config.PUBLISHED = published

        detail = c.get("/exercise/ouvert.json").json()
        assert detail == {"statement": "Consigne.",
                          "files": [{"name": "submission.c", "template": ""}]}, detail
        assert c.get("/statement/ouvert/dark-1.svg").status_code == 404


def test_the_csp_allows_api_images_and_blobs():
    with context() as (c, _, tmp):
        config.PAGE = os.path.join(tmp, "web")
        with open(os.path.join(config.PAGE, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head></head><body></body></html>")
        r = c.get("/")
        csp_header = r.headers["content-security-policy"]
        directives = {d.split()[0]: d.split()[1:] for d in csp_header.split("; ")}
        assert "'self'" in directives["img-src"], csp_header
        assert "blob:" in directives["img-src"], csp_header
        assert config.API_ORIGIN in directives["img-src"], csp_header
        assert "data:" not in directives["img-src"], csp_header
        assert "*" not in directives["img-src"], csp_header


def test_dates_apply_to_students_and_the_teacher_still_sees():
    import content_catalog as content_catalogue
    import publish_content

    with context(tokens={"alice": "sub-alice", "prof": "sub-prof"},
                  moderators=["sub-prof"]) as (c, base, tmp):
        root, published = os.path.join(tmp, "v2"), os.path.join(tmp, "releases")
        _content_v2(root)
        publish_content.publish(content_catalogue.discover(root), published)
        config.PUBLISHED = published

        assert c.get("/exercise/ferme.json").status_code == 404
        assert c.get("/exercise/ferme.json", headers=auth("alice")).status_code == 404
        r = c.get("/exercise/ferme.json", headers=auth("prof"))
        assert r.status_code == 200 and r.json()["statement"] == "Consigne.", r.text
        assert r.headers["cache-control"] == "no-store", dict(r.headers)
        assert "etag" not in r.headers, dict(r.headers)

        opened = c.get("/exercise/ouvert.json", headers=auth("prof"))
        assert opened.headers["cache-control"] == "no-cache", dict(opened.headers)
        assert opened.headers["etag"], dict(opened.headers)

        body = {"key": config.KEY, "files": {"submission.c": "int main(void){}"},
                 "exercise_id": "ferme"}
        assert c.post("/submit", json=body).status_code == 400
        assert c.post("/submit", json=body, headers=auth("alice")).status_code == 400
        r = c.post("/submit", json=body, headers=auth("prof"))
        assert r.status_code == 200, r.text
        job = r.json()["id"]
        with open(os.path.join(config.SPOOL, job, "job.json"), encoding="utf-8") as fh:
            assert json.load(fh) == {"exercise_id": "ferme", "owner": "sub-prof"}

        with open(_output(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        assert c.get("/r/" + job).json()["status"] == "ok"
        assert base.states[("sub-prof", "ferme")] == "solved", base.states

        draft = {"exercise_id": "ferme", "files": {"submission.c": "int main(void){}"}}
        assert c.put("/draft", json=draft,
                     headers=auth("alice")).status_code == 400
        assert c.put("/draft", json=draft,
                     headers=auth("prof")).status_code == 200

        assert c.get("/states", headers=auth("prof")).json()["moderator"] is True
        assert c.get("/states", headers=auth("alice")).json()["moderator"] is False


def auth(name):
    return {"Authorization": "Bearer " + name}


def test_healthz_touches_neither_database_nor_spool():
    r = client.get("/healthz")
    assert r.status_code == 200, r.status_code
    assert r.json() == {"ok": True}, r.json()


def test_cors_known_and_unknown_origin():
    r = client.get("/healthz", headers={"Origin": KNOWN_ORIGIN})
    assert r.headers.get("access-control-allow-origin") == KNOWN_ORIGIN, dict(r.headers)

    r = client.get("/healthz", headers={"Origin": UNKNOWN_ORIGIN})
    assert r.status_code == 200, r.status_code
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)

    assert "access-control-allow-credentials" not in r.headers

    r = client.get("/healthz", headers={"Origin": KNOWN_ORIGIN + "/"})
    assert r.headers.get("access-control-allow-origin") == KNOWN_ORIGIN, dict(r.headers)


def test_a_single_vary_announcing_both_axes():
    r = client.get("/healthz", headers={"Origin": KNOWN_ORIGIN})
    vary = r.headers.get("vary", "")
    assert vary == "Accept-Encoding, Origin", vary
    assert vary.count("Origin") == 1 and vary.count("Accept-Encoding") == 1, vary


def test_preflight_on_every_route_even_unknown():
    for path in ("/submit", "/forum", "/pas-encore-invente"):
        r = client.options(path, headers={"Origin": KNOWN_ORIGIN})
        assert r.status_code == 204, (path, r.status_code)
        methods = r.headers.get("access-control-allow-methods", "")
        assert "DELETE" in methods, methods
        assert r.headers.get("access-control-max-age") == "86400", dict(r.headers)
        assert r.headers.get("access-control-allow-origin") == KNOWN_ORIGIN

    r = client.options("/submit", headers={"Origin": UNKNOWN_ORIGIN})
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)


def test_unknown_path_stays_a_404():
    r = client.get("/pas-une-route")
    assert r.status_code == 404, r.status_code
    assert r.json() == {"error": "inconnu"}, r.json()


def test_automatic_documentation_is_off():
    assert not config.DOCS, "CTESTER_DOCS must not be set in production"
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_no_store_by_default_on_data():
    assert client.get("/healthz").headers.get("cache-control") == "no-store"
    assert client.get("/rien").headers.get("cache-control") == "no-store"
    with context() as (c, _, _tmp):
        assert c.get("/catalog.json").headers.get("cache-control") == "no-cache"
        assert c.get("/oidc.json").headers.get("cache-control") == "no-store"


def test_no_server_version_announcement():
    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert "server_header=False" in source
    assert "workers=1" in source


def test_body_limit_on_both_sides():
    cap = config.MAX_CODE + 4096
    with context() as (c, _, _tmp):
        body = b'{"exercise_id": "tp2-ex3", "key": "x", "bourrage": "'
        body += b"a" * (cap - len(body) - 2) + b'"}'
        assert len(body) == cap
        r = c.post("/submit", content=body,
                   headers={"Content-Type": "application/json"})
        assert r.status_code != 413, (r.status_code, r.text)

        r = c.post("/submit", content=body + b" ",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, r.status_code
        assert r.json() == {"error": "corps trop gros ou vide"}, r.json()


def test_empty_body_or_no_declared_length():
    with context() as (c, _, _tmp):
        r = c.post("/submit", content=b"",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)

        def flux():
            yield b'{"exercise_id": "tp2-ex3"}'

        r = c.post("/submit", content=flux(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)


def test_a_malformed_body_does_not_echo_the_input():
    with context() as (c, _, _tmp):
        secret = "MonMotDePasseColleParErreur"
        r = c.post("/submit", content=json.dumps([secret]).encode(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json() == {"error": "requête malformée"}, r.json()
        assert secret not in r.text, r.text


def test_key_checked_before_any_other_work():
    with context() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "mauvaise", "exercise_id": "nexiste-pas"})
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "nexiste-pas"})
        assert r.status_code == 400, (r.status_code, r.text)


def test_an_empty_server_key_refuses_everything():
    with context() as (c, _, _tmp):
        config.KEY = ""
        r = c.post("/submit", json={"key": "", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "int main(){}"}})
        assert r.status_code == 403, (r.status_code, r.text)


def test_file_size_on_both_sides():
    with context() as (c, _, _tmp):
        from services import catalog as catalogue
        entry = catalogue.find_exercise("tp2-ex3")
        envelope = len(json.dumps({"submission.c": ""}).encode())
        pile = "a" * (config.MAX_CODE - envelope)
        files, message, code = catalogue.validate_files(
            entry, {"submission.c": pile})
        assert message is None, message
        assert len(json.dumps(files).encode()) == config.MAX_CODE

        _, message, code = catalogue.validate_files(
            entry, {"submission.c": pile + "a"})
        assert code == 413 and message, (code, message)

        _, message, code = catalogue.validate_files(entry, ["pas", "un", "dict"])
        assert code == 400 and message == "fichiers manquants", (code, message)


def test_an_unexpected_file_is_refused_not_ignored():
    with context() as (c, _, _tmp):
        r = c.post("/submit", json={
            "key": "cle-de-session", "exercise_id": "tp5-mod",
            "files": {"calendrier.h": "x", "calendrier.c": "y",
                      "secret.c": "z"}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert "secret.c" in r.json()["error"], r.json()


def test_an_entirely_blank_submission_is_refused():
    with context() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "   \n\t  "}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json()["error"] == "soumission vide", r.json()


def test_quiz_bounds_the_number_and_length_of_answers():
    with context() as (c, _, tmp):
        answers = {"q%d" % i: "x" for i in range(600)}
        answers["k" * 100] = "v" * 400
        answers["liste"] = ["item " * 100] * 60
        answers["paires"] = {"p%d" % i: "long " * 100 for i in range(60)}
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": answers})
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()["id"]
        with open(os.path.join(config.SPOOL, job, "answers.json"),
                  encoding="utf-8") as fh:
            written = json.load(fh)
        assert len(written) <= 500, len(written)
        for key, value in written.items():
            assert len(key) <= 64, key
            if isinstance(value, list):
                assert len(value) <= 40 and all(len(one) <= 256 for one in value)
            elif isinstance(value, dict):
                assert len(value) <= 40
                assert all(len(k) <= 256 and len(v) <= 256 for k, v in value.items())
            else:
                assert len(value) <= 256, value


def test_quiz_keeps_a_structured_answer_whole_but_flattens_anything_deeper():
    with context() as (c, _, tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {"ordre": ["b", "a"],
                                                "paires": {"malloc": "réserve"},
                                                "trous": ["0", "<"],
                                                "profond": [{"x": 1}]}})
        assert r.status_code == 200, r.text
        with open(os.path.join(config.SPOOL, r.json()["id"], "answers.json"),
                  encoding="utf-8") as fh:
            written = json.load(fh)
        assert written["ordre"] == ["b", "a"]
        assert written["paires"] == {"malloc": "réserve"}
        assert written["trous"] == ["0", "<"]
        # One level only: the worker is never handed a shape it has not been told to expect.
        assert written["profond"] == ["{'x': 1}"]


def test_quiz_refuses_a_payload_too_long_to_be_a_quiz():
    with context() as (c, _, _tmp):
        # Big enough to pass the answers cap, small enough to pass the request-body one.
        flood = {"q%d" % i: ["x" * 20] * 40 for i in range(30)}
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": flood})
        assert r.status_code == 413, (r.status_code, r.text)
        assert "trop longues" in r.json()["error"]


def test_quiz_with_no_answer_entered():
    with context() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {"q1": "  ", "q2": ""}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1"})
        assert r.status_code == 400 and r.json() == {"error": "réponses manquantes"}, r.text


def test_malformed_exercise_id():
    from services import catalog as catalogue
    with context() as (c, _, _tmp):
        assert catalogue.find_exercise("a" * 32) is None
        for hostile in ("../tps", "tp2/../../etc", "TP2-EX3", "tp2 ex3", ""):
            assert catalogue.find_exercise(hostile) is None, hostile
        assert c.get("/exercise/..%2Fcatalog.json").status_code == 404
        assert c.get("/quiz/tp2-ex3.json").status_code == 404
        base, name = catalogue.published_source(
            catalogue.find_exercise("tp2-ex3"), "detail")
        assert base == catalogue.release_dir()
        assert name == os.path.join("exercises", "tp2-ex3.json"), name


def test_hourly_quota_exactly_and_one_too_many():
    with context() as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=3)
        payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        for i in range(3):
            assert c.post("/submit", json=payload).status_code == 200, i
        r = c.post("/submit", json=payload)
        assert r.status_code == 429, (r.status_code, r.text)
        assert r.json()["retry_after"] > 0, r.json()


def test_quota_per_account_not_per_ip_behind_a_nat():
    with context(tokens={"alice": "sub-alice", "bob": "sub-bob"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=1)
        deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=1)
        payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for name in ("alice", "bob"):
            r = c.post("/submit", json=payload, headers={**auth(name), **nat})
            assert r.status_code == 200, (name, r.status_code, r.text)
        r = c.post("/submit", json=payload, headers={**auth("alice"), **nat})
        assert r.status_code == 429, r.status_code
        assert c.post("/submit", json=payload, headers=nat).status_code == 200


def test_anonymous_quota_per_station_and_shorter_window_when_logged_in():
    with context(tokens={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=30, hourly=100)
        deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=100)
        payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for station in ("p1", "p2"):
            r = c.post("/submit?station=" + station, json=payload, headers=nat)
            assert r.status_code == 200, (station, r.status_code, r.text)
        assert c.post("/submit?station=p1", json=payload, headers=nat).status_code == 429
        assert c.post("/submit?station=p3", json=payload, headers=nat).status_code == 200
        assert c.post("/submit", json=payload, headers=nat).status_code == 200
        assert c.post("/submit", json=payload, headers=nat).status_code == 429
        for _ in range(3):
            r = c.post("/submit?station=p1", json=payload,
                       headers={**auth("alice"), **nat})
            assert r.status_code == 200, (r.status_code, r.text)


def test_an_anonymous_job_carries_a_station_tag_and_a_signed_in_one_does_not():
    with context(tokens={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=100)
        deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=100)
        payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                   "files": {"submission.c": "int main(){return 0;}"}}

        def job(query, headers=None):
            r = c.post("/submit" + query, json=payload, headers=headers or {})
            assert r.status_code == 200, (r.status_code, r.text)
            with open(os.path.join(config.SPOOL, r.json()["id"], "job.json"),
                      encoding="utf-8") as fh:
                return json.load(fh)

        first, again, other = job("?station=p1"), job("?station=p1"), job("?station=p2")
        assert first["station"] == again["station"] == security.station_tag("p1")
        assert other["station"] != first["station"]
        assert "p1" not in json.dumps(first), "the raw station id must not be stored"
        assert "station" not in job("")
        signed_in = job("?station=p1", auth("alice"))
        assert signed_in == {"exercise_id": "tp2-ex3", "owner": "sub-alice"}


def test_quota_consumes_nothing_on_a_refused_request():
    with context(tokens={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.state_quota = quotas.Quota(cooldown=0, hourly=2)
        for _ in range(5):
            r = c.put("/draft", json={"exercise_id": "inconnu", "files": {}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.status_code
        for _ in range(2):
            r = c.put("/draft",
                      json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 200, (r.status_code, r.text)
        r = c.put("/draft",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 429, (r.status_code, r.text)


def test_queue_full_exactly_at_the_cap():
    with context() as (c, _, _tmp):
        saved = config.QUEUE_MAX
        try:
            config.QUEUE_MAX = 2
            payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            assert c.post("/submit", json=payload).status_code == 200
            assert c.post("/submit", json=payload).status_code == 200
            r = c.post("/submit", json=payload)
            assert r.status_code == 503, (r.status_code, r.text)
        finally:
            config.QUEUE_MAX = saved


def test_presence_expires_exactly_at_the_ttl():
    p = quotas.Presence()
    assert p.touch("a", 1000.0) == 1
    assert p.touch("a", 1000.0) == 1, "the same token does not count twice"
    assert p.touch("b", 1000.0) == 2
    assert p.touch("c", 1000.0 + config.PRESENCE_TTL) == 1
    q = quotas.Presence()
    q.touch("a", 1000.0)
    assert q.touch("c", 1000.0 + config.PRESENCE_TTL - 1) == 2


def test_live_truncates_a_too_long_token_instead_of_refusing():
    with context() as (c, _, _tmp):
        r = c.get("/live?id=" + "z" * 500)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["n"] == 1, r.json()


def test_a_window_cannot_open_someone_elses_presence():
    # The window id refines its caller's key instead of replacing it, or anyone could
    # count under the name ctester-pull reads to decide the host is calm.
    with context() as (c, _, _tmp):
        first = c.get("/live?id=ctester-pull",
                        headers={"CF-Connecting-IP": "203.0.113.1"})
        second = c.get("/live?id=ctester-pull",
                       headers={"CF-Connecting-IP": "203.0.113.2"})
        assert first.json()["n"] == 1, first.json()
        assert second.json()["n"] == 2, second.json()


def test_refusal_order_forum_off_before_missing_token():
    with context(forum_enabled=False) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 503, (r.status_code, r.text)
        assert "discussions" in r.json()["error"], r.json()
    with context(moderators=["sub-prof"]) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 401, (r.status_code, r.text)


def test_forum_activity_only_reports_visible_threads():
    tokens = {"prof": "sub-prof", "alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _, _tmp):
        assert c.get("/forum/activity").status_code == 401
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "salut"},
               headers=auth("alice"))
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "je bloque",
                                   "step": "compilation", "visibility": "private"},
                   headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)

        threads = c.get("/forum/activity", headers=auth("alice")).json()["threads"]
        assert set(threads) == {"@chat:general", "tp2-ex3"}, threads

        # Alice's private thread lights nothing up for Bob, but the teacher sees it.
        assert set(c.get("/forum/activity",
                         headers=auth("bob")).json()["threads"]) == {"@chat:general"}
        assert "tp2-ex3" in c.get("/forum/activity",
                                  headers=auth("prof")).json()["threads"]


def test_moderation_role_recomputed_and_never_received():
    tokens = {"prof": "sub-prof", "alice": "sub-alice"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _, _tmp):
        assert c.get("/forum/moderation", headers=auth("prof")).status_code == 200
        r = c.get("/forum/moderation", headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/forum/moderation",
                   json={"id": "0" * 32, "action": "hide",
                         "moderateur": True, "account": "sub-prof"},
                   headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)


def test_no_route_accepts_an_identity_in_the_body():
    import schemas
    forbidden = {"account", "sub", "owner", "user", "moderateur",
                 "set_by_moderator"}
    for name in dir(schemas):
        model = getattr(schemas, name)
        champs = getattr(model, "model_fields", None)
        if champs:
            leak = forbidden & set(champs)
            assert not leak, (name, leak)

    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens) as (c, base, _tmp):
        r = c.put("/draft",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "a moi"},
                        "account": "sub-bob", "sub": "sub-bob"},
                  headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert base.drafts == {("sub-alice", "tp2-ex3"):
                                   {"submission.c": "a moi"}}, base.drafts


def test_no_sub_crosses_the_forum_boundary():
    tokens = {"prof": "sub-prof", "alice": "sub-alice"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, base, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "une question"},
               headers=auth("alice"))
        c.post("/forum/profile",
               json={"display_name": "Alice", "group_number": 4, "display_name_public": True,
                     "group_number_public": True}, headers=auth("alice"))
        r = c.get("/forum?ex=tp2-ex3", headers=auth("prof"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert "sub-alice" not in r.text and "sub-prof" not in r.text, r.text
        assert "Alice" in r.text, r.text


def test_forum_text_on_both_sides_of_the_limit():
    from services import forum
    assert forum.forum_text("")[0] is None
    assert forum.forum_text("   \n ")[0] is None
    assert forum.forum_text("a")[0] == "a"
    assert forum.forum_text("a" * config.FORUM_MAX_CHARS)[0] is not None
    too_many, message = forum.forum_text("a" * (config.FORUM_MAX_CHARS + 1))
    assert too_many is None and str(config.FORUM_MAX_CHARS) in message, message


def test_forum_pseudonym_bounds_and_reserved_names():
    from services import forum
    assert forum.forum_display_name("a")[0] == "a"
    assert forum.forum_display_name("a" * config.FORUM_PSEUDO_MAX)[0] is not None
    assert forum.forum_display_name("a" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    for reserved in ("Vous", "PARTICIPANT", "Enseignant", "Équipe du cours",
                    "modérateur"):
        name, message = forum.forum_display_name(reserved)
        assert name is None and message, reserved


def test_forum_group_closed_list_and_free_field():
    from services import forum
    with context(groups=(4, 6)) as (_c, _b, _tmp):
        assert forum.forum_group(4)[0] == 4
        assert forum.forum_group("6")[0] == 6
        assert forum.forum_group(5)[0] is None
        assert forum.forum_group(0)[0] is None
    with context(groups=()) as (_c, _b, _tmp):
        assert forum.forum_group(1)[0] == 1
        assert forum.forum_group(99)[0] == 99
        assert forum.forum_group(0)[0] is None
        assert forum.forum_group(100)[0] is None
        assert forum.forum_group("douze")[0] is None


def test_malformed_message_and_job_ids():
    from routers.forum import MSG_RE
    from routers.submission import JOB_RE
    for pattern in (MSG_RE, JOB_RE):
        assert pattern.match("0" * 32)
        assert not pattern.match("0" * 31)
        assert not pattern.match("0" * 33)
        assert not pattern.match("A" * 32)
        assert not pattern.match("0" * 31 + "g")
    with context() as (c, _, _tmp):
        assert c.get("/r/pas-un-id").status_code == 400
        assert c.get("/r/" + "0" * 32).status_code == 404


def test_opting_in_without_writing_shows_nothing():
    with context(tokens={"alice": "sub-alice"},
                  moderators=["sub-prof"]) as (c, base, _tmp):
        r = c.post("/forum/profile",
                   json={"display_name": "", "group_number": None, "display_name_public": True,
                         "group_number_public": True}, headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        profile = base.profiles["sub-alice"]
        assert profile["display_name_public"] is False, profile
        assert profile["group_number_public"] is False, profile


def test_a_silent_database_never_becomes_a_zero():
    base = FakeDatabase()
    base.read_progress = lambda user: None
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progress", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "xp" not in r.text, r.text


def test_an_empty_theme_is_a_200_and_an_outage_a_503():
    with context(tokens={"alice": "sub-alice"}) as (c, _, _tmp):
        r = c.get("/preferences", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"theme": ""}, r.text
    base = FakeDatabase()
    base.read_theme = lambda user: None
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        assert c.get("/preferences", headers=auth("alice")).status_code == 503


def test_a_failed_write_does_not_answer_200():
    base = FakeDatabase()
    base.write_theme = lambda user, theme: False
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)


def test_write_preferences_succeeds_and_says_so():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert base.themes["sub-alice"] == "dark", base.themes


def test_an_unknown_theme_is_refused():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        for bad in ("", "sepia", "DARK", "light; DROP TABLE"):
            r = c.put("/preferences", json={"theme": bad},
                      headers=auth("alice"))
            assert r.status_code == 400, (bad, r.status_code)
        assert not base.themes, base.themes


def test_release_dir_and_load_catalog_survive_a_broken_pointer():
    from services import catalog as catalogue
    guard = config.PUBLISHED
    tmp = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        config.PUBLISHED = tmp
        assert catalogue.release_dir() is None
        assert catalogue.load_catalog() is None
        assert catalogue.published_source({"id": "x"}, "detail") == (None, None)

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            fh.write("{ this is not JSON")
        assert catalogue.release_dir() is None

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert catalogue.release_dir() is None

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "../../etc"}, fh)
        assert catalogue.release_dir() is None

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "0123456789abcdef"}, fh)
        assert catalogue.release_dir() is None

        os.makedirs(os.path.join(tmp, "0123456789abcdef"))
        assert catalogue.release_dir() == os.path.join(tmp, "0123456789abcdef")
        assert catalogue.load_catalog() is None
        with open(os.path.join(tmp, "0123456789abcdef", "catalog.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        assert catalogue.load_catalog() is None
    finally:
        config.PUBLISHED = guard
        shutil.rmtree(tmp)


def test_quiz_json_serves_the_published_quiz():
    with context() as (c, _base, _tmp):
        r = c.get("/quiz/quiz1.json")
        assert r.status_code == 200, r.text
        assert r.json()["questions"][0]["id"] == "q1", r.json()
        assert "answer" not in r.text, r.text


def test_detail_and_quiz_survive_a_rollback_mid_request():
    import routers.catalog as catalog_router
    guard = catalog_router.published_source
    try:
        with context() as (c, _base, _tmp):
            catalog_router.published_source = lambda entry, what: (None, None)
            r = c.get("/exercise/tp2-ex3.json")
            assert r.status_code == 404 and r.json() == {"error": "inconnu"}, r.text
            r = c.get("/quiz/quiz1.json")
            assert r.status_code == 404 and r.json() == {"error": "pas un quiz"}, r.text
    finally:
        catalog_router.published_source = guard


def test_states_and_practice_during_a_database_outage():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        assert c.get("/states", headers=auth("alice")).json() == {
            "states": [], "moderator": False}
        assert c.get("/practice", headers=auth("alice")).json() == {"practice": []}
        base.states[("sub-alice", "tp2-ex3")] = "solved"
        r = c.get("/states", headers=auth("alice"))
        assert r.json() == {"states": [{"exercise_id": "tp2-ex3", "status": "solved"}],
                            "moderator": False}, r.text

    base = FakeDatabase()
    base.read_states = lambda user: None
    base.read_practice_summary = lambda user: None
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        assert c.get("/states", headers=auth("alice")).status_code == 503
        assert c.get("/practice", headers=auth("alice")).status_code == 503


def test_read_draft_refuses_an_unknown_exercise_and_distinguishes_absence():
    with context(tokens={"alice": "sub-alice"}) as (c, _base, _tmp):
        r = c.get("/draft?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.get("/draft?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"sources": None}, r.text

        c.put("/draft", json={"exercise_id": "tp2-ex3", "files": {"submission.c": "int x;"}},
              headers=auth("alice"))
        r = c.get("/draft?ex=tp2-ex3", headers=auth("alice"))
        assert r.json() == {"sources": {"submission.c": "int x;"}}, r.text


def test_the_draft_is_stored_in_its_canonical_form():
    with context(tokens={"alice": "sub-alice"}) as (c, _base, _tmp):
        c.put("/draft",
              json={"exercise_id": "tp2-ex3",
                    "files": {"submission.c": "\ufeffint main(void){\r\n"
                                              "    return 0;   \r\n}\r\n\r\n"}},
              headers=auth("alice"))
        r = c.get("/draft?ex=tp2-ex3", headers=auth("alice"))
        saved = r.json()["sources"]["submission.c"]
        assert saved == "int main(void){\n    return 0;\n}\n\n", repr(saved)
        assert saved.count("\n") == 4, repr(saved)


def test_write_draft_refuses_a_file_outside_the_allow_list_before_the_quota():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        for _ in range(5):
            r = c.put("/draft",
                      json={"exercise_id": "tp2-ex3", "files": {"hack.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.text
            assert "fichier inattendu" in r.json()["error"], r.text
        assert not base.drafts
        r = c.put("/draft",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 200, r.text


def test_write_draft_during_a_database_outage():
    base = FakeDatabase()
    base.write_draft = lambda *a: False
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.put("/draft",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_deleting_the_account_fails_without_leaving_the_illusion_of_success():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        base.states[("sub-alice", "tp2-ex3")] = "solved"
        r = c.delete("/account", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert c.get("/states", headers=auth("alice")).json() == {
            "states": [], "moderator": False}

    base = FakeDatabase()
    base.forget = lambda user: False
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.delete("/account", headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_gzip_exactly_at_the_1024_byte_threshold():
    with context() as (c, _, _tmp):
        import headers as h

        class FakeRequest:
            def __init__(self, headers):
                self.headers = headers

        gzip_ok = FakeRequest({"accept-encoding": "gzip"})
        petit = h.file_response(gzip_ok, b"a" * 1023, "application/json")
        gros = h.file_response(gzip_ok, b"a" * 1024, "application/json")
        assert "content-encoding" not in petit.headers, dict(petit.headers)
        assert gros.headers["content-encoding"] == "gzip", dict(gros.headers)
        assert not petit.headers["etag"].endswith('-gz"')
        assert gros.headers["etag"].endswith('-gz"')
        nu = h.file_response(FakeRequest({}), b"a" * 1024, "application/json")
        assert nu.headers["etag"] != gros.headers["etag"]


def test_file_from_disk_responds_500_when_the_file_is_missing():
    import headers as h

    class FakeRequest:
        headers = {}

    r = h.file_from_disk(FakeRequest(), "/path/that/does/not/exist",
                         "missing.json", "application/json")
    assert r.status_code == 500 and json.loads(r.body) == {"error": "fichier manquant"}


def test_the_middleware_ignores_non_http_scopes():
    with TestClient(main.app):
        pass


def test_int_falls_back_to_the_default_when_the_variable_is_unreadable():
    os.environ["CTESTER_TEST_ENTIER_INVALIDE"] = "not-a-number"
    try:
        assert config._int("CTESTER_TEST_ENTIER_INVALIDE", "42") == 42
    finally:
        del os.environ["CTESTER_TEST_ENTIER_INVALIDE"]


def test_304_keeps_the_csp_and_the_cache_headers():
    page = os.path.join(ROOT, "web")
    if not os.path.isdir(page):
        return
    with context() as (c, _, _tmp):
        config.PAGE = page
        c2 = TestClient(main.create_app())
        r = c2.get("/")
        assert r.status_code == 200, r.status_code
        assert "content-security-policy" in r.headers, dict(r.headers)
        label = r.headers["etag"]
        r2 = c2.get("/", headers={"If-None-Match": label})
        assert r2.status_code == 304, r2.status_code
        assert r2.headers.get("content-security-policy"), dict(r2.headers)
        assert r2.headers.get("cache-control") == "no-cache", dict(r2.headers)
        assert r2.content == b"", r2.content


def test_page_serves_a_root_file_from_the_closed_list():
    with context() as (c, _, _tmp):
        with open(os.path.join(config.PAGE, "theme.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("/* the theme before the first paint */")
        c2 = TestClient(main.create_app())
        r = c2.get("/theme.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")


def test_page_serves_a_closed_list_not_a_directory():
    from routers import page as router_page
    with context() as (c, _, tmp):
        del tmp
        active = os.path.join(config.PAGE, "assets")
        os.makedirs(active)
        with open(os.path.join(config.PAGE, "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("pas pour toi")
        with open(os.path.join(active, "index-abc123.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("export default 1;")
        c2 = TestClient(main.create_app())
        assert c2.get("/secret.txt").status_code == 404
        assert c2.get("/../app/catalog.json").status_code in (404, 400)
        assert "secret.txt" not in router_page.SERVED
        r = c2.get("/assets/index-abc123.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")
        for path in ("/assets/absent-000000.js", "/assets/secret.txt",
                       "/assets/../secret.txt", "/assets/..%2fsecret.txt",
                       "/assets/sous/dossier.js", "/assets/.env",
                       "/assets/" + "x" * 200 + ".js"):
            assert c2.get(path).status_code in (400, 404), path
        assert c2.get("/assets/secret-txt.js").status_code == 404


def test_a_missing_page_mounts_no_file_route():
    with context() as (c, _, _tmp):
        del c
        config.PAGE = ""
        c2 = TestClient(main.create_app())
        assert c2.get("/").status_code == 404
        assert c2.get("/theme.js").status_code == 404
        assert c2.get("/assets/index-abc123.js").status_code == 404
        assert c2.get("/healthz").status_code == 200
        assert c2.get("/catalog.json").status_code == 200


def test_xp_granted_only_once_per_exercise():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        verdict = {"status": "ok", "passed": 3, "total": 3}
        for number in range(2):
            job = "%032x" % number
            os.makedirs(os.path.join(config.SPOOL, job))
            with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
            with open(_output(job, "result.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(verdict, fh)
            assert c.get("/r/" + job).status_code == 200
            assert c.get("/r/" + job).status_code == 200
        grants = [t for t in base.xp.values() if t["amount"] > 0]
        assert len(grants) == 1, base.xp


def test_r_returns_an_anonymous_job_s_verdict_without_recording_it():
    with context() as (c, base, _tmp):
        job = "a" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": None}, fh)
        with open(_output(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.states, (base.xp, base.states)


def test_r_records_nothing_if_the_exercise_closed_since_the_submission():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "b" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "vanished-exercise", "owner": "sub-alice"}, fh)
        with open(_output(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.states, (base.xp, base.states)


def test_a_failure_grants_nothing():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "f" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
        with open(_output(job, "result.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 2, "total": 3}, fh)
        assert c.get("/r/" + job).status_code == 200
        assert not base.xp, base.xp
        assert base.states[("sub-alice", "tp2-ex3")] == "attempted", base.states


def _output(job, name):
    """Where the judge would write `nom` for `job`; the directory is the judge's to create."""
    os.makedirs(os.path.join(config.RESULTS, job), exist_ok=True)
    return os.path.join(config.RESULTS, job, name)


def _verdict(exercise_id, job, result):
    os.makedirs(os.path.join(config.SPOOL, job))
    with open(os.path.join(config.SPOOL, job, "job.json"), "w", encoding="utf-8") as fh:
        json.dump({"exercise_id": exercise_id, "owner": "sub-alice"}, fh)
    with open(_output(job, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh)


def test_a_verification_leaves_evidence_and_no_xp():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "a" * 32, {"status": "ok", "passed": 3, "total": 3})
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert not base.xp, base.xp
        evidences = [f for f in base.facts if f["type"] == "VerificationEvaluated"]
        assert len(evidences) == 1, base.facts
        assert evidences[0]["payload"]["passed"] is True
        assert set(evidences[0]["payload"]) == {"job", "passed"}

        view = c.get("/progress", headers=auth("alice")).json()
        assert view["xp"] == 0, view
        assert {c_["id"]: c_["band"] for c_ in view["mastery"]["skills"]} == {
            "variables": "verifie"}
        assert view["exercises"]["total"] == len(CONTENT) - 1, view["exercises"]
        assert [s["id"] for s in view["achievements"]] == ["premiere-verification"]


def test_a_failed_verification_reads_as_to_consolidate():
    with context(tokens={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "b" * 32, {"status": "ok", "passed": 1, "total": 3})
        assert c.get("/r/" + "b" * 32).status_code == 200
        view = c.get("/progress", headers=auth("alice")).json()
        assert [c_["band"] for c_ in view["mastery"]["skills"]] == ["a-consolider"]
        assert not base.xp and not view["achievements"], (base.xp, view["achievements"])


def test_silent_evidence_answers_503():
    base = FakeDatabase()
    base.read_events = lambda *a, **k: None
    with context(tokens={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progress", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "mastery" not in r.text and "xp" not in r.text, r.text


def test_an_unreadable_verdict_does_not_loop():
    with context() as (c, _, _tmp):
        job = "e" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(_output(job, "result.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ pas du json")
        r = c.get("/r/" + job)
        assert r.status_code == 500, (r.status_code, r.text)
        assert r.json()["state"] == "error", r.json()


def test_queue_rank_and_vanished_job():
    with context() as (c, _, _tmp):
        payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){}"}}
        first = c.post("/submit", json=payload).json()["id"]
        second = c.post("/submit", json=payload).json()["id"]
        for job in (first, second):
            os.utime(os.path.join(config.SPOOL, job, "job.json"), (1e9, 1e9))
        for job, rank in ((first, 1), (second, 2)):
            body = c.get("/r/" + job).json()
            assert body["state"] == "queued" and body["position"] == rank, body
        os.makedirs(_output(first, ".lock"))
        assert c.get("/r/" + first).json() == {"state": "running"}
        r = c.get("/r/" + "a" * 32)
        assert r.status_code == 404 and r.json() == {"state": "gone"}, r.text


def test_eta_sums_measured_durations_and_falls_back_to_an_average():
    with context() as (c, _, _tmp):
        saved = config.WORKERS
        try:
            config.WORKERS = 1
            payload = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            first = c.post("/submit", json=payload).json()["id"]
            second = c.post("/submit", json=payload).json()["id"]

            assert c.get("/r/" + first).json()["eta"] == 15
            assert c.get("/r/" + second).json()["eta"] == 30

            with open(os.path.join(config.RESULTS, "durations.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp2-ex3": [4.0, 20]}, fh)
            assert c.get("/r/" + first).json()["eta"] == 4
            assert c.get("/r/" + second).json()["eta"] == 8

            with open(os.path.join(config.RESULTS, "durations.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp1": [2.0, 20], "tp7-ex1": [10.0, 20]}, fh)
            assert c.get("/r/" + first).json()["eta"] == 6

            config.WORKERS = 2
            assert c.get("/r/" + second).json()["eta"] == 6

            with open(os.path.join(config.RESULTS, "durations.json"), "w",
                      encoding="utf-8") as fh:
                fh.write("{ pas du json")
            r = c.get("/r/" + first)
            assert r.status_code == 200 and r.json()["eta"] > 0, r.text
        finally:
            config.WORKERS = saved


def test_a_private_question_does_not_cross_the_http_boundary():
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "stuck",
                                   "step": "compilation",
                                   "blocked_kind": "unclear-error"},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        assert fake.messages[0]["visibility"] == "private", fake.messages
        assert fake.messages[0]["step"] == "compilation"

        seen = lambda who: c.get("/forum?ex=tp2-ex3", headers=auth(who)).json()["messages"]
        assert [m["id"] for m in seen("alice")]
        assert seen("bob") == []
        assert len(seen("prof")) == 1

        mid = fake.messages[0]["id"]
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[0]["visibility"] == "group"
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 404


def test_voting_refuses_ones_own_and_refuses_minus_one_on_a_question():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "ma question"},
               headers=auth("alice"))
        question = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "ma réponse",
                               "reply_to": question}, headers=auth("bob"))
        response = fake.messages[1]["id"]

        assert c.post("/forum/helpful", json={"id": question},
                      headers=auth("alice")).status_code == 404
        assert c.post("/forum/helpful", json={"id": "0" * 32},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": question},
                      headers=auth("bob")).status_code == 200

        assert c.post("/forum/helpful", json={"id": question, "value": -1},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": response, "value": -1},
                      headers=auth("alice")).status_code == 200

        thread = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"]
        question_view = [m for m in thread if m["id"] == question][0]
        answer_view = [m for m in thread if m["id"] == response][0]
        assert question_view["upvotes"] == 1 and question_view["my_vote"] == 1
        assert question_view["downvotes"] == 0
        assert answer_view["downvotes"] == 1

        assert c.post("/forum/helpful", json={"id": question, "value": 1},
                      headers=auth("bob")).status_code == 200
        assert c.post("/forum/helpful", json={"id": question, "value": 0},
                      headers=auth("bob")).status_code == 200
        thread = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"]
        assert [m for m in thread if m["id"] == question][0]["upvotes"] == 0

        assert fake.xp == {} and fake.achievement == {}


def test_the_chat_is_a_separate_thread_and_everything_in_it_is_public():
    tokens = {"alice": "sub-alice"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        for key in ("@chat:general", "@chat:tp2-ex3"):
            r = c.get("/forum?ex=" + key, headers=auth("alice"))
            assert r.status_code == 200, (key, r.text)
            assert r.json()["chat"] is True, key
        assert c.get("/forum?ex=tp2-ex3",
                     headers=auth("alice")).json()["chat"] is False
        for invented in ("@chat:inconnu", "@chat:", "@chat:../etc"):
            assert c.get("/forum?ex=" + invented,
                         headers=auth("alice")).status_code == 400, invented

        r = c.post("/forum", json={"exercise_id": "@chat:general",
                                   "text": "j'ose demander", "step": "statement",
                                   "visibility": "private"}, headers=auth("alice"))
        assert r.status_code == 400 and "publics" in r.json()["error"], r.text
        assert c.post("/forum", json={"exercise_id": "@chat:general",
                                      "text": "j'ose demander"},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[0]["visibility"] == "thread"
        assert c.post("/forum", json={"exercise_id": "tp2-ex3",
                                      "text": "bloqué", "step": "compilation"},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[1]["visibility"] == "private"


def test_the_discord_bridge_does_not_exist_without_a_key_and_refuses_everything_else():
    tokens = {"alice": "sub-alice"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/bridge", json={"exercise_id": "@chat:general",
                                          "discord_id": "4711",
                                          "display_name": "Vianney",
                                          "text": "salut"})
        assert r.status_code == 404, r.text

    with context(tokens=tokens, moderators=["sub-prof"],
                  bridge="secret-du-pont") as (c, fake, _tmp):
        bon = {"Authorization": "Bearer secret-du-pont"}
        body = {"exercise_id": "@chat:general", "discord_id": "4711",
                 "display_name": "Vianney", "text": "salut la classe"}
        for headers in ({}, {"Authorization": "Bearer autre"},
                        {"Authorization": "secret-du-pont"}):
            assert c.post("/forum/bridge", json=body,
                          headers=headers).status_code == 401, headers

        private = dict(body, exercise_id="tp2-ex3")
        r = c.post("/forum/bridge", json=private, headers=bon)
        assert r.status_code == 400 and "chat public" in r.json()["error"], r.text
        assert c.post("/forum/bridge", json=dict(body, exercise_id="@chat:inconnu"),
                      headers=bon).status_code == 400

        for bad in ("", "abc", "47-11", "@chat:general", "1" * 25):
            assert c.post("/forum/bridge", json=dict(body, discord_id=bad),
                          headers=bon).status_code == 400, bad

        assert c.post("/forum/bridge", json=dict(body, text=""),
                      headers=bon).status_code == 400
        assert c.post("/forum/bridge",
                      json=dict(body, text="x" * (config.FORUM_MAX_CHARS + 1)),
                      headers=bon).status_code == 400
        for reserved in ("Enseignant", "Vous", "PARTICIPANT"):
            assert c.post("/forum/bridge", json=dict(body, display_name=reserved),
                          headers=bon).status_code == 400, reserved

        assert c.post("/forum/bridge", json=body, headers=bon).status_code == 200
        written = fake.messages[-1]
        assert written["text"] == "salut la classe"
        assert written["exercise_id"] == "@chat:general"
        assert written["account"] == "@discord:4711", written["account"]
        assert written["visibility"] == "thread"

        view = c.get("/forum?ex=@chat:general", headers=auth("alice"))
        assert view.status_code == 200, view.text
        assert "Vianney" in view.text, view.text
        assert "@discord:" not in view.text and "sub-alice" not in view.text, view.text


def test_a_reply_targets_its_root_and_has_no_visibility_of_its_own():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "ma question"},
               headers=auth("alice"))
        root = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "@chat:tp2-ex3", "text": "ailleurs"},
               headers=auth("alice"))
        elsewhere = fake.messages[1]["id"]

        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": "pas-un-id"},
                      headers=auth("bob")).status_code == 400
        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": elsewhere},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": "0" * 32},
                      headers=auth("bob")).status_code == 404
        r = c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                   "reply_to": root, "visibility": "private"},
                   headers=auth("bob"))
        assert r.status_code == 400 and "hérite" in r.json()["error"], r.text

        assert c.post("/forum", json={"exercise_id": "@chat:general",
                                      "text": "ma réponse", "reply_to": root},
                      headers=auth("bob")).status_code == 200
        response = fake.messages[2]["id"]
        assert fake.messages[2]["reply_to"] == root
        assert c.post("/forum", json={"exercise_id": "@chat:general",
                                      "text": "et encore", "reply_to": response},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[3]["reply_to"] == root

        payload = c.get("/forum?ex=@chat:general", headers=auth("bob")).text
        assert "sub-alice" not in payload and "sub-bob" not in payload


def test_the_permalink_returns_a_conversation_and_the_same_404_everywhere():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "question"},
               headers=auth("alice"))
        root = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "réponse",
                               "reply_to": root}, headers=auth("bob"))
        view = c.get("/forum/message?id=" + root, headers=auth("bob")).json()
        assert [m["text"] for m in view["messages"]] == ["question", "réponse"]
        assert view["exercise_id"] == "@chat:general" and view["chat"] is True
        since = c.get("/forum/message?id=" + fake.messages[1]["id"],
                       headers=auth("bob")).json()
        assert len(since["messages"]) == 2
        assert c.get("/forum/message?id=zz", headers=auth("bob")).status_code == 400
        assert c.get("/forum/message?id=" + "0" * 32,
                     headers=auth("bob")).status_code == 404


def test_search_never_surfaces_someone_elses_private_question():
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3",
                               "text": "segfault mysterieux", "step": "execution"},
               headers=auth("alice"))
        c.post("/forum", json={"exercise_id": "@chat:general",
                               "text": "segfault en public"}, headers=auth("alice"))

        def found(who):
            r = c.get("/forum/search?q=segfault", headers=auth(who))
            assert r.status_code == 200, r.text
            return [x["excerpt"] for x in r.json()["results"]]

        assert "segfault mysterieux" in found("alice")
        assert "segfault mysterieux" not in found("bob")
        assert "segfault mysterieux" not in found("prof")
        assert "segfault en public" in found("bob")
        assert c.get("/forum/search?q=", headers=auth("bob")).json()["results"] == []


def test_the_chat_bell_refuses_in_the_right_order_and_says_nothing_else():
    from starlette.websockets import WebSocketDisconnect

    with context(tokens={"alice": "sub-alice"}, moderators=[]) as (c, _f, _t):
        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "n'importe quoi",
                                  "thread": "@chat:general"})
                socket.receive_json()
            raise AssertionError("a socket opened without the forum")
        except WebSocketDisconnect as exc:
            assert exc.code == 4503, exc.code

    with context(tokens={"alice": "sub-alice"},
                  moderators=["sub-prof"]) as (c, fake, _tmp):
        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "faux",
                                  "thread": "@chat:general"})
                socket.receive_json()
            raise AssertionError("an invalid token was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 4401, exc.code

        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "alice",
                                  "thread": "@chat:inconnu"})
                socket.receive_json()
            raise AssertionError("an invented thread was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 4400, exc.code

        with c.websocket_connect("/forum/live") as socket:
            socket.send_json({"t": "hello", "token": "alice",
                              "thread": "@chat:general"})
            ready = socket.receive_json()
            assert ready == {"t": "ready", "thread": "@chat:general"}, ready
            try:
                socket.send_text("x" * (config.FORUM_LIVE_FRAME + 1))
                socket.receive_json()
                raise AssertionError("an out-of-bounds frame was accepted")
            except WebSocketDisconnect as exc:
                assert exc.code == 4400, exc.code

    forum_live.reset()

    class SilentSocket:
        def __init__(self):
            self.frames = []

        async def send_text(self, data):
            self.frames.append(json.loads(data))

    fake_socket = SilentSocket()
    login = forum_live.Connection(fake_socket, "@chat:general")
    forum_live.join(login)
    try:
        asyncio.new_event_loop().run_until_complete(
            forum_live._ring("@chat:general"))
        assert fake_socket.frames == [{"t": "new", "thread": "@chat:general"}], \
            fake_socket.frames
        assert set(fake_socket.frames[0]) == {"t", "thread"}
    finally:
        forum_live.leave(login)
        forum_live.reset()


def test_the_leaderboard_excludes_the_teacher_without_saying_so_backwards():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        for who, group, alias in (("sub-alice", 4, "Rotor cuivré"),
                                   ("sub-prof", 6, "Vilebrequin trempé")):
            fake.profiles[who] = {"account": who, "alias": alias,
                                 "group_number": group,
                                 "leaderboard_opt_in": True,
                                 "display_name": None,
                                 "display_name_public": False,
                                 "group_number_public": False}
        response = c.get("/leaderboard?scope=course", headers=auth("prof"))
        view = response.json()
        assert view["moderator"] is True
        assert "Vilebrequin trempé" not in response.text, response.text
        assert "sub-prof" not in response.text
        assert view["cohort"] == 1 and view["rows"] == []
        assert sum(d["accounts"] for d in view["divisions"]) == 1

        mien = c.get("/leaderboard?scope=group&group=6", headers=auth("alice")).json()
        assert mien["group"] == 4 and mien["moderator"] is False
        assert mien["groups"] == []
        vise = c.get("/leaderboard?scope=group&group=4", headers=auth("prof")).json()
        assert vise["group"] == 4 and vise["groups"] == [4, 6]


def test_retaining_an_answer_does_not_edit_the_message():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "the answer"},
               headers=auth("alice"))
        mid, before = fake.messages[0]["id"], fake.messages[0]["text"]
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("alice")).status_code == 403
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before, "the message was edited"
        thread = c.get("/forum?ex=tp2-ex3", headers=auth("alice")).json()
        assert thread["messages"][0]["retained"] is True
        assert thread["state"]["resolved"] == 1
        assert c.post("/forum/moderation", json={"id": mid, "action": "unretain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before
        assert c.get("/forum?ex=tp2-ex3",
                     headers=auth("alice")).json()["messages"][0]["retained"] is False


def test_who_needs_help_counts_without_naming_and_stays_restricted():
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _fake, _tmp):
        for who in ("alice", "bob"):
            c.post("/forum", json={"exercise_id": "tp2-ex3",
                                   "text": "I don't understand the error",
                                   "step": "compilation"}, headers=auth(who))
        assert c.get("/forum/help", headers=auth("alice")).status_code == 403
        r = c.get("/forum/help", headers=auth("prof"))
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) == 1 and rows[0]["people"] == 2, rows
        assert rows[0]["step"] == "compilation"
        payload = r.text
        for forbidden in ("sub-alice", "sub-bob", "I don't understand"):
            assert forbidden not in payload, payload


def test_the_leaderboard_is_opt_in_and_mute_under_the_cohort():
    tokens = {"alice": "sub-alice"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        r = c.get("/leaderboard", headers=auth("alice"))
        assert r.status_code == 200 and r.json()["participating"] is False

        r = c.post("/forum/profile",
                   json={"group_number": 4, "leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        alias = fake.profiles["sub-alice"]["alias"]
        assert alias and alias in policy.possible_aliases(), alias

        view = c.get("/leaderboard", headers=auth("alice")).json()
        assert view["participating"] is True and view["me"]["rank"] == 1
        assert view["rows"] == [] and view["cohort"] < view["minimum"]
        assert "sub-alice" not in c.get("/leaderboard", headers=auth("alice")).text

        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 200 and r.json()["alias"] != alias

        c.post("/forum/profile", json={"group_number": 4,
                                      "leaderboard_opt_in": False},
               headers=auth("alice"))
        assert fake.profiles["sub-alice"]["group_number"] == 4
        assert c.get("/leaderboard", headers=auth("alice")
                     ).json()["participating"] is False


def test_a_locked_frame_is_refused():
    with context(tokens={"alice": "sub-alice"},
                  moderators=["sub-prof"]) as (c, _fake, _tmp):
        offered = c.get("/forum/profile", headers=auth("alice")).json()["frames"]
        assert [f["id"] for f in offered] == ["simple"], offered
        r = c.post("/forum/profile", json={"plate_frame": "tolerance"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        assert c.post("/forum/profile", json={"plate_frame": "simple"},
                      headers=auth("alice")).status_code == 200


def test_the_collection_shows_locked_cards_with_their_condition():
    with context(tokens={"alice": "sub-alice"},
                  moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/collection", headers=auth("alice"))
        assert r.status_code == 200, r.text
        cards = r.json()["cards"]
        assert len(cards) == len(policy.POLICY["cards"])
        assert all(not card["held"] for card in cards)
        assert all(card["condition"] for card in cards), cards
        assert all(card["rarity"] is None for card in cards)


def test_a_mute_database_answers_503_on_the_new_screens():
    class Mute(FakeDatabase):
        leaderboard_rows = staticmethod(lambda *a: None)
        read_unlock_rates = staticmethod(lambda *a: None)
        read_practice_days = staticmethod(lambda *a: None)

    with context(tokens={"alice": "sub-alice"}, base=Mute(),
                  moderators=["sub-prof"]) as (c, _fake, _tmp):
        for route in ("/leaderboard", "/collection", "/progress"):
            r = c.get(route, headers=auth("alice"))
            assert r.status_code == 503, (route, r.status_code, r.text)
            assert not re.search(r"\\d", r.json().get("error", "")), r.text


def test_forum_id_based_routes_reject_an_invalid_form():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _fake, _tmp):
        calls = [
            lambda: c.post("/forum/visibility", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.post("/forum/helpful", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.delete("/forum?id=too-short", headers=auth("alice")),
            lambda: c.post("/forum/report",
                          json={"id": "too-short", "kind": "message"},
                          headers=auth("alice")),
            lambda: c.post("/forum/moderation",
                          json={"id": "too-short", "action": "hide"},
                          headers=auth("prof")),
        ]
        for call in calls:
            r = call()
            assert r.status_code == 400 and r.json() == {"error": "identifiant invalide"}, r.text


def test_delete_ones_own_message_never_someone_elses():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "mine"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 404, r.text
        r = c.delete("/forum?id=" + mid, headers=auth("bob"))
        assert r.status_code == 404, (r.status_code, r.text)
        assert fake.messages, "bob's message should not have disappeared"
        r = c.delete("/forum?id=" + mid, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert not fake.messages

    base = FakeDatabase()
    base.forum_delete = lambda *a: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_report_a_message_or_a_name():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "dubious"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/report", json={"id": mid, "kind": "message"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        r = c.post("/forum/report", json={"id": mid, "kind": "name"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        r = c.post("/forum/report", json={"id": mid}, headers=auth("bob"))
        assert r.status_code == 200, r.text

    base = FakeDatabase()
    base.forum_report = lambda *a: None
    base.forum_report_name = lambda *a: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        for body in ({"id": "0" * 32, "kind": "message"},
                     {"id": "0" * 32, "kind": "name"}):
            r = c.post("/forum/report", json=body, headers=auth("alice"))
            assert r.status_code == 503, (body, r.text)


def test_moderation_clears_a_reported_name_without_touching_the_rest_of_the_profile():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum/profile",
              json={"display_name": "Léa", "display_name_public": True,
                    "group_number": 4, "group_number_public": True},
              headers=auth("alice"))
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "hi"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/moderation", json={"id": mid, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        profile = fake.profiles["sub-alice"]
        assert profile["display_name"] is None
        assert profile["group_number"] == 4 and profile["group_number_public"] is True

        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = FakeDatabase()
    base.forum_profile = lambda user: None
    with context(tokens={"alice": "sub-alice", "prof": "sub-prof"}, base=base,
                 moderators=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "1" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "1" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text

    base2 = FakeDatabase()
    base2.forum_write_profile = lambda *a, **k: False
    with context(tokens={"alice": "sub-alice", "prof": "sub-prof"}, base=base2,
                 moderators=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "2" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "2" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_moderation_refuses_an_unknown_action():
    tokens = {"prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "edit"},
                   headers=auth("prof"))
        assert r.status_code == 400 and r.json() == {"error": "action inconnue"}, r.text


def test_thread_refuses_an_unknown_exercise():
    with context(tokens={"alice": "sub-alice"},
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text


def test_visibility_and_helpful_report_a_database_outage():
    base = FakeDatabase()
    base.forum_open_to_group = lambda *a: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/visibility", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_vote = lambda *a: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/helpful", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_moderate_hide_restore_retain_report_an_outage_and_an_unknown_id():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with context(tokens=tokens, moderators=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x"},
              headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/moderation", json={"id": mid, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert fake.messages[0]["hidden"] is True
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "restore"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = FakeDatabase()
    base.forum_moderate = lambda *a: None
    with context(tokens=tokens, base=base, moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_forum_reports_a_database_outage_on_each_read_route():
    base = FakeDatabase()
    base.forum_thread = lambda *a, **k: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_reports = lambda *a: None
    with context(tokens={"prof": "sub-prof"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/moderation", headers=auth("prof"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_help_rows = lambda *a: None
    with context(tokens={"prof": "sub-prof"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/help", headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_post_validates_each_field_then_reports_an_outage():
    with context(tokens={"alice": "sub-alice"},
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "inconnu", "text": "x"},
                   headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": ""},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "step": "whatever"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "step": "compilation",
                                   "blocked_kind": "whatever"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "visibility": "group"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = FakeDatabase()
    base.forum_post = lambda *a: False
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_profile_validates_the_name_and_group_then_reports_an_outage():
    with context(tokens={"alice": "sub-alice"}, groups=(4, 6),
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profile", json={"display_name": "x" * 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        r = c.post("/forum/profile", json={"group_number": 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = FakeDatabase()
    base.forum_profile = lambda user: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/profile", headers=auth("alice"))
        assert r.status_code == 503, r.text
        r = c.post("/forum/profile", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_write_profile = lambda *a, **k: False
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profile", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_taken_aliases = lambda: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profile", json={"leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_oidc_json_is_empty_when_sign_in_is_disabled():
    assert client.get("/oidc.json").json() == {}


def test_sub_responds_503_outside_oidc_configuration():
    r = client.get("/states", headers=auth("alice"))
    assert r.status_code == 503 and "persistance" in r.json()["error"], r.text


def test_forum_throttle_blocks_a_burst_of_messages():
    with context(tokens={"alice": "sub-alice"},
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        deps.forum_quota = quotas.Quota(cooldown=999, hourly=100)
        r1 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "one"},
                   headers=auth("alice"))
        assert r1.status_code == 200, r1.text
        r2 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "two"},
                   headers=auth("alice"))
        assert r2.status_code == 429 and "retry_after" in r2.json(), r2.text


def test_leaderboard_and_alias_report_every_database_outage():
    base = FakeDatabase()
    base.forum_profile = lambda user: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        assert c.get("/leaderboard", headers=auth("alice")).status_code == 503
        assert c.post("/leaderboard/alias", json={}, headers=auth("alice")).status_code == 503

    base = FakeDatabase()
    base.forum_taken_aliases = lambda: None
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = FakeDatabase()
    base.forum_write_profile = lambda *a, **k: False
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, fake, _tmp):
        fake.profiles["sub-alice"] = dict(FakeDatabase.EMPTY_PROFILE, alias="Faucon-12")
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_redraw_alias_exhausts_the_vocabulary():
    import policy
    every_alias = set(policy.possible_aliases())
    base = FakeDatabase()
    with context(tokens={"alice": "sub-alice"}, base=base,
                 moderators=["sub-prof"]) as (c, fake, _tmp):
        for i, alias in enumerate(every_alias):
            fake.profiles["sub-%d" % i] = dict(FakeDatabase.EMPTY_PROFILE, alias=alias)
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503 and "pseudonyme" in r.json()["error"], r.text


def test_warn_reports_each_incomplete_configuration_independently():
    guard = (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
             security.oidc_enabled)
    try:
        config.OIDC_ISSUER = "https://auth.exemple"
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = False
        security.oidc_enabled = lambda: False
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._warn()
        out = buffer.getvalue()
        assert "sign-in disabled" in out
        assert "forum disabled" not in out
        assert "CTESTER_DOCS" not in out

        security.oidc_enabled = lambda: True
        config.FORUM_MODERATORS = frozenset()
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._warn()
        out = buffer.getvalue()
        assert "sign-in disabled" not in out
        assert "forum disabled" in out

        config.OIDC_ISSUER = ""
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._warn()
        out = buffer.getvalue()
        assert "CTESTER_DOCS=1" in out
        assert "sign-in disabled" not in out
        assert "forum disabled" not in out

        config.OIDC_ISSUER = "https://auth.exemple"
        config.DOCS = False
        security.oidc_enabled = lambda: True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._warn()
        assert buffer.getvalue() == ""
    finally:
        (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
         security.oidc_enabled) = guard


def test_http_exception_handler_only_rewrites_the_generic_404():
    import asyncio
    from starlette.exceptions import HTTPException as StarletteHTTPException
    handler = main.app.exception_handlers[StarletteHTTPException]
    response = asyncio.run(handler(
        None, StarletteHTTPException(status_code=404, detail="Not Found")))
    assert json.loads(response.body) == {"error": "inconnu"}
    response = asyncio.run(handler(
        None, StarletteHTTPException(status_code=404, detail="exercice retiré")))
    assert json.loads(response.body) == {"error": "exercice retiré"}


def test_uvicorn_is_launched_with_a_single_worker():
    source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    block = source.split("uvicorn.run(", 1)[1].split(")", 1)[0]
    assert re.search(r"workers\s*=\s*1\b", block), block
    assert not re.search(r"workers\s*=\s*(?!1\b)\d", block), block


TEAM_TOKENS = {"t-alice": "sub-alice", "t-bob": "sub-bob",
                 "t-cleo": "sub-cleo", "t-prof": "sub-prof"}


def _headers(token):
    return {"Authorization": "Bearer " + token}


@contextlib.contextmanager
def assignment_deployment(*, deadline=None, team=True, moderators=("sub-prof",)):
    base = FakeDatabase()
    with context(tokens=TEAM_TOKENS, moderators=moderators, base=base,
                  exercises=ASSIGNMENT,
                  assignment=_assignment_json(deadline=deadline, team=team)) as (c, fake, tmp):
        fake.register("devoir", "e1", ["sub-alice", "sub-cleo"], group_number=4,
                      label="Équipe 1")
        fake.register("devoir", "e2", ["sub-bob"], group_number=6,
                      label="Équipe 2")
        yield c, fake, tmp


def _console_hello(socket, token="t-alice", code="int main(void){return 0;}"):
    socket.send_json({"t": "hello", "token": token, "code": code})


def _requires_flock():
    from services import scratch as _scratch
    if _scratch.fcntl is None:
        raise RuntimeError("flock unavailable: the Console needs POSIX")


def test_the_console_says_it_is_not_offered_before_refusing_the_token():
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS, console=False) as (client, _, _):
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, token="t-inconnu")
                socket.receive_json()
            raise AssertionError("the disabled Console accepted a session")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_UNAVAILABLE, exc.code

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, token="t-inconnu")
                socket.receive_json()
            raise AssertionError("an unknown token opened a session")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_UNAUTHORIZED, exc.code


def test_the_console_refuses_an_unknown_origin_before_accepting():
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        try:
            with client.websocket_connect(
                    "/scratch/live",
                    headers={"origin": "https://ailleurs.example"}) as socket:
                socket.receive_json()
            raise AssertionError("an unknown origin got through")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_FORBIDDEN, exc.code


def test_the_console_bounds_the_code_on_both_sides():
    _requires_flock()
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket, code="/*" + "x" * (config.MAX_CODE - 4) + "*/")
            frame = socket.receive_json()
            assert frame["t"] == "queued", frame
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, code="x" * (config.MAX_CODE + 1))
                socket.receive_json()
            raise AssertionError("out-of-bounds code got through")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BAD, exc.code


def test_the_console_bounds_typed_input_on_both_sides():
    _requires_flock()
    with context(tokens=TEAM_TOKENS) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            path = _console_job()
            socket.send_json({"t": "stdin", "d": "a" * config.SCRATCH_FRAME})
            socket.send_json({"t": "stdin", "d": "b" * (config.SCRATCH_FRAME + 1)})
            socket.send_json({"t": "stdin", "d": "FIN\n"})
            for _ in range(40):
                time.sleep(0.02)
                if b"FIN" in _read_bytes(os.path.join(path, "in")):
                    break
            entry = _read_bytes(os.path.join(path, "in"))
        assert b"a" * config.SCRATCH_FRAME in entry
        assert b"b" not in entry, entry[:200]
        assert entry.endswith(b"FIN\n")


def test_the_console_writes_neither_owner_nor_exercise_to_the_spool():
    _requires_flock()
    base = FakeDatabase()
    with context(tokens=TEAM_TOKENS, base=base) as (client, fake, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            path = _console_job()
            job = json.loads(_read_bytes(os.path.join(path, "job.json")))
            assert job == {"kind": "console"}, job
            identifier = os.path.basename(path)
            r = client.get("/r/" + identifier, headers=_headers("t-alice"))
            assert r.status_code == 200, r.text
            assert r.json()["state"] in ("queued", "running"), r.json()
        assert not fake.practice, fake.practice
        assert not fake.jobs, fake.jobs
        assert not fake.states, fake.states


def test_one_console_session_per_account():
    _requires_flock()
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        with client.websocket_connect("/scratch/live") as first:
            _console_hello(first)
            assert first.receive_json()["t"] == "queued"
            try:
                with client.websocket_connect("/scratch/live") as second:
                    _console_hello(second)
                    second.receive_json()
                raise AssertionError("one account opened two sessions")
            except WebSocketDisconnect as exc:
                assert exc.code == deps.CLOSE_BUSY, exc.code
        with client.websocket_connect("/scratch/live") as other:
            _console_hello(other, token="t-bob")
            assert other.receive_json()["t"] == "queued"


def test_the_hourly_console_quota_passes_at_N_and_refuses_at_N_plus_1():
    _requires_flock()
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        deps.scratch_quota = quotas.Quota(cooldown=0, hourly=2)
        for attempt in range(2):
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket)
                assert socket.receive_json()["t"] == "queued", attempt
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket)
                socket.receive_json()
            raise AssertionError("the 3rd session got through despite a quota of 2")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BUSY, exc.code


def test_the_notepad_follows_the_account_and_is_bounded():
    with context(tokens=TEAM_TOKENS) as (client, _, _):
        r = client.get("/scratch/draft", headers=_headers("t-alice"))
        assert r.status_code == 200 and r.json() == {"code": "", "header_name": "",
                                                      "header": ""}, r.text
        assert client.get("/scratch/draft").status_code == 401
        assert client.put("/scratch/draft", json={"code": "x" * config.MAX_CODE},
                          headers=_headers("t-alice")).status_code == 200
        too_many = client.put("/scratch/draft",
                          json={"code": "x" * (config.MAX_CODE + 1)},
                          headers=_headers("t-alice"))
        assert too_many.status_code == 413, too_many.status_code
        client.put("/scratch/draft", json={"code": "a-moi"},
                   headers=_headers("t-alice"))
        assert client.get("/scratch/draft",
                          headers=_headers("t-alice")).json()["code"] == "a-moi"
        assert client.get("/scratch/draft",
                          headers=_headers("t-bob")).json()["code"] == ""


def test_the_notepad_keeps_its_header_and_refuses_a_bad_name():
    with context(tokens=TEAM_TOKENS) as (client, _, _):
        draft = {"code": '#include "pile.h"\n', "header_name": "pile.h",
                     "header": "#define N 3   \r\n"}
        r = client.put("/scratch/draft", json=draft, headers=_headers("t-alice"))
        assert r.status_code == 200, r.text
        assert client.get("/scratch/draft", headers=_headers("t-alice")).json() == {
            "code": '#include "pile.h"\n', "header_name": "pile.h",
            "header": "#define N 3\n"}
        for name, text in (("../pile.h", ""), ("pile.c", ""), ("", "orphelin"),
                           ("a" * 33 + ".h", "")):
            r = client.put("/scratch/draft", json={"code": "", "header_name": name,
                                                   "header": text},
                           headers=_headers("t-alice"))
            assert r.status_code == 400 and "en-tête" in r.text, (name, r.text)
        too_many = client.put("/scratch/draft",
                          json={"code": "", "header_name": "pile.h",
                                "header": "x" * (config.MAX_CODE + 1)},
                          headers=_headers("t-alice"))
        assert too_many.status_code == 413, too_many.status_code


def test_the_console_places_the_header_next_to_main_c():
    _requires_flock()
    from starlette.websockets import WebSocketDisconnect

    with context(tokens=TEAM_TOKENS) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            socket.send_json({"t": "hello", "token": "t-alice",
                              "code": '#include "pile.h"\nint main(void){return N;}',
                              "header_name": "pile.h", "header": "#define N 0\n"})
            assert socket.receive_json()["t"] == "queued"
            path = _console_job()
            job = json.loads(_read_bytes(os.path.join(path, "job.json")))
            assert job == {"kind": "console", "header": "pile.h"}, job
            assert _read_bytes(os.path.join(path, "src", "pile.h")) == b"#define N 0\n"
        # Both files at their limit still fit in the first frame.
        with client.websocket_connect("/scratch/live") as socket:
            socket.send_json({"t": "hello", "token": "t-alice",
                              "code": "/*" + "x" * (config.MAX_CODE - 4) + "*/",
                              "header_name": "gros.h",
                              "header": "/*" + "x" * (config.MAX_CODE - 4) + "*/"})
            assert socket.receive_json()["t"] == "queued"
        try:
            with client.websocket_connect("/scratch/live") as socket:
                socket.send_json({"t": "hello", "token": "t-alice", "code": "int x;",
                                  "header_name": "../evade.h", "header": ""})
                socket.receive_json()
            raise AssertionError("a header name breaking the rule got through")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BAD, exc.code


def test_oidc_json_announces_the_console():
    with context(tokens=TEAM_TOKENS) as (client, _, _):
        assert client.get("/oidc.json").json()["scratch"] is True
    with context(tokens=TEAM_TOKENS, console=False) as (client, _, _):
        assert client.get("/oidc.json").json()["scratch"] is False


def test_the_console_announces_running_before_any_output():
    """A program that reads before writing produces nothing until something is typed.
    Without the "running" frame the page stays on "Compilation…" and suggests that
    one must wait before answering."""
    _requires_flock()
    from services import scratch as _scratch
    with context(tokens=TEAM_TOKENS) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            job = os.path.basename(_console_job())

            # The judge claims the job, then holds its presence lock.
            os.makedirs(_output(job, ".lock"), exist_ok=True)
            with open(_output(job, "claim"), "w", encoding="utf-8") as claim:
                _scratch.fcntl.flock(claim, _scratch.fcntl.LOCK_EX)
                assert socket.receive_json()["t"] == "ready"

                # Compiling: nothing more to say.
                _write_json(_output(job, "state.json"), {"state": "compiling"})
                # Then the program starts, without having written anything yet.
                _write_json(_output(job, "state.json"), {"state": "running"})
                frame = socket.receive_json()
                assert frame == {"t": "running"}, frame

                # Announced only once, even if the state no longer changes.
                with open(_output(job, "out"), "w", encoding="utf-8") as fh:
                    fh.write("recu 7\n")
                following = socket.receive_json()
                assert following == {"t": "out", "d": "recu 7\n"}, following

                _write_json(_output(job, "state.json"),
                             {"state": "exited", "code": 0, "reason": "exited"})
                done = socket.receive_json()
                assert done["t"] == "exit" and done["code"] == 0, done
                _scratch.fcntl.flock(claim, _scratch.fcntl.LOCK_UN)


def _write_json(path, value):
    """Atomic write, like the judge's: never a half-written file for the API."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh)
    os.replace(tmp, path)


def _console_job():
    for name in os.listdir(config.SPOOL):
        path = os.path.join(config.SPOOL, name)
        if os.path.exists(os.path.join(path, "job.json")):
            return path
    raise AssertionError("no console job in the spool")


def _read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def test_the_team_context_names_teammates_without_any_sub():
    with assignment_deployment() as (client, fake, _):
        r = client.get("/team/context?assignment=devoir",
                       headers=_headers("t-alice"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "sub-" not in r.text, r.text
        assert body["team"]["id"] == "e1"
        assert body["team"]["group_number"] == 4
        assert [m["id"] for m in body["team"]["members"]] == ["m1", "m2"]
        assert [m["you"] for m in body["team"]["members"]] == [True, False]
        assert body["assignment"]["items"] == ["dev-a", "dev-b"]
        assert body["assignment"]["team"] == {"min": 3, "max": 4, "count": 6}
        assert body["submission"] == {}
        assert not fake.profiles


def test_the_team_socket_bounds_its_opening_frame_like_the_others():
    from starlette.websockets import WebSocketDisconnect

    def refused(sender):
        with assignment_deployment() as (client, _f, _t):
            try:
                with client.websocket_connect("/team/live") as socket:
                    sender(socket)
                    socket.receive_json()
            except WebSocketDisconnect as exc:
                return exc.code
            raise AssertionError("the socket stayed open")

    assert refused(lambda s: s.send_text("pas du json")) == 4400
    assert refused(lambda s: s.send_json({"t": "bonjour", "token": "t-alice"})) == 4400
    # Padded out past the bound but otherwise a hello this deployment would accept, so the
    # length is the only thing that can refuse it.
    padded = {"t": "hello", "token": "t-alice", "assignment": "devoir",
              "exercise": "dev-a", "pad": "x" * config.TEAM_LIVE_MAX_FRAME}
    assert refused(lambda s: s.send_json(padded)) == 4400
    assert refused(lambda s: s.send_json({"t": "hello", "token": "faux",
                                          "assignment": "devoir",
                                          "exercise": "dev-a"})) == 4401


def test_no_team_route_opens_without_proven_membership():
    with assignment_deployment() as (client, fake, _):
        fake.teams.pop(("devoir", "sub-bob"))
        for path in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/revisions?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            r = client.get(path, headers=_headers("t-bob"))
            assert r.status_code == 403, (path, r.status_code)
            assert "équipe" in r.json()["error"]
        r = client.get("/team/context?assignment=inconnu",
                       headers=_headers("t-alice"))
        assert r.status_code == 404
        assert client.get("/team/context?assignment=devoir").status_code == 401


def test_an_assignment_without_a_team_block_answers_that_it_is_not_team_work():
    with assignment_deployment(team=False) as (client, _, _):
        r = client.get("/team/context?assignment=devoir",
                       headers=_headers("t-alice"))
        assert r.status_code == 400
        assert "travail d'équipe" in r.json()["error"]


def test_the_document_is_shared_by_the_team_and_only_the_team():
    with assignment_deployment() as (client, fake, _):
        write = client.put("/team/document", headers=_headers("t-alice"),
                            json={"assignment_id": "devoir",
                                  "exercise_id": "dev-a",
                                  "files": {"main.c": "int main(void){}\n"}})
        assert write.status_code == 200, write.text
        pour_cleo = client.get("/team/document?assignment=devoir&ex=dev-a",
                               headers=_headers("t-cleo")).json()
        assert pour_cleo["sources"] == {"main.c": "int main(void){}\n"}
        pour_bob = client.get("/team/document?assignment=devoir&ex=dev-a",
                              headers=_headers("t-bob")).json()
        assert pour_bob["sources"] == {}
        client.put("/team/document", headers=_headers("t-bob"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "team_id": "e1", "team": "e1",
                         "files": {"main.c": "/* bob */\n"}})
        assert fake.documents[("e1", "dev-a")] == {"main.c": "int main(void){}\n"}
        assert fake.documents[("e2", "dev-a")] == {"main.c": "/* bob */\n"}


def test_an_exercise_outside_the_assignment_does_not_resolve_even_for_a_member():
    with assignment_deployment() as (client, _, _):
        for ex in ("tp2-ex3", "../catalog", "", "quiz1"):
            r = client.get("/team/document?assignment=devoir&ex="
                           + ex, headers=_headers("t-alice"))
            assert r.status_code == 404, (ex, r.status_code)
        r = client.put("/team/document", headers=_headers("t-alice"),
                       json={"assignment_id": "devoir",
                             "exercise_id": "tp2-ex3", "files": {}})
        assert r.status_code == 404


def test_the_team_document_does_not_touch_the_individual_draft():
    with assignment_deployment() as (client, fake, _):
        client.put("/team/document", headers=_headers("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "équipe\n"}})
        assert fake.drafts == {}
        client.put("/draft", headers=_headers("t-alice"),
                   json={"exercise_id": "tp2-ex3",
                         "files": {"submission.c": "moi\n"}})
        assert fake.drafts[("sub-alice", "tp2-ex3")] == {"submission.c": "moi\n"}
        assert fake.documents[("e1", "dev-a")] == {"main.c": "équipe\n"}
        r = client.put("/draft", headers=_headers("t-bob"),
                       json={"exercise_id": "dev-a",
                             "files": {"main.c": "seul\n"}})
        assert r.status_code == 200
        assert fake.drafts[("sub-bob", "dev-a")] == {"main.c": "seul\n"}


def test_the_team_document_is_canonicalized_on_both_sides():
    with assignment_deployment() as (client, fake, _):
        client.put("/team/document", headers=_headers("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "int main(void){\r\n}\r\n\r\n"}})
        assert fake.documents[("e1", "dev-a")] == {
            "main.c": "int main(void){\n}\n\n"}, fake.documents
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_headers("t-alice"))
        assert r.json()["sources"] == {"main.c": "int main(void){\n}\n\n"}, r.text


def test_the_document_goes_through_the_same_allowlist_as_everything_else():
    with assignment_deployment() as (client, _, _):
        r = client.put("/team/document", headers=_headers("t-alice"),
                       json={"assignment_id": "devoir", "exercise_id": "dev-a",
                             "files": {"secret.c": "x"}})
        assert r.status_code == 400 and "inattendu" in r.json()["error"]
        pile = "a" * (config.MAX_CODE - len(json.dumps({"main.c": ""})))
        assert client.put("/team/document", headers=_headers("t-alice"),
                          json={"assignment_id": "devoir",
                                "exercise_id": "dev-a",
                                "files": {"main.c": pile}}).status_code == 200
        assert client.put("/team/document", headers=_headers("t-alice"),
                          json={"assignment_id": "devoir",
                                "exercise_id": "dev-a",
                                "files": {"main.c": pile + "a"}}).status_code == 413


def test_a_revision_is_coalesced_then_restorable():
    with assignment_deployment() as (client, fake, _):
        def write(token, text):
            return client.put("/team/document", headers=_headers(token),
                              json={"assignment_id": "devoir",
                                    "exercise_id": "dev-a",
                                    "files": {"main.c": text}})
        write("t-alice", "un\n")
        write("t-alice", "deux\n")
        write("t-alice", "trois\n")
        assert len(fake.revisions) == 1, fake.revisions
        write("t-cleo", "quatre\n")
        assert len(fake.revisions) == 2
        fake.clock += config.TEAM_REVISION_WINDOW + 1
        write("t-alice", "cinq\n")
        assert len(fake.revisions) == 3
        fake.clock += config.TEAM_REVISION_WINDOW + 1
        write("t-alice", "cinq\n")
        assert len(fake.revisions) == 3

        listed = client.get("/team/revisions?assignment=devoir&ex=dev-a",
                             headers=_headers("t-alice")).json()["revisions"]
        assert len(listed) == 3
        assert "sub-" not in json.dumps(listed)
        assert {r["author"] for r in listed} == {"m1", "m2"}
        assert "%" not in json.dumps(listed)

        first = listed[-1]["id"]
        detail = client.get("/team/revision?assignment=devoir&ex=dev-a&id="
                            + first, headers=_headers("t-alice"))
        assert detail.json()["sources"] == {"main.c": "un\n"}
        handed_in = client.post("/team/restore", headers=_headers("t-cleo"),
                            json={"assignment_id": "devoir",
                                  "exercise_id": "dev-a",
                                  "revision_id": first})
        assert handed_in.status_code == 200
        assert fake.documents[("e1", "dev-a")] == {"main.c": "un\n"}
        assert len(fake.revisions) == 4


def test_another_teams_revision_does_not_resolve():
    with assignment_deployment() as (client, fake, _):
        client.put("/team/document", headers=_headers("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "secret d'alice\n"}})
        [revision] = fake.revisions
        for path, method, body in (
                ("/team/revision?assignment=devoir&ex=dev-a&id="
                 + revision["revision_id"], "GET", None),
                ("/team/restore", "POST",
                 {"assignment_id": "devoir", "exercise_id": "dev-a",
                  "revision_id": revision["revision_id"]})):
            r = (client.get(path, headers=_headers("t-bob")) if method == "GET"
                 else client.post(path, headers=_headers("t-bob"), json=body))
            assert r.status_code == 404, (path, r.status_code)
        assert ("e2", "dev-a") not in fake.documents
        assert "secret" not in client.get(
            "/team/revisions?assignment=devoir&ex=dev-a",
            headers=_headers("t-bob")).text


def test_the_zip_archive_is_built_by_the_server_and_deterministic():
    import io as _io
    import zipfile as _zipfile

    with assignment_deployment() as (client, fake, _):
        empty = client.get("/team/handin.zip?assignment=devoir",
                          headers=_headers("t-alice"))
        assert empty.status_code == 400 and "rien à remettre" in empty.json()["error"]
        fake.documents[("e1", "dev-a")] = {"main.c": "int main(void){return 0;}\n"}
        fake.documents[("e1", "dev-b")] = {"lib.h": "#pragma once\n",
                                           "lib.c": "double f(void){return 1;}\n"}
        r = client.get("/team/handin.zip?assignment=devoir",
                       headers=_headers("t-alice"))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert "Devoir-e1.zip" in r.headers["content-disposition"]
        assert r.headers["cache-control"] == "no-store"
        with _zipfile.ZipFile(_io.BytesIO(r.content)) as archive:
            assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
            assert archive.read("Devoir/matrac_lib.c").decode() \
                == "double f(void){return 1;}\n"
        again = client.get("/team/handin.zip?assignment=devoir",
                            headers=_headers("t-cleo"))
        assert again.content == r.content
        other = client.get("/team/handin.zip?assignment=devoir",
                           headers=_headers("t-bob"))
        assert other.status_code == 400, other.text


def test_the_handin_is_one_per_team_and_refuses_a_gap():
    with assignment_deployment() as (client, fake, _):
        fake.documents[("e1", "dev-a")] = {"main.c": "int main(void){}\n"}
        incomplete = client.post("/team/handin", headers=_headers("t-alice"),
                                json={"assignment_id": "devoir"})
        assert incomplete.status_code == 400
        assert "matrac_lib.c" in incomplete.json()["error"]
        assert fake.handins == {}

        fake.documents[("e1", "dev-b")] = {"lib.c": "double f(void){return 1;}\n"}
        record = client.post("/team/handin", headers=_headers("t-alice"),
                             json={"assignment_id": "devoir"})
        assert record.status_code == 200, record.text
        assert sorted(record.json()["files"]) == ["Devoir/main.c",
                                                   "Devoir/matrac_lib.c"]
        again = client.post("/team/handin", headers=_headers("t-cleo"),
                             json={"assignment_id": "devoir"})
        assert again.status_code == 200
        assert list(fake.handins) == [("devoir", "e1")]
        assert fake.handins[("devoir", "e1")]["submitted_by"] == "sub-cleo"
        cleo_context = client.get("/team/context?assignment=devoir",
                                   headers=_headers("t-cleo")).json()
        assert cleo_context["submission"]["submitted_at"]
        assert client.get("/team/context?assignment=devoir",
                          headers=_headers("t-bob")).json()["submission"] == {}


def test_the_handin_closes_at_the_deadline():
    with assignment_deployment(deadline="2020-01-01T00:00:00-05:00") as (client, fake, _):
        fake.documents[("e1", "dev-a")] = {"main.c": "x\n"}
        fake.documents[("e1", "dev-b")] = {"lib.c": "y\n"}
        r = client.post("/team/handin", headers=_headers("t-alice"),
                        json={"assignment_id": "devoir"})
        assert r.status_code == 403 and "date de remise" in r.json()["error"]
        assert fake.handins == {}
        assert client.get("/team/handin.zip?assignment=devoir",
                          headers=_headers("t-alice")).status_code == 200
        view = client.get("/team/context?assignment=devoir",
                         headers=_headers("t-alice")).json()
        assert view["assignment"]["deadline_passed"] is True


def test_an_assignment_exercise_grants_no_xp_but_keeps_the_state():
    with assignment_deployment() as (client, fake, tmp):
        _verdict("dev-a", "d" * 32, {"status": "ok", "total": 2, "passed": 2})
        assert client.get("/r/" + "d" * 32).status_code == 200
        assert fake.states[("sub-alice", "dev-a")] == "solved"
        assert fake.practice[("sub-alice", "dev-a")][0] == 1
        assert fake.xp == {} and fake.achievement == {}
        _verdict("tp2-ex3", "e" * 32, {"status": "ok", "total": 1, "passed": 1})
        client.get("/r/" + "e" * 32)
        assert fake.xp, "an ordinary exercise must still grant XP"


def test_the_team_roster_is_for_the_teacher_only_and_names_nobody():
    with assignment_deployment() as (client, _, _):
        refused = client.get("/team/roster?assignment=devoir",
                            headers=_headers("t-alice"))
        assert refused.status_code == 403
        r = client.get("/team/roster?assignment=devoir",
                       headers=_headers("t-prof"))
        assert r.status_code == 200, r.text
        assert "sub-" not in r.text, r.text
        teams = {e["team_id"]: e for e in r.json()["teams"]}
        assert teams["e1"]["members"] == 2 and teams["e1"]["group_number"] == 4
        assert teams["e2"]["members"] == 1


def test_a_silent_database_returns_503_and_no_document():
    with assignment_deployment() as (client, fake, _):
        fake.read_team_document = lambda *_: None
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_headers("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}
        fake.team_roster = lambda *_: None
        assert client.get("/team/context?assignment=devoir",
                          headers=_headers("t-alice")).status_code == 503


def _hello(socket, token, exercise="dev-a", assignment="devoir"):
    socket.send_json({"t": "hello", "token": token, "assignment": assignment,
                      "exercise": exercise})


def _close_code(client, send):
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/team/live") as socket:
            send(socket)
            socket.receive_json()
        return None
    except WebSocketDisconnect as exc:
        return exc.code


def test_the_socket_refuses_before_relaying():
    with assignment_deployment() as (client, fake, _):
        collab.reset()
        assert _close_code(
            client, lambda s: s.send_json({"t": "update", "d": "x"})) == 4400
        assert _close_code(client, lambda s: s.send_text("pas du json")) == 4400
        assert _close_code(client, lambda s: _hello(s, "t-inconnu")) == 4401
        fake.teams.pop(("devoir", "sub-bob"))
        assert _close_code(client, lambda s: _hello(s, "t-bob")) == 4403
        assert _close_code(
            client, lambda s: _hello(s, "t-alice", exercise="tp2-ex3")) == 4403
        collab.reset()


def test_two_teammates_see_each_other_and_the_other_team_sees_nothing():
    with assignment_deployment() as (client, fake, _):
        collab.reset()
        with client.websocket_connect("/team/live") as alice:
            _hello(alice, "t-alice")
            ready_alice = alice.receive_json()
            assert ready_alice["t"] == "ready"
            assert ready_alice["peers"] == 0 and ready_alice["me"] == "m1"
            assert ready_alice["epoch"]
            assert alice.receive_json()["t"] == "presence"
            with client.websocket_connect("/team/live") as cleo:
                _hello(cleo, "t-cleo")
                ready_cleo = cleo.receive_json()
                assert ready_cleo["peers"] == 1 and ready_cleo["me"] == "m2"
                assert ready_cleo["epoch"] == ready_alice["epoch"]
                assert cleo.receive_json()["t"] == "presence"
                assert alice.receive_json() == {"t": "presence",
                                                "online": ["m1", "m2"]}
                with client.websocket_connect("/team/live") as bob:
                    _hello(bob, "t-bob")
                    ready_bob = bob.receive_json()
                    assert ready_bob["peers"] == 0
                    assert ready_bob["epoch"] != ready_alice["epoch"]
                    assert bob.receive_json()["t"] == "presence"

                    alice.send_json({"t": "update", "d": "AAEC",
                                     "from": "m2", "token": "t-alice"})
                    received = cleo.receive_json()
                    assert received["d"] == "AAEC"
                    assert received["from"] == "m1"
                    assert "token" not in received

                    alice.send_json({"t": "cursor", "file": "main.c",
                                     "a": "AA", "h": "AQ"})
                    cursor = cleo.receive_json()
                    assert cursor["t"] == "cursor" and cursor["from"] == "m1"

                    bob.send_json({"t": "update", "d": "ZZZ"})
                    with client.websocket_connect("/team/live") as bob2:
                        _hello(bob2, "t-bob")
                        bob2.receive_json()
                        bob2.receive_json()
                        assert bob.receive_json()["t"] == "presence"
                        bob.send_json({"t": "update", "d": "BBBB"})
                        following = bob2.receive_json()
                        assert following == {"t": "update", "d": "BBBB", "from": "m1"}
        collab.reset()


def test_an_unknown_or_oversized_frame_does_not_get_through():
    from starlette.websockets import WebSocketDisconnect

    with assignment_deployment() as (client, _, _):
        collab.reset()
        with client.websocket_connect("/team/live") as alice:
            _hello(alice, "t-alice")
            alice.receive_json(); alice.receive_json()
            with client.websocket_connect("/team/live") as cleo:
                _hello(cleo, "t-cleo")
                cleo.receive_json(); cleo.receive_json()
                alice.receive_json()
                alice.send_json({"t": "evil", "d": "x"})
                alice.send_json({"t": "update", "d": "ok"})
                assert cleo.receive_json()["d"] == "ok"
            try:
                alice.receive_json()
                alice.send_text("x" * (config.TEAM_LIVE_MAX_FRAME + 1))
                alice.receive_json()
                raise AssertionError("an out-of-bounds frame was accepted")
            except WebSocketDisconnect as exc:
                assert exc.code == 4400
        collab.reset()


def test_the_socket_refuses_an_unknown_origin():
    from starlette.websockets import WebSocketDisconnect

    with assignment_deployment() as (client, _, _):
        collab.reset()
        try:
            with client.websocket_connect(
                    "/team/live", headers={"Origin": UNKNOWN_ORIGIN}) as socket:
                socket.receive_json()
            raise AssertionError("unknown origin accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 4403
        with client.websocket_connect("/team/live",
                                      headers={"Origin": KNOWN_ORIGIN}) as socket:
            _hello(socket, "t-alice")
            assert socket.receive_json()["t"] == "ready"
        collab.reset()


def test_my_team_is_readable_before_the_assignment_opens():
    with assignment_deployment() as (client, fake, tmp):
        published = _publish(tmp, ASSIGNMENT, _assignment_json())
        root = os.path.join(tmp, "content")
        _write_content(root, ASSIGNMENT, assignment=dict(
            _assignment_json(), release={"state": "scheduled",
                                     "available_from": "2099-10-16T00:00:00-04:00"}))
        import content_catalog as content_catalogue
        import publish_content
        publish_content.publish(content_catalogue.discover(root), published)

        for path in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            assert client.get(path, headers=_headers("t-alice")).status_code == 404, path

        r = client.get("/team/mine", headers=_headers("t-alice"))
        assert r.status_code == 200, r.text
        [team] = r.json()["teams"]
        assert team["label"] == "Équipe 1" and team["group_number"] == 4
        assert team["number"] == 1
        assert team["access"] == "scheduled"
        assert team["available_from"].startswith("2099-10-16")
        assert [m["id"] for m in team["members"]] == ["m1", "m2"]
        assert [m["you"] for m in team["members"]] == [True, False]
        assert "sub-" not in r.text, r.text
        assert "sources" not in r.text and "revision" not in r.text

        fake.teams.pop(("devoir", "sub-bob"))
        empty = client.get("/team/mine", headers=_headers("t-bob"))
        assert empty.status_code == 200 and empty.json() == {"teams": []}
        assert client.get("/team/mine").status_code == 401


def test_my_team_reports_an_outage_instead_of_inventing_an_absence():
    with assignment_deployment() as (client, fake, _):
        fake.team_memberships = lambda *_: None
        r = client.get("/team/mine", headers=_headers("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}


@contextlib.contextmanager
def choice_deployment(opened=False):
    base = FakeDatabase()
    assignment = _assignment_json()
    if not opened:
        assignment = dict(assignment, release={
            "state": "scheduled",
            "available_from": "2099-10-16T00:00:00-04:00"})
    with context(tokens=TEAM_TOKENS, moderators=("sub-prof",), base=base,
                  exercises=ASSIGNMENT, assignment=assignment) as (c, fake, tmp):
        for account in ("sub-alice", "sub-bob", "sub-cleo"):
            fake.forum_write_profile(account + "-p", account, None, 4,
                                     False, False)
        yield c, fake, tmp


def test_teams_are_chosen_from_a_numbered_list():
    with choice_deployment() as (client, fake, _):
        view = client.get("/team/available?assignment=devoir",
                         headers=_headers("t-alice"))
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["group_number"] == 4 and body["mine"] is None
        assert [e["number"] for e in body["teams"]] == [1, 2, 3, 4, 5, 6]
        assert body["teams"][0] == {"number": 1, "name": "Équipe 1",
                                     "members": 0, "max": 4, "full": False}
        assert "sub-" not in view.text and "Coéquipier" not in view.text

        joined = client.post("/team/join", headers=_headers("t-alice"),
                           json={"assignment_id": "devoir", "number": 3})
        assert joined.status_code == 200, joined.text
        assert joined.json()["mine"] == 3
        assert joined.json()["teams"][2]["members"] == 1
        assert fake.teams[("devoir", "sub-alice")] == "g04-e03"

        again = client.post("/team/join", headers=_headers("t-alice"),
                             json={"assignment_id": "devoir", "number": 4})
        assert again.status_code == 409 and "quitte-la" in again.json()["error"]

        for number in (0, 7, 999):
            r = client.post("/team/join", headers=_headers("t-bob"),
                            json={"assignment_id": "devoir", "number": number})
            assert r.status_code == 404, (number, r.status_code)
            assert "il y en a 6" in r.json()["error"]


def test_a_full_team_refuses_the_next_seat():
    with choice_deployment() as (client, fake, _):
        fake.register("devoir", "g04-e02", ["a", "b", "c", "d"],
                      group_number=4, number=2)
        r = client.post("/team/join", headers=_headers("t-alice"),
                        json={"assignment_id": "devoir", "number": 2})
        assert r.status_code == 409, r.text
        assert "complète (4 places)" in r.json()["error"]
        view = client.get("/team/available?assignment=devoir",
                         headers=_headers("t-alice")).json()
        assert view["teams"][1]["full"] is True


def test_teams_can_change_while_the_assignment_is_closed():
    with choice_deployment() as (client, fake, _):
        client.post("/team/join", headers=_headers("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        left = client.post("/team/leave", headers=_headers("t-alice"),
                            json={"assignment_id": "devoir"})
        assert left.status_code == 200 and left.json()["mine"] is None
        assert ("g04-e01", "devoir") in fake.team_meta
        assert client.post("/team/join", headers=_headers("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 5}).json()["mine"] == 5
        client.post("/team/leave", headers=_headers("t-alice"),
                    json={"assignment_id": "devoir"})
        assert client.post("/team/leave", headers=_headers("t-alice"),
                           json={"assignment_id": "devoir"}).status_code == 404


def test_opening_the_assignment_freezes_the_teams():
    with choice_deployment(opened=True) as (client, fake, _):
        for path, body in (("/team/join", {"assignment_id": "devoir",
                                              "number": 1}),
                              ("/team/leave", {"assignment_id": "devoir"})):
            r = client.post(path, headers=_headers("t-alice"), json=body)
            assert r.status_code == 409, (path, r.text)
            assert "figées" in r.json()["error"]
        assert client.get("/team/available?assignment=devoir",
                          headers=_headers("t-alice")).status_code == 409
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_headers("t-alice"))
        assert r.status_code == 403 and "enseignant" in r.json()["error"]

    with choice_deployment() as (client, fake, _):
        assert client.post("/team/join", headers=_headers("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 1}).status_code == 200
        assert client.get("/team/document?assignment=devoir&ex=dev-a",
                          headers=_headers("t-alice")).status_code == 404


def test_without_a_profile_group_the_list_says_what_to_do():
    with choice_deployment() as (client, fake, _):
        fake.profiles.pop("sub-bob", None)
        r = client.get("/team/available?assignment=devoir",
                       headers=_headers("t-bob"))
        assert r.status_code == 409, r.text
        assert "Mon identité" in r.json()["error"]


def test_two_groups_each_have_their_own_team_number_1():
    with choice_deployment() as (client, fake, _):
        fake.forum_write_profile("p6", "sub-bob", None, 6, False, False)
        client.post("/team/join", headers=_headers("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        client.post("/team/join", headers=_headers("t-bob"),
                    json={"assignment_id": "devoir", "number": 1})
        assert fake.teams[("devoir", "sub-alice")] == "g04-e01"
        assert fake.teams[("devoir", "sub-bob")] == "g06-e01"
        view4 = client.get("/team/available?assignment=devoir",
                          headers=_headers("t-alice")).json()
        view6 = client.get("/team/available?assignment=devoir",
                          headers=_headers("t-bob")).json()
        assert view4["group_number"] == 4 and view6["group_number"] == 6
        assert view4["teams"][0]["members"] == 1
        assert view6["teams"][0]["members"] == 1, "both count 1, separately"


def test_choosing_a_team_opens_no_document():
    with choice_deployment() as (client, fake, _):
        r = client.post("/team/join", headers=_headers("t-alice"),
                        json={"assignment_id": "devoir", "number": 1})
        assert "sources" not in r.text and "revision" not in r.text
        for path in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            assert client.get(path, headers=_headers("t-alice")).status_code == 404
        assert _close_code(client, lambda s: _hello(s, "t-alice")) == 4403
        collab.reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    skipped = 0
    for fn in tests:
        try:
            fn()
        except RuntimeError as e:
            if "flock unavailable" not in str(e):
                raise
            skipped += 1
            print("skip " + fn.__name__ + " (no flock outside POSIX)")
            continue
        print("ok   " + fn.__name__)
    print("\n%d checks passed%s."
          % (len(tests) - skipped,
             ", %d skipped outside POSIX" % skipped if skipped else ""))
