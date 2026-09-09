#!/usr/bin/env python3
"""La frontière HTTP de l'API FastAPI, éprouvée par `fastapi.testclient`.

Ce qui se voit depuis un navigateur -- codes, en-têtes, formes de corps -- et surtout
LES BORNES. Les règles pures (progression, forum, catalogue) restent éprouvées
par appel direct dans `test_ctester.py`, sans serveur.

    python3 test_api.py

UNE dépendance de test, `httpx2` (`pip install -r requirements-dev.txt`), tirée
par `TestClient`. L'APPLICATION, elle, n'a que ce que liste `requirements.txt`.

CE FICHIER TESTE LES EXTRÊMES, PAS LE CHEMIN HEUREUX. Chaque borne y est
éprouvée des DEUX CÔTÉS -- la valeur qui passe et la première qui ne passe plus.
Un test qui ne vérifie qu'un refus laisse passer une borne posée un cran trop
serré, et c'est l'étudiant qui la découvre à 23 h la veille de la remise.
"""

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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

# AVANT D'IMPORTER `main` : `config` lit l'environnement à l'import.
os.environ.setdefault("CTESTER_ORIGINS",
                      "https://tch009.thevhome.com,https://vianpyro.github.io")

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover -- message, pas trace
    sys.exit("test_api.py a besoin de httpx2 : pip install -r requirements-dev.txt")

import config      # noqa: E402
import deps        # noqa: E402
import state        # noqa: E402
import main        # noqa: E402
import security    # noqa: E402
import policy as politique  # noqa: E402
from services import collab  # noqa: E402
from services import quotas  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
INCONNUE = "https://mechant.example"

client = TestClient(main.app)


# --- Harnais ----------------------------------------------------------------

def _modules_avec_etat():
    """Tous les modules qui ont importé `state`, pour le remplacer PARTOUT.

    `security`, `services.forum`, `services.progress` et quatre routeurs
    importent `state` chacun de leur côté. En oublier un ferait
    parler un test à une VRAIE base -- absente en test, donc `enabled()` faux,
    donc des 503 partout et un contrôle qui « passe » sans rien avoir éprouvé.

    Le balayage est dynamique exprès : un module ajouté demain est couvert sans
    que personne n'ait à penser à cette liste.
    """
    return [m for m in list(sys.modules.values())
            if getattr(m, "state", None) is state]


class BaseSimulee:
    """Une base en mémoire. Chaque méthode rend ce que `state.py` promet.

    `None` VEUT DIRE « LA BASE N'A PAS RÉPONDU », et c'est la moitié la plus
    importante du contrat : les routes doivent alors répondre 503, jamais 200
    avec un zéro. Les tests de panne remplacent une méthode par `lambda *_: None`.
    """

    STATUSES = ("attempted", "solved")
    THEMES = ("light", "dark")
    enabled = staticmethod(lambda: True)

    EMPTY_PROFILE = {"display_name": None, "group_number": None,
                   "display_name_public": False, "group_number_public": False,
                   "alias": None, "plate_frame": None,
                   "badges_public": False, "leaderboard_opt_in": False}

    def __init__(self):
        self.brouillons, self.etats, self.themes = {}, {}, {}
        self.blocsnotes = {}      # La Console : un par compte
        self.messages, self.profils = [], {}
        self.pratique, self.jobs = {}, set()
        self.evenements, self.xp, self.succes = {}, {}, {}
        self.faits = []          # le journal, dans l'ordre d'écriture
        self.utiles = set()      # (message, account) -- "ça m'a aidé"
        self.retenus = {}        # message -> retained by a moderator?
        # LE LISTAGE EST ECRIT PAR L'ENSEIGNANT, PAS PAR L'API : ces deux
        # tables se remplissent ici comme `import_teams.py` les remplit en
        # production, et AUCUNE methode ci-dessous ne les ecrit. C'est la
        # moitie du contrat que le GRANT tient en vrai (`SELECT` seulement),
        # et la moitie que ce harnais peut tenir.
        self.equipes = {}        # (assignment, account) -> team_id
        self.equipes_meta = {}   # (team_id, assignment) -> {group_number, label, ...}
        self.verrous = {}        # (assignment, account) -> a confirme ?
        self.documents = {}      # (team_id, exercise) -> sources
        self.revisions = []      # append-only, newest last
        self.remises = {}        # (assignment, team_id) -> {...}
        self.horloge = 1000.0    # a clock the coalescing tests can move

    # -- comptes
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
        # CE QUI PART EST CE QUI PORTE UN COMPTE : l'appartenance et les
        # revisions signees. Le document et la remise de l'equipe restent --
        # ce sont trois autres personnes.
        for cle in [k for k in self.equipes if k[1] == user]:
            del self.equipes[cle]
        self.revisions = [r for r in self.revisions if r["account"] != user]
        return True

    # -- equipes
    def inscrire(self, assignment_id, team_id, comptes, group_number=4,
                 label=None, number=1):
        """Une équipe déjà constituée, comme après la période de choix.

        Les contrôles qui parlent du document, de la remise ou de la socket
        n'ont pas à rejouer le choix pour y arriver : c'est un autre sujet.
        """
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
        # LA PLACE EST COMPTÉE AVANT D'ENTRER, comme le `WHERE` de l'INSERT :
        # c'est le seul refus, et il n'est pas dans un `if` du routeur.
        if len(self._membres(assignment_id, team_id)) >= taille_max:
            return None
        self.equipes_meta.setdefault(
            (team_id, assignment_id),
            {"group_number": group_number, "number": number, "label": label})
        self.equipes[(assignment_id, user)] = team_id
        return team_id

    def team_leave(self, user, assignment_id):
        # L'ÉQUIPE VIDÉE RESTE : son numéro est celui de Moodle, et elle porte
        # peut-être déjà un document.
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
        # LA MEME REGLE QUE LE `WHERE` DE L'INSERT : rien si ce compte en a
        # ecrit une dans la fenetre, rien si la derniere porte deja ces
        # octets-la.
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
            # L'EQUIPE EST DANS LA CONDITION, comme dans le `WHERE` du SQL :
            # une revision d'une autre equipe ne resout pas.
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

    # -- pratique et progression
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
        # LA CLÉ EST LE FAIT, pas l'appel : rejouer le même verdict retombe sur
        # la même clé et ne crée rien.
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
        # Même clé, même refus que `grant_first_solve` : un sondage rejoué
        # n'ajoute pas une évidence de plus.
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
        # Un seul jour, celui de tout ce harnais : ce qu'on eprouve ici est que
        # la route porte le calendrier, pas que Postgres sache grouper.
        n = sum(a for (u, _), (a, _) in self.pratique.items() if u == user)
        return [{"date": "2026-09-04", "attempts": n}] if n else []

    def read_unlock_rates(self):
        compte = {}
        for (_, succes_id) in self.succes:
            compte[succes_id] = compte.get(succes_id, 0) + 1
        return compte, len({u for (u, _) in self.pratique})

    def leaderboard_rows(self, group_number, days):
        rows = []
        for compte, profil in self.profils.items():
            if not profil.get("leaderboard_opt_in"):
                continue
            if group_number is not None and profil.get("group_number") != group_number:
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

    # -- forum
    def forum_fil(self, ex, limite, reader=None):
        views = []
        for m in self.messages:
            if m["exercise_id"] != ex:
                continue
            views.append(dict(m, retained=self.retenus.get(m["id"], False),
                              helpful=sum(1 for (i, _) in self.utiles if i == m["id"]),
                              helped_me=(m["id"], reader or "") in self.utiles))
        return views[:limite]

    def forum_publier(self, mid, ex, user, texte, step=None, blocked_kind=None,
                      visibility="thread"):
        self.messages.append({"id": mid, "exercise_id": ex, "account": user,
                              "text": texte, "hidden": False,
                              "step": step, "blocked_kind": blocked_kind,
                              "visibility": visibility,
                              "created_at": "2026-09-04"})
        return True

    def forum_open_to_group(self, mid, user):
        # THE SAME RULE AS THE SQL `WHERE`: one's own, and private only.
        for m in self.messages:
            if (m["id"] == mid and m["account"] == user
                    and m.get("visibility") == "private"):
                m["visibility"] = "group"
                return [mid]
        return []

    def forum_mark_helpful(self, mid, user):
        for m in self.messages:
            if m["id"] == mid and m["account"] != user:
                if (mid, user) in self.utiles:
                    return []
                self.utiles.add((mid, user))
                return [mid]
        return []

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

    def forum_supprimer(self, mid, user):
        avant = len(self.messages)
        self.messages = [m for m in self.messages
                         if not (m["id"] == mid and m["account"] == user)]
        return len(self.messages) < avant

    def forum_signaler(self, mid, user):
        return True

    def forum_nom_signaler(self, mid, user):
        return True

    def forum_signalements(self, limite):
        return []

    def forum_noms_signales(self, limite):
        return []

    def forum_moderer(self, aid, mid, moderateur, action):
        for m in self.messages:
            if m["id"] == mid:
                # RETAINING EDITS NOTHING: the message stays identical, only
                # the mark moves -- like the journal in the real database.
                if action in ("retain", "unretain"):
                    self.retenus[mid] = (action == "retain")
                else:
                    m["hidden"] = (action == "hide")
                return True
        return False

    def forum_auteur(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["account"]
        return None

    def forum_profil(self, user):
        return self.profils.get(user, dict(self.EMPTY_PROFILE))

    def forum_profils(self, users):
        return {u: self.profils[u] for u in users if u in self.profils}

    def forum_profil_ecrire(self, pid, user, pseudo, groupe, pseudo_public,
                            groupe_public, set_by_moderator=False, alias=None,
                            plate_frame=None, badges_public=False,
                            leaderboard_opt_in=False):
        # LA DERNIERE LIGNE EST LE PROFIL, comme en base : on remplace tout,
        # et c'est ce qui fait echouer une ecriture partielle ici aussi.
        self.profils[user] = {"display_name": pseudo, "group_number": groupe,
                              "display_name_public": pseudo_public,
                              "group_number_public": groupe_public,
                              "alias": alias, "plate_frame": plate_frame,
                              "badges_public": badges_public,
                              "leaderboard_opt_in": leaderboard_opt_in}
        return True


# LE CONTENU DU DÉPLOIEMENT DE TEST, DANS SA FORME PRIVÉE. Le catalogue servi
# en est TIRÉ par `publish_content`, exactement comme en production : écrire un
# `catalog.json` à la main ici éprouverait une forme que rien ne produit.
#
# Un exercice par mode, parce que c'est le mode qui décide de ce que l'API
# attend -- des fichiers, un module à deux fichiers, ou des réponses.
CONTENU = [
    ("tp2-ex3", "TP2 ex.3", "io", ["submission.c"], ["variables"], "foundation"),
    ("tp5-mod", "TP5 module", "unity", ["calendrier.h", "calendrier.c"],
     ["structs"], "intermediate"),
    ("quiz1", "Quiz 1", "quiz", [], ["variables"], "intro"),
    # UNE VÉRIFICATION, marquée par son identifiant dans ce harnais seulement
    # (voir `_ecrire_contenu`). Elle est ici pour que TOUTE la suite traverse
    # la branche : un catalogue de test sans vérification laisserait la phase 2
    # éprouvée uniquement par les trois tests qui la visent.
    ("verif-tp2", "Vérification TP2", "quiz", [], ["variables"], "foundation"),
]


# LE CONTENU DU DEPLOIEMENT DE TEST, PLUS UN DEVOIR D'EQUIPE. Une liste a
# part plutot qu'un ajout a CONTENU : les controles existants comptent des
# exercices publies, et un devoir qui apparaitrait partout ferait echouer des
# tests qui n'ont rien a voir -- ce qui est exactement ce que "la
# fonctionnalite est additive" doit vouloir dire.
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
        # `count` : COMBIEN D'ÉQUIPES PAR GROUPE. C'est lui qui rend la
        # numérotation comparable à celle de Moodle, donc il est obligatoire.
        devoir["team"] = {"min": 3, "max": 4, "count": 6}
    if deadline:
        devoir["deadline"] = deadline
    return devoir


def _ecrire_contenu(racine, exercices=CONTENU, release=None, devoir=None):
    """Une racine de contenu privé v2, prête pour `discover()`."""
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
    """Publie ce contenu et pose le pointeur. Rend le répertoire des releases."""
    import content_catalog as content_catalogue
    import publish_content
    racine = os.path.join(tmp, "content")
    publie = os.path.join(tmp, "published")
    _ecrire_contenu(racine, exercices, devoir=devoir)
    publish_content.publish(content_catalogue.discover(racine), publie)
    return publie


@contextlib.contextmanager
def contexte(*, jetons=None, moderateurs=(), forum_actif=True, base=None,
             groupes=(4, 6), exercices=CONTENU, devoir=None, console=True):
    """Un déploiement complet en mémoire, remis en place à la sortie.

    TOUT EST RESTAURÉ DANS UN `finally`, y compris les quotas : un test qui
    laisserait un compteur rempli ferait échouer le SUIVANT, et on chercherait
    le bug dans le mauvais fichier.
    """
    tmp = tempfile.mkdtemp()
    spool, page = (os.path.join(tmp, n) for n in ("spool", "web"))
    for chemin in (spool, page):
        os.makedirs(chemin)
    publie = _publier(tmp, exercices, devoir)

    faux = base if base is not None else BaseSimulee()
    modules = _modules_avec_etat()
    garde_etat = [(m, m.state) for m in modules]
    garde_config = {n: getattr(config, n) for n in
                    ("PUBLISHED", "SPOOL", "PAGE", "KEY", "OIDC_ISSUER",
                     "OIDC_CLIENT_ID", "FORUM_MODERATORS", "FORUM_GROUPES",
                     "SCRATCH")}
    garde_secu = (security.current_user, security.current_name)
    garde_quotas = (deps.quota, deps.quota_connecte, deps.state_quota,
                    deps.forum_quota, deps.presence, deps.scratch_quota)

    for m in modules:
        m.state = faux
    config.SPOOL, config.PAGE = spool, page
    # LA RELEASE DE CE DÉPLOIEMENT, pas celle de la machine qui lance les tests :
    # un `CTESTER_PUBLISHED` exporté dans un shell ne doit pas décider de ce
    # qu'ils éprouvent.
    config.PUBLISHED = publie
    config.KEY = "cle-de-session"
    config.OIDC_ISSUER = "https://auth.exemple.com"
    config.OIDC_CLIENT_ID = "ctester"
    config.FORUM_MODERATORS = frozenset(moderateurs) if forum_actif else frozenset()
    config.FORUM_GROUPES = tuple(groupes)
    config.SCRATCH = console
    jetons = jetons or {}
    security.current_user = lambda entetes: jetons.get(
        entetes.get("Authorization", "").replace("Bearer ", ""))
    security.current_name = lambda entetes: ""
    # Des quotas neufs et larges : ces contrôles éprouvent des bornes précises,
    # et ceux qui éprouvent un quota posent le leur.
    deps.quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.quota_connecte = quotas.Quota(cooldown=0, hourly=100000)
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
        (deps.quota, deps.quota_connecte, deps.state_quota, deps.forum_quota,
         deps.presence, deps.scratch_quota) = garde_quotas
        shutil.rmtree(tmp, ignore_errors=True)


def _contenu_v2(racine):
    """Une racine de contenu v2 : un exercice ouvert, un exercice programmé."""
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
    """Le catalogue vient de la release, et le cadenas tient partout.

    LES DEUX MOITIÉS COMPTENT. Un exercice programmé est VISIBLE dans
    `/catalog.json` (avec son état) et reste injoignable partout ailleurs :
    ni consigne, ni soumission. Montrer n'est pas donner, et l'inverse --
    le faire disparaître, comme en v1 -- ressemblait à une panne.

    ET SANS RELEASE, RIEN. Depuis la phase 8 il n'y a plus de repli `tps.json` :
    un pointeur absent est un catalogue absent, ce que la page dit au lieu
    d'afficher un menu vide.
    """
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

        # PLUS DE POINTEUR : le catalogue est absent, et plus rien ne se résout.
        config.PUBLISHED = ""
        assert c.get("/catalog.json").status_code == 404
        assert c.get("/tp/ouvert.json").status_code == 404
        assert c.post("/submit", json=dict(corps, exercise_id="ouvert")).status_code == 400


def auth(nom):
    return {"Authorization": "Bearer " + nom}


# --- Transport : CORS, cache, préflight, 404 --------------------------------

def test_healthz_ne_touche_ni_base_ni_spool():
    """Le healthcheck du conteneur : vrai tant que ce processus sert du HTTP.

    S'il interrogeait Postgres, une panne de base ferait redémarrer en boucle le
    conteneur web -- alors que le parcours anonyme, lui, fonctionne encore.
    """
    r = client.get("/healthz")
    assert r.status_code == 200, r.status_code
    assert r.json() == {"ok": True}, r.json()


def test_cors_origine_connue_et_inconnue():
    """Une origine connue reçoit l'en-tête ; une inconnue ne reçoit RIEN.

    Pas de 403 : un réglage oublié ne doit pas ressembler à une panne de
    service, et le navigateur bloque de lui-même. Et jamais `*` -- chaque
    requête de compte porte un `Authorization`.
    """
    r = client.get("/healthz", headers={"Origin": CONNUE})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)

    r = client.get("/healthz", headers={"Origin": INCONNUE})
    assert r.status_code == 200, r.status_code
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)

    # Aucun cookie ici : le jeton voyage en en-tête.
    assert "access-control-allow-credentials" not in r.headers

    # La barre oblique finale ne doit pas faire d'une origine connue une
    # inconnue : `config.ORIGINS` et l'en-tête reçu sont tous deux `rstrip`és.
    r = client.get("/healthz", headers={"Origin": CONNUE + "/"})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)


