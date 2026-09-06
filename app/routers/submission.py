"""Submit code, and read the verdict. The heart of ctester.

THESE TWO ROUTES ARE ANONYMOUS: a student pastes their code, picks their
exercise, and gets a verdict, with no account. The session key in the link is
the access control; an account, when there is one, only adds memory
(progression, drafts) on top.

NOTHING IS COMPILED OR EXECUTED HERE. `POST /submit` writes a directory into
the spool and returns an id; a worker on the host picks it up, compiles it
under gVisor in a disposable, network-less container, and drops `result.json`.
That separation is what allows this process to be exposed to the Internet.
"""

import hmac
import json
import os
import re
import time

import config
import deps
import state
import headers
import security
from fastapi import APIRouter, Request
from schemas import SoumissionIn
from services import progress as progression
from services import spool
from services.catalog import find_exercise, validate_files

JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["soumission"])


@router.post("/submit")
def submit(corps: SoumissionIn, request: Request):
    """Drop a submission into the queue.

    THE KEY FIRST, IN CONSTANT TIME, BEFORE ANY OTHER WORK: nothing must be
    measurable from the outside without it -- not whether an exercise exists,
    not the queue length, not how long a validation takes.
    """
    if not config.KEY or not hmac.compare_digest(corps.key, config.KEY):
        return headers.erreur(403, "clé de session invalide ou expirée")

    entree = find_exercise(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")

    # THE MODE COMES FROM THE CATALOG, not a field the client would have
    # chosen. It decides what is expected and the name of the file dropped
    # into the spool; the worker re-derives it from the test directory, and
    # both sides agree through the catalog.
    if entree.get("mode") == "quiz":
        if not isinstance(corps.answers, dict):
            return headers.erreur(400, "réponses manquantes")
        # BOUNDED IN COUNT AND IN LENGTH: an answer is a handful of
        # characters, and `Content-Length` alone does not stop a
        # ten-thousand-single-letter-key dictionary.
        reduit = {str(k)[:64]: str(v)[:64]
                  for k, v in list(corps.answers.items())[:500]}
        if not any(v.strip() for v in reduit.values()):
            return headers.erreur(400, "aucune réponse saisie")
        nom, blob = "answers.json", json.dumps(reduit).encode()
    else:
        # THE SAME ALLOW-LIST AS THE DRAFT (`validate_files`). Two copies of
        # "which names are allowed" would eventually drift, and the one that
        # drifts is the one that lets an unexpected name through.
        fichiers, message, code = validate_files(entree, corps.files)
        if message:
            return headers.erreur(code, message)
        if not any(v.strip() for v in fichiers.values()):
            return headers.erreur(400, "soumission vide")
        nom, blob = "files.json", json.dumps(fichiers).encode()

    # `poste` is a browser-issued token, NOT an identity: it only separates
    # two anonymous visitors behind the same NATed IP. Truncated, never
    # refused -- an odd token should cost its own counter, not a 400.
    sub = security.current_user(request.headers)
    qui = security.client_id(request.headers, deps.pair_tcp(request),
                             station=request.query_params.get("poste", "")[:64])
    with deps.verrou:
        attente = (deps.quota_connecte if sub else deps.quota).check(qui, time.time())
        if attente:
            return headers.erreur(
                429, f"trop de soumissions -- réessaie dans {attente} s",
                retry_after=attente)
        en_attente = sum(1 for _, _, fini in spool.scan_jobs() if not fini)
        if en_attente >= config.QUEUE_MAX:
            return headers.erreur(503, "file pleine -- réessaie dans une minute")
        # THE WRITE STAYS UNDER THE LOCK: otherwise the queue cap gets
        # outrun by the number of concurrent requests, which is exactly the
        # situation it exists to cover. Writing 64 KB while holding a global
        # lock costs less than reasoning about the race.
        #
        # The account is OPTIONAL: a signed-in student gets an attempt
        # attached to their account, everyone else keeps the anonymous path.
        job_id = spool.ecrire_job(entree["id"], nom, blob, sub)
    return {"id": job_id}


@router.get("/r/{job_id}")
def resultat(job_id: str):
    """A job's verdict, or its position in the queue.

    THIS IS WHERE THE SERVER READS THE VERDICT AND DRAWS VALUE FROM IT --
    never the browser. The first complete solve of a published exercise
    grants XP; a failure grants nothing, and redoing the same exercise grants
    nothing either, because the event id `reussite:<exercise>` has a primary
    key that refuses the duplicate. A VERIFICATION exercise goes through the
    other door: a piece of mastery evidence, solved or not, and not a cent of
    XP.

    A DATABASE OUTAGE MUST NEVER HIDE A VERDICT nor stop ctester's anonymous
    core: the writes below are attempted, and the next poll will safely
    replay them thanks to the uniqueness of `job_id`.
    """
    if not JOB_RE.match(job_id):
        return headers.erreur(400, "identifiant invalide")
    exercise_id, owner = spool.job_metadata(job_id)
    chemin = os.path.join(config.SPOOL, job_id, "result.json")
    try:
        with open(chemin, encoding="utf-8") as fh:
            resultat = json.load(fh)
    except OSError:
        resultat = None
    except ValueError:
        # The worker writes `result.json` via an atomic rename, so this case
        # should not exist. If it does, it is a worker bug, not a race: say so
        # rather than loop forever.
        return headers.erreur(500, "verdict illisible", cle="message",
                              state="error")

    if resultat is not None:
        if owner is not None and exercise_id and isinstance(resultat, dict):
            _enregistrer(owner, exercise_id, job_id, resultat)
        return resultat

    # `.lock` is set by the worker that claimed the job. Without this check, a
    # job being compiled would show "1st in queue" until the verdict --
    # correct as far as position goes, wrong as far as what is happening.
    if os.path.exists(os.path.join(config.SPOOL, job_id, ".lock")):
        return {"state": "running"}
    jobs = spool.scan_jobs()
    rang = spool.queue_position(jobs, job_id)
    if rang:
        return {"state": "queued", "position": rang,
                "eta": spool.eta_secondes(jobs, job_id)}
    # Swept by the worker (ten minutes) or never existed.
    return headers.erreur(404, "gone", cle="state")


def _enregistrer(owner, exercise_id, job_id, resultat):
    """What the server keeps from a verdict, for a signed-in account."""
    state.write_practice_attempt(owner, job_id, exercise_id, resultat)
    entree = find_exercise(exercise_id)
    if entree is None:
        return
    reussi = (resultat.get("status") == "ok"
              and resultat.get("total", 0) > 0
              and resultat.get("passed") == resultat.get("total"))
    # `write_state` NEVER lets a `valide` go backwards. This replaces the
    # state transition the browser used to declare on its own.
    state.write_state(owner, exercise_id, "valide" if reussi else "essaye",
                     spool.job_sources(job_id, entree))
    # TWO DOMAINS, NEVER BOTH AT ONCE. A verification produces mastery
    # evidence -- solved or not -- and NO XP; a practice exercise does the
    # opposite. The state and attempt above hold for both: the student must
    # see they did the activity, and keep their draft.
    if entree.get("verification"):
        progression.enregistrer_verification(owner, entree, job_id, reussi)
    elif reussi:
        progression.recompenser(owner, entree, job_id)
