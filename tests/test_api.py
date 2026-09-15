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
import policy as politique  # noqa: E402
from services import collab  # noqa: E402
from services import forum_live  # noqa: E402
from services import quotas  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
INCONNUE = "https://mechant.example"

client = TestClient(main.app)


def _modules_avec_etat():
    return [m for m in list(sys.modules.values())
            if getattr(m, "state", None) is state]


class BaseSimulee:
    STATUSES = ("attempted", "solved")
    THEMES = ("light", "dark")
    enabled = staticmethod(lambda: True)

    EMPTY_PROFILE = {"display_name": None, "group_number": None,
                   "display_name_public": False, "group_number_public": False,
                   "alias": None, "plate_frame": None,
                   "badges_public": False, "leaderboard_opt_in": False}

    def __init__(self):
        self.brouillons, self.etats, self.themes = {}, {}, {}
        self.blocsnotes = {}
        self.messages, self.profils = [], {}
        self.pratique, self.jobs = {}, set()
        self.evenements, self.xp, self.succes = {}, {}, {}
        self.faits = []
        self.utiles = {}
        self.retenus = {}
        self.equipes = {}
        self.equipes_meta = {}
        self.verrous = {}
        self.documents = {}
        self.revisions = []
        self.remises = {}
        self.horloge = 1000.0

    def read_resume(self, user, ex):
        return self.brouillons.get((user, ex))

    def write_draft(self, user, ex, sources):
        self.brouillons[(user, ex)] = sources
        return True

    def read_states(self, user):
        return [{"exercise_id": ex, "status": s}
                for (u, ex), s in self.etats.items() if u == user]

    def write_state(self, user, ex, status, sources):
        self.etats[(user, ex)] = status
        return True

    def read_scratch(self, user):
        return self.blocsnotes.get(user, "")

    def write_scratch(self, user, code):
        self.blocsnotes[user] = code
        return True

    def read_theme(self, user):
        return self.themes.get(user, "")

    def write_theme(self, user, theme):
        self.themes[user] = theme
        return True

    def forget(self, user):
        for table in (self.brouillons, self.etats, self.themes, self.profils):
            for cle in [k for k in table if (k[0] if isinstance(k, tuple) else k) == user]:
                del table[cle]
        self.messages = [m for m in self.messages if m["account"] != user]
        for cle in [k for k in self.equipes if k[1] == user]:
            del self.equipes[cle]
        self.revisions = [r for r in self.revisions if r["account"] != user]
        return True

    def inscrire(self, assignment_id, team_id, comptes, group_number=4,
                 label=None, number=1):
        self.equipes_meta[(team_id, assignment_id)] = {
            "group_number": group_number, "number": number,
            "label": label or ("Équipe %d" % number)}
        for compte in comptes:
            self.equipes[(assignment_id, compte)] = team_id

    def _meta(self, team_id, assignment_id):
        return self.equipes_meta.setdefault(
            (team_id, assignment_id),
            {"group_number": 4, "number": 1, "label": "Équipe 1"})

    def _membres(self, assignment_id, team_id):
        return [compte for (devoir, compte), equipe in sorted(self.equipes.items())
                if devoir == assignment_id and equipe == team_id]

    def team_of(self, user, assignment_id):
        team_id = self.equipes.get((assignment_id, user))
        if team_id is None:
            return None
        meta = self._meta(team_id, assignment_id)
        return {"team_id": team_id, "assignment_id": assignment_id,
                "group_number": meta["group_number"], "number": meta["number"],
                "label": meta["label"]}

    def team_join(self, user, assignment_id, team_id, group_number, number,
                  label, taille_max):
        if (assignment_id, user) in self.equipes:
            return None
        if len(self._membres(assignment_id, team_id)) >= taille_max:
            return None
        self.equipes_meta.setdefault(
            (team_id, assignment_id),
            {"group_number": group_number, "number": number, "label": label})
        self.equipes[(assignment_id, user)] = team_id
        return team_id

    def team_leave(self, user, assignment_id):
        self.equipes.pop((assignment_id, user), None)
        return True

    def team_counts(self, assignment_id, group_number):
        lignes = [{"number": meta["number"], "team_id": team_id,
                   "label": meta["label"],
                   "members": len(self._membres(devoir, team_id))}
                  for (team_id, devoir), meta in self.equipes_meta.items()
                  if devoir == assignment_id
                  and meta["group_number"] == group_number]
        return sorted(lignes, key=lambda ligne: ligne["number"])

    def team_memberships(self, user):
        lignes = []
        for (devoir, compte), equipe in sorted(self.equipes.items()):
            if compte != user:
                continue
            meta = self._meta(equipe, devoir)
            lignes.append({"assignment_id": devoir, "team_id": equipe,
                           "group_number": meta["group_number"],
                           "number": meta["number"], "label": meta["label"]})
        return lignes

    def team_roster(self, assignment_id, team_id):
        return self._membres(assignment_id, team_id)

    def read_team_document(self, team_id, exercise_id):
        return dict(self.documents.get((team_id, exercise_id), {}))

    def write_team_document(self, team_id, exercise_id, user, sources,
                            revision_id, window):
        self.documents[(team_id, exercise_id)] = dict(sources)
        charge = json.dumps(sources)
        anciennes = [r for r in self.revisions
                     if r["team_id"] == team_id and r["exercise_id"] == exercise_id]
        recente = any(r["account"] == user and r["at"] > self.horloge - window
                      for r in anciennes)
        identique = bool(anciennes) and anciennes[-1]["sources"] == charge
        if not recente and not identique:
            self.revisions.append({
                "revision_id": revision_id, "team_id": team_id,
                "exercise_id": exercise_id, "account": user,
                "sources": charge, "at": self.horloge})
        return True

    def read_team_revisions(self, team_id, exercise_id, limit):
        lignes = [r for r in self.revisions
                  if r["team_id"] == team_id and r["exercise_id"] == exercise_id]
        return [{"revision_id": r["revision_id"], "account": r["account"],
                 "created_at": "2026-09-07T14:0%d" % (i % 10),
                 "bytes": len(r["sources"])}
                for i, r in enumerate(reversed(lignes))][:limit]

    def read_team_revision(self, team_id, revision_id):
        for r in self.revisions:
            if r["revision_id"] == revision_id and r["team_id"] == team_id:
                return json.loads(r["sources"])
        return {}

    def write_team_submission(self, assignment_id, team_id, user, files):
        self.remises[(assignment_id, team_id)] = {
            "submitted_by": user, "files": files,
            "submitted_at": "2026-09-07T15:00Z"}
        return True

    def read_team_submission(self, assignment_id, team_id):
        remise = self.remises.get((assignment_id, team_id))
        if remise is None:
            return {}
        return {"submitted_by": remise["submitted_by"],
                "submitted_at": remise["submitted_at"]}

    def read_teams(self, assignment_id):
        lignes = []
        for (team_id, devoir), meta in sorted(self.equipes_meta.items()):
            if devoir != assignment_id:
                continue
            lignes.append({"team_id": team_id,
                           "group_number": meta["group_number"],
                           "label": meta["label"],
                           "members": len(self.team_roster(devoir, team_id))})
        return lignes

    def read_practice_summary(self, user):
        return [{"exercise_id": ex, "attempts": n, "successes": r}
                for (u, ex), (n, r) in self.pratique.items() if u == user]

    def write_practice_attempt(self, user, job_id, ex, result):
        if job_id not in self.jobs:
            self.jobs.add(job_id)
            n, r = self.pratique.get((user, ex), (0, 0))
            gagne = (result.get("total", 0) > 0
                     and result.get("passed") == result.get("total"))
            self.pratique[(user, ex)] = (n + 1, r + int(gagne))
        return True

    def grant_first_solve(self, user, ex, event_id, amount, reason, policy,
                          payload, daily_cap):
        if (user, event_id) in self.evenements:
            return None
        self.evenements[(user, event_id)] = payload
        self.faits.append({"account": user, "type": "ExerciceReussi",
                           "exercise_id": ex, "payload": payload})
        deja = sum(t["amount"] for (u, _), t in self.xp.items() if u == user)
        self.xp[(user, event_id)] = {
            "exercise_id": ex, "amount": max(min(amount, daily_cap - deja), 0),
            "reason": reason, "granted_at": "2026-09-04"}
        return self.xp[(user, event_id)]["amount"]

    def record_event(self, user, event_id, kind, ex, policy, payload):
        if (user, event_id) in self.evenements:
            return None
        self.evenements[(user, event_id)] = payload
        self.faits.append({"account": user, "type": kind,
                           "exercise_id": ex, "payload": payload})
        return event_id

    def read_events(self, user, kind, limit=500):
        return [{"exercise_id": fait["exercise_id"], "payload": fait["payload"]}
                for fait in reversed(self.faits)
                if fait["account"] == user and fait["type"] == kind][:limit]

    def unlock(self, user, ids, event_id, policy):
        for succes_id in ids:
            self.succes.setdefault((user, succes_id),
                                   {"id": succes_id, "unlocked_at": "2026-09-04",
                                    "policy": policy})
        return True

    def read_practice_days(self, user, days):
        n = sum(a for (u, _), (a, _) in self.pratique.items() if u == user)
        return [{"date": "2026-09-04", "attempts": n}] if n else []

    def read_unlock_rates(self):
        compte = {}
        for (_, succes_id) in self.succes:
            compte[succes_id] = compte.get(succes_id, 0) + 1
        return compte, len({u for (u, _) in self.pratique})

    def leaderboard_rows(self, group_number, days, staff=()):
        self._staff = set(staff or ())
        rows = []
        for compte, profil in self.profils.items():
            if not profil.get("leaderboard_opt_in"):
                continue
            if group_number is not None and profil.get("group_number") != group_number:
                continue
            if compte in self._staff:
                continue
            n = sum(1 for (u, _) in self.xp if u == compte)
            rows.append({"account": compte, "alias": profil.get("alias"),
                         "group_number": profil.get("group_number"),
                         "recent": n, "lifetime": n})
        return rows

    def forum_taken_aliases(self):
        return {p["alias"] for p in self.profils.values() if p.get("alias")}

    def read_progress(self, user):
        mien = lambda t: [v for (u, _), v in sorted(t.items()) if u == user]  # noqa: E731
        return {"xp": sum(t["amount"] for t in mien(self.xp)),
                "achievements": mien(self.succes), "transactions": mien(self.xp)}

    def _vue_message(self, m, reader):
        return dict(m, retained=self.retenus.get(m["id"], False),
                    upvotes=sum(1 for (i, _), v in self.utiles.items()
                                if i == m["id"] and v == 1),
                    downvotes=sum(1 for (i, _), v in self.utiles.items()
                                  if i == m["id"] and v == -1),
                    my_vote=self.utiles.get((m["id"], reader or ""), 0))

    def forum_thread(self, ex, limite, reader=None):
        racines = [m["id"] for m in self.messages
                   if m["exercise_id"] == ex and not m.get("reply_to")][-limite:]
        gardes = set(racines)
        return [self._vue_message(m, reader) for m in self.messages
                if m["exercise_id"] == ex
                and (m["id"] in gardes or m.get("reply_to") in gardes)]

    def forum_thread_of(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["exercise_id"]
        return ""

    def forum_conversation(self, mid, reader=None):
        cible = next((m for m in self.messages if m["id"] == mid), None)
        if cible is None:
            return None, []
        racine = cible.get("reply_to") or cible["id"]
        vus = [self._vue_message(m, reader) for m in self.messages
               if m["id"] == racine or m.get("reply_to") == racine]
        return (cible["exercise_id"], vus) if vus else (None, [])

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
            racine = m.get("reply_to") or m["id"]
            hits.append({"id": m["id"], "exercise_id": m["exercise_id"],
                         "extrait": m["text"][:240],
                         "created_at": m["created_at"],
                         "upvotes": sum(1 for (i, _), v in self.utiles.items()
                                        if i == m["id"] and v == 1),
                         "replies": sum(1 for r in self.messages
                                        if r.get("reply_to") == racine)})
        return hits[:limit]

    def forum_top(self, hours, limit):
        roots = [m for m in self.messages
                 if not m.get("reply_to") and not m["hidden"]]
        rows = [{"id": m["id"], "exercise_id": m["exercise_id"],
                 "text": m["text"], "created_at": m["created_at"],
                 "visibility": m.get("visibility") or "thread",
                 "step": m.get("step"), "blocked_kind": m.get("blocked_kind"),
                 "upvotes": sum(1 for (i, _), v in self.utiles.items()
                                if i == m["id"] and v == 1),
                 "replies": sum(1 for r in self.messages
                                if r.get("reply_to") == m["id"])}
                for m in roots]
        return sorted(rows, key=lambda r: -r["upvotes"])[:limit]

    def forum_post(self, mid, ex, user, texte, step=None, blocked_kind=None,
                   visibility="thread"):
        self.messages.append({"id": mid, "exercise_id": ex, "account": user,
                              "text": texte, "hidden": False,
                              "step": step, "blocked_kind": blocked_kind,
                              "visibility": visibility, "reply_to": None,
                              "created_at": "2026-09-04"})
        return True

    def forum_reply(self, mid, ex, user, texte, target):
        for m in self.messages:
            if m["id"] == target and m["exercise_id"] == ex:
                self.messages.append(
                    {"id": mid, "exercise_id": ex, "account": user,
                     "text": texte, "hidden": False, "step": None,
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
                self.utiles[(mid, user)] = value
                return [mid]
        return []

    def forum_unvote(self, mid, user):
        return [mid] if self.utiles.pop((mid, user), None) is not None else []

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
        avant = len(self.messages)
        self.messages = [m for m in self.messages
                         if not (m["id"] == mid and m["account"] == user)]
        return len(self.messages) < avant

    def forum_report(self, mid, user):
        return True

    def forum_report_name(self, mid, user):
        return True

    def forum_reports(self, limite):
        return []

    def forum_reported_names(self, limite):
        return []

    def forum_moderate(self, aid, mid, moderateur, action):
        for m in self.messages:
            if m["id"] == mid:
                if action in ("retain", "unretain"):
                    self.retenus[mid] = (action == "retain")
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
        return self.profils.get(user, dict(self.EMPTY_PROFILE))

    def forum_profiles(self, users):
        return {u: self.profils[u] for u in users if u in self.profils}

    def forum_write_profile(self, pid, user, pseudo, groupe, pseudo_public,
                            groupe_public, set_by_moderator=False, alias=None,
                            plate_frame=None, badges_public=False,
                            leaderboard_opt_in=False):
        self.profils[user] = {"display_name": pseudo, "group_number": groupe,
                              "display_name_public": pseudo_public,
                              "group_number_public": groupe_public,
                              "alias": alias, "plate_frame": plate_frame,
                              "badges_public": badges_public,
                              "leaderboard_opt_in": leaderboard_opt_in}
        return True


CONTENU = [
    ("tp2-ex3", "TP2 ex.3", "io", ["submission.c"], ["variables"], "foundation"),
    ("tp5-mod", "TP5 module", "unity", ["calendrier.h", "calendrier.c"],
     ["structs"], "intermediate"),
    ("quiz1", "Quiz 1", "quiz", [], ["variables"], "intro"),
    ("verif-tp2", "Vérification TP2", "quiz", [], ["variables"], "foundation"),
]


DEVOIR = CONTENU + [
    ("dev-a", "Devoir : partie A", "io", ["main.c"], ["variables"], "advanced"),
    ("dev-b", "Devoir : partie B", "unity", ["lib.h", "lib.c"],
     ["variables"], "advanced"),
]


def _devoir_json(deadline=None, team=True):
    devoir = {"schema_version": 1, "id": "devoir", "title": "Le devoir",
              "description": "Trois ou quatre, une seule remise.",
              "items": ["dev-a", "dev-b"], "release": {"state": "available"},
              "handin": {"root": "Devoir", "files": [
                  {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"},
                  {"name": "matrac_lib.c", "exercise_id": "dev-b",
                   "file": "lib.c"}]}}
    if team:
        devoir["team"] = {"min": 3, "max": 4, "count": 6}
    if deadline:
        devoir["deadline"] = deadline
    return devoir


def _ecrire_contenu(racine, exercices=CONTENU, release=None, devoir=None):
    def ecrire(chemin, valeur):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(valeur, fh)

    competences = sorted({c for _, _, _, _, skills, _ in exercices for c in skills})
    ecrire(os.path.join(racine, "catalog.json"),
           {"schema_version": 1, "skills": competences})
    for identifiant, titre, mode, fichiers, skills, difficulte in exercices:
        dossier = os.path.join(racine, "exercises", identifiant)
        ecrire(os.path.join(dossier, "exercise.json"),
               {"schema_version": 1, "id": identifiant, "title": titre,
                "skills": skills, "difficulty": difficulte,
                "verification": identifiant.startswith("verif-"),
                "release": release or {"state": "available"}})
        with open(os.path.join(dossier, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        assessment = os.path.join(dossier, "assessment")
        if mode == "io":
            ecrire(os.path.join(assessment, "io.json"),
                   {"cases": [{"stdin": "1\n", "expect": [1]}]})
        elif mode == "unity":
            ecrire(os.path.join(assessment, "unity.json"), {})
            with open(os.path.join(assessment, "test_x.c"), "w",
                      encoding="utf-8") as fh:
                fh.write("void test_x(void) {}\n")
        else:
            ecrire(os.path.join(assessment, "quiz.json"),
                   {"questions": [{"id": "q1", "type": "int", "text": "2+2 ?",
                                   "answer": 4}]})
        if fichiers:
            ecrire(os.path.join(dossier, "public", "files.json"),
                   {"files": [{"name": nom, "template": ""} for nom in fichiers]})
    if devoir is not None:
        ecrire(os.path.join(racine, "assignments", "devoir.json"), devoir)


def _publier(tmp, exercices=CONTENU, devoir=None):
    import content_catalog as content_catalogue
    import publish_content
    racine = os.path.join(tmp, "content")
    publie = os.path.join(tmp, "published")
    _ecrire_contenu(racine, exercices, devoir=devoir)
    publish_content.publish(content_catalogue.discover(racine), publie)
    return publie


@contextlib.contextmanager
def contexte(*, jetons=None, moderateurs=(), forum_actif=True, base=None,
             groupes=(4, 6), exercices=CONTENU, devoir=None, console=True,
             pont="", webhook=""):
    tmp = tempfile.mkdtemp()
    spool, page, resultats = (os.path.join(tmp, n) for n in ("spool", "web", "results"))
    for chemin in (spool, page, resultats):
        os.makedirs(chemin)
    publie = _publier(tmp, exercices, devoir)

    faux = base if base is not None else BaseSimulee()
    modules = _modules_avec_etat()
    garde_etat = [(m, m.state) for m in modules]
    garde_config = {n: getattr(config, n) for n in
                    ("PUBLISHED", "SPOOL", "RESULTS", "PAGE", "KEY", "OIDC_ISSUER",
                     "OIDC_CLIENT_ID", "FORUM_MODERATORS", "FORUM_GROUPS",
                     "SCRATCH", "DISCORD_BRIDGE_KEY", "DISCORD_WEBHOOK")}
    garde_secu = (security.current_user, security.current_name)
    garde_quotas = (deps.quota, deps.signed_in_quota, deps.state_quota,
                    deps.forum_quota, deps.presence, deps.scratch_quota)

    for m in modules:
        m.state = faux
    config.SPOOL, config.PAGE, config.RESULTS = spool, page, resultats
    config.PUBLISHED = publie
    config.KEY = "cle-de-session"
    config.OIDC_ISSUER = "https://auth.exemple.com"
    config.OIDC_CLIENT_ID = "ctester"
    config.FORUM_MODERATORS = frozenset(moderateurs) if forum_actif else frozenset()
    config.FORUM_GROUPS = tuple(groupes)
    config.SCRATCH = console
    config.DISCORD_BRIDGE_KEY = pont
    config.DISCORD_WEBHOOK = webhook
    jetons = jetons or {}
    security.current_user = lambda entetes: jetons.get(
        entetes.get("Authorization", "").replace("Bearer ", ""))
    security.current_name = lambda entetes: ""
    deps.quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.state_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.presence = quotas.Presence()
    deps.scratch_quota = quotas.Quota(cooldown=0, hourly=100000)

    try:
        yield TestClient(main.create_app()), faux, tmp
    finally:
        for m, ancien in garde_etat:
            m.state = ancien
        for nom, valeur in garde_config.items():
            setattr(config, nom, valeur)
        security.current_user, security.current_name = garde_secu
        (deps.quota, deps.signed_in_quota, deps.state_quota, deps.forum_quota,
         deps.presence, deps.scratch_quota) = garde_quotas
        shutil.rmtree(tmp, ignore_errors=True)


def _contenu_v2(racine):
    def ecrire(chemin, valeur):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(valeur, fh)

    ecrire(os.path.join(racine, "catalog.json"), {"schema_version": 1, "skills": []})
    for identifiant, release in (("ouvert", {"state": "available"}),
                                 ("ferme", {"state": "scheduled",
                                            "available_from": "2099-01-01T00:00:00-05:00"})):
        exercice = os.path.join(racine, "exercises", identifiant)
        ecrire(os.path.join(exercice, "exercise.json"),
               {"schema_version": 1, "id": identifiant, "title": identifiant.title(),
                "release": release})
        with open(os.path.join(exercice, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        ecrire(os.path.join(exercice, "assessment", "io.json"),
               {"cases": [{"stdin": "1\\n", "expect": [1]}]})
        ecrire(os.path.join(exercice, "public", "files.json"),
               {"files": [{"name": "submission.c", "template": ""}]})
    ecrire(os.path.join(racine, "collections", "tp1.json"),
           {"schema_version": 1, "id": "tp1", "title": "TP 1",
            "items": ["ouvert", "ferme"], "release": {"state": "available"}})


def test_release_pilote_le_catalogue_et_ferme_le_reste():
    import content_catalog as content_catalogue
    import publish_content

    with contexte() as (c, _, tmp):
        racine, publie = os.path.join(tmp, "v2"), os.path.join(tmp, "releases")
        _contenu_v2(racine)
        publish_content.publish(content_catalogue.discover(racine), publie)
        config.PUBLISHED = publie

        catalog = c.get("/catalog.json").json()
        etats = {e["id"]: e["access"] for e in catalog["exercises"]}
        assert etats == {"ouvert": "available", "ferme": "scheduled"}, etats
        assert catalog["collections"][0]["items"] == ["ouvert", "ferme"]

        assert c.get("/tp/ouvert.json").json()["statement"] == "Consigne."
        assert c.get("/tp/ferme.json").status_code == 404

        corps = {"key": config.KEY, "files": {"submission.c": "int main(void){}"}}
        assert c.post("/submit", json=dict(corps, exercise_id="ferme")).status_code == 400
        assert c.post("/submit", json=dict(corps, exercise_id="ouvert")).status_code == 200

        config.PUBLISHED = ""
        assert c.get("/catalog.json").status_code == 404
        assert c.get("/tp/ouvert.json").status_code == 404
        assert c.post("/submit", json=dict(corps, exercise_id="ouvert")).status_code == 400


def _contenu_typst(racine, pages=2, ouvert_et_ferme=True):
    def ecrire(chemin, valeur):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(valeur, fh)

    ecrire(os.path.join(racine, "catalog.json"), {"schema_version": 1, "skills": []})
    etats = (("ouvert", {"state": "available"}),
             ("ferme", {"state": "scheduled",
                        "available_from": "2099-01-01T00:00:00-05:00"}))
    for identifiant, release in (etats if ouvert_et_ferme else etats[:1]):
        exercice = os.path.join(racine, "exercises", identifiant)
        ecrire(os.path.join(exercice, "exercise.json"),
               {"schema_version": 1, "id": identifiant, "title": identifiant.title(),
                "release": release})
        with open(os.path.join(exercice, "statement.typ"), "w", encoding="utf-8") as fh:
            fh.write("= Titre\n")
        ecrire(os.path.join(exercice, "assessment", "io.json"),
               {"cases": [{"stdin": "1\n", "expect": [1]}]})
        ecrire(os.path.join(exercice, "public", "files.json"),
               {"files": [{"name": "submission.c", "template": ""}]})
    ecrire(os.path.join(racine, "collections", "tp1.json"),
           {"schema_version": 1, "id": "tp1", "title": "TP 1",
            "items": [i for i, _ in (etats if ouvert_et_ferme else etats[:1])],
            "release": {"state": "available"}})


def _publier_typst(tmp, pages=2):
    import content_catalog as content_catalogue
    import publish_content

    racine, publie = os.path.join(tmp, "typ"), os.path.join(tmp, "typreleases")
    _contenu_typst(racine)
    modele = content_catalogue.discover(racine)
    rendus = {identifiant: {theme: [("<svg id='%s-%s-%d'/>" % (identifiant, theme, n)).encode()
                                    for n in range(1, pages + 1)]
                            for theme in ("dark", "light")}
              for identifiant in modele["exercises"]}
    publish_content.publish(modele, publie, renders=rendus)
    config.PUBLISHED = publie
    return publie


def test_une_page_d_enonce_typst_est_un_fichier_cacheable():
    with contexte() as (c, _, tmp):
        _publier_typst(tmp)

        r = c.get("/statement/ouvert/dark-1.svg")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/svg+xml", dict(r.headers)
        assert r.headers["cache-control"] == "no-cache", dict(r.headers)
        assert r.headers["etag"], dict(r.headers)
        assert r.content == b"<svg id='ouvert-dark-1'/>", r.content

        clair = c.get("/statement/ouvert/light-1.svg")
        assert clair.status_code == 200 and clair.content != r.content
        assert clair.headers["etag"] != r.headers["etag"], "deux corps, un ETag"

        assert c.get("/statement/ouvert/dark-2.svg").status_code == 200
        assert c.get("/statement/ouvert/dark-3.svg").status_code == 404

        detail = c.get("/tp/ouvert.json").json()
        assert detail["statement"] == "", detail
        assert detail["statement_format"] == "typst", detail
        assert detail["statement_pages"] == 2, detail
        assert "statements/" not in json.dumps(detail), detail


def test_une_page_d_enonce_refuse_tout_ce_qui_n_est_pas_une_page():
    with contexte() as (c, _, tmp):
        _publier_typst(tmp)
        for nom in ("dark-0.svg", "dark-17.svg", "sepia-1.svg", "dark-1.png",
                    "dark-1.svg.typ", "dark-1", "", "dark--1.svg",
                    "dark-01.svg", "DARK-1.svg",
                    "index.html", "statement.htm", "dark-1.html",
                    "..%2Fcatalog.json", "%2e%2e%2fcatalog.json",
                    "%2E%2E/catalog.json", "dark-1.svg%00.typ"):
            r = c.get("/statement/ouvert/" + nom)
            assert r.status_code == 404, (nom, r.status_code, r.text[:120])
        r = c.get("/statement/ouvert/../../catalog.json")
        assert str(r.url).endswith("/catalog.json"), str(r.url)
        assert c.get("/statement/inconnu/dark-1.svg").status_code == 404


def test_une_page_d_enonce_fermee_n_est_servie_qu_au_moderateur():
    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"},
                  moderateurs=["sub-prof"]) as (c, _, tmp):
        _publier_typst(tmp)

        assert c.get("/statement/ferme/dark-1.svg").status_code == 404
        assert c.get("/statement/ferme/dark-1.svg",
                     headers=auth("alice")).status_code == 404
        r = c.get("/statement/ferme/dark-1.svg", headers=auth("prof"))
        assert r.status_code == 200, r.text
        assert r.content == b"<svg id='ferme-dark-1'/>", r.content
        assert r.headers["cache-control"] == "no-store", dict(r.headers)
        assert "etag" not in r.headers, dict(r.headers)

        ouvert = c.get("/statement/ouvert/dark-1.svg", headers=auth("prof"))
        assert ouvert.headers["cache-control"] == "no-cache", dict(ouvert.headers)
        assert ouvert.headers["etag"], dict(ouvert.headers)


def test_un_enonce_markdown_repond_exactement_ce_qu_il_repondait():
    with contexte() as (c, _, tmp):
        racine, publie = os.path.join(tmp, "md"), os.path.join(tmp, "mdreleases")
        import content_catalog as content_catalogue
        import publish_content
        _contenu_v2(racine)
        publish_content.publish(content_catalogue.discover(racine), publie)
        config.PUBLISHED = publie

        detail = c.get("/tp/ouvert.json").json()
        assert detail == {"statement": "Consigne.",
                          "files": [{"name": "submission.c", "template": ""}]}, detail
        assert c.get("/statement/ouvert/dark-1.svg").status_code == 404


def test_la_csp_autorise_les_images_de_l_api_et_les_blobs():
    with contexte() as (c, _, tmp):
        config.PAGE = os.path.join(tmp, "web")
        with open(os.path.join(config.PAGE, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head></head><body></body></html>")
        r = c.get("/")
        politique = r.headers["content-security-policy"]
        directives = {d.split()[0]: d.split()[1:] for d in politique.split("; ")}
        assert "'self'" in directives["img-src"], politique
        assert "blob:" in directives["img-src"], politique
        assert config.API_ORIGIN in directives["img-src"], politique
        assert "data:" not in directives["img-src"], politique
        assert "*" not in directives["img-src"], politique


def test_les_dates_sont_pour_les_etudiants_et_l_enseignant_voit_quand_meme():
    import content_catalog as content_catalogue
    import publish_content

    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"},
                  moderateurs=["sub-prof"]) as (c, base, tmp):
        racine, publie = os.path.join(tmp, "v2"), os.path.join(tmp, "releases")
        _contenu_v2(racine)
        publish_content.publish(content_catalogue.discover(racine), publie)
        config.PUBLISHED = publie

        assert c.get("/tp/ferme.json").status_code == 404
        assert c.get("/tp/ferme.json", headers=auth("alice")).status_code == 404
        r = c.get("/tp/ferme.json", headers=auth("prof"))
        assert r.status_code == 200 and r.json()["statement"] == "Consigne.", r.text
        assert r.headers["cache-control"] == "no-store", dict(r.headers)
        assert "etag" not in r.headers, dict(r.headers)

        ouvert = c.get("/tp/ouvert.json", headers=auth("prof"))
        assert ouvert.headers["cache-control"] == "no-cache", dict(ouvert.headers)
        assert ouvert.headers["etag"], dict(ouvert.headers)

        corps = {"key": config.KEY, "files": {"submission.c": "int main(void){}"},
                 "exercise_id": "ferme"}
        assert c.post("/submit", json=corps).status_code == 400
        assert c.post("/submit", json=corps, headers=auth("alice")).status_code == 400
        r = c.post("/submit", json=corps, headers=auth("prof"))
        assert r.status_code == 200, r.text
        job = r.json()["id"]
        with open(os.path.join(config.SPOOL, job, "job.json"), encoding="utf-8") as fh:
            assert json.load(fh) == {"exercise_id": "ferme", "owner": "sub-prof"}

        with open(_sortie(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        assert c.get("/r/" + job).json()["status"] == "ok"
        assert base.etats[("sub-prof", "ferme")] == "solved", base.etats

        brouillon = {"exercise_id": "ferme", "files": {"submission.c": "int main(void){}"}}
        assert c.put("/brouillon", json=brouillon,
                     headers=auth("alice")).status_code == 400
        assert c.put("/brouillon", json=brouillon,
                     headers=auth("prof")).status_code == 200

        assert c.get("/etats", headers=auth("prof")).json()["moderator"] is True
        assert c.get("/etats", headers=auth("alice")).json()["moderator"] is False


def auth(nom):
    return {"Authorization": "Bearer " + nom}


def test_healthz_ne_touche_ni_base_ni_spool():
    r = client.get("/healthz")
    assert r.status_code == 200, r.status_code
    assert r.json() == {"ok": True}, r.json()


def test_cors_origine_connue_et_inconnue():
    r = client.get("/healthz", headers={"Origin": CONNUE})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)

    r = client.get("/healthz", headers={"Origin": INCONNUE})
    assert r.status_code == 200, r.status_code
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)

    assert "access-control-allow-credentials" not in r.headers

    r = client.get("/healthz", headers={"Origin": CONNUE + "/"})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)


def test_un_seul_vary_annoncant_les_deux_axes():
    r = client.get("/healthz", headers={"Origin": CONNUE})
    vary = r.headers.get("vary", "")
    assert vary == "Accept-Encoding, Origin", vary
    assert vary.count("Origin") == 1 and vary.count("Accept-Encoding") == 1, vary


def test_preflight_sur_toute_route_meme_inconnue():
    for chemin in ("/submit", "/forum", "/pas-encore-invente"):
        r = client.options(chemin, headers={"Origin": CONNUE})
        assert r.status_code == 204, (chemin, r.status_code)
        methodes = r.headers.get("access-control-allow-methods", "")
        assert "DELETE" in methodes, methodes
        assert r.headers.get("access-control-max-age") == "86400", dict(r.headers)
        assert r.headers.get("access-control-allow-origin") == CONNUE

    r = client.options("/submit", headers={"Origin": INCONNUE})
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)


def test_chemin_inconnu_reste_un_404():
    r = client.get("/pas-une-route")
    assert r.status_code == 404, r.status_code
    assert r.json() == {"error": "inconnu"}, r.json()


def test_documentation_automatique_eteinte():
    assert not config.DOCS, "CTESTER_DOCS ne doit pas être posé en production"
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(chemin).status_code == 404, chemin


def test_no_store_par_defaut_sur_les_donnees():
    assert client.get("/healthz").headers.get("cache-control") == "no-store"
    assert client.get("/rien").headers.get("cache-control") == "no-store"
    with contexte() as (c, _, _tmp):
        assert c.get("/catalog.json").headers.get("cache-control") == "no-cache"
        assert c.get("/oidc.json").headers.get("cache-control") == "no-store"


def test_pas_d_annonce_de_version_de_serveur():
    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert "server_header=False" in source
    assert "workers=1" in source


def test_borne_du_corps_des_deux_cotes():
    plafond = config.MAX_CODE + 4096
    with contexte() as (c, _, _tmp):
        corps = b'{"exercise_id": "tp2-ex3", "key": "x", "bourrage": "'
        corps += b"a" * (plafond - len(corps) - 2) + b'"}'
        assert len(corps) == plafond
        r = c.post("/submit", content=corps,
                   headers={"Content-Type": "application/json"})
        assert r.status_code != 413, (r.status_code, r.text)

        r = c.post("/submit", content=corps + b" ",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, r.status_code
        assert r.json() == {"error": "corps trop gros ou vide"}, r.json()


def test_corps_vide_ou_sans_longueur_annoncee():
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", content=b"",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)

        def flux():
            yield b'{"exercise_id": "tp2-ex3"}'

        r = c.post("/submit", content=flux(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)


def test_corps_malforme_ne_renvoie_pas_l_entree():
    with contexte() as (c, _, _tmp):
        secret = "MonMotDePasseColleParErreur"
        r = c.post("/submit", content=json.dumps([secret]).encode(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json() == {"error": "requête malformée"}, r.json()
        assert secret not in r.text, r.text


def test_cle_verifiee_avant_tout_autre_travail():
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "mauvaise", "exercise_id": "nexiste-pas"})
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "nexiste-pas"})
        assert r.status_code == 400, (r.status_code, r.text)


def test_cle_vide_du_serveur_refuse_tout():
    with contexte() as (c, _, _tmp):
        config.KEY = ""
        r = c.post("/submit", json={"key": "", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "int main(){}"}})
        assert r.status_code == 403, (r.status_code, r.text)


def test_taille_des_fichiers_des_deux_cotes():
    with contexte() as (c, _, _tmp):
        from services import catalog as catalogue
        entree = catalogue.find_exercise("tp2-ex3")
        enveloppe = len(json.dumps({"submission.c": ""}).encode())
        pile = "a" * (config.MAX_CODE - enveloppe)
        fichiers, message, code = catalogue.validate_files(
            entree, {"submission.c": pile})
        assert message is None, message
        assert len(json.dumps(fichiers).encode()) == config.MAX_CODE

        _, message, code = catalogue.validate_files(
            entree, {"submission.c": pile + "a"})
        assert code == 413 and message, (code, message)

        _, message, code = catalogue.validate_files(entree, ["pas", "un", "dict"])
        assert code == 400 and message == "fichiers manquants", (code, message)


def test_fichier_inattendu_est_refuse_pas_ignore():
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={
            "key": "cle-de-session", "exercise_id": "tp5-mod",
            "files": {"calendrier.h": "x", "calendrier.c": "y",
                      "secret.c": "z"}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert "secret.c" in r.json()["error"], r.json()


def test_soumission_entierement_blanche_est_refusee():
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "   \n\t  "}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json()["error"] == "soumission vide", r.json()


def test_quiz_bornes_du_nombre_et_de_la_longueur_des_reponses():
    with contexte() as (c, _, tmp):
        reponses = {"q%d" % i: "x" for i in range(600)}
        reponses["k" * 100] = "v" * 100
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": reponses})
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()["id"]
        with open(os.path.join(config.SPOOL, job, "answers.json"),
                  encoding="utf-8") as fh:
            ecrit = json.load(fh)
        assert len(ecrit) <= 500, len(ecrit)
        assert all(len(k) <= 64 and len(v) <= 64 for k, v in ecrit.items())


def test_quiz_sans_aucune_reponse_saisie():
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {"q1": "  ", "q2": ""}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1"})
        assert r.status_code == 400 and r.json() == {"error": "réponses manquantes"}, r.text


def test_identifiant_d_exercice_hors_forme():
    from services import catalog as catalogue
    with contexte() as (c, _, _tmp):
        assert catalogue.find_exercise("a" * 32) is None
        for hostile in ("../tps", "tp2/../../etc", "TP2-EX3", "tp2 ex3", ""):
            assert catalogue.find_exercise(hostile) is None, hostile
        assert c.get("/tp/..%2Fcatalog.json").status_code == 404
        assert c.get("/quiz/tp2-ex3.json").status_code == 404
        base, nom = catalogue.published_source(
            catalogue.find_exercise("tp2-ex3"), "detail")
        assert base == catalogue.release_dir()
        assert nom == os.path.join("exercises", "tp2-ex3.json"), nom


def test_quota_horaire_pile_et_un_de_trop():
    with contexte() as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=3)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        for i in range(3):
            assert c.post("/submit", json=charge).status_code == 200, i
        r = c.post("/submit", json=charge)
        assert r.status_code == 429, (r.status_code, r.text)
        assert r.json()["retry_after"] > 0, r.json()


def test_quota_par_compte_pas_par_ip_derriere_un_nat():
    with contexte(jetons={"alice": "sub-alice", "bob": "sub-bob"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=1)
        deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=1)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for nom in ("alice", "bob"):
            r = c.post("/submit", json=charge, headers={**auth(nom), **nat})
            assert r.status_code == 200, (nom, r.status_code, r.text)
        r = c.post("/submit", json=charge, headers={**auth("alice"), **nat})
        assert r.status_code == 429, r.status_code
        assert c.post("/submit", json=charge, headers=nat).status_code == 200


def test_quota_anonyme_par_poste_et_cadran_plus_court_connecte():
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=30, hourly=100)
        deps.signed_in_quota = quotas.Quota(cooldown=0, hourly=100)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for poste in ("p1", "p2"):
            r = c.post("/submit?poste=" + poste, json=charge, headers=nat)
            assert r.status_code == 200, (poste, r.status_code, r.text)
        assert c.post("/submit?poste=p1", json=charge, headers=nat).status_code == 429
        assert c.post("/submit?poste=p3", json=charge, headers=nat).status_code == 200
        assert c.post("/submit", json=charge, headers=nat).status_code == 200
        assert c.post("/submit", json=charge, headers=nat).status_code == 429
        for _ in range(3):
            r = c.post("/submit?poste=p1", json=charge,
                       headers={**auth("alice"), **nat})
            assert r.status_code == 200, (r.status_code, r.text)


def test_quota_ne_consomme_rien_sur_une_requete_refusee():
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.state_quota = quotas.Quota(cooldown=0, hourly=2)
        for _ in range(5):
            r = c.put("/brouillon", json={"exercise_id": "inconnu", "files": {}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.status_code
        for _ in range(2):
            r = c.put("/brouillon",
                      json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 200, (r.status_code, r.text)
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 429, (r.status_code, r.text)


def test_file_pleine_pile_sur_le_plafond():
    with contexte() as (c, _, _tmp):
        garde = config.QUEUE_MAX
        try:
            config.QUEUE_MAX = 2
            charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            assert c.post("/submit", json=charge).status_code == 200
            assert c.post("/submit", json=charge).status_code == 200
            r = c.post("/submit", json=charge)
            assert r.status_code == 503, (r.status_code, r.text)
        finally:
            config.QUEUE_MAX = garde


def test_presence_expire_pile_au_ttl():
    p = quotas.Presence()
    assert p.touch("a", 1000.0) == 1
    assert p.touch("a", 1000.0) == 1, "le même jeton ne compte pas deux fois"
    assert p.touch("b", 1000.0) == 2
    assert p.touch("c", 1000.0 + config.PRESENCE_TTL) == 1
    q = quotas.Presence()
    q.touch("a", 1000.0)
    assert q.touch("c", 1000.0 + config.PRESENCE_TTL - 1) == 2


def test_live_tronque_un_jeton_trop_long_au_lieu_de_refuser():
    with contexte() as (c, _, _tmp):
        r = c.get("/live?id=" + "z" * 500)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["n"] == 1, r.json()


def test_ordre_des_refus_forum_eteint_avant_jeton_absent():
    with contexte(forum_actif=False) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 503, (r.status_code, r.text)
        assert "discussions" in r.json()["error"], r.json()
    with contexte(moderateurs=["sub-prof"]) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 401, (r.status_code, r.text)


def test_role_de_moderation_recalcule_et_jamais_recu():
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, _, _tmp):
        assert c.get("/forum/moderation", headers=auth("prof")).status_code == 200
        r = c.get("/forum/moderation", headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/forum/moderation",
                   json={"id": "0" * 32, "action": "hide",
                         "moderateur": True, "account": "sub-prof"},
                   headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)


def test_aucune_route_n_accepte_un_identifiant_dans_le_corps():
    import schemas
    interdits = {"account", "sub", "owner", "user", "moderateur",
                 "set_by_moderator"}
    for nom in dir(schemas):
        modele = getattr(schemas, nom)
        champs = getattr(modele, "model_fields", None)
        if champs:
            fuite = interdits & set(champs)
            assert not fuite, (nom, fuite)

    jetons = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=jetons) as (c, base, _tmp):
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "a moi"},
                        "account": "sub-bob", "sub": "sub-bob"},
                  headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert base.brouillons == {("sub-alice", "tp2-ex3"):
                                   {"submission.c": "a moi"}}, base.brouillons


def test_aucun_sub_ne_franchit_la_frontiere_du_forum():
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, base, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "une question"},
               headers=auth("alice"))
        c.post("/forum/profil",
               json={"display_name": "Alice", "group_number": 4, "display_name_public": True,
                     "group_number_public": True}, headers=auth("alice"))
        r = c.get("/forum?ex=tp2-ex3", headers=auth("prof"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert "sub-alice" not in r.text and "sub-prof" not in r.text, r.text
        assert "Alice" in r.text, r.text


def test_forum_texte_des_deux_cotes_de_la_borne():
    from services import forum
    assert forum.forum_text("")[0] is None
    assert forum.forum_text("   \n ")[0] is None
    assert forum.forum_text("a")[0] == "a"
    assert forum.forum_text("a" * config.FORUM_MAX_CHARS)[0] is not None
    trop, message = forum.forum_text("a" * (config.FORUM_MAX_CHARS + 1))
    assert trop is None and str(config.FORUM_MAX_CHARS) in message, message


def test_forum_pseudo_bornes_et_noms_reserves():
    from services import forum
    assert forum.forum_display_name("a")[0] == "a"
    assert forum.forum_display_name("a" * config.FORUM_PSEUDO_MAX)[0] is not None
    assert forum.forum_display_name("a" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    for reserve in ("Vous", "PARTICIPANT", "Enseignant", "Équipe du cours",
                    "modérateur"):
        nom, message = forum.forum_display_name(reserve)
        assert nom is None and message, reserve


def test_forum_groupe_liste_fermee_et_champ_libre():
    from services import forum
    with contexte(groupes=(4, 6)) as (_c, _b, _tmp):
        assert forum.forum_group(4)[0] == 4
        assert forum.forum_group("6")[0] == 6
        assert forum.forum_group(5)[0] is None
        assert forum.forum_group(0)[0] is None
    with contexte(groupes=()) as (_c, _b, _tmp):
        assert forum.forum_group(1)[0] == 1
        assert forum.forum_group(99)[0] == 99
        assert forum.forum_group(0)[0] is None
        assert forum.forum_group(100)[0] is None
        assert forum.forum_group("douze")[0] is None


def test_identifiant_de_message_et_de_job_hors_forme():
    from routers.forum import MSG_RE
    from routers.submission import JOB_RE
    for motif in (MSG_RE, JOB_RE):
        assert motif.match("0" * 32)
        assert not motif.match("0" * 31)
        assert not motif.match("0" * 33)
        assert not motif.match("A" * 32)
        assert not motif.match("0" * 31 + "g")
    with contexte() as (c, _, _tmp):
        assert c.get("/r/pas-un-id").status_code == 400
        assert c.get("/r/" + "0" * 32).status_code == 404


def test_cocher_sans_ecrire_n_affiche_rien():
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, base, _tmp):
        r = c.post("/forum/profil",
                   json={"display_name": "", "group_number": None, "display_name_public": True,
                         "group_number_public": True}, headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        profil = base.profils["sub-alice"]
        assert profil["display_name_public"] is False, profil
        assert profil["group_number_public"] is False, profil


def test_base_muette_ne_devient_jamais_un_zero():
    base = BaseSimulee()
    base.read_progress = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "xp" not in r.text, r.text


def test_theme_vide_est_un_200_et_une_panne_un_503():
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        r = c.get("/preferences", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"theme": ""}, r.text
    base = BaseSimulee()
    base.read_theme = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        assert c.get("/preferences", headers=auth("alice")).status_code == 503


def test_ecriture_qui_echoue_ne_repond_pas_200():
    base = BaseSimulee()
    base.write_theme = lambda user, theme: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)


def test_write_preferences_succeeds_and_says_so():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert base.themes["sub-alice"] == "dark", base.themes


def test_theme_inconnu_est_refuse():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for mauvais in ("", "sepia", "DARK", "light; DROP TABLE"):
            r = c.put("/preferences", json={"theme": mauvais},
                      headers=auth("alice"))
            assert r.status_code == 400, (mauvais, r.status_code)
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
    with contexte() as (c, _base, _tmp):
        r = c.get("/quiz/quiz1.json")
        assert r.status_code == 200, r.text
        assert r.json()["questions"][0]["id"] == "q1", r.json()
        assert "answer" not in r.text, r.text


def test_detail_and_quiz_survive_a_rollback_mid_request():
    import routers.catalog as catalog_router
    guard = catalog_router.published_source
    try:
        with contexte() as (c, _base, _tmp):
            catalog_router.published_source = lambda entry, quoi: (None, None)
            r = c.get("/tp/tp2-ex3.json")
            assert r.status_code == 404 and r.json() == {"error": "inconnu"}, r.text
            r = c.get("/quiz/quiz1.json")
            assert r.status_code == 404 and r.json() == {"error": "pas un quiz"}, r.text
    finally:
        catalog_router.published_source = guard


def test_etats_and_pratique_during_a_database_outage():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        assert c.get("/etats", headers=auth("alice")).json() == {
            "states": [], "moderator": False}
        assert c.get("/pratique", headers=auth("alice")).json() == {"practice": []}
        base.etats[("sub-alice", "tp2-ex3")] = "solved"
        r = c.get("/etats", headers=auth("alice"))
        assert r.json() == {"states": [{"exercise_id": "tp2-ex3", "status": "solved"}],
                            "moderator": False}, r.text

    base = BaseSimulee()
    base.read_states = lambda user: None
    base.read_practice_summary = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        assert c.get("/etats", headers=auth("alice")).status_code == 503
        assert c.get("/pratique", headers=auth("alice")).status_code == 503


def test_read_draft_refuses_an_unknown_exercise_and_distinguishes_absence():
    with contexte(jetons={"alice": "sub-alice"}) as (c, _base, _tmp):
        r = c.get("/brouillon?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"sources": None}, r.text

        c.put("/brouillon", json={"exercise_id": "tp2-ex3", "files": {"submission.c": "int x;"}},
              headers=auth("alice"))
        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.json() == {"sources": {"submission.c": "int x;"}}, r.text


def test_le_brouillon_est_range_sous_sa_forme_canonique():
    with contexte(jetons={"alice": "sub-alice"}) as (c, _base, _tmp):
        c.put("/brouillon",
              json={"exercise_id": "tp2-ex3",
                    "files": {"submission.c": "\ufeffint main(void){\r\n"
                                              "    return 0;   \r\n}\r\n\r\n"}},
              headers=auth("alice"))
        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        garde = r.json()["sources"]["submission.c"]
        assert garde == "int main(void){\n    return 0;\n}\n\n", repr(garde)
        assert garde.count("\n") == 4, repr(garde)


def test_write_draft_refuses_a_file_outside_the_allow_list_before_the_quota():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for _ in range(5):
            r = c.put("/brouillon",
                      json={"exercise_id": "tp2-ex3", "files": {"hack.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.text
            assert "fichier inattendu" in r.json()["error"], r.text
        assert not base.brouillons
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 200, r.text


def test_write_draft_during_a_database_outage():
    base = BaseSimulee()
    base.write_draft = lambda *a: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_deleting_the_account_fails_without_leaving_the_illusion_of_success():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        base.etats[("sub-alice", "tp2-ex3")] = "solved"
        r = c.delete("/moi", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert c.get("/etats", headers=auth("alice")).json() == {
            "states": [], "moderator": False}

    base = BaseSimulee()
    base.forget = lambda user: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.delete("/moi", headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_gzip_pile_a_la_borne_de_1024_octets():
    with contexte() as (c, _, _tmp):
        import headers as h

        class FausseRequete:
            def __init__(self, entetes):
                self.headers = entetes

        gzip_ok = FausseRequete({"accept-encoding": "gzip"})
        petit = h.file_response(gzip_ok, b"a" * 1023, "application/json")
        gros = h.file_response(gzip_ok, b"a" * 1024, "application/json")
        assert "content-encoding" not in petit.headers, dict(petit.headers)
        assert gros.headers["content-encoding"] == "gzip", dict(gros.headers)
        assert not petit.headers["etag"].endswith('-gz"')
        assert gros.headers["etag"].endswith('-gz"')
        nu = h.file_response(FausseRequete({}), b"a" * 1024, "application/json")
        assert nu.headers["etag"] != gros.headers["etag"]


def test_fichier_du_disque_responds_500_when_the_file_is_missing():
    import headers as h

    class FakeRequest:
        headers = {}

    r = h.file_from_disk(FakeRequest(), "/path/that/does/not/exist",
                         "missing.json", "application/json")
    assert r.status_code == 500 and json.loads(r.body) == {"error": "fichier manquant"}


def test_the_middleware_ignores_non_http_scopes():
    with TestClient(main.app):
        pass


def test_entier_falls_back_to_the_default_when_the_variable_is_unreadable():
    os.environ["CTESTER_TEST_ENTIER_INVALIDE"] = "not-a-number"
    try:
        assert config._int("CTESTER_TEST_ENTIER_INVALIDE", "42") == 42
    finally:
        del os.environ["CTESTER_TEST_ENTIER_INVALIDE"]


def test_304_garde_la_csp_et_le_cache():
    page = os.path.join(ROOT, "web")
    if not os.path.isdir(page):
        return
    with contexte() as (c, _, _tmp):
        config.PAGE = page
        c2 = TestClient(main.create_app())
        r = c2.get("/")
        assert r.status_code == 200, r.status_code
        assert "content-security-policy" in r.headers, dict(r.headers)
        etiquette = r.headers["etag"]
        r2 = c2.get("/", headers={"If-None-Match": etiquette})
        assert r2.status_code == 304, r2.status_code
        assert r2.headers.get("content-security-policy"), dict(r2.headers)
        assert r2.headers.get("cache-control") == "no-cache", dict(r2.headers)
        assert r2.content == b"", r2.content


def test_page_sert_un_fichier_racine_de_la_liste_close():
    with contexte() as (c, _, _tmp):
        with open(os.path.join(config.PAGE, "theme.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("/* le theme avant la premiere peinture */")
        c2 = TestClient(main.create_app())
        r = c2.get("/theme.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")


def test_page_sert_une_liste_close_pas_un_repertoire():
    from routers import page as routeur_page
    with contexte() as (c, _, tmp):
        del tmp
        actifs = os.path.join(config.PAGE, "assets")
        os.makedirs(actifs)
        with open(os.path.join(config.PAGE, "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("pas pour toi")
        with open(os.path.join(actifs, "index-abc123.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("export default 1;")
        c2 = TestClient(main.create_app())
        assert c2.get("/secret.txt").status_code == 404
        assert c2.get("/../app/catalog.json").status_code in (404, 400)
        assert "secret.txt" not in routeur_page.SERVED
        r = c2.get("/assets/index-abc123.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")
        for chemin in ("/assets/absent-000000.js", "/assets/secret.txt",
                       "/assets/../secret.txt", "/assets/..%2fsecret.txt",
                       "/assets/sous/dossier.js", "/assets/.env",
                       "/assets/" + "x" * 200 + ".js"):
            assert c2.get(chemin).status_code in (400, 404), chemin
        assert c2.get("/assets/secret-txt.js").status_code == 404


def test_page_absente_ne_monte_aucune_route_de_fichier():
    with contexte() as (c, _, _tmp):
        del c
        config.PAGE = ""
        c2 = TestClient(main.create_app())
        assert c2.get("/").status_code == 404
        assert c2.get("/theme.js").status_code == 404
        assert c2.get("/assets/index-abc123.js").status_code == 404
        assert c2.get("/healthz").status_code == 200
        assert c2.get("/catalog.json").status_code == 200


def test_xp_accorde_une_seule_fois_par_exercice():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        verdict = {"status": "ok", "passed": 3, "total": 3}
        for numero in range(2):
            job = "%032x" % numero
            os.makedirs(os.path.join(config.SPOOL, job))
            with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
            with open(_sortie(job, "result.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(verdict, fh)
            assert c.get("/r/" + job).status_code == 200
            assert c.get("/r/" + job).status_code == 200
        accorde = [t for t in base.xp.values() if t["amount"] > 0]
        assert len(accorde) == 1, base.xp


def test_r_returns_an_anonymous_job_s_verdict_without_recording_it():
    with contexte() as (c, base, _tmp):
        job = "a" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": None}, fh)
        with open(_sortie(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.etats, (base.xp, base.etats)


def test_r_records_nothing_if_the_exercise_closed_since_the_submission():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "b" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "vanished-exercise", "owner": "sub-alice"}, fh)
        with open(_sortie(job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.etats, (base.xp, base.etats)


def test_un_echec_n_accorde_rien():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "f" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
        with open(_sortie(job, "result.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 2, "total": 3}, fh)
        assert c.get("/r/" + job).status_code == 200
        assert not base.xp, base.xp
        assert base.etats[("sub-alice", "tp2-ex3")] == "attempted", base.etats


def _sortie(job, nom):
    """Where the judge would write `nom` for `job`; the directory is the judge's to create."""
    os.makedirs(os.path.join(config.RESULTS, job), exist_ok=True)
    return os.path.join(config.RESULTS, job, nom)


def _verdict(exercise_id, job, resultat):
    os.makedirs(os.path.join(config.SPOOL, job))
    with open(os.path.join(config.SPOOL, job, "job.json"), "w", encoding="utf-8") as fh:
        json.dump({"exercise_id": exercise_id, "owner": "sub-alice"}, fh)
    with open(_sortie(job, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(resultat, fh)


def test_une_verification_laisse_une_evidence_et_aucun_xp():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "a" * 32, {"status": "ok", "passed": 3, "total": 3})
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert not base.xp, base.xp
        evidences = [f for f in base.faits if f["type"] == "VerificationEvaluated"]
        assert len(evidences) == 1, base.faits
        assert evidences[0]["payload"]["passed"] is True
        assert set(evidences[0]["payload"]) == {"job", "passed"}

        vue = c.get("/progres", headers=auth("alice")).json()
        assert vue["xp"] == 0, vue
        assert {c_["id"]: c_["band"] for c_ in vue["mastery"]["skills"]} == {
            "variables": "verifie"}
        assert vue["exercises"]["total"] == len(CONTENU) - 1, vue["exercises"]
        assert [s["id"] for s in vue["achievements"]] == ["premiere-verification"]


def test_une_verification_ratee_se_lit_a_consolider():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "b" * 32, {"status": "ok", "passed": 1, "total": 3})
        assert c.get("/r/" + "b" * 32).status_code == 200
        vue = c.get("/progres", headers=auth("alice")).json()
        assert [c_["band"] for c_ in vue["mastery"]["skills"]] == ["a-consolider"]
        assert not base.xp and not vue["achievements"], (base.xp, vue["achievements"])


def test_les_evidences_muettes_repondent_503():
    base = BaseSimulee()
    base.read_events = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "mastery" not in r.text and "xp" not in r.text, r.text


def test_verdict_illisible_ne_boucle_pas():
    with contexte() as (c, _, _tmp):
        job = "e" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(_sortie(job, "result.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ pas du json")
        r = c.get("/r/" + job)
        assert r.status_code == 500, (r.status_code, r.text)
        assert r.json()["state"] == "error", r.json()


def test_rang_dans_la_file_et_job_disparu():
    with contexte() as (c, _, _tmp):
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){}"}}
        premier = c.post("/submit", json=charge).json()["id"]
        second = c.post("/submit", json=charge).json()["id"]
        for job in (premier, second):
            os.utime(os.path.join(config.SPOOL, job, "job.json"), (1e9, 1e9))
        for job, rang in ((premier, 1), (second, 2)):
            corps = c.get("/r/" + job).json()
            assert corps["state"] == "queued" and corps["position"] == rang, corps
        os.makedirs(_sortie(premier, ".lock"))
        assert c.get("/r/" + premier).json() == {"state": "running"}
        r = c.get("/r/" + "a" * 32)
        assert r.status_code == 404 and r.json() == {"state": "gone"}, r.text


def test_eta_somme_les_durees_mesurees_et_retombe_sur_une_moyenne():
    with contexte() as (c, _, _tmp):
        garde = config.WORKERS
        try:
            config.WORKERS = 1
            charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            premier = c.post("/submit", json=charge).json()["id"]
            second = c.post("/submit", json=charge).json()["id"]

            assert c.get("/r/" + premier).json()["eta"] == 15
            assert c.get("/r/" + second).json()["eta"] == 30

            with open(os.path.join(config.RESULTS, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp2-ex3": [4.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 4
            assert c.get("/r/" + second).json()["eta"] == 8

            with open(os.path.join(config.RESULTS, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp1": [2.0, 20], "tp7-ex1": [10.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 6

            config.WORKERS = 2
            assert c.get("/r/" + second).json()["eta"] == 6

            with open(os.path.join(config.RESULTS, "durees.json"), "w",
                      encoding="utf-8") as fh:
                fh.write("{ pas du json")
            r = c.get("/r/" + premier)
            assert r.status_code == 200 and r.json()["eta"] > 0, r.text
        finally:
            config.WORKERS = garde


def test_a_private_question_does_not_cross_the_http_boundary():
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
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


def test_le_vote_refuse_le_sien_et_refuse_le_moins_un_sur_une_question():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "ma question"},
               headers=auth("alice"))
        question = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "ma réponse",
                               "reply_to": question}, headers=auth("bob"))
        reponse = fake.messages[1]["id"]

        assert c.post("/forum/helpful", json={"id": question},
                      headers=auth("alice")).status_code == 404
        assert c.post("/forum/helpful", json={"id": "0" * 32},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": question},
                      headers=auth("bob")).status_code == 200

        assert c.post("/forum/helpful", json={"id": question, "value": -1},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": reponse, "value": -1},
                      headers=auth("alice")).status_code == 200

        fil = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"]
        vue_question = [m for m in fil if m["id"] == question][0]
        vue_reponse = [m for m in fil if m["id"] == reponse][0]
        assert vue_question["upvotes"] == 1 and vue_question["my_vote"] == 1
        assert vue_question["downvotes"] == 0
        assert vue_reponse["downvotes"] == 1

        assert c.post("/forum/helpful", json={"id": question, "value": 1},
                      headers=auth("bob")).status_code == 200
        assert c.post("/forum/helpful", json={"id": question, "value": 0},
                      headers=auth("bob")).status_code == 200
        fil = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"]
        assert [m for m in fil if m["id"] == question][0]["upvotes"] == 0

        assert fake.xp == {} and fake.succes == {}


def test_le_chat_est_un_fil_a_part_et_tout_y_est_public():
    tokens = {"alice": "sub-alice"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        for cle in ("@chat:general", "@chat:tp2-ex3"):
            r = c.get("/forum?ex=" + cle, headers=auth("alice"))
            assert r.status_code == 200, (cle, r.text)
            assert r.json()["chat"] is True, cle
        assert c.get("/forum?ex=tp2-ex3",
                     headers=auth("alice")).json()["chat"] is False
        for invente in ("@chat:inconnu", "@chat:", "@chat:../etc"):
            assert c.get("/forum?ex=" + invente,
                         headers=auth("alice")).status_code == 400, invente

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


def test_le_pont_discord_n_existe_pas_sans_cle_et_refuse_tout_le_reste():
    tokens = {"alice": "sub-alice"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/bridge", json={"exercise_id": "@chat:general",
                                          "discord_id": "4711",
                                          "display_name": "Vianney",
                                          "text": "salut"})
        assert r.status_code == 404, r.text

    with contexte(jetons=tokens, moderateurs=["sub-prof"],
                  pont="secret-du-pont") as (c, fake, _tmp):
        bon = {"Authorization": "Bearer secret-du-pont"}
        corps = {"exercise_id": "@chat:general", "discord_id": "4711",
                 "display_name": "Vianney", "text": "salut la classe"}
        for entetes in ({}, {"Authorization": "Bearer autre"},
                        {"Authorization": "secret-du-pont"}):
            assert c.post("/forum/bridge", json=corps,
                          headers=entetes).status_code == 401, entetes

        prive = dict(corps, exercise_id="tp2-ex3")
        r = c.post("/forum/bridge", json=prive, headers=bon)
        assert r.status_code == 400 and "chat public" in r.json()["error"], r.text
        assert c.post("/forum/bridge", json=dict(corps, exercise_id="@chat:inconnu"),
                      headers=bon).status_code == 400

        for mauvais in ("", "abc", "47-11", "@chat:general", "1" * 25):
            assert c.post("/forum/bridge", json=dict(corps, discord_id=mauvais),
                          headers=bon).status_code == 400, mauvais

        assert c.post("/forum/bridge", json=dict(corps, text=""),
                      headers=bon).status_code == 400
        assert c.post("/forum/bridge",
                      json=dict(corps, text="x" * (config.FORUM_MAX_CHARS + 1)),
                      headers=bon).status_code == 400
        for reserve in ("Enseignant", "Vous", "PARTICIPANT"):
            assert c.post("/forum/bridge", json=dict(corps, display_name=reserve),
                          headers=bon).status_code == 400, reserve

        assert c.post("/forum/bridge", json=corps, headers=bon).status_code == 200
        ecrit = fake.messages[-1]
        assert ecrit["text"] == "salut la classe"
        assert ecrit["exercise_id"] == "@chat:general"
        assert ecrit["account"] == "@discord:4711", ecrit["account"]
        assert ecrit["visibility"] == "thread"

        vue = c.get("/forum?ex=@chat:general", headers=auth("alice"))
        assert vue.status_code == 200, vue.text
        assert "Vianney" in vue.text, vue.text
        assert "@discord:" not in vue.text and "sub-alice" not in vue.text, vue.text


def test_une_reponse_vise_sa_racine_et_n_a_pas_de_visibilite_a_elle():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "ma question"},
               headers=auth("alice"))
        racine = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "@chat:tp2-ex3", "text": "ailleurs"},
               headers=auth("alice"))
        ailleurs = fake.messages[1]["id"]

        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": "pas-un-id"},
                      headers=auth("bob")).status_code == 400
        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": ailleurs},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                      "reply_to": "0" * 32},
                      headers=auth("bob")).status_code == 404
        r = c.post("/forum", json={"exercise_id": "@chat:general", "text": "r",
                                   "reply_to": racine, "visibility": "private"},
                   headers=auth("bob"))
        assert r.status_code == 400 and "hérite" in r.json()["error"], r.text

        assert c.post("/forum", json={"exercise_id": "@chat:general",
                                      "text": "ma réponse", "reply_to": racine},
                      headers=auth("bob")).status_code == 200
        reponse = fake.messages[2]["id"]
        assert fake.messages[2]["reply_to"] == racine
        assert c.post("/forum", json={"exercise_id": "@chat:general",
                                      "text": "et encore", "reply_to": reponse},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[3]["reply_to"] == racine

        charge = c.get("/forum?ex=@chat:general", headers=auth("bob")).text
        assert "sub-alice" not in charge and "sub-bob" not in charge


def test_le_permalien_rend_une_conversation_et_le_meme_404_partout():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "question"},
               headers=auth("alice"))
        racine = fake.messages[0]["id"]
        c.post("/forum", json={"exercise_id": "@chat:general", "text": "réponse",
                               "reply_to": racine}, headers=auth("bob"))
        vue = c.get("/forum/message?id=" + racine, headers=auth("bob")).json()
        assert [m["text"] for m in vue["messages"]] == ["question", "réponse"]
        assert vue["exercise_id"] == "@chat:general" and vue["chat"] is True
        depuis = c.get("/forum/message?id=" + fake.messages[1]["id"],
                       headers=auth("bob")).json()
        assert len(depuis["messages"]) == 2
        assert c.get("/forum/message?id=zz", headers=auth("bob")).status_code == 400
        assert c.get("/forum/message?id=" + "0" * 32,
                     headers=auth("bob")).status_code == 404


def test_la_recherche_ne_remonte_jamais_la_question_privee_d_un_autre():
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3",
                               "text": "segfault mysterieux", "step": "execution"},
               headers=auth("alice"))
        c.post("/forum", json={"exercise_id": "@chat:general",
                               "text": "segfault en public"}, headers=auth("alice"))

        def trouve(qui):
            r = c.get("/forum/search?q=segfault", headers=auth(qui))
            assert r.status_code == 200, r.text
            return [x["extrait"] for x in r.json()["results"]]

        assert "segfault mysterieux" in trouve("alice")
        assert "segfault mysterieux" not in trouve("bob")
        assert "segfault mysterieux" not in trouve("prof")
        assert "segfault en public" in trouve("bob")
        assert c.get("/forum/search?q=", headers=auth("bob")).json()["results"] == []


def test_la_sonnette_du_chat_refuse_dans_le_bon_ordre_et_ne_dit_rien_d_autre():
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons={"alice": "sub-alice"}, moderateurs=[]) as (c, _f, _t):
        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "n'importe quoi",
                                  "thread": "@chat:general"})
                socket.receive_json()
            raise AssertionError("une socket s'est ouverte sans forum")
        except WebSocketDisconnect as exc:
            assert exc.code == 4503, exc.code

    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, fake, _tmp):
        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "faux",
                                  "thread": "@chat:general"})
                socket.receive_json()
            raise AssertionError("un jeton invalide a été accepté")
        except WebSocketDisconnect as exc:
            assert exc.code == 4401, exc.code

        try:
            with c.websocket_connect("/forum/live") as socket:
                socket.send_json({"t": "hello", "token": "alice",
                                  "thread": "@chat:inconnu"})
                socket.receive_json()
            raise AssertionError("un fil inventé a été accepté")
        except WebSocketDisconnect as exc:
            assert exc.code == 4400, exc.code

        with c.websocket_connect("/forum/live") as socket:
            socket.send_json({"t": "hello", "token": "alice",
                              "thread": "@chat:general"})
            pret = socket.receive_json()
            assert pret == {"t": "ready", "thread": "@chat:general"}, pret
            try:
                socket.send_text("x" * (config.FORUM_LIVE_FRAME + 1))
                socket.receive_json()
                raise AssertionError("une trame hors bornes a été acceptée")
            except WebSocketDisconnect as exc:
                assert exc.code == 4400, exc.code

    forum_live.reset()

    class SocketMuette:
        def __init__(self):
            self.trames = []

        async def send_text(self, data):
            self.trames.append(json.loads(data))

    fausse = SocketMuette()
    connexion = forum_live.Connection(fausse, "@chat:general")
    forum_live.join(connexion)
    try:
        asyncio.new_event_loop().run_until_complete(
            forum_live._ring("@chat:general"))
        assert fausse.trames == [{"t": "new", "thread": "@chat:general"}], \
            fausse.trames
        assert set(fausse.trames[0]) == {"t", "thread"}
    finally:
        forum_live.leave(connexion)
        forum_live.reset()


def test_le_classement_exclut_l_enseignant_et_ne_le_dit_pas_a_l_envers():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        for qui, groupe, alias in (("sub-alice", 4, "Rotor cuivré"),
                                   ("sub-prof", 6, "Vilebrequin trempé")):
            fake.profils[qui] = {"account": qui, "alias": alias,
                                 "group_number": groupe,
                                 "leaderboard_opt_in": True,
                                 "display_name": None,
                                 "display_name_public": False,
                                 "group_number_public": False}
        reponse = c.get("/leaderboard?scope=course", headers=auth("prof"))
        vue = reponse.json()
        assert vue["moderator"] is True
        assert "Vilebrequin trempé" not in reponse.text, reponse.text
        assert "sub-prof" not in reponse.text
        assert vue["cohort"] == 1 and vue["rows"] == []
        assert sum(d["accounts"] for d in vue["divisions"]) == 1

        mien = c.get("/leaderboard?scope=group&group=6", headers=auth("alice")).json()
        assert mien["group"] == 4 and mien["moderator"] is False
        assert mien["groups"] == []
        vise = c.get("/leaderboard?scope=group&group=4", headers=auth("prof")).json()
        assert vise["group"] == 4 and vise["groups"] == [4, 6]


def test_retaining_an_answer_does_not_edit_the_message():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
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
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
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
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        r = c.get("/leaderboard", headers=auth("alice"))
        assert r.status_code == 200 and r.json()["participating"] is False

        r = c.post("/forum/profil",
                   json={"group_number": 4, "leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        alias = fake.profils["sub-alice"]["alias"]
        assert alias and alias in politique.possible_aliases(), alias

        view = c.get("/leaderboard", headers=auth("alice")).json()
        assert view["participating"] is True and view["me"]["rank"] == 1
        assert view["rows"] == [] and view["cohort"] < view["minimum"]
        assert "sub-alice" not in c.get("/leaderboard", headers=auth("alice")).text

        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 200 and r.json()["alias"] != alias

        c.post("/forum/profil", json={"group_number": 4,
                                      "leaderboard_opt_in": False},
               headers=auth("alice"))
        assert fake.profils["sub-alice"]["group_number"] == 4
        assert c.get("/leaderboard", headers=auth("alice")
                     ).json()["participating"] is False


def test_a_locked_frame_is_refused():
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        offered = c.get("/forum/profil", headers=auth("alice")).json()["frames"]
        assert [f["id"] for f in offered] == ["simple"], offered
        r = c.post("/forum/profil", json={"plate_frame": "tolerance"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        assert c.post("/forum/profil", json={"plate_frame": "simple"},
                      headers=auth("alice")).status_code == 200


def test_the_collection_shows_locked_cards_with_their_condition():
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/collection", headers=auth("alice"))
        assert r.status_code == 200, r.text
        cards = r.json()["cards"]
        assert len(cards) == len(politique.POLICY["cards"])
        assert all(not card["held"] for card in cards)
        assert all(card["condition"] for card in cards), cards
        assert all(card["rarity"] is None for card in cards)


def test_a_mute_database_answers_503_on_the_new_screens():
    class Mute(BaseSimulee):
        leaderboard_rows = staticmethod(lambda *a: None)
        read_unlock_rates = staticmethod(lambda *a: None)
        read_practice_days = staticmethod(lambda *a: None)

    with contexte(jetons={"alice": "sub-alice"}, base=Mute(),
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for route in ("/leaderboard", "/collection", "/progres"):
            r = c.get(route, headers=auth("alice"))
            assert r.status_code == 503, (route, r.status_code, r.text)
            assert not re.search(r"\\d", r.json().get("error", "")), r.text


def test_forum_id_based_routes_reject_an_invalid_form():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        calls = [
            lambda: c.post("/forum/visibility", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.post("/forum/helpful", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.delete("/forum?id=too-short", headers=auth("alice")),
            lambda: c.post("/forum/signalement",
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
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
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

    base = BaseSimulee()
    base.forum_delete = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_report_a_message_or_a_name():
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "dubious"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/signalement", json={"id": mid, "kind": "message"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        r = c.post("/forum/signalement", json={"id": mid, "kind": "name"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        r = c.post("/forum/signalement", json={"id": mid}, headers=auth("bob"))
        assert r.status_code == 200, r.text

    base = BaseSimulee()
    base.forum_report = lambda *a: None
    base.forum_report_name = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for body in ({"id": "0" * 32, "kind": "message"},
                     {"id": "0" * 32, "kind": "name"}):
            r = c.post("/forum/signalement", json=body, headers=auth("alice"))
            assert r.status_code == 503, (body, r.text)


def test_moderation_clears_a_reported_name_without_touching_the_rest_of_the_profile():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum/profil",
              json={"display_name": "Léa", "display_name_public": True,
                    "group_number": 4, "group_number_public": True},
              headers=auth("alice"))
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "hi"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/moderation", json={"id": mid, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        profile = fake.profils["sub-alice"]
        assert profile["display_name"] is None
        assert profile["group_number"] == 4 and profile["group_number_public"] is True

        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = BaseSimulee()
    base.forum_profile = lambda user: None
    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "1" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "1" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text

    base2 = BaseSimulee()
    base2.forum_write_profile = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"}, base=base2,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "2" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "2" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_moderation_refuses_an_unknown_action():
    tokens = {"prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "edit"},
                   headers=auth("prof"))
        assert r.status_code == 400 and r.json() == {"error": "action inconnue"}, r.text


def test_fil_refuses_an_unknown_exercise():
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text


def test_visibility_and_helpful_report_a_database_outage():
    base = BaseSimulee()
    base.forum_open_to_group = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/visibility", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_vote = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/helpful", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_moderer_hide_restore_retain_report_an_outage_and_an_unknown_id():
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
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

    base = BaseSimulee()
    base.forum_moderate = lambda *a: None
    with contexte(jetons=tokens, base=base, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_forum_reports_a_database_outage_on_each_read_route():
    base = BaseSimulee()
    base.forum_thread = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_reports = lambda *a: None
    with contexte(jetons={"prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/moderation", headers=auth("prof"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_help_rows = lambda *a: None
    with contexte(jetons={"prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/help", headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_publier_validates_each_field_then_reports_an_outage():
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
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

    base = BaseSimulee()
    base.forum_post = lambda *a: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_profil_validates_the_name_and_group_then_reports_an_outage():
    with contexte(jetons={"alice": "sub-alice"}, groupes=(4, 6),
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"display_name": "x" * 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        r = c.post("/forum/profil", json={"group_number": 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = BaseSimulee()
    base.forum_profile = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/profil", headers=auth("alice"))
        assert r.status_code == 503, r.text
        r = c.post("/forum/profil", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_write_profile = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_taken_aliases = lambda: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_oidc_json_is_empty_when_sign_in_is_disabled():
    assert client.get("/oidc.json").json() == {}


def test_sub_responds_503_outside_oidc_configuration():
    r = client.get("/etats", headers=auth("alice"))
    assert r.status_code == 503 and "persistance" in r.json()["error"], r.text


def test_freiner_forum_blocks_a_burst_of_messages():
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        deps.forum_quota = quotas.Quota(cooldown=999, hourly=100)
        r1 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "one"},
                   headers=auth("alice"))
        assert r1.status_code == 200, r1.text
        r2 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "two"},
                   headers=auth("alice"))
        assert r2.status_code == 429 and "retry_after" in r2.json(), r2.text


def test_leaderboard_and_alias_report_every_database_outage():
    base = BaseSimulee()
    base.forum_profile = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        assert c.get("/leaderboard", headers=auth("alice")).status_code == 503
        assert c.post("/leaderboard/alias", json={}, headers=auth("alice")).status_code == 503

    base = BaseSimulee()
    base.forum_taken_aliases = lambda: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_write_profile = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.profils["sub-alice"] = dict(BaseSimulee.EMPTY_PROFILE, alias="Faucon-12")
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_redraw_alias_exhausts_the_vocabulary():
    import policy
    every_alias = set(policy.possible_aliases())
    base = BaseSimulee()
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        for i, alias in enumerate(every_alias):
            fake.profils["sub-%d" % i] = dict(BaseSimulee.EMPTY_PROFILE, alias=alias)
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503 and "pseudonyme" in r.json()["error"], r.text


def test_avertir_reports_each_incomplete_configuration_independently():
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


JETONS_EQUIPE = {"t-alice": "sub-alice", "t-bob": "sub-bob",
                 "t-cleo": "sub-cleo", "t-prof": "sub-prof"}


def _entetes(jeton):
    return {"Authorization": "Bearer " + jeton}


@contextlib.contextmanager
def deploiement_devoir(*, deadline=None, team=True, moderateurs=("sub-prof",)):
    base = BaseSimulee()
    with contexte(jetons=JETONS_EQUIPE, moderateurs=moderateurs, base=base,
                  exercices=DEVOIR,
                  devoir=_devoir_json(deadline=deadline, team=team)) as (c, faux, tmp):
        faux.inscrire("devoir", "e1", ["sub-alice", "sub-cleo"], group_number=4,
                      label="Équipe 1")
        faux.inscrire("devoir", "e2", ["sub-bob"], group_number=6,
                      label="Équipe 2")
        yield c, faux, tmp


def _console_hello(socket, jeton="t-alice", code="int main(void){return 0;}"):
    socket.send_json({"t": "hello", "token": jeton, "code": code})


def _exige_flock():
    from services import scratch as _scratch
    if _scratch.fcntl is None:
        raise RuntimeError("flock indisponible : la Console demande POSIX")


def test_la_console_dit_qu_elle_n_est_pas_offerte_avant_de_refuser_le_jeton():
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE, console=False) as (client, _, _):
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, jeton="t-inconnu")
                socket.receive_json()
            raise AssertionError("la Console éteinte a accepté une session")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_UNAVAILABLE, exc.code

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, jeton="t-inconnu")
                socket.receive_json()
            raise AssertionError("un jeton inconnu a ouvert une session")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_UNAUTHORIZED, exc.code


def test_la_console_refuse_une_origine_inconnue_avant_d_accepter():
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        try:
            with client.websocket_connect(
                    "/scratch/live",
                    headers={"origin": "https://ailleurs.example"}) as socket:
                socket.receive_json()
            raise AssertionError("une origine inconnue est passée")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_FORBIDDEN, exc.code


def test_la_console_borne_le_code_des_deux_cotes():
    _exige_flock()
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket, code="/*" + "x" * (config.MAX_CODE - 4) + "*/")
            trame = socket.receive_json()
            assert trame["t"] == "queued", trame
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, code="x" * (config.MAX_CODE + 1))
                socket.receive_json()
            raise AssertionError("un code hors bornes est passé")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BAD, exc.code


def test_la_console_borne_ce_qu_on_tape_des_deux_cotes():
    _exige_flock()
    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            chemin = _le_job_de_console()
            socket.send_json({"t": "stdin", "d": "a" * config.SCRATCH_FRAME})
            socket.send_json({"t": "stdin", "d": "b" * (config.SCRATCH_FRAME + 1)})
            socket.send_json({"t": "stdin", "d": "FIN\n"})
            for _ in range(40):
                time.sleep(0.02)
                if b"FIN" in _lire_octets(os.path.join(chemin, "in")):
                    break
            entree = _lire_octets(os.path.join(chemin, "in"))
        assert b"a" * config.SCRATCH_FRAME in entree
        assert b"b" not in entree, entree[:200]
        assert entree.endswith(b"FIN\n")


def test_la_console_n_ecrit_ni_owner_ni_exercice_dans_le_spool():
    _exige_flock()
    base = BaseSimulee()
    with contexte(jetons=JETONS_EQUIPE, base=base) as (client, faux, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            chemin = _le_job_de_console()
            job = json.loads(_lire_octets(os.path.join(chemin, "job.json")))
            assert job == {"kind": "console"}, job
            identifiant = os.path.basename(chemin)
            r = client.get("/r/" + identifiant, headers=_entetes("t-alice"))
            assert r.status_code == 200, r.text
            assert r.json()["state"] in ("queued", "running"), r.json()
        assert not faux.pratique, faux.pratique
        assert not faux.jobs, faux.jobs
        assert not faux.etats, faux.etats


def test_une_seule_session_de_console_par_compte():
    _exige_flock()
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        with client.websocket_connect("/scratch/live") as premiere:
            _console_hello(premiere)
            assert premiere.receive_json()["t"] == "queued"
            try:
                with client.websocket_connect("/scratch/live") as seconde:
                    _console_hello(seconde)
                    seconde.receive_json()
                raise AssertionError("un compte a ouvert deux sessions")
            except WebSocketDisconnect as exc:
                assert exc.code == deps.CLOSE_BUSY, exc.code
        with client.websocket_connect("/scratch/live") as autre:
            _console_hello(autre, jeton="t-bob")
            assert autre.receive_json()["t"] == "queued"


def test_le_quota_horaire_de_console_passe_a_N_et_refuse_a_N_plus_1():
    _exige_flock()
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        deps.scratch_quota = quotas.Quota(cooldown=0, hourly=2)
        for essai in range(2):
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket)
                assert socket.receive_json()["t"] == "queued", essai
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket)
                socket.receive_json()
            raise AssertionError("la 3e session est passée malgré un quota de 2")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BUSY, exc.code


def test_le_bloc_notes_suit_le_compte_et_se_borne():
    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        r = client.get("/scratch/draft", headers=_entetes("t-alice"))
        assert r.status_code == 200 and r.json() == {"code": ""}, r.text
        assert client.get("/scratch/draft").status_code == 401
        assert client.put("/scratch/draft", json={"code": "x" * config.MAX_CODE},
                          headers=_entetes("t-alice")).status_code == 200
        trop = client.put("/scratch/draft",
                          json={"code": "x" * (config.MAX_CODE + 1)},
                          headers=_entetes("t-alice"))
        assert trop.status_code == 413, trop.status_code
        client.put("/scratch/draft", json={"code": "a-moi"},
                   headers=_entetes("t-alice"))
        assert client.get("/scratch/draft",
                          headers=_entetes("t-alice")).json()["code"] == "a-moi"
        assert client.get("/scratch/draft",
                          headers=_entetes("t-bob")).json()["code"] == ""


def test_oidc_json_annonce_la_console():
    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        assert client.get("/oidc.json").json()["scratch"] is True
    with contexte(jetons=JETONS_EQUIPE, console=False) as (client, _, _):
        assert client.get("/oidc.json").json()["scratch"] is False


def _le_job_de_console():
    for nom in os.listdir(config.SPOOL):
        chemin = os.path.join(config.SPOOL, nom)
        if os.path.exists(os.path.join(chemin, "job.json")):
            return chemin
    raise AssertionError("aucun job de console dans le spool")


def _lire_octets(chemin):
    try:
        with open(chemin, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def test_le_contexte_d_equipe_nomme_les_coequipiers_sans_aucun_sub():
    with deploiement_devoir() as (client, faux, _):
        r = client.get("/team/context?assignment=devoir",
                       headers=_entetes("t-alice"))
        assert r.status_code == 200, r.text
        corps = r.json()
        assert "sub-" not in r.text, r.text
        assert corps["team"]["id"] == "e1"
        assert corps["team"]["group_number"] == 4
        assert [m["id"] for m in corps["team"]["members"]] == ["m1", "m2"]
        assert [m["you"] for m in corps["team"]["members"]] == [True, False]
        assert corps["assignment"]["items"] == ["dev-a", "dev-b"]
        assert corps["assignment"]["team"] == {"min": 3, "max": 4, "count": 6}
        assert corps["submission"] == {}
        assert not faux.profils


def test_aucune_route_d_equipe_n_ouvre_sans_appartenance_prouvee():
    with deploiement_devoir() as (client, faux, _):
        faux.equipes.pop(("devoir", "sub-bob"))
        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/revisions?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            r = client.get(chemin, headers=_entetes("t-bob"))
            assert r.status_code == 403, (chemin, r.status_code)
            assert "équipe" in r.json()["error"]
        r = client.get("/team/context?assignment=inconnu",
                       headers=_entetes("t-alice"))
        assert r.status_code == 404
        assert client.get("/team/context?assignment=devoir").status_code == 401


def test_un_devoir_sans_bloc_team_repond_que_ce_n_est_pas_du_travail_d_equipe():
    with deploiement_devoir(team=False) as (client, _, _):
        r = client.get("/team/context?assignment=devoir",
                       headers=_entetes("t-alice"))
        assert r.status_code == 400
        assert "travail d'équipe" in r.json()["error"]


def test_le_document_est_partage_par_l_equipe_et_par_elle_seule():
    with deploiement_devoir() as (client, faux, _):
        ecrire = client.put("/team/document", headers=_entetes("t-alice"),
                            json={"assignment_id": "devoir",
                                  "exercise_id": "dev-a",
                                  "files": {"main.c": "int main(void){}\n"}})
        assert ecrire.status_code == 200, ecrire.text
        pour_cleo = client.get("/team/document?assignment=devoir&ex=dev-a",
                               headers=_entetes("t-cleo")).json()
        assert pour_cleo["sources"] == {"main.c": "int main(void){}\n"}
        pour_bob = client.get("/team/document?assignment=devoir&ex=dev-a",
                              headers=_entetes("t-bob")).json()
        assert pour_bob["sources"] == {}
        client.put("/team/document", headers=_entetes("t-bob"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "team_id": "e1", "team": "e1",
                         "files": {"main.c": "/* bob */\n"}})
        assert faux.documents[("e1", "dev-a")] == {"main.c": "int main(void){}\n"}
        assert faux.documents[("e2", "dev-a")] == {"main.c": "/* bob */\n"}


def test_un_exercice_hors_du_devoir_ne_resout_pas_meme_pour_un_membre():
    with deploiement_devoir() as (client, _, _):
        for ex in ("tp2-ex3", "../catalog", "", "quiz1"):
            r = client.get("/team/document?assignment=devoir&ex="
                           + ex, headers=_entetes("t-alice"))
            assert r.status_code == 404, (ex, r.status_code)
        r = client.put("/team/document", headers=_entetes("t-alice"),
                       json={"assignment_id": "devoir",
                             "exercise_id": "tp2-ex3", "files": {}})
        assert r.status_code == 404


def test_le_document_d_equipe_ne_touche_pas_au_brouillon_individuel():
    with deploiement_devoir() as (client, faux, _):
        client.put("/team/document", headers=_entetes("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "équipe\n"}})
        assert faux.brouillons == {}
        client.put("/brouillon", headers=_entetes("t-alice"),
                   json={"exercise_id": "tp2-ex3",
                         "files": {"submission.c": "moi\n"}})
        assert faux.brouillons[("sub-alice", "tp2-ex3")] == {"submission.c": "moi\n"}
        assert faux.documents[("e1", "dev-a")] == {"main.c": "équipe\n"}
        r = client.put("/brouillon", headers=_entetes("t-bob"),
                       json={"exercise_id": "dev-a",
                             "files": {"main.c": "seul\n"}})
        assert r.status_code == 200
        assert faux.brouillons[("sub-bob", "dev-a")] == {"main.c": "seul\n"}


def test_le_document_d_equipe_est_canonise_des_deux_cotes():
    with deploiement_devoir() as (client, faux, _):
        client.put("/team/document", headers=_entetes("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "int main(void){\r\n}\r\n\r\n"}})
        assert faux.documents[("e1", "dev-a")] == {
            "main.c": "int main(void){\n}\n\n"}, faux.documents
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_entetes("t-alice"))
        assert r.json()["sources"] == {"main.c": "int main(void){\n}\n\n"}, r.text


def test_le_document_passe_par_la_meme_liste_blanche_que_tout_le_reste():
    with deploiement_devoir() as (client, _, _):
        r = client.put("/team/document", headers=_entetes("t-alice"),
                       json={"assignment_id": "devoir", "exercise_id": "dev-a",
                             "files": {"secret.c": "x"}})
        assert r.status_code == 400 and "inattendu" in r.json()["error"]
        pile = "a" * (config.MAX_CODE - len(json.dumps({"main.c": ""})))
        assert client.put("/team/document", headers=_entetes("t-alice"),
                          json={"assignment_id": "devoir",
                                "exercise_id": "dev-a",
                                "files": {"main.c": pile}}).status_code == 200
        assert client.put("/team/document", headers=_entetes("t-alice"),
                          json={"assignment_id": "devoir",
                                "exercise_id": "dev-a",
                                "files": {"main.c": pile + "a"}}).status_code == 413


def test_une_revision_est_coalescee_puis_restaurable():
    with deploiement_devoir() as (client, faux, _):
        def ecrire(jeton, texte):
            return client.put("/team/document", headers=_entetes(jeton),
                              json={"assignment_id": "devoir",
                                    "exercise_id": "dev-a",
                                    "files": {"main.c": texte}})
        ecrire("t-alice", "un\n")
        ecrire("t-alice", "deux\n")
        ecrire("t-alice", "trois\n")
        assert len(faux.revisions) == 1, faux.revisions
        ecrire("t-cleo", "quatre\n")
        assert len(faux.revisions) == 2
        faux.horloge += config.TEAM_REVISION_WINDOW + 1
        ecrire("t-alice", "cinq\n")
        assert len(faux.revisions) == 3
        faux.horloge += config.TEAM_REVISION_WINDOW + 1
        ecrire("t-alice", "cinq\n")
        assert len(faux.revisions) == 3

        liste = client.get("/team/revisions?assignment=devoir&ex=dev-a",
                           headers=_entetes("t-alice")).json()["revisions"]
        assert len(liste) == 3
        assert "sub-" not in json.dumps(liste)
        assert {r["author"] for r in liste} == {"m1", "m2"}
        assert "%" not in json.dumps(liste)

        premiere = liste[-1]["id"]
        detail = client.get("/team/revision?assignment=devoir&ex=dev-a&id="
                            + premiere, headers=_entetes("t-alice"))
        assert detail.json()["sources"] == {"main.c": "un\n"}
        remis = client.post("/team/restore", headers=_entetes("t-cleo"),
                            json={"assignment_id": "devoir",
                                  "exercise_id": "dev-a",
                                  "revision_id": premiere})
        assert remis.status_code == 200
        assert faux.documents[("e1", "dev-a")] == {"main.c": "un\n"}
        assert len(faux.revisions) == 4


def test_une_revision_d_une_autre_equipe_ne_resout_pas():
    with deploiement_devoir() as (client, faux, _):
        client.put("/team/document", headers=_entetes("t-alice"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "files": {"main.c": "secret d'alice\n"}})
        [revision] = faux.revisions
        for chemin, methode, corps in (
                ("/team/revision?assignment=devoir&ex=dev-a&id="
                 + revision["revision_id"], "GET", None),
                ("/team/restore", "POST",
                 {"assignment_id": "devoir", "exercise_id": "dev-a",
                  "revision_id": revision["revision_id"]})):
            r = (client.get(chemin, headers=_entetes("t-bob")) if methode == "GET"
                 else client.post(chemin, headers=_entetes("t-bob"), json=corps))
            assert r.status_code == 404, (chemin, r.status_code)
        assert ("e2", "dev-a") not in faux.documents
        assert "secret" not in client.get(
            "/team/revisions?assignment=devoir&ex=dev-a",
            headers=_entetes("t-bob")).text


def test_l_archive_zip_est_construite_par_le_serveur_et_deterministe():
    import io as _io
    import zipfile as _zipfile

    with deploiement_devoir() as (client, faux, _):
        vide = client.get("/team/handin.zip?assignment=devoir",
                          headers=_entetes("t-alice"))
        assert vide.status_code == 400 and "rien à remettre" in vide.json()["error"]
        faux.documents[("e1", "dev-a")] = {"main.c": "int main(void){return 0;}\n"}
        faux.documents[("e1", "dev-b")] = {"lib.h": "#pragma once\n",
                                           "lib.c": "double f(void){return 1;}\n"}
        r = client.get("/team/handin.zip?assignment=devoir",
                       headers=_entetes("t-alice"))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert "Devoir-e1.zip" in r.headers["content-disposition"]
        assert r.headers["cache-control"] == "no-store"
        with _zipfile.ZipFile(_io.BytesIO(r.content)) as archive:
            assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
            assert archive.read("Devoir/matrac_lib.c").decode() \
                == "double f(void){return 1;}\n"
        encore = client.get("/team/handin.zip?assignment=devoir",
                            headers=_entetes("t-cleo"))
        assert encore.content == r.content
        autre = client.get("/team/handin.zip?assignment=devoir",
                           headers=_entetes("t-bob"))
        assert autre.status_code == 400, autre.text


def test_la_remise_est_une_seule_par_equipe_et_refuse_un_trou():
    with deploiement_devoir() as (client, faux, _):
        faux.documents[("e1", "dev-a")] = {"main.c": "int main(void){}\n"}
        incomplet = client.post("/team/handin", headers=_entetes("t-alice"),
                                json={"assignment_id": "devoir"})
        assert incomplet.status_code == 400
        assert "matrac_lib.c" in incomplet.json()["error"]
        assert faux.remises == {}

        faux.documents[("e1", "dev-b")] = {"lib.c": "double f(void){return 1;}\n"}
        remise = client.post("/team/handin", headers=_entetes("t-alice"),
                             json={"assignment_id": "devoir"})
        assert remise.status_code == 200, remise.text
        assert sorted(remise.json()["files"]) == ["Devoir/main.c",
                                                   "Devoir/matrac_lib.c"]
        encore = client.post("/team/handin", headers=_entetes("t-cleo"),
                             json={"assignment_id": "devoir"})
        assert encore.status_code == 200
        assert list(faux.remises) == [("devoir", "e1")]
        assert faux.remises[("devoir", "e1")]["submitted_by"] == "sub-cleo"
        contexte_cleo = client.get("/team/context?assignment=devoir",
                                   headers=_entetes("t-cleo")).json()
        assert contexte_cleo["submission"]["submitted_at"]
        assert client.get("/team/context?assignment=devoir",
                          headers=_entetes("t-bob")).json()["submission"] == {}


def test_la_remise_ferme_a_la_date_limite():
    with deploiement_devoir(deadline="2020-01-01T00:00:00-05:00") as (client, faux, _):
        faux.documents[("e1", "dev-a")] = {"main.c": "x\n"}
        faux.documents[("e1", "dev-b")] = {"lib.c": "y\n"}
        r = client.post("/team/handin", headers=_entetes("t-alice"),
                        json={"assignment_id": "devoir"})
        assert r.status_code == 403 and "date de remise" in r.json()["error"]
        assert faux.remises == {}
        assert client.get("/team/handin.zip?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 200
        vue = client.get("/team/context?assignment=devoir",
                         headers=_entetes("t-alice")).json()
        assert vue["assignment"]["deadline_passed"] is True


def test_un_exercice_de_devoir_n_accorde_aucun_xp_mais_garde_l_etat():
    with deploiement_devoir() as (client, faux, tmp):
        _verdict("dev-a", "d" * 32, {"status": "ok", "total": 2, "passed": 2})
        assert client.get("/r/" + "d" * 32).status_code == 200
        assert faux.etats[("sub-alice", "dev-a")] == "solved"
        assert faux.pratique[("sub-alice", "dev-a")][0] == 1
        assert faux.xp == {} and faux.succes == {}
        _verdict("tp2-ex3", "e" * 32, {"status": "ok", "total": 1, "passed": 1})
        client.get("/r/" + "e" * 32)
        assert faux.xp, "un exercice ordinaire doit toujours accorder de l'XP"


def test_le_listage_des_equipes_est_reserve_a_l_enseignant_et_ne_nomme_personne():
    with deploiement_devoir() as (client, _, _):
        refuse = client.get("/team/roster?assignment=devoir",
                            headers=_entetes("t-alice"))
        assert refuse.status_code == 403
        r = client.get("/team/roster?assignment=devoir",
                       headers=_entetes("t-prof"))
        assert r.status_code == 200, r.text
        assert "sub-" not in r.text, r.text
        equipes = {e["team_id"]: e for e in r.json()["teams"]}
        assert equipes["e1"]["members"] == 2 and equipes["e1"]["group_number"] == 4
        assert equipes["e2"]["members"] == 1


def test_une_base_muette_rend_503_et_aucun_document():
    with deploiement_devoir() as (client, faux, _):
        faux.read_team_document = lambda *_: None
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_entetes("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}
        faux.team_roster = lambda *_: None
        assert client.get("/team/context?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 503


def _hello(socket, jeton, exercice="dev-a", devoir="devoir"):
    socket.send_json({"t": "hello", "token": jeton, "assignment": devoir,
                      "exercise": exercice})


def _code_de_fermeture(client, envoyer):
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/team/live") as socket:
            envoyer(socket)
            socket.receive_json()
        return None
    except WebSocketDisconnect as exc:
        return exc.code


def test_la_socket_refuse_avant_de_relayer():
    with deploiement_devoir() as (client, faux, _):
        collab.reset()
        assert _code_de_fermeture(
            client, lambda s: s.send_json({"t": "update", "d": "x"})) == 4400
        assert _code_de_fermeture(client, lambda s: s.send_text("pas du json")) == 4400
        assert _code_de_fermeture(client, lambda s: _hello(s, "t-inconnu")) == 4401
        faux.equipes.pop(("devoir", "sub-bob"))
        assert _code_de_fermeture(client, lambda s: _hello(s, "t-bob")) == 4403
        assert _code_de_fermeture(
            client, lambda s: _hello(s, "t-alice", exercice="tp2-ex3")) == 4403
        collab.reset()


def test_deux_coequipiers_se_voient_et_l_autre_equipe_ne_voit_rien():
    with deploiement_devoir() as (client, faux, _):
        collab.reset()
        with client.websocket_connect("/team/live") as alice:
            _hello(alice, "t-alice")
            pret_alice = alice.receive_json()
            assert pret_alice["t"] == "ready"
            assert pret_alice["peers"] == 0 and pret_alice["me"] == "m1"
            assert pret_alice["epoch"]
            assert alice.receive_json()["t"] == "presence"
            with client.websocket_connect("/team/live") as cleo:
                _hello(cleo, "t-cleo")
                pret_cleo = cleo.receive_json()
                assert pret_cleo["peers"] == 1 and pret_cleo["me"] == "m2"
                assert pret_cleo["epoch"] == pret_alice["epoch"]
                assert cleo.receive_json()["t"] == "presence"
                assert alice.receive_json() == {"t": "presence",
                                                "online": ["m1", "m2"]}
                with client.websocket_connect("/team/live") as bob:
                    _hello(bob, "t-bob")
                    pret_bob = bob.receive_json()
                    assert pret_bob["peers"] == 0
                    assert pret_bob["epoch"] != pret_alice["epoch"]
                    assert bob.receive_json()["t"] == "presence"

                    alice.send_json({"t": "update", "d": "AAEC",
                                     "from": "m2", "token": "t-alice"})
                    recue = cleo.receive_json()
                    assert recue["d"] == "AAEC"
                    assert recue["from"] == "m1"
                    assert "token" not in recue

                    alice.send_json({"t": "cursor", "file": "main.c",
                                     "a": "AA", "h": "AQ"})
                    curseur = cleo.receive_json()
                    assert curseur["t"] == "cursor" and curseur["from"] == "m1"

                    bob.send_json({"t": "update", "d": "ZZZ"})
                    with client.websocket_connect("/team/live") as bob2:
                        _hello(bob2, "t-bob")
                        bob2.receive_json()
                        bob2.receive_json()
                        assert bob.receive_json()["t"] == "presence"
                        bob.send_json({"t": "update", "d": "BBBB"})
                        suite = bob2.receive_json()
                        assert suite == {"t": "update", "d": "BBBB", "from": "m1"}
        collab.reset()


def test_une_trame_inconnue_ou_trop_grosse_ne_traverse_pas():
    from starlette.websockets import WebSocketDisconnect

    with deploiement_devoir() as (client, _, _):
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
                raise AssertionError("une trame hors bornes a été acceptée")
            except WebSocketDisconnect as exc:
                assert exc.code == 4400
        collab.reset()


def test_la_socket_refuse_une_origine_inconnue():
    from starlette.websockets import WebSocketDisconnect

    with deploiement_devoir() as (client, _, _):
        collab.reset()
        try:
            with client.websocket_connect(
                    "/team/live", headers={"Origin": INCONNUE}) as socket:
                socket.receive_json()
            raise AssertionError("origine inconnue acceptée")
        except WebSocketDisconnect as exc:
            assert exc.code == 4403
        with client.websocket_connect("/team/live",
                                      headers={"Origin": CONNUE}) as socket:
            _hello(socket, "t-alice")
            assert socket.receive_json()["t"] == "ready"
        collab.reset()


def test_mon_equipe_se_lit_avant_que_le_devoir_n_ouvre():
    with deploiement_devoir() as (client, faux, tmp):
        publie = _publier(tmp, DEVOIR, _devoir_json())
        racine = os.path.join(tmp, "content")
        _ecrire_contenu(racine, DEVOIR, devoir=dict(
            _devoir_json(), release={"state": "scheduled",
                                     "available_from": "2099-10-16T00:00:00-04:00"}))
        import content_catalog as content_catalogue
        import publish_content
        publish_content.publish(content_catalogue.discover(racine), publie)

        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            assert client.get(chemin, headers=_entetes("t-alice")).status_code == 404, chemin

        r = client.get("/team/mine", headers=_entetes("t-alice"))
        assert r.status_code == 200, r.text
        [equipe] = r.json()["teams"]
        assert equipe["label"] == "Équipe 1" and equipe["group_number"] == 4
        assert equipe["number"] == 1
        assert equipe["access"] == "scheduled"
        assert equipe["available_from"].startswith("2099-10-16")
        assert [m["id"] for m in equipe["members"]] == ["m1", "m2"]
        assert [m["you"] for m in equipe["members"]] == [True, False]
        assert "sub-" not in r.text, r.text
        assert "sources" not in r.text and "revision" not in r.text

        faux.equipes.pop(("devoir", "sub-bob"))
        vide = client.get("/team/mine", headers=_entetes("t-bob"))
        assert vide.status_code == 200 and vide.json() == {"teams": []}
        assert client.get("/team/mine").status_code == 401


def test_mon_equipe_dit_une_panne_au_lieu_d_inventer_une_absence():
    with deploiement_devoir() as (client, faux, _):
        faux.team_memberships = lambda *_: None
        r = client.get("/team/mine", headers=_entetes("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}


@contextlib.contextmanager
def deploiement_choix(ouvert=False):
    base = BaseSimulee()
    devoir = _devoir_json()
    if not ouvert:
        devoir = dict(devoir, release={
            "state": "scheduled",
            "available_from": "2099-10-16T00:00:00-04:00"})
    with contexte(jetons=JETONS_EQUIPE, moderateurs=("sub-prof",), base=base,
                  exercices=DEVOIR, devoir=devoir) as (c, faux, tmp):
        for compte in ("sub-alice", "sub-bob", "sub-cleo"):
            faux.forum_write_profile(compte + "-p", compte, None, 4,
                                     False, False)
        yield c, faux, tmp


def test_les_equipes_se_choisissent_dans_une_liste_numerotee():
    with deploiement_choix() as (client, faux, _):
        vue = client.get("/team/available?assignment=devoir",
                         headers=_entetes("t-alice"))
        assert vue.status_code == 200, vue.text
        corps = vue.json()
        assert corps["group_number"] == 4 and corps["mine"] is None
        assert [e["number"] for e in corps["teams"]] == [1, 2, 3, 4, 5, 6]
        assert corps["teams"][0] == {"number": 1, "name": "Équipe 1",
                                     "members": 0, "max": 4, "full": False}
        assert "sub-" not in vue.text and "Coéquipier" not in vue.text

        pris = client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir", "number": 3})
        assert pris.status_code == 200, pris.text
        assert pris.json()["mine"] == 3
        assert pris.json()["teams"][2]["members"] == 1
        assert faux.equipes[("devoir", "sub-alice")] == "g04-e03"

        encore = client.post("/team/join", headers=_entetes("t-alice"),
                             json={"assignment_id": "devoir", "number": 4})
        assert encore.status_code == 409 and "quitte-la" in encore.json()["error"]

        for numero in (0, 7, 999):
            r = client.post("/team/join", headers=_entetes("t-bob"),
                            json={"assignment_id": "devoir", "number": numero})
            assert r.status_code == 404, (numero, r.status_code)
            assert "il y en a 6" in r.json()["error"]


def test_une_equipe_complete_refuse_la_place_suivante():
    with deploiement_choix() as (client, faux, _):
        faux.inscrire("devoir", "g04-e02", ["a", "b", "c", "d"],
                      group_number=4, number=2)
        r = client.post("/team/join", headers=_entetes("t-alice"),
                        json={"assignment_id": "devoir", "number": 2})
        assert r.status_code == 409, r.text
        assert "complète (4 places)" in r.json()["error"]
        vue = client.get("/team/available?assignment=devoir",
                         headers=_entetes("t-alice")).json()
        assert vue["teams"][1]["full"] is True


def test_on_change_d_equipe_tant_que_le_devoir_est_ferme():
    with deploiement_choix() as (client, faux, _):
        client.post("/team/join", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        parti = client.post("/team/leave", headers=_entetes("t-alice"),
                            json={"assignment_id": "devoir"})
        assert parti.status_code == 200 and parti.json()["mine"] is None
        assert ("g04-e01", "devoir") in faux.equipes_meta
        assert client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 5}).json()["mine"] == 5
        client.post("/team/leave", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir"})
        assert client.post("/team/leave", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir"}).status_code == 404


def test_l_ouverture_du_devoir_fige_les_equipes():
    with deploiement_choix(ouvert=True) as (client, faux, _):
        for chemin, corps in (("/team/join", {"assignment_id": "devoir",
                                              "number": 1}),
                              ("/team/leave", {"assignment_id": "devoir"})):
            r = client.post(chemin, headers=_entetes("t-alice"), json=corps)
            assert r.status_code == 409, (chemin, r.text)
            assert "figées" in r.json()["error"]
        assert client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 409
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_entetes("t-alice"))
        assert r.status_code == 403 and "enseignant" in r.json()["error"]

    with deploiement_choix() as (client, faux, _):
        assert client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 1}).status_code == 200
        assert client.get("/team/document?assignment=devoir&ex=dev-a",
                          headers=_entetes("t-alice")).status_code == 404


def test_sans_groupe_au_profil_la_liste_dit_quoi_faire():
    with deploiement_choix() as (client, faux, _):
        faux.profils.pop("sub-bob", None)
        r = client.get("/team/available?assignment=devoir",
                       headers=_entetes("t-bob"))
        assert r.status_code == 409, r.text
        assert "Mon identité" in r.json()["error"]


def test_deux_groupes_ont_chacun_leur_equipe_numero_1():
    with deploiement_choix() as (client, faux, _):
        faux.forum_write_profile("p6", "sub-bob", None, 6, False, False)
        client.post("/team/join", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        client.post("/team/join", headers=_entetes("t-bob"),
                    json={"assignment_id": "devoir", "number": 1})
        assert faux.equipes[("devoir", "sub-alice")] == "g04-e01"
        assert faux.equipes[("devoir", "sub-bob")] == "g06-e01"
        vue4 = client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-alice")).json()
        vue6 = client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-bob")).json()
        assert vue4["group_number"] == 4 and vue6["group_number"] == 6
        assert vue4["teams"][0]["members"] == 1
        assert vue6["teams"][0]["members"] == 1, "les deux comptent 1, séparément"


def test_choisir_une_equipe_n_ouvre_aucun_document():
    with deploiement_choix() as (client, faux, _):
        r = client.post("/team/join", headers=_entetes("t-alice"),
                        json={"assignment_id": "devoir", "number": 1})
        assert "sources" not in r.text and "revision" not in r.text
        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            assert client.get(chemin, headers=_entetes("t-alice")).status_code == 404
        assert _code_de_fermeture(client, lambda s: _hello(s, "t-alice")) == 4403
        collab.reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    sautes = 0
    for fn in tests:
        try:
            fn()
        except RuntimeError as e:
            if "flock indisponible" not in str(e):
                raise
            sautes += 1
            print("saute " + fn.__name__ + " (pas de flock hors POSIX)")
            continue
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées%s."
          % (len(tests) - sautes,
             ", %d sautées hors POSIX" % sautes if sautes else ""))