def test_un_seul_vary_annoncant_les_deux_axes():
    """Deux lignes `Vary` sont légales et mal recombinées par certains caches.

    Un cache qui perd `Origin` sert la réponse d'une origine à une autre.
    `httpx` joint les doublons par « , » : on compte donc les occurrences de
    chaque axe, pas la longueur de la chaîne.
    """
    r = client.get("/healthz", headers={"Origin": CONNUE})
    vary = r.headers.get("vary", "")
    assert vary == "Accept-Encoding, Origin", vary
    assert vary.count("Origin") == 1 and vary.count("Accept-Encoding") == 1, vary


def test_preflight_sur_toute_route_meme_inconnue():
    """204, et `DELETE` dans la liste -- `compte.js` et `forum.js` en dépendent.

    Le préflight ne passe pas par le routeur : il répond avant, donc un chemin
    qui n'existe pas encore répond quand même. `Max-Age` évite un aller-retour
    de plus par PUT et par DELETE.
    """
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
    """Et pas un 405.

    Une route attrape-tout `OPTIONS /{chemin:path}` ferait répondre « méthode
    non autorisée » à tout chemin inexistant : Starlette retient sa
    correspondance partielle et ne descend jamais jusqu'au 404. C'est faux, et
    ça confirme au passage que le chemin existe.
    """
    r = client.get("/pas-une-route")
    assert r.status_code == 404, r.status_code
    assert r.json() == {"error": "inconnu"}, r.json()


def test_documentation_automatique_eteinte():
    """`/docs`, `/redoc` et `/openapi.json` décrivent toute la surface de l'API.

    FastAPI les sert publiquement par défaut. Sur une infra personnelle, c'est
    un plan des lieux offert. `config.DOCS` les retire -- la route n'existe pas,
    il n'y a donc rien à contourner.
    """
    assert not config.DOCS, "CTESTER_DOCS ne doit pas être posé en production"
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(chemin).status_code == 404, chemin


def test_no_store_par_defaut_sur_les_donnees():
    """Le défaut est `no-store` ; seuls les fichiers disent `no-cache`."""
    assert client.get("/healthz").headers.get("cache-control") == "no-store"
    assert client.get("/rien").headers.get("cache-control") == "no-store"
    with contexte() as (c, _, _tmp):
        assert c.get("/catalog.json").headers.get("cache-control") == "no-cache"
        assert c.get("/oidc.json").headers.get("cache-control") == "no-store"


def test_pas_d_annonce_de_version_de_serveur():
    """`Server: uvicorn` ne sert que celui qui cherche une version vulnérable.

    Le contrôle porte sur le RÉGLAGE et pas sur la réponse : `TestClient` ne
    passe pas par uvicorn, donc l'en-tête n'apparaît qu'en vrai.
    """
    with open(os.path.join(HERE, "app", "main.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert "server_header=False" in source
    assert "workers=1" in source


# --- Bornes du corps de requête ---------------------------------------------

def test_borne_du_corps_des_deux_cotes():
    """`MAX_CODE + 4096` passe, un octet de plus ne passe pas.

    Uvicorn N'A PAS de limite de taille de corps. Sans cette borne, un POST
    annonçant deux gigaoctets ferait lire deux gigaoctets avant la moindre
    validation. Le test porte sur le `Content-Length` ANNONCÉ : c'est lui qu'on
    refuse, avant de lire quoi que ce soit.
    """
    plafond = config.MAX_CODE + 4096
    with contexte() as (c, _, _tmp):
        # Pile sur la borne : accepté par le middleware (le 400 qui suit vient
        # de la validation, ce qui prouve justement qu'on est allé plus loin).
        corps = b'{"exercise_id": "tp2-ex3", "key": "x", "bourrage": "'
        corps += b"a" * (plafond - len(corps) - 2) + b'"}'
        assert len(corps) == plafond
        r = c.post("/submit", content=corps,
                   headers={"Content-Type": "application/json"})
        assert r.status_code != 413, (r.status_code, r.text)

        # Un octet de plus : refusé sans être lu.
        r = c.post("/submit", content=corps + b" ",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, r.status_code
        assert r.json() == {"error": "corps trop gros ou vide"}, r.json()


def test_corps_vide_ou_sans_longueur_annoncee():
    """Zéro octet et `Content-Length` absent sont tous deux refusés.

    Absent vaut « hors bornes » : une requête `chunked` n'annonce pas sa taille,
    et on ne lit pas un corps dont on ignore la longueur.
    """
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
    """422 de Pydantic -> 400 `{"error": ...}`, sans recopier ce qui a été reçu.

    Le défaut de FastAPI renvoie la valeur refusée à l'expéditeur. La page n'y
    comprendrait rien (elle lit `out.error`), et un corps refusé peut contenir
    le code de quelqu'un ou un jeton mal collé.
    """
    with contexte() as (c, _, _tmp):
        secret = "MonMotDePasseColleParErreur"
        r = c.post("/submit", content=json.dumps([secret]).encode(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json() == {"error": "requête malformée"}, r.json()
        assert secret not in r.text, r.text


# --- La clé de session ------------------------------------------------------

def test_cle_verifiee_avant_tout_autre_travail():
    """Une mauvaise clé répond 403 MÊME sur un TP inconnu.

    L'ordre est la propriété : si le catalogue était consulté d'abord, la
    différence entre « TP inconnu » (400) et « clé invalide » (403) dirait à qui
    sonde quels exercices existent, sans clé.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "mauvaise", "exercise_id": "nexiste-pas"})
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "nexiste-pas"})
        assert r.status_code == 400, (r.status_code, r.text)


def test_cle_vide_du_serveur_refuse_tout():
    """`CTESTER_KEY` vide n'ouvre pas la porte à une clé vide.

    Sans le premier `if`, `compare_digest("", "")` est vrai : un déploiement qui
    a perdu sa variable d'environnement servirait tout le monde.
    """
    with contexte() as (c, _, _tmp):
        config.KEY = ""
        r = c.post("/submit", json={"key": "", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "int main(){}"}})
        assert r.status_code == 403, (r.status_code, r.text)


# --- Bornes du catalogue et des fichiers ------------------------------------

def test_taille_des_fichiers_des_deux_cotes():
    """Exactement `MAX_CODE` passe, un octet de plus rend 413.

    La borne porte sur le JSON des fichiers, pas sur le corps de la requête :
    les deux existent, et c'est celle-ci qui protège la base et le spool.
    """
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

        # `sent` hors-forme : Pydantic bloque déjà ceci à la frontière HTTP
        # (`files: dict`), mais la fonction reste appelable directement par le
        # brouillon comme par la soumission, et doit refuser proprement.
        _, message, code = catalogue.validate_files(entree, ["pas", "un", "dict"])
        assert code == 400 and message == "fichiers manquants", (code, message)


def test_fichier_inattendu_est_refuse_pas_ignore():
    """Un nom hors catalogue est REFUSÉ, pas silencieusement jeté.

    Un étudiant doit savoir que son fichier n'a pas été pris. Le laisser tomber
    en silence produit un verdict sur un module incomplet, que personne ne
    comprend.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={
            "key": "cle-de-session", "exercise_id": "tp5-mod",
            "files": {"calendrier.h": "x", "calendrier.c": "y",
                      "secret.c": "z"}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert "secret.c" in r.json()["error"], r.json()


def test_soumission_entierement_blanche_est_refusee():
    """Espaces et retours à la ligne ne sont pas du code.

    Sans ça, cliquer « Tester » sur un éditeur vide occuperait un cœur du Dell
    pour compiler du vide.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "   \n\t  "}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json()["error"] == "soumission vide", r.json()


def test_quiz_bornes_du_nombre_et_de_la_longueur_des_reponses():
    """500 réponses gardées, la 501e jetée ; clés et valeurs coupées à 64.

    `Content-Length` ne suffit pas : un dictionnaire de dix mille clés d'une
    lettre tient largement sous la borne de corps.
    """
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
    """Un quiz de 40 cases vides ne part pas dans la file."""
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {"q1": "  ", "q2": ""}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {}})
        assert r.status_code == 400, (r.status_code, r.text)
        # `answers` complètement absent (ou `null`) : refusé plus tôt, avant
        # même de regarder si une case porte quelque chose.
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1"})
        assert r.status_code == 400 and r.json() == {"error": "réponses manquantes"}, r.text


def test_identifiant_d_exercice_hors_forme():
    """Un chemin n'est pas un identifiant, et il ne le devient jamais.

    `find_exercise` COMPARE À L'IDENTIFIANT DU CATALOGUE, il ne le concatène
    pas : c'est ce qui fait que `/tp/../catalog.json` n'est pas un chemin à
    traverser mais un nom qui n'existe pas. Le chemin lu, lui, est reconstruit
    par `source_publiee` depuis l'entrée trouvée -- jamais depuis l'URL.
    """
    from services import catalog as catalogue
    with contexte() as (c, _, _tmp):
        assert catalogue.find_exercise("a" * 32) is None  # bien formé, mais absent
        for hostile in ("../tps", "tp2/../../etc", "TP2-EX3", "tp2 ex3", ""):
            assert catalogue.find_exercise(hostile) is None, hostile
        assert c.get("/tp/..%2Fcatalog.json").status_code == 404
        assert c.get("/quiz/tp2-ex3.json").status_code == 404  # pas un quiz
        # L'entrée trouvée, elle, donne un chemin sous la release et rien d'autre.
        base, nom = catalogue.source_publiee(
            catalogue.find_exercise("tp2-ex3"), "detail")
        assert base == catalogue.release_dir()
        assert nom == os.path.join("exercises", "tp2-ex3.json"), nom


# --- Bornes des quotas et de la file ----------------------------------------

def test_quota_horaire_pile_et_un_de_trop():
    """Le Nième passe, le N+1e rend 429 avec `retry_after`.

    Le `retry_after` est ce que la page affiche : sans lui, elle inviterait à
    recliquer tout de suite, ce qui rallongerait l'attente de tout le monde.
    """
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
    """Deux comptes derrière UNE SEULE IP ne partagent pas le quota.

    C'est le cas du labo : 27 postes sortent par la même IP NATée, et compter
    par IP y ferait qu'un seul étudiant bloque toute la salle. L'anonyme, lui,
    reste compté par IP -- il n'a rien d'autre.
    """
    with contexte(jetons={"alice": "sub-alice", "bob": "sub-bob"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=1)
        deps.quota_connecte = quotas.Quota(cooldown=0, hourly=1)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for nom in ("alice", "bob"):
            r = c.post("/submit", json=charge, headers={**auth(nom), **nat})
            assert r.status_code == 200, (nom, r.status_code, r.text)
        # Chacun épuise le SIEN, et seulement le sien.
        r = c.post("/submit", json=charge, headers={**auth("alice"), **nat})
        assert r.status_code == 429, r.status_code
        # L'anonyme de la même salle garde son compteur d'IP, intact.
        assert c.post("/submit", json=charge, headers=nat).status_code == 200


def test_quota_anonyme_par_poste_et_cadran_plus_court_connecte():
    """Aux premiers labos personne n'est connecté, et la salle partage une IP.

    Deux postes anonymes derrière la MÊME IP ont chacun leur compteur ; sans
    jeton de poste, on retombe sur l'ancien comportement (l'IP seule). Et un
    compte attend moins entre deux soumissions -- son étiquette de quota est
    plus juste, donc moins facile à rejouer.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=30, hourly=100)
        deps.quota_connecte = quotas.Quota(cooldown=0, hourly=100)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for poste in ("p1", "p2"):
            r = c.post("/submit?poste=" + poste, json=charge, headers=nat)
            assert r.status_code == 200, (poste, r.status_code, r.text)
        # Chaque poste épuise le sien, et seulement le sien.
        assert c.post("/submit?poste=p1", json=charge, headers=nat).status_code == 429
        assert c.post("/submit?poste=p3", json=charge, headers=nat).status_code == 200
        # Sans jeton : le compteur d'IP, comme avant. Deux d'affilée, la
        # seconde attend.
        assert c.post("/submit", json=charge, headers=nat).status_code == 200
        assert c.post("/submit", json=charge, headers=nat).status_code == 429
        # Le compte a son propre cadran, et le poste ne le concerne pas.
        for _ in range(3):
            r = c.post("/submit?poste=p1", json=charge,
                       headers={**auth("alice"), **nat})
            assert r.status_code == 200, (r.status_code, r.text)


def test_quota_ne_consomme_rien_sur_une_requete_refusee():
    """Un TP inconnu ne doit pas grignoter le quota de quelqu'un.

    Sinon un client bogué qui envoie un mauvais identifiant épuise le quota d'un
    étudiant qui n'a rien demandé, et c'est LUI qui reçoit le 429.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.state_quota = quotas.Quota(cooldown=0, hourly=2)
        for _ in range(5):
            r = c.put("/brouillon", json={"exercise_id": "inconnu", "files": {}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.status_code
        # Le quota est intact : les deux écritures valides passent encore.
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
    """`QUEUE_MAX` jobs en attente : le suivant rend 503, pas 200.

    Le plafond existe pour que la file reste lisible et que le Dell garde ses
    cœurs. Un job de plus accepté « juste cette fois » est ce qui fait déborder.
    """
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
    """Une fenêtre vue il y a exactement TTL secondes ne compte plus.

    Le TTL vaut 2,5 battements pour qu'un ping raté ne fasse pas clignoter le
    total. La borne est stricte (`>`), donc « pile au TTL » est expiré.
    """
    p = quotas.Presence()
    assert p.touch("a", 1000.0) == 1
    assert p.touch("a", 1000.0) == 1, "le même jeton ne compte pas deux fois"
    assert p.touch("b", 1000.0) == 2
    # `a` et `b` ont exactement TTL secondes : tous deux expirés, seul `c` reste.
    assert p.touch("c", 1000.0 + config.PRESENCE_TTL) == 1
    # Une seconde plus tôt, ils tiennent encore.
    q = quotas.Presence()
    q.touch("a", 1000.0)
    assert q.touch("c", 1000.0 + config.PRESENCE_TTL - 1) == 2


def test_live_tronque_un_jeton_trop_long_au_lieu_de_refuser():
    """La seule route anonyme ne doit jamais pouvoir échouer sur une entrée.

    Un `max_length` ferait un 400 sur un jeton fabriqué. Ce n'est qu'un chiffre
    affiché : il se tronque, il ne se plaint pas.
    """
    with contexte() as (c, _, _tmp):
        r = c.get("/live?id=" + "z" * 500)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["n"] == 1, r.json()


# --- Frontières d'authentification et de rôle -------------------------------

def test_ordre_des_refus_forum_eteint_avant_jeton_absent():
    """Forum éteint : 503 même sans jeton, jamais 401.

    Un 401 laisserait croire qu'il suffit de se connecter pour voir un forum qui
    n'existe pas sur ce déploiement.
    """
    with contexte(forum_actif=False) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 503, (r.status_code, r.text)
        assert "discussions" in r.json()["error"], r.json()
    with contexte(moderateurs=["sub-prof"]) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 401, (r.status_code, r.text)


def test_role_de_moderation_recalcule_et_jamais_recu():
    """Un étudiant qui se déclare modérateur reste un étudiant.

    Le drapeau `moderateur` de la réponse est un drapeau d'AFFICHAGE. Les deux
    routes réservées repartent du `sub` authentifié et de la liste du serveur.
    """
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, _, _tmp):
        assert c.get("/forum/moderation", headers=auth("prof")).status_code == 200
        r = c.get("/forum/moderation", headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)
        # Même en le réclamant dans le corps d'une route d'écriture.
        r = c.post("/forum/moderation",
                   json={"id": "0" * 32, "action": "hide",
                         "moderateur": True, "account": "sub-prof"},
                   headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)


def test_aucune_route_n_accepte_un_identifiant_dans_le_corps():
    """Écrire au nom d'un autre : la seule source de `sub` est le jeton.

    Le contrôle est structurel -- aucun modèle de `schemas.py` ne porte de champ
    d'identité -- et il est aussi éprouvé en vrai ci-dessous.
    """
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
    """Y compris dans la vue la plus renseignée, celle d'un modérateur."""
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


# --- Bornes du contenu du forum ---------------------------------------------

def test_forum_texte_des_deux_cotes_de_la_borne():
    """1 caractère passe, `FORUM_MAX_CHARS` passe, un de plus ne passe pas."""
    from services import forum
    assert forum.forum_texte("")[0] is None
    assert forum.forum_texte("   \n ")[0] is None
    assert forum.forum_texte("a")[0] == "a"
    assert forum.forum_texte("a" * config.FORUM_MAX_CHARS)[0] is not None
    trop, message = forum.forum_texte("a" * (config.FORUM_MAX_CHARS + 1))
    assert trop is None and str(config.FORUM_MAX_CHARS) in message, message


def test_forum_pseudo_bornes_et_noms_reserves():
    """Les étiquettes de l'interface ne se reprennent pas, casse comprise.

    Un message qui se ferait passer pour une réponse du cours ne se rattrape par
    aucune couleur.
    """
    from services import forum
    assert forum.forum_pseudo("a")[0] == "a"
    assert forum.forum_pseudo("a" * config.FORUM_PSEUDO_MAX)[0] is not None
    assert forum.forum_pseudo("a" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    for reserve in ("Vous", "PARTICIPANT", "Enseignant", "Équipe du cours",
                    "modérateur"):
        nom, message = forum.forum_pseudo(reserve)
        assert nom is None and message, reserve


def test_forum_groupe_liste_fermee_et_champ_libre():
    """Liste non vide : seuls ses numéros. Liste vide : 1..99, bornes comprises."""
    from services import forum
    with contexte(groupes=(4, 6)) as (_c, _b, _tmp):
        assert forum.forum_groupe(4)[0] == 4
        assert forum.forum_groupe("6")[0] == 6
        assert forum.forum_groupe(5)[0] is None
        assert forum.forum_groupe(0)[0] is None
    with contexte(groupes=()) as (_c, _b, _tmp):
        assert forum.forum_groupe(1)[0] == 1
        assert forum.forum_groupe(99)[0] == 99
        assert forum.forum_groupe(0)[0] is None
        assert forum.forum_groupe(100)[0] is None
        assert forum.forum_groupe("douze")[0] is None


def test_identifiant_de_message_et_de_job_hors_forme():
    """32 hexadécimaux minuscules, ni 31, ni 33, ni majuscules."""
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
    """Un champ vide n'est pas un champ visible.

    Sans ça, cocher la case sans rien écrire afficherait « Participant » en
    croyant s'être nommé.
    """
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, base, _tmp):
        r = c.post("/forum/profil",
                   json={"display_name": "", "group_number": None, "display_name_public": True,
                         "group_number_public": True}, headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        profil = base.profils["sub-alice"]
        assert profil["display_name_public"] is False, profil
        assert profil["group_number_public"] is False, profil


# --- Panne de base : 503, jamais un zéro ------------------------------------

def test_base_muette_ne_devient_jamais_un_zero():
    """Annoncer « 0 XP » pendant une panne, c'est dire que le travail a disparu."""
    base = BaseSimulee()
    base.read_progress = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "xp" not in r.text, r.text


def test_theme_vide_est_un_200_et_une_panne_un_503():
    """Les confondre écraserait le réglage de quelqu'un à la première panne."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        r = c.get("/preferences", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"theme": ""}, r.text
    base = BaseSimulee()
    base.read_theme = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        assert c.get("/preferences", headers=auth("alice")).status_code == 503


def test_ecriture_qui_echoue_ne_repond_pas_200():
    """La page n'affiche « enregistré » que sur une réponse vraie."""
    base = BaseSimulee()
    base.write_theme = lambda user, theme: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)


def test_write_preferences_succeeds_and_says_so():
    """The happy path of PUT /preferences was never verified: neither the
    200, nor the `{"ok": true}` body the page reads to show "saved"."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert base.themes["sub-alice"] == "dark", base.themes


def test_theme_inconnu_est_refuse():
    """`state.THEMES` est la liste close, et elle est vérifiée avant d'écrire."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for mauvais in ("", "sepia", "DARK", "light; DROP TABLE"):
            r = c.put("/preferences", json={"theme": mauvais},
                      headers=auth("alice"))
            assert r.status_code == 400, (mauvais, r.status_code)
        assert not base.themes, base.themes


def test_release_dir_and_load_catalog_survive_a_broken_pointer():
    """`release_dir()` never raises: a broken `current.json` returns `None`,
    not a stack trace that would surface to a student.
    """
    from services import catalog as catalogue
    guard = config.PUBLISHED
    tmp = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        config.PUBLISHED = tmp
        assert catalogue.release_dir() is None                 # nothing published
        assert catalogue.load_catalog() is None
        assert catalogue.source_publiee({"id": "x"}, "detail") == (None, None)

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            fh.write("{ this is not JSON")
        assert catalogue.release_dir() is None                 # unreadable

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert catalogue.release_dir() is None                 # no "revision"

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "../../etc"}, fh)
        assert catalogue.release_dir() is None                 # out of form

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "0123456789abcdef"}, fh)
        assert catalogue.release_dir() is None                 # directory absent

        os.makedirs(os.path.join(tmp, "0123456789abcdef"))
        assert catalogue.release_dir() == os.path.join(tmp, "0123456789abcdef")
        assert catalogue.load_catalog() is None                # catalog.json absent
        with open(os.path.join(tmp, "0123456789abcdef", "catalog.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")                               # JSON, but not an object
        assert catalogue.load_catalog() is None
    finally:
        config.PUBLISHED = guard
        shutil.rmtree(tmp)


def test_quiz_json_serves_the_published_quiz():
    """The happy path of GET /quiz/<id>.json was never verified."""
    with contexte() as (c, _base, _tmp):
        r = c.get("/quiz/quiz1.json")
        assert r.status_code == 200, r.text
        assert r.json()["questions"][0]["id"] == "q1", r.json()
        assert "answer" not in r.text, r.text


def test_detail_and_quiz_survive_a_rollback_mid_request():
    """Between `find_exercise` and `source_publiee`, the release can
    disappear (a rollback in flight, see services/catalog.py::source_publiee):
    a clean 404, never a stack trace.
    """
    import routers.catalog as catalog_router
    guard = catalog_router.source_publiee
    try:
        with contexte() as (c, _base, _tmp):
            catalog_router.source_publiee = lambda entry, quoi: (None, None)
            r = c.get("/tp/tp2-ex3.json")
            assert r.status_code == 404 and r.json() == {"error": "inconnu"}, r.text
            r = c.get("/quiz/quiz1.json")
            assert r.status_code == 404 and r.json() == {"error": "pas un quiz"}, r.text
    finally:
        catalog_router.source_publiee = guard


def test_etats_and_pratique_during_a_database_outage():
    """Two screens forgotten by the outage check: never a 200 on a mute database."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        assert c.get("/etats", headers=auth("alice")).json() == {"states": []}
        assert c.get("/pratique", headers=auth("alice")).json() == {"practice": []}
        base.etats[("sub-alice", "tp2-ex3")] = "solved"
        r = c.get("/etats", headers=auth("alice"))
        assert r.json() == {"states": [{"exercise_id": "tp2-ex3", "status": "solved"}]}, r.text

    base = BaseSimulee()
    base.read_states = lambda user: None
    base.read_practice_summary = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        assert c.get("/etats", headers=auth("alice")).status_code == 503
        assert c.get("/pratique", headers=auth("alice")).status_code == 503


def test_read_draft_refuses_an_unknown_exercise_and_distinguishes_absence():
    """`sources: null` is an exercise never opened, not an outage."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, _base, _tmp):
        r = c.get("/brouillon?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"sources": None}, r.text

        c.put("/brouillon", json={"exercise_id": "tp2-ex3", "files": {"submission.c": "int x;"}},
              headers=auth("alice"))
        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.json() == {"sources": {"submission.c": "int x;"}}, r.text


def test_write_draft_refuses_a_file_outside_the_allow_list_before_the_quota():
    """The name allow-list is checked BEFORE the write throttle.

    Otherwise a client insisting on a bad file name would exhaust the
    cooldown of someone who saved nothing -- the same defect as for an
    unknown exercise, but on the file-validation side this time (deps.py:65).
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for _ in range(5):
            r = c.put("/brouillon",
                      json={"exercise_id": "tp2-ex3", "files": {"hack.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.text
            assert "fichier inattendu" in r.json()["error"], r.text
        assert not base.brouillons
        # The cooldown is intact: a valid write still goes through right
        # away, it was not consumed by the earlier refusals.
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
        assert c.get("/etats", headers=auth("alice")).json() == {"states": []}

    base = BaseSimulee()
    base.forget = lambda user: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.delete("/moi", headers=auth("alice"))
        assert r.status_code == 503, r.text


# --- Fichiers servis : ETag, gzip, CSP --------------------------------------

def test_gzip_pile_a_la_borne_de_1024_octets():
    """1023 octets partent tels quels, 1024 partent compressés.

    L'étiquette DIFFÈRE entre les deux représentations (`-gz`) : un cache
    intermédiaire ne doit jamais servir l'une en croyant valider l'autre.
    """
    with contexte() as (c, _, _tmp):
        # Le catalogue est court ; on éprouve la borne sur la fonction elle-même.
        import headers as h

        class FausseRequete:
            def __init__(self, entetes):
                self.headers = entetes

        gzip_ok = FausseRequete({"accept-encoding": "gzip"})
        petit = h.fichier(gzip_ok, b"a" * 1023, "application/json")
        gros = h.fichier(gzip_ok, b"a" * 1024, "application/json")
        assert "content-encoding" not in petit.headers, dict(petit.headers)
        assert gros.headers["content-encoding"] == "gzip", dict(gros.headers)
        assert not petit.headers["etag"].endswith('-gz"')
        assert gros.headers["etag"].endswith('-gz"')
        # Sans `Accept-Encoding: gzip`, la même ressource garde une AUTRE
        # étiquette : deux corps, deux étiquettes.
        nu = h.fichier(FausseRequete({}), b"a" * 1024, "application/json")
        assert nu.headers["etag"] != gros.headers["etag"]


def test_fichier_du_disque_responds_500_when_the_file_is_missing():
    """The catalog promises a file; if it vanished from disk (a rollback in
    flight, corruption), that is a server error, never a bare trace.
    """
    import headers as h

    class FakeRequest:
        headers = {}

    r = h.fichier_du_disque(FakeRequest(), "/path/that/does/not/exist",
                            "missing.json", "application/json")
    assert r.status_code == 500 and json.loads(r.body) == {"error": "fichier manquant"}


def test_the_middleware_ignores_non_http_scopes():
    """The ASGI startup/shutdown ("lifespan") does not go through CORS/Vary:
    the middleware must let it through untouched, not crash on it.
    """
    with TestClient(main.app):
        pass   # entering/exiting the context sends startup then shutdown


def test_entier_falls_back_to_the_default_when_the_variable_is_unreadable():
    os.environ["CTESTER_TEST_ENTIER_INVALIDE"] = "not-a-number"
    try:
        assert config._entier("CTESTER_TEST_ENTIER_INVALIDE", "42") == 42
    finally:
        del os.environ["CTESTER_TEST_ENTIER_INVALIDE"]


def test_304_garde_la_csp_et_le_cache():
    """Une CSP qui n'apparaîtrait que sur le 200 disparaîtrait dès la 2e visite.

    C'est-à-dire presque toujours : le navigateur revalide à chaque chargement.
    """
    page = os.path.join(HERE, "web")
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


def test_page_serves_an_allow_listed_file_other_than_index():
    """`/{nom:path}`: `index.html` has its own test; another name from the
    list (`app.js`) was never served successfully, only its 404 was.
    """
    page = os.path.join(HERE, "web")
    if not os.path.isdir(page):
        return
    with contexte() as (c, _, _tmp):
        config.PAGE = page
        c2 = TestClient(main.create_app())
        r = c2.get("/app.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")


def test_page_sert_une_liste_close_pas_un_repertoire():
    """`StaticFiles` monterait un RÉPERTOIRE. Ici chaque nom est écrit en clair."""
    from routers import page as routeur_page
    with contexte() as (c, _, tmp):
        config.PAGE = os.path.join(tmp, "web")
        with open(os.path.join(config.PAGE, "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("pas pour toi")
        c2 = TestClient(main.create_app())
        assert c2.get("/secret.txt").status_code == 404
        assert c2.get("/../app/catalog.json").status_code in (404, 400)
        assert "secret.txt" not in routeur_page.SERVIS


def test_page_absente_ne_monte_aucune_route_de_fichier():
    """Sans `CTESTER_PAGE`, cette origine ne répond plus que sur des données.

    C'est l'état visé par la séparation front/back : `/` n'existe plus.
    """
    with contexte() as (c, _, _tmp):
        config.PAGE = ""
        c2 = TestClient(main.create_app())
        assert c2.get("/").status_code == 404
        assert c2.get("/app.js").status_code == 404
        # L'API, elle, répond toujours.
        assert c2.get("/healthz").status_code == 200
        assert c2.get("/catalog.json").status_code == 200


# --- Progression : la première réussite seulement ---------------------------

def test_xp_accorde_une_seule_fois_par_exercice():
    """Rejouer le verdict, ou refaire l'exercice, ne rapporte pas deux fois.

    Les deux tiennent par la même chose : l'identifiant d'événement vaut
    `reussite:<exercice>` et sa clé primaire refuse le doublon. C'est ce qui
    permet de laisser la pratique illimitée sans la rendre farmable.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        verdict = {"status": "ok", "passed": 3, "total": 3}
        for numero in range(2):
            job = "%032x" % numero
            os.makedirs(os.path.join(config.SPOOL, job))
            with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
            with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(verdict, fh)
            # Sondé deux fois, comme le fait la page.
            assert c.get("/r/" + job).status_code == 200
            assert c.get("/r/" + job).status_code == 200
        accorde = [t for t in base.xp.values() if t["amount"] > 0]
        assert len(accorde) == 1, base.xp


def test_r_returns_an_anonymous_job_s_verdict_without_recording_it():
    """A job with NO account: the verdict still goes out, and nothing is
    written to the database -- there is nobody to attribute it to.
    """
    with contexte() as (c, base, _tmp):
        job = "a" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": None}, fh)
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.etats, (base.xp, base.etats)


def test_r_records_nothing_if_the_exercise_closed_since_the_submission():
    """Between the submission and the read, the exercise may have closed or
    vanished: the state and the XP are then not written, but the verdict is
    still returned.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "b" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "vanished-exercise", "owner": "sub-alice"}, fh)
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
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
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 2, "total": 3}, fh)
        assert c.get("/r/" + job).status_code == 200
        assert not base.xp, base.xp
        assert base.etats[("sub-alice", "tp2-ex3")] == "attempted", base.etats


# --- Maîtrise vérifiée : l'autre domaine ------------------------------------

def _verdict(exercise_id, job, resultat):
    """Un job jugé, tel que le worker le laisse dans le spool."""
    os.makedirs(os.path.join(config.SPOOL, job))
    for nom, valeur in (("job.json", {"exercise_id": exercise_id,
                                      "owner": "sub-alice"}),
                        ("result.json", resultat)):
        with open(os.path.join(config.SPOOL, job, nom), "w",
                  encoding="utf-8") as fh:
            json.dump(valeur, fh)


def test_une_verification_laisse_une_evidence_et_aucun_xp():
    """Deux domaines : la vérification mesure, l'XP compte de l'activité.

    CE QUI EST VÉRIFIÉ ICI : qu'une vérification réussie ne verse RIEN au solde
    -- sans quoi elle serait farmable et l'XP se confondrait avec une note --
    et qu'un sondage rejoué n'ajoute pas une évidence de plus.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "a" * 32, {"status": "ok", "passed": 3, "total": 3})
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert not base.xp, base.xp
        evidences = [f for f in base.faits if f["type"] == "VerificationEvaluated"]
        assert len(evidences) == 1, base.faits
        assert evidences[0]["payload"]["passed"] is True
        # La charge ne porte QUE de quoi remonter au job : ni code, ni verdict.
        assert set(evidences[0]["payload"]) == {"job", "passed"}

        vue = c.get("/progres", headers=auth("alice")).json()
        assert vue["xp"] == 0, vue
        assert {c_["id"]: c_["band"] for c_ in vue["mastery"]["skills"]} == {
            "variables": "verifie"}
        # Elle ne compte pas non plus comme un exercice de pratique.
        assert vue["exercises"]["total"] == len(CONTENU) - 1, vue["exercises"]
        assert [s["id"] for s in vue["achievements"]] == ["premiere-verification"]


def test_une_verification_ratee_se_lit_a_consolider():
    """Sans la trace d'un échec, « à consolider » n'existerait pas.

    Une compétence tentée sans succès serait alors indistinguable d'une
    compétence jamais abordée, et l'étudiant ne saurait pas où revenir.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "b" * 32, {"status": "ok", "passed": 1, "total": 3})
        assert c.get("/r/" + "b" * 32).status_code == 200
        vue = c.get("/progres", headers=auth("alice")).json()
        assert [c_["band"] for c_ in vue["mastery"]["skills"]] == ["a-consolider"]
        assert not base.xp and not vue["achievements"], (base.xp, vue["achievements"])


def test_les_evidences_muettes_repondent_503():
    """Une bande « pas encore vérifié » ne doit jamais être le zéro d'une panne."""
    base = BaseSimulee()
    base.read_events = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "mastery" not in r.text and "xp" not in r.text, r.text


def test_verdict_illisible_ne_boucle_pas():
    """Le worker écrit par rename atomique, donc ce cas est un bug du worker.

    Le dire (500) plutôt que de laisser la page sonder indéfiniment.
    """
    with contexte() as (c, _, _tmp):
        job = "e" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ pas du json")
        r = c.get("/r/" + job)
        assert r.status_code == 500, (r.status_code, r.text)
        assert r.json()["state"] == "error", r.json()


def test_rang_dans_la_file_et_job_disparu():
    """« En cours » n'est pas « 1er dans la file », et un job balayé rend 404."""
    with contexte() as (c, _, _tmp):
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){}"}}
        premier = c.post("/submit", json=charge).json()["id"]
        second = c.post("/submit", json=charge).json()["id"]
        for job, rang in ((premier, 1), (second, 2)):
            corps = c.get("/r/" + job).json()
            assert corps["state"] == "queued" and corps["position"] == rang, corps
        # Le worker prend le premier : il n'est plus « 1er dans la file ».
        open(os.path.join(config.SPOOL, premier, ".lock"), "w").close()
        assert c.get("/r/" + premier).json() == {"state": "running"}
        r = c.get("/r/" + "a" * 32)
        assert r.status_code == 404 and r.json() == {"state": "gone"}, r.text


def test_eta_somme_les_durees_mesurees_et_retombe_sur_une_moyenne():
    """L'ETA est la SOMME des jobs devant, pas un rang fois une constante.

    Un quiz se corrige instantanément, un TP de dix cas paie dix exécutions :
    deux files du même rang n'attendent pas la même chose. Ce que le worker a
    mesuré (`durees.json`) prime ; un exercice jamais vu prend la moyenne des
    autres, et sans aucune mesure la constante pessimiste.
    """
    with contexte() as (c, _, _tmp):
        garde = config.WORKERS
        try:
            config.WORKERS = 1  # sinon l'ETA est divisé, et le calcul illisible
            charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            premier = c.post("/submit", json=charge).json()["id"]
            second = c.post("/submit", json=charge).json()["id"]

            # 1. Aucune mesure : la constante pessimiste, une fois par job devant.
            assert c.get("/r/" + premier).json()["eta"] == 15
            assert c.get("/r/" + second).json()["eta"] == 30

            # 2. Avec une mesure, c'est ELLE qui compte, pour les deux jobs.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp2-ex3": [4.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 4
            assert c.get("/r/" + second).json()["eta"] == 8

            # 3. Un exercice non mesuré prend la moyenne des autres, JAMAIS zéro :
            #    annoncer « tout de suite » sur une file pleine est pire que rien.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp1": [2.0, 20], "tp6-ex1": [10.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 6

            # 4. Deux workers dépilent deux fois plus vite.
            config.WORKERS = 2
            assert c.get("/r/" + second).json()["eta"] == 6

            # 5. Un fichier de durées corrompu ne casse pas le sondage.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                fh.write("{ pas du json")
            r = c.get("/r/" + premier)
            assert r.status_code == 200 and r.json()["eta"] > 0, r.text
        finally:
            config.WORKERS = garde


# --- The redesign: private help, helpful marks, leaderboard, collection -----


def test_a_private_question_does_not_cross_the_http_boundary():
    """THE LEAK THAT MUST BE PROVEN FOR REAL, not only in unit tests.

    "Only the lab instructor" is written on the student's form. This check
    goes through the real router, with two real accounts, because that is the
    promise easiest to break by changing one request.
    """
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        # Alice asks for help: private by default, without even saying so.
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "stuck",
                                   "step": "compilation",
                                   "blocked_kind": "unclear-error"},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        assert fake.messages[0]["visibility"] == "private", fake.messages
        assert fake.messages[0]["step"] == "compilation"

        seen = lambda who: c.get("/forum?ex=tp2-ex3", headers=auth(who)).json()["messages"]
        assert [m["id"] for m in seen("alice")]         # its own author sees it
        assert seen("bob") == []                        # nobody else
        assert len(seen("prof")) == 1                   # the moderator, yes

        # AND ITS AUTHOR CAN OPEN IT TO THEIR GROUP, in one click, with no republishing.
        mid = fake.messages[0]["id"]
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("bob")).status_code == 404   # not theirs
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[0]["visibility"] == "group"
        # THE TRANSITION IS ONE-WAY: replayed, it no longer finds a private
        # message -- so nothing to close back, and nothing to hide behind
        # after others have read it.
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 404


def test_helpful_mark_cannot_be_self_voted_and_counts_once():
    """A usefulness counter, not a popularity vote -- and it grants NOTHING.

    Three refusals in a single database statement: the made-up id, one's own
    message, and the duplicate. All three return the same response.
    """
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "my answer"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        # One's own message: refused, like a made-up id.
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("alice")).status_code == 404
        assert c.post("/forum/helpful", json={"id": "0" * 32},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("bob")).status_code == 200
        # Twice: the primary key refuses, and the route says the same thing.
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("bob")).status_code == 404
        seen = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"][0]
        assert seen["helpful"] == 1 and seen["helped_me"] is True
        # AND NO XP COMES OUT OF IT: marking helpful does not touch progression.
        assert fake.xp == {} and fake.succes == {}


def test_retaining_an_answer_does_not_edit_the_message():
    """Retaining an answer edits nothing: the text is identical before and after.

    That is the message's immutability, which is what keeps a report
    readable. The action lives in the journal, and it is reversible.
    """
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "the answer"},
               headers=auth("alice"))
        mid, before = fake.messages[0]["id"], fake.messages[0]["text"]
        # Reserved to the moderator, like hiding.
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("alice")).status_code == 403
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before, "the message was edited"
        thread = c.get("/forum?ex=tp2-ex3", headers=auth("alice")).json()
        assert thread["messages"][0]["retained"] is True
        assert thread["state"]["resolved"] == 1
        # REVERSIBLE, and the message still has not moved.
        assert c.post("/forum/moderation", json={"id": mid, "action": "unretain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before
        assert c.get("/forum?ex=tp2-ex3",
                     headers=auth("alice")).json()["messages"][0]["retained"] is False


def test_who_needs_help_counts_without_naming_and_stays_restricted():
    """The instructor's aggregate: accounts and steps, never people.

    A private question is COUNTED there without being revealed -- that is
    exactly what the student's form promises, and the compromise holds only
    because nothing else comes out.
    """
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
        # NO `sub`, NO TEXT, NO CODE: a count is enough to know where to go.
        payload = r.text
        for forbidden in ("sub-alice", "sub-bob", "I don't understand"):
            assert forbidden not in payload, payload


def test_the_leaderboard_is_opt_in_and_mute_under_the_cohort():
    """An unticked box is not a hidden row: it is an absence.

    And the alias is DRAWN by the server the moment one ticks the box --
    otherwise ticking the box would lead to a nameless leaderboard, or to a
    400 telling one to press another button first.
    """
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
        # UNDER THE MINIMUM COHORT: one's own row, no table.
        assert view["rows"] == [] and view["cohort"] < view["minimum"]
        # AND NO `sub` COMES OUT, no more than elsewhere.
        assert "sub-alice" not in c.get("/leaderboard", headers=auth("alice")).text

        # THE ALIAS REDRAWS, as often as one likes.
        # A BODY, EVEN EMPTY: the middleware bounds every POST before
        # parsing, and a missing `Content-Length` counts as out of bounds.
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 200 and r.json()["alias"] != alias

        # OPTING OUT ERASES NOTHING ELSE: the group and the name stay.
        c.post("/forum/profil", json={"group_number": 4,
                                      "leaderboard_opt_in": False},
               headers=auth("alice"))
        assert fake.profils["sub-alice"]["group_number"] == 4
        assert c.get("/leaderboard", headers=auth("alice")
                     ).json()["participating"] is False


def test_a_locked_frame_is_refused():
    """The frame is decorative, but "which ones do I have" is still a fact.

    The list comes from the server, computed on the level actually reached:
    the browser never gets to assert it.
    """
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
    """A grey card says under what condition it drops. Nothing is drawn.

    That is the difference between a collection and a loot box, and it reads
    in the payload: every card carries its condition, held or not.
    """
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/collection", headers=auth("alice"))
        assert r.status_code == 200, r.text
        cards = r.json()["cards"]
        assert len(cards) == len(politique.POLICY["cards"])
        assert all(not card["held"] for card in cards)
        assert all(card["condition"] for card in cards), cards
        # Under the minimum cohort, no rarity is announced.
        assert all(card["rarity"] is None for card in cards)


def test_a_mute_database_answers_503_on_the_new_screens():
    """No invented number during an outage, on either new screen.

    "0 XP", "nobody on the leaderboard", "no card": all three tell someone
    their work is gone, and all three would be false.
    """
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
    """`_message_id()` is the common gate for five routes; out of form,
    all of them respond 400 before touching the database.
    """
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
    """DELETE /forum was never tested anywhere: neither success nor refusal."""
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "mine"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        # A well-formed id that does not exist: the same 404 as someone
        # else's message, so nothing more is revealed.
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 404, r.text
        r = c.delete("/forum?id=" + mid, headers=auth("bob"))
        assert r.status_code == 404, (r.status_code, r.text)
        assert fake.messages, "bob's message should not have disappeared"
        r = c.delete("/forum?id=" + mid, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert not fake.messages

    base = BaseSimulee()
    base.forum_supprimer = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_report_a_message_or_a_name():
    """POST /forum/signalement had no test at all: neither the message nor the name."""
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
        # `kind` absent: the schema's default is a message report.
        r = c.post("/forum/signalement", json={"id": mid}, headers=auth("bob"))
        assert r.status_code == 200, r.text

    base = BaseSimulee()
    base.forum_signaler = lambda *a: None
    base.forum_nom_signaler = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for body in ({"id": "0" * 32, "kind": "message"},
                     {"id": "0" * 32, "kind": "name"}):
            r = c.post("/forum/signalement", json=body, headers=auth("alice"))
            assert r.status_code == 503, (body, r.text)


def test_moderation_clears_a_reported_name_without_touching_the_rest_of_the_profile():
    """`clear-name` was never tested anywhere -- neither the success nor its
    three failure modes.
    """
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
        # The rest of the profile survives the write: ONLY the name leaves.
        assert profile["group_number"] == 4 and profile["group_number_public"] is True

        # A well-formed id whose message has no retrievable author.
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = BaseSimulee()
    base.forum_profil = lambda user: None
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
    base2.forum_profil_ecrire = lambda *a, **k: False
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
    base.forum_mark_helpful = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/helpful", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_moderer_hide_restore_retain_report_an_outage_and_an_unknown_id():
    """`hide`/`restore`/`retain`/`unretain` share the same 503 and 404 as
    `clear-name`, but through a different code path (`state.forum_moderer`).
    """
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
    base.forum_moderer = lambda *a: None
    with contexte(jetons=tokens, base=base, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_forum_reports_a_database_outage_on_each_read_route():
    """GET /forum, /forum/moderation and /forum/help: each its own outage."""
    base = BaseSimulee()
    base.forum_fil = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_signalements = lambda *a: None
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
    """POST /forum: the exercise, the text, the step, the block, the
    visibility -- each refusal must arrive BEFORE freiner_forum, and a write
    that fails must respond 503, never 200.
    """
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

        # A "group" visibility refused outright: it is never a choice at
        # publish time, only `open_to_group` performs that transition.
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "visibility": "group"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = BaseSimulee()
    base.forum_publier = lambda *a: False
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
    base.forum_profil = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/profil", headers=auth("alice"))
        assert r.status_code == 503, r.text
        r = c.post("/forum/profil", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_profil_ecrire = lambda *a, **k: False
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
    """"Nothing more to offer": the sign-in block stays inert."""
    assert client.get("/oidc.json").json() == {}


def test_sub_responds_503_outside_oidc_configuration():
    """503, not 401: "there are no accounts here" is not "sign in again"."""
    r = client.get("/etats", headers=auth("alice"))
    assert r.status_code == 503 and "persistance" in r.json()["error"], r.text


def test_freiner_forum_blocks_a_burst_of_messages():
    # `contexte()` restores `deps.forum_quota` on exit -- no need to do it here.
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
    base.forum_profil = lambda user: None
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
    base.forum_profil_ecrire = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.profils["sub-alice"] = dict(BaseSimulee.EMPTY_PROFILE, alias="Faucon-12")
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_redraw_alias_exhausts_the_vocabulary():
    """The closed vocabulary is finite: no more pseudonym -> 503, never a
    server-invented name as a stopgap.
    """
    import policy
    every_alias = set(policy.possible_aliases())
    base = BaseSimulee()
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        # The whole vocabulary is already taken by OTHER accounts: none is
        # left to draw for alice, whatever her own alias is.
        for i, alias in enumerate(every_alias):
            fake.profils["sub-%d" % i] = dict(BaseSimulee.EMPTY_PROFILE, alias=alias)
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503 and "pseudonyme" in r.json()["error"], r.text


def test_avertir_reports_each_incomplete_configuration_independently():
    """`_avertir()` never blocks startup: three silent warnings, each
    independent of the other two (see the docstring of app/main.py::_avertir).
    """
    guard = (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
             security.oidc_enabled)
    try:
        # 1. An issuer configured but OIDC not really active (e.g. no
        # database): only the sign-in warning.
        config.OIDC_ISSUER = "https://auth.exemple"
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = False
        security.oidc_enabled = lambda: False
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "connexion desactivee" in out
        assert "discussions desactivees" not in out
        assert "CTESTER_DOCS" not in out

        # 2. OIDC really active but no moderator: the forum, silent.
        security.oidc_enabled = lambda: True
        config.FORUM_MODERATORS = frozenset()
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "connexion desactivee" not in out
        assert "discussions desactivees" in out

        # 3. Public documentation depends on nothing else.
        config.OIDC_ISSUER = ""
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "CTESTER_DOCS=1" in out
        assert "connexion desactivee" not in out
        assert "discussions desactivees" not in out

        # 4. Everything is in order: complete silence.
        config.OIDC_ISSUER = "https://auth.exemple"
        config.DOCS = False
        security.oidc_enabled = lambda: True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        assert buffer.getvalue() == ""
    finally:
        (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
         security.oidc_enabled) = guard


def test_http_exception_handler_only_rewrites_the_generic_404():
    """`_http()` only replaces "Not Found" on Starlette's generic 404
    (unknown route): a future application-level 404, with its own message,
    must stay readable and not be overwritten.
    """
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
    """A non-negotiable invariant (see app/main.py's docstring): a second
    worker would silently double quotas, presence and the OIDC token cache,
    all in process memory. A source check rather than an execution one --
    launching a real server is not the point here, and the whole point is
    that nobody copies this line with `--workers 4`.
    """
    source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    block = source.split("uvicorn.run(", 1)[1].split(")", 1)[0]
    assert re.search(r"workers\s*=\s*1\b", block), block
    assert not re.search(r"workers\s*=\s*(?!1\b)\d", block), block


# ---------------------------------------------------------------------------
# Le devoir d'équipe : la frontière HTTP, et surtout la frontière entre DEUX
# ÉQUIPES.
#
# CE QUI EST ÉPROUVÉ ICI, ET NULLE PART AILLEURS : qu'aucune route n'accepte
# une équipe dans son corps ni dans son URL. Toutes les fonctions pures sont
# éprouvées par appel direct dans `test_ctester.py` ; ce qui ne peut se voir
# que depuis un client HTTP, c'est qu'un compte inscrit dans l'équipe 2 ne
# peut atteindre AUCUN octet de l'équipe 1, quoi qu'il écrive.

JETONS_EQUIPE = {"t-alice": "sub-alice", "t-bob": "sub-bob",
                 "t-cleo": "sub-cleo", "t-prof": "sub-prof"}


def _entetes(jeton):
    return {"Authorization": "Bearer " + jeton}


@contextlib.contextmanager
def deploiement_devoir(*, deadline=None, team=True, moderateurs=("sub-prof",)):
    """Un déploiement avec un devoir publié et DEUX équipes inscrites.

    Deux équipes, toujours : un contrôle d'isolement avec une seule équipe ne
    prouve rien -- il n'y a personne à ne pas atteindre.
    """
    base = BaseSimulee()
    with contexte(jetons=JETONS_EQUIPE, moderateurs=moderateurs, base=base,
                  exercices=DEVOIR,
                  devoir=_devoir_json(deadline=deadline, team=team)) as (c, faux, tmp):
        faux.inscrire("devoir", "e1", ["sub-alice", "sub-cleo"], group_number=4,
                      label="Équipe 1")
        faux.inscrire("devoir", "e2", ["sub-bob"], group_number=6,
                      label="Équipe 2")
        yield c, faux, tmp


# --------------------------------------------------------------------------
# La Console
# --------------------------------------------------------------------------
# CE QUI EST ÉPROUVÉ ICI : l'ordre des refus et LES BORNES DES DEUX CÔTÉS -- la
# valeur qui passe et la première qui ne passe plus. Un contrôle qui ne vérifie
# qu'un refus laisse passer une borne posée un cran trop serré, et c'est
# l'étudiant qui la découvre à 23 h.


def _console_hello(socket, jeton="t-alice", code="int main(void){return 0;}"):
    socket.send_json({"t": "hello", "token": jeton, "code": code})


def _exige_flock():
    """Les contrôles qui ouvrent une VRAIE session ont besoin de `flock`.

    Hors POSIX il n'y en a pas, et l'erreur remonterait déguisée : le routeur
    avale toute exception de l'endpoint et ferme la socket, donc le harnais ne
    verrait qu'un `WebSocketDisconnect` -- indistinguable d'un refus légitime,
    c'est-à-dire le pire des contrôles : celui qui rassure. On la lève ici, à
    découvert, et la boucle de fin de fichier la reconnaît et le DIT.

    Les contrôles qui s'arrêtent AVANT la session -- ordre des refus, origine,
    bornes du `hello` -- ne l'appellent pas : ce sont eux qui gardent la
    frontière, et ils tournent partout.
    """
    from services import scratch as _scratch
    if _scratch.fcntl is None:
        raise RuntimeError("flock indisponible : la Console demande POSIX")


def test_la_console_dit_qu_elle_n_est_pas_offerte_avant_de_refuser_le_jeton():
    """L'ORDRE, et c'est la règle du forum : « pas offerte ici » AVANT « jeton
    refusé ». Un étudiant sur un déploiement sans Console ne doit pas croire
    que sa session a expiré et se déconnecter pour rien."""
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE, console=False) as (client, _, _):
        try:
            with client.websocket_connect("/scratch/live") as socket:
                # Un jeton VOLONTAIREMENT invalide : c'est 4503 qu'on doit lire,
                # pas 4401.
                _console_hello(socket, jeton="t-inconnu")
                socket.receive_json()
            raise AssertionError("la Console éteinte a accepté une session")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_UNAVAILABLE, exc.code

    # Et allumée, c'est bien le jeton qui décide.
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
    """`MAX_CODE` pile passe, `MAX_CODE + 1` ne passe plus."""
    _exige_flock()
    from starlette.websockets import WebSocketDisconnect

    with contexte(jetons=JETONS_EQUIPE) as (client, _, _):
        # Pile à la borne : accepté (la session s'ouvre, le worker n'existe
        # pas, donc elle finit en file -- ce qui prouve qu'elle a été acceptée).
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket, code="/*" + "x" * (config.MAX_CODE - 4) + "*/")
            trame = socket.receive_json()
            assert trame["t"] == "queued", trame
        # Un octet de plus : refusé.
        try:
            with client.websocket_connect("/scratch/live") as socket:
                _console_hello(socket, code="x" * (config.MAX_CODE + 1))
                socket.receive_json()
            raise AssertionError("un code hors bornes est passé")
        except WebSocketDisconnect as exc:
            assert exc.code == deps.CLOSE_BAD, exc.code


def test_la_console_borne_ce_qu_on_tape_des_deux_cotes():
    """La trame d'entrée à `SCRATCH_FRAME` pile, puis un octet de plus.

    UNE TRAME WEBSOCKET NE PASSE PAR AUCUN MIDDLEWARE, donc par aucune borne de
    corps : celle-ci est reposée à la main dans le routeur, ou la Console
    serait la seule porte non bornée de l'application.
    """
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
        # Celle qui passe est écrite, celle qui dépasse est IGNORÉE -- pas
        # tronquée : une entrée coupée en silence serait pire, le programme
        # lirait autre chose que ce que l'étudiant a tapé.
        assert b"a" * config.SCRATCH_FRAME in entree
        assert b"b" not in entree, entree[:200]
        assert entree.endswith(b"FIN\n")


def test_la_console_n_ecrit_ni_owner_ni_exercice_dans_le_spool():
    """Aucune identité ne franchit la frontière du worker.

    C'est ce qui rend `_enregistrer()` inatteignable : il exige un `owner` ET
    un `exercise_id`, et le job de console n'a ni l'un ni l'autre. Un sondage
    de `/r/<id>` sur ce job ne doit donc écrire aucune tentative de pratique.
    """
    _exige_flock()
    base = BaseSimulee()
    with contexte(jetons=JETONS_EQUIPE, base=base) as (client, faux, _):
        with client.websocket_connect("/scratch/live") as socket:
            _console_hello(socket)
            assert socket.receive_json()["t"] == "queued"
            chemin = _le_job_de_console()
            job = json.loads(_lire_octets(os.path.join(chemin, "job.json")))
            assert job == {"kind": "console"}, job
            # Le sondage ordinaire ne doit rien enregistrer non plus.
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
        # Un AUTRE compte n'est pas gêné : le plafond est par compte.
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
        # Absent n'est pas une panne : "" et 200.
        r = client.get("/scratch/draft", headers=_entetes("t-alice"))
        assert r.status_code == 200 and r.json() == {"code": ""}, r.text
        assert client.get("/scratch/draft").status_code == 401
        # Pile à la borne, puis un octet de plus.
        assert client.put("/scratch/draft", json={"code": "x" * config.MAX_CODE},
                          headers=_entetes("t-alice")).status_code == 200
        trop = client.put("/scratch/draft",
                          json={"code": "x" * (config.MAX_CODE + 1)},
                          headers=_entetes("t-alice"))
        assert trop.status_code == 413, trop.status_code
        # Et il est bien à l'étudiant qui l'a écrit.
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
    """Le répertoire de spool que la session vient d'écrire."""
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
    """Ce que le bandeau lit, et ce qu'il n'a pas le droit de recevoir."""
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
        # LE GROUPE DE L'EQUIPE VIENT DU LISTAGE, pas du profil : cleo n'a
        # jamais rempli "Mon identité", et l'équipe a quand même un groupe.
        assert not faux.profils


def test_aucune_route_d_equipe_n_ouvre_sans_appartenance_prouvee():
    """Trois refus, trois phrases : le devoir, le mode, l'inscription."""
    with deploiement_devoir() as (client, faux, _):
        # Un compte sans équipe pour ce devoir.
        faux.equipes.pop(("devoir", "sub-bob"))
        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/revisions?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            r = client.get(chemin, headers=_entetes("t-bob"))
            assert r.status_code == 403, (chemin, r.status_code)
            assert "équipe" in r.json()["error"]
        # Un devoir qui n'existe pas -- ou qui n'est pas ouvert.
        r = client.get("/team/context?assignment=inconnu",
                       headers=_entetes("t-alice"))
        assert r.status_code == 404
        # Et sans jeton du tout : 401, comme toute route de compte.
        assert client.get("/team/context?assignment=devoir").status_code == 401


def test_un_devoir_sans_bloc_team_repond_que_ce_n_est_pas_du_travail_d_equipe():
    with deploiement_devoir(team=False) as (client, _, _):
        r = client.get("/team/context?assignment=devoir",
                       headers=_entetes("t-alice"))
        assert r.status_code == 400
        assert "travail d'équipe" in r.json()["error"]


def test_le_document_est_partage_par_l_equipe_et_par_elle_seule():
    """LE CŒUR DE LA FONCTIONNALITÉ, et le cœur de sa sécurité.

    Alice écrit, Cleo (même équipe) lit la même chose, Bob (autre équipe) ne
    lit rien -- et il n'a AUCUN moyen de demander autre chose : il n'y a pas
    d'équipe dans l'URL ni dans le corps, alors il n'y a rien à modifier.
    """
    with deploiement_devoir() as (client, faux, _):
        ecrire = client.put("/team/document", headers=_entetes("t-alice"),
                            json={"assignment_id": "devoir",
                                  "exercise_id": "dev-a",
                                  "files": {"main.c": "int main(void){}\n"}})
        assert ecrire.status_code == 200, ecrire.text
        pour_cleo = client.get("/team/document?assignment=devoir&ex=dev-a",
                               headers=_entetes("t-cleo")).json()
        assert pour_cleo["sources"] == {"main.c": "int main(void){}\n"}
        # BOB EST DANS UNE AUTRE EQUIPE : il obtient SON document, qui est
        # vide -- jamais celui d'alice, et jamais un 403 qui confirmerait au
        # passage que l'autre équipe a écrit quelque chose.
        pour_bob = client.get("/team/document?assignment=devoir&ex=dev-a",
                              headers=_entetes("t-bob")).json()
        assert pour_bob["sources"] == {}
        # ET IL NE PEUT PAS ECRIRE CHEZ ELLE : un corps qui nommerait une
        # équipe n'est pas lu (`extra="ignore"`), l'écriture va dans la sienne.
        client.put("/team/document", headers=_entetes("t-bob"),
                   json={"assignment_id": "devoir", "exercise_id": "dev-a",
                         "team_id": "e1", "team": "e1",
                         "files": {"main.c": "/* bob */\n"}})
        assert faux.documents[("e1", "dev-a")] == {"main.c": "int main(void){}\n"}
        assert faux.documents[("e2", "dev-a")] == {"main.c": "/* bob */\n"}


def test_un_exercice_hors_du_devoir_ne_resout_pas_meme_pour_un_membre():
    """La SECONDE moitié de la porte. Prouver l'équipe ne prouve pas l'exercice.

    Sans ce contrôle, un membre pourrait atteindre un document clé sur SON
    équipe et n'importe quel identifiant d'exercice -- y compris ceux d'un
    autre devoir où il n'a rien à faire.
    """
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
    """LES DEUX CHEMINS COEXISTENT, et c'est la non-régression de la refonte.

    Le brouillon individuel reste clé sur (compte, exercice) ; le document
    d'équipe sur (équipe, exercice). Écrire l'un ne doit rien faire à l'autre,
    dans les deux sens.
    """
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
        # ET LE BROUILLON INDIVIDUEL D'UN EXERCICE DE DEVOIR RESTE POSSIBLE :
        # un étudiant sans équipe doit pouvoir travailler l'exercice seul.
        r = client.put("/brouillon", headers=_entetes("t-bob"),
                       json={"exercise_id": "dev-a",
                             "files": {"main.c": "seul\n"}})
        assert r.status_code == 200
        assert faux.brouillons[("sub-bob", "dev-a")] == {"main.c": "seul\n"}


def test_le_document_passe_par_la_meme_liste_blanche_que_tout_le_reste():
    with deploiement_devoir() as (client, _, _):
        r = client.put("/team/document", headers=_entetes("t-alice"),
                       json={"assignment_id": "devoir", "exercise_id": "dev-a",
                             "files": {"secret.c": "x"}})
        assert r.status_code == 400 and "inattendu" in r.json()["error"]
        # LA BORNE DES DEUX COTES, comme partout : ce qui passe, et le premier
        # octet qui ne passe plus.
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
    """PAS UNE LIGNE POSTGRES PAR FRAPPE, et une histoire quand même lisible.

    Une révision par auteur et par fenêtre : quatre personnes qui tapent en
    même temps laissent quatre traces -- ce qu'il faut pour dire qui a fait
    quoi -- et une personne qui tape pendant dix minutes en laisse cinq, pas
    six mille.
    """
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
        # UN AUTRE AUTEUR EN OUVRE UNE TOUT DE SUITE : sans ça, la trace du
        # coéquipier qui a tapé dans la fenêtre de quelqu'un d'autre
        # n'existerait pas.
        ecrire("t-cleo", "quatre\n")
        assert len(faux.revisions) == 2
        # LA FENETRE PASSE : alice réécrit et laisse une trace de plus.
        faux.horloge += config.TEAM_REVISION_WINDOW + 1
        ecrire("t-alice", "cinq\n")
        assert len(faux.revisions) == 3
        # DEUX ECRITURES IDENTIQUES N'EN FONT PAS DEUX : une sauvegarde
        # déclenchée par un collage annulé n'ajoute rien.
        faux.horloge += config.TEAM_REVISION_WINDOW + 1
        ecrire("t-alice", "cinq\n")
        assert len(faux.revisions) == 3

        liste = client.get("/team/revisions?assignment=devoir&ex=dev-a",
                           headers=_entetes("t-alice")).json()["revisions"]
        assert len(liste) == 3
        assert "sub-" not in json.dumps(liste)
        assert {r["author"] for r in liste} == {"m1", "m2"}
        # ET IL N'Y A AUCUN POURCENTAGE : l'historique sert à récupérer et à
        # comprendre, jamais à noter.
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
        # RESTAURER AVANCE, ça ne rembobine pas : l'histoire garde tout.
        assert len(faux.revisions) == 4


def test_une_revision_d_une_autre_equipe_ne_resout_pas():
    """L'équipe est dans la condition, pas dans un `if` posé après coup."""
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
    """CE QUI PART EST CE QUE L'EQUIPE A ECRIT, lu côté serveur.

    Le navigateur n'envoie que l'identifiant du devoir : une archive
    assemblée depuis l'éditeur serait l'archive d'un onglet, et l'équipe
    l'apprendrait à la correction.
    """
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
        # UNE ARCHIVE EST UNE DONNEE DE COMPTE : jamais mise en cache.
        assert r.headers["cache-control"] == "no-store"
        with _zipfile.ZipFile(_io.BytesIO(r.content)) as archive:
            assert archive.namelist() == ["Devoir/main.c", "Devoir/matrac_lib.c"]
            assert archive.read("Devoir/matrac_lib.c").decode() \
                == "double f(void){return 1;}\n"
        # DETERMINISTE : même contenu, mêmes octets.
        encore = client.get("/team/handin.zip?assignment=devoir",
                            headers=_entetes("t-cleo"))
        assert encore.content == r.content
        # ET L'AUTRE EQUIPE N'OBTIENT PAS CELLE-LA.
        autre = client.get("/team/handin.zip?assignment=devoir",
                           headers=_entetes("t-bob"))
        assert autre.status_code == 400, autre.text


def test_la_remise_est_une_seule_par_equipe_et_refuse_un_trou():
    with deploiement_devoir() as (client, faux, _):
        faux.documents[("e1", "dev-a")] = {"main.c": "int main(void){}\n"}
        incomplet = client.post("/team/handin", headers=_entetes("t-alice"),
                                json={"assignment_id": "devoir"})
        assert incomplet.status_code == 400
        # ELLE DIT CE QUI MANQUE : "remise incomplète" tout court enverrait
        # l'équipe chercher dans six exercices.
        assert "matrac_lib.c" in incomplet.json()["error"]
        assert faux.remises == {}

        faux.documents[("e1", "dev-b")] = {"lib.c": "double f(void){return 1;}\n"}
        remise = client.post("/team/handin", headers=_entetes("t-alice"),
                             json={"assignment_id": "devoir"})
        assert remise.status_code == 200, remise.text
        assert sorted(remise.json()["files"]) == ["Devoir/main.c",
                                                   "Devoir/matrac_lib.c"]
        # UNE SEULE LIGNE, ET REMETTRE A NOUVEAU LA REMPLACE : une équipe qui
        # trouve un bogue à 22 h doit pouvoir corriger.
        encore = client.post("/team/handin", headers=_entetes("t-cleo"),
                             json={"assignment_id": "devoir"})
        assert encore.status_code == 200
        assert list(faux.remises) == [("devoir", "e1")]
        assert faux.remises[("devoir", "e1")]["submitted_by"] == "sub-cleo"
        # LA REMISE EST CELLE DE L'EQUIPE : cleo la voit dans son contexte.
        contexte_cleo = client.get("/team/context?assignment=devoir",
                                   headers=_entetes("t-cleo")).json()
        assert contexte_cleo["submission"]["submitted_at"]
        # ET L'AUTRE EQUIPE N'EN A PAS.
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
        # LE ZIP RESTE TELECHARGEABLE APRES LA DATE : relire son propre travail
        # n'est pas une remise, et le refuser ne protégerait rien.
        assert client.get("/team/handin.zip?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 200
        # ET LE BANDEAU LE SAIT AVANT DE CLIQUER.
        vue = client.get("/team/context?assignment=devoir",
                         headers=_entetes("t-alice")).json()
        assert vue["assignment"]["deadline_passed"] is True


def test_un_exercice_de_devoir_n_accorde_aucun_xp_mais_garde_l_etat():
    """QUATRE PERSONNES, UN SEUL DOCUMENT : une première réussite chacune pour
    le même code serait quatre récompenses pour un seul travail.

    Ce qui reste écrit, c'est l'état et la tentative : chaque membre doit voir
    que l'exercice passe, et garder son brouillon.
    """
    with deploiement_devoir() as (client, faux, tmp):
        _verdict("dev-a", "d" * 32, {"status": "ok", "total": 2, "passed": 2})
        assert client.get("/r/" + "d" * 32).status_code == 200
        assert faux.etats[("sub-alice", "dev-a")] == "solved"
        assert faux.pratique[("sub-alice", "dev-a")][0] == 1
        assert faux.xp == {} and faux.succes == {}
        # ET UN EXERCICE ORDINAIRE CONTINUE D'EN ACCORDER : la non-régression
        # de la même branche.
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
    """Comme partout : « la base n'a pas répondu » n'est pas « il n'y a rien »."""
    with deploiement_devoir() as (client, faux, _):
        faux.read_team_document = lambda *_: None
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_entetes("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}
        faux.team_roster = lambda *_: None
        assert client.get("/team/context?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 503


# --- La socket de collaboration -------------------------------------------------
# CE QU'ELLE DOIT REFUSER AVANT DE RELAYER QUOI QUE CE SOIT, et le fait que
# l'émetteur d'une trame est décidé par le serveur. Une trame relayée telle
# quelle laisserait un membre signer le curseur de quelqu'un d'autre.


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
        # Une première trame qui n'est pas un `hello`.
        assert _code_de_fermeture(
            client, lambda s: s.send_json({"t": "update", "d": "x"})) == 4400
        assert _code_de_fermeture(client, lambda s: s.send_text("pas du json")) == 4400
        # Un jeton qui ne vaut rien.
        assert _code_de_fermeture(client, lambda s: _hello(s, "t-inconnu")) == 4401
        # Un compte réel, mais sans équipe pour ce devoir.
        faux.equipes.pop(("devoir", "sub-bob"))
        assert _code_de_fermeture(client, lambda s: _hello(s, "t-bob")) == 4403
        # Un exercice qui n'est pas dans ce devoir.
        assert _code_de_fermeture(
            client, lambda s: _hello(s, "t-alice", exercice="tp2-ex3")) == 4403
        collab.reset()


def test_deux_coequipiers_se_voient_et_l_autre_equipe_ne_voit_rien():
    """L'ISOLEMENT DE LA SALLE, ET LE TAMPON DU SERVEUR SUR CHAQUE TRAME.

    Bob est dans une autre équipe, sur le MÊME exercice : sa socket est
    acceptée -- il a le droit d'y travailler -- et il ne reçoit rien de
    l'équipe 1. Et le `from` qu'alice écrit elle-même est écrasé : un membre
    ne peut pas signer le curseur d'un autre.
    """
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
                # LA SECONDE ARRIVEE NE SEME PAS LE DOCUMENT : c'est ce
                # `peers` qui l'en empêche, et l'ordre est décidé ici.
                assert pret_cleo["peers"] == 1 and pret_cleo["me"] == "m2"
                assert pret_cleo["epoch"] == pret_alice["epoch"]
                assert cleo.receive_json()["t"] == "presence"
                assert alice.receive_json() == {"t": "presence",
                                                "online": ["m1", "m2"]}
                with client.websocket_connect("/team/live") as bob:
                    _hello(bob, "t-bob")
                    pret_bob = bob.receive_json()
                    # UNE AUTRE EQUIPE, UNE AUTRE SALLE : époque différente,
                    # et il y est seul.
                    assert pret_bob["peers"] == 0
                    assert pret_bob["epoch"] != pret_alice["epoch"]
                    assert bob.receive_json()["t"] == "presence"

                    alice.send_json({"t": "update", "d": "AAEC",
                                     "from": "m2", "token": "t-alice"})
                    recue = cleo.receive_json()
                    assert recue["d"] == "AAEC"
                    # LE SERVEUR TAMPONNE L'EMETTEUR : alice a écrit "m2",
                    # elle ressort en "m1". Et le jeton ne repart pas.
                    assert recue["from"] == "m1"
                    assert "token" not in recue

                    alice.send_json({"t": "cursor", "file": "main.c",
                                     "a": "AA", "h": "AQ"})
                    curseur = cleo.receive_json()
                    assert curseur["t"] == "cursor" and curseur["from"] == "m1"

                    # BOB N'A RIEN RECU. On le prouve en lui envoyant quelque
                    # chose depuis SA salle : la trame suivante qu'il lit est
                    # la sienne, pas celle d'alice.
                    bob.send_json({"t": "update", "d": "ZZZ"})
                    with client.websocket_connect("/team/live") as bob2:
                        _hello(bob2, "t-bob")
                        bob2.receive_json()          # ready
                        bob2.receive_json()          # presence
                        assert bob.receive_json()["t"] == "presence"
                        bob.send_json({"t": "update", "d": "BBBB"})
                        suite = bob2.receive_json()
                        assert suite == {"t": "update", "d": "BBBB", "from": "m1"}
        collab.reset()


def test_une_trame_inconnue_ou_trop_grosse_ne_traverse_pas():
    """Le relais ne LIT pas la charge, mais il la BORNE -- une trame de
    WebSocket ne passe par aucun middleware, donc par aucune borne de corps."""
    from starlette.websockets import WebSocketDisconnect

    with deploiement_devoir() as (client, _, _):
        collab.reset()
        with client.websocket_connect("/team/live") as alice:
            _hello(alice, "t-alice")
            alice.receive_json(); alice.receive_json()
            with client.websocket_connect("/team/live") as cleo:
                _hello(cleo, "t-cleo")
                cleo.receive_json(); cleo.receive_json()
                alice.receive_json()                     # presence
                # Un type que le relais ne connaît pas est ignoré, pas relayé.
                alice.send_json({"t": "evil", "d": "x"})
                alice.send_json({"t": "update", "d": "ok"})
                assert cleo.receive_json()["d"] == "ok"
            try:
                alice.receive_json()                     # presence (cleo part)
                alice.send_text("x" * (config.TEAM_LIVE_MAX_FRAME + 1))
                alice.receive_json()
                raise AssertionError("une trame hors bornes a été acceptée")
            except WebSocketDisconnect as exc:
                assert exc.code == 4400
        collab.reset()


def test_la_socket_refuse_une_origine_inconnue():
    """Une WebSocket n'est pas soumise à CORS : le navigateur l'ouvre vers
    n'importe quel hôte et n'envoie qu'`Origin`. Le jeton reste la vraie
    barrière -- une page hostile ne lit pas le `sessionStorage` d'une autre
    origine -- mais refuser ici ferme la porte plus tôt."""
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
        # L'origine connue passe, et l'absence d'origine aussi (un client qui
        # n'est pas un navigateur doit de toute façon connaître un jeton).
        with client.websocket_connect("/team/live",
                                      headers={"Origin": CONNUE}) as socket:
            _hello(socket, "t-alice")
            assert socket.receive_json()["t"] == "ready"
        collab.reset()


def test_mon_equipe_se_lit_avant_que_le_devoir_n_ouvre():
    """LA SEULE ROUTE QUI RÉPOND AVANT LE DEVOIR, et c'est délibéré.

    Le listage est chargé AVANT le premier cours ; « suis-je dans la bonne
    équipe, avec les bonnes personnes ? » est exactement la question qu'un
    étudiant doit pouvoir poser à ce moment-là. Toutes les autres routes
    passent par `workspace()`, qui refuse un devoir pas encore ouvert — et
    elles ont raison, il n'y a rien à travailler. Celle-ci montre sans donner,
    comme le catalogue montre un exercice verrouillé avec sa date.
    """
    with deploiement_devoir() as (client, faux, tmp):
        # Le devoir de ce déploiement est OUVERT ; on le referme pour éprouver
        # précisément le cas qui compte : le listage existe, le devoir non.
        publie = _publier(tmp, DEVOIR, _devoir_json())
        racine = os.path.join(tmp, "content")
        _ecrire_contenu(racine, DEVOIR, devoir=dict(
            _devoir_json(), release={"state": "scheduled",
                                     "available_from": "2099-10-16T00:00:00-04:00"}))
        import content_catalog as content_catalogue
        import publish_content
        publish_content.publish(content_catalogue.discover(racine), publie)

        # Le devoir ne résout plus : rien de ce qui touche au travail n'ouvre.
        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            assert client.get(chemin, headers=_entetes("t-alice")).status_code == 404, chemin

        # Mais l'équipe, elle, se lit -- avec la date à laquelle ça ouvrira.
        r = client.get("/team/mine", headers=_entetes("t-alice"))
        assert r.status_code == 200, r.text
        [equipe] = r.json()["teams"]
        assert equipe["label"] == "Équipe 1" and equipe["group_number"] == 4
        assert equipe["number"] == 1
        assert equipe["access"] == "scheduled"
        assert equipe["available_from"].startswith("2099-10-16")
        # LES COÉQUIPIERS SONT DES POSITIONS, et aucun `sub` ne sort -- même
        # règle et même contrôle que partout ailleurs.
        assert [m["id"] for m in equipe["members"]] == ["m1", "m2"]
        assert [m["you"] for m in equipe["members"]] == [True, False]
        assert "sub-" not in r.text, r.text
        # ET ELLE N'OUVRE RIEN : ni document, ni révision, ni salle.
        assert "sources" not in r.text and "revision" not in r.text

        # UN COMPTE SANS ÉQUIPE OBTIENT UNE LISTE VIDE, PAS UN 403 : « je n'ai
        # pas d'équipe » est une réponse, et c'est celle qui envoie l'étudiant
        # voir son enseignant pendant qu'il est encore temps.
        faux.equipes.pop(("devoir", "sub-bob"))
        vide = client.get("/team/mine", headers=_entetes("t-bob"))
        assert vide.status_code == 200 and vide.json() == {"teams": []}
        # Sans jeton, 401, comme toute route de compte.
        assert client.get("/team/mine").status_code == 401


def test_mon_equipe_dit_une_panne_au_lieu_d_inventer_une_absence():
    """« La base n'a pas répondu » n'est pas « tu n'as pas d'équipe ».

    Les confondre annoncerait à quelqu'un qu'il n'est inscrit nulle part, un
    matin de panne Postgres, la veille d'une remise.
    """
    with deploiement_devoir() as (client, faux, _):
        faux.team_memberships = lambda *_: None
        r = client.get("/team/mine", headers=_entetes("t-alice"))
        assert r.status_code == 503 and r.json() == {"error": "la base ne répond pas"}


# --- Choisir son équipe ---------------------------------------------------------
# LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE, et un étudiant prend une
# place libre -- le geste qu'il fait déjà sur Moodle, avec les MÊMES numéros.
#
# CE QUI LES FERME EST UNE DATE QUE LE CONTENU PORTE DÉJÀ : on choisit tant que
# le devoir est fermé. Les deux conditions lisent la même valeur, donc elles
# sont mutuellement exclusives PAR CONSTRUCTION -- c'est la propriété que ces
# contrôles éprouvent, et elle remplace tout un protocole de confirmation.


@contextlib.contextmanager
def deploiement_choix(ouvert=False):
    """Un déploiement où les équipes se choisissent (devoir encore FERMÉ)."""
    base = BaseSimulee()
    devoir = _devoir_json()
    if not ouvert:
        devoir = dict(devoir, release={
            "state": "scheduled",
            "available_from": "2099-10-16T00:00:00-04:00"})
    with contexte(jetons=JETONS_EQUIPE, moderateurs=("sub-prof",), base=base,
                  exercices=DEVOIR, devoir=devoir) as (c, faux, tmp):
        # LE GROUPE VIENT DU PROFIL, et c'est le SEUL endroit où ce numéro
        # auto-déclaré décide de quelque chose : quelle liste on voit.
        for compte in ("sub-alice", "sub-bob", "sub-cleo"):
            faux.forum_profil_ecrire(compte + "-p", compte, None, 4,
                                     False, False)
        yield c, faux, tmp


def test_les_equipes_se_choisissent_dans_une_liste_numerotee():
    """LA MÊME LISTE QUE MOODLE, et les mêmes numéros : c'est tout l'intérêt."""
    with deploiement_choix() as (client, faux, _):
        vue = client.get("/team/available?assignment=devoir",
                         headers=_entetes("t-alice"))
        assert vue.status_code == 200, vue.text
        corps = vue.json()
        assert corps["group_number"] == 4 and corps["mine"] is None
        # LES `count` ÉQUIPES DU CONTENU, ni plus ni moins -- au-delà, elles
        # n'existent pas non plus dans Moodle.
        assert [e["number"] for e in corps["teams"]] == [1, 2, 3, 4, 5, 6]
        assert corps["teams"][0] == {"number": 1, "name": "Équipe 1",
                                     "members": 0, "max": 4, "full": False}
        # AUCUN `sub`, ET PAS MÊME UN NOM : une liste de choix n'a pas à dire
        # QUI est dans quelle équipe. « 3/4 » suffit à choisir, et publier les
        # compositions ferait de ce choix un tri social.
        assert "sub-" not in vue.text and "Coéquipier" not in vue.text

        pris = client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir", "number": 3})
        assert pris.status_code == 200, pris.text
        assert pris.json()["mine"] == 3
        assert pris.json()["teams"][2]["members"] == 1
        # LA POIGNÉE PORTE LE GROUPE ET LE NUMÉRO : `g04-e03`. Sans le groupe,
        # « Équipe 3 » du groupe 04 et du groupe 06 partageraient UN document.
        assert faux.equipes[("devoir", "sub-alice")] == "g04-e03"

        # DEUX FOIS, NON : on quitte d'abord. Le message le dit.
        encore = client.post("/team/join", headers=_entetes("t-alice"),
                             json={"assignment_id": "devoir", "number": 4})
        assert encore.status_code == 409 and "quitte-la" in encore.json()["error"]

        # UNE ÉQUIPE QUI N'EXISTE PAS : bornée par le CONTENU, pas par la
        # requête -- au-delà de `count`, il n'y a rien dans Moodle non plus.
        for numero in (0, 7, 999):
            r = client.post("/team/join", headers=_entetes("t-bob"),
                            json={"assignment_id": "devoir", "number": numero})
            assert r.status_code == 404, (numero, r.status_code)
            assert "il y en a 6" in r.json()["error"]


def test_une_equipe_complete_refuse_la_place_suivante():
    """LA PLACE EST COMPTÉE DANS LE `WHERE` DE L'INSERT, jamais relue avant.

    Deux étudiants qui cliquent sur la dernière place au même instant
    passeraient tous les deux un `if` posé côté routeur.
    """
    with deploiement_choix() as (client, faux, _):
        faux.inscrire("devoir", "g04-e02", ["a", "b", "c", "d"],
                      group_number=4, number=2)
        r = client.post("/team/join", headers=_entetes("t-alice"),
                        json={"assignment_id": "devoir", "number": 2})
        assert r.status_code == 409, r.text
        assert "complète (4 places)" in r.json()["error"]
        # Et la liste le disait AVANT le clic.
        vue = client.get("/team/available?assignment=devoir",
                         headers=_entetes("t-alice")).json()
        assert vue["teams"][1]["full"] is True


def test_on_change_d_equipe_tant_que_le_devoir_est_ferme():
    """Quitter et reprendre ailleurs : c'est ce que Moodle permet aussi."""
    with deploiement_choix() as (client, faux, _):
        client.post("/team/join", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        parti = client.post("/team/leave", headers=_entetes("t-alice"),
                            json={"assignment_id": "devoir"})
        assert parti.status_code == 200 and parti.json()["mine"] is None
        # L'ÉQUIPE VIDÉE RESTE : son numéro est celui de Moodle, et elle porte
        # peut-être déjà un document. La supprimer renumérioterait tout.
        assert ("g04-e01", "devoir") in faux.equipes_meta
        assert client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 5}).json()["mine"] == 5
        # Quitter sans équipe est un 404, pas un succès silencieux.
        client.post("/team/leave", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir"})
        assert client.post("/team/leave", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir"}).status_code == 404


def test_l_ouverture_du_devoir_fige_les_equipes():
    """LA PROPRIÉTÉ CENTRALE, et elle tient sans aucun état supplémentaire.

    `joinable()` demande que le devoir soit FERMÉ, `find_assignment()` qu'il
    soit OUVERT, et les deux lisent la MÊME valeur (`access`). Il n'existe donc
    aucun instant où l'on peut à la fois rejoindre une équipe et lire son
    document -- pas parce qu'on l'a vérifié quelque part, mais parce que c'est
    la même condition prise dans les deux sens.
    """
    with deploiement_choix(ouvert=True) as (client, faux, _):
        # DEVOIR OUVERT : plus personne ne choisit.
        for chemin, corps in (("/team/join", {"assignment_id": "devoir",
                                              "number": 1}),
                              ("/team/leave", {"assignment_id": "devoir"})):
            r = client.post(chemin, headers=_entetes("t-alice"), json=corps)
            assert r.status_code == 409, (chemin, r.text)
            assert "figées" in r.json()["error"]
        assert client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-alice")).status_code == 409
        # ET CELUI QUI N'A PAS D'ÉQUIPE EST RENVOYÉ VERS SON ENSEIGNANT, pas
        # vers une liste qui ne s'ouvrira plus.
        r = client.get("/team/document?assignment=devoir&ex=dev-a",
                       headers=_entetes("t-alice"))
        assert r.status_code == 403 and "enseignant" in r.json()["error"]

    with deploiement_choix() as (client, faux, _):
        # DEVOIR FERMÉ : on choisit, et le document reste inatteignable.
        assert client.post("/team/join", headers=_entetes("t-alice"),
                           json={"assignment_id": "devoir",
                                 "number": 1}).status_code == 200
        assert client.get("/team/document?assignment=devoir&ex=dev-a",
                          headers=_entetes("t-alice")).status_code == 404


def test_sans_groupe_au_profil_la_liste_dit_quoi_faire():
    """Le groupe auto-déclaré décide QUELLE LISTE on voit, et rien d'autre.

    Sans lui on ne sait pas quoi montrer -- et en montrer une au hasard
    mettrait quelqu'un dans les équipes d'une autre section. La réponse envoie
    donc au formulaire qui est juste en dessous, dans le même écran.
    """
    with deploiement_choix() as (client, faux, _):
        faux.profils.pop("sub-bob", None)
        r = client.get("/team/available?assignment=devoir",
                       headers=_entetes("t-bob"))
        assert r.status_code == 409, r.text
        assert "Mon identité" in r.json()["error"]


def test_deux_groupes_ont_chacun_leur_equipe_numero_1():
    """« Équipe 1 » du groupe 04 et du groupe 06 sont DEUX équipes.

    C'est ce que la poignée porte (`g04-e01` / `g06-e01`), et c'est ce qui les
    empêche de partager un document. Sans le groupe dans la poignée, les deux
    sections travailleraient dans le même fichier.
    """
    with deploiement_choix() as (client, faux, _):
        faux.forum_profil_ecrire("p6", "sub-bob", None, 6, False, False)
        client.post("/team/join", headers=_entetes("t-alice"),
                    json={"assignment_id": "devoir", "number": 1})
        client.post("/team/join", headers=_entetes("t-bob"),
                    json={"assignment_id": "devoir", "number": 1})
        assert faux.equipes[("devoir", "sub-alice")] == "g04-e01"
        assert faux.equipes[("devoir", "sub-bob")] == "g06-e01"
        # ET CHACUN NE VOIT QUE LES ÉQUIPES DE SON GROUPE.
        vue4 = client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-alice")).json()
        vue6 = client.get("/team/available?assignment=devoir",
                          headers=_entetes("t-bob")).json()
        assert vue4["group_number"] == 4 and vue6["group_number"] == 6
        assert vue4["teams"][0]["members"] == 1
        assert vue6["teams"][0]["members"] == 1, "les deux comptent 1, séparément"


def test_choisir_une_equipe_n_ouvre_aucun_document():
    """LES TROIS ROUTES DE CHOIX N'OUVRENT RIEN. `workspace()` reste la porte."""
    with deploiement_choix() as (client, faux, _):
        r = client.post("/team/join", headers=_entetes("t-alice"),
                        json={"assignment_id": "devoir", "number": 1})
        assert "sources" not in r.text and "revision" not in r.text
        for chemin in ("/team/context?assignment=devoir",
                       "/team/document?assignment=devoir&ex=dev-a",
                       "/team/handin.zip?assignment=devoir"):
            # 404 : le devoir n'est pas ouvert, donc il ne résout pas.
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
            # LE SEUL SAUT TOLÉRÉ, et il se nomme : la Console a besoin de
            # `flock`, qui n'existe pas hors POSIX. Sur le Dell -- le seul
            # endroit où elle tourne -- rien n'est sauté. Attraper le message
            # plutôt que de tenir une liste de noms de tests : une liste
            # rouillerait, et c'est celle-là qu'on oublierait de vider.
            if "flock indisponible" not in str(e):
                raise
            sautes += 1
            print("saute " + fn.__name__ + " (pas de flock hors POSIX)")
            continue
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées%s."
          % (len(tests) - sautes,
             ", %d sautées hors POSIX" % sautes if sautes else ""))
