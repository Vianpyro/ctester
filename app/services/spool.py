"""Le spool : le seul canal entre l'API et le worker de l'hôte.

L'API ÉCRIT ET LIT DES FICHIERS, elle n'exécute rien. Le worker tourne sur
l'hôte, en root, et ne lit ce répertoire que pour lancer un conteneur jetable
sous gVisor. C'est cette séparation qui permet d'exposer l'API à Internet sans
lui donner le socket Docker.

`job.json` EST ÉCRIT EN DERNIER, par rename atomique : le worker ne déclenche
que sur sa présence, et sans cet ordre il lirait un `submission.c` à moitié
écrit et rendrait une erreur de compilation fantôme, une fois sur cent, à
l'étudiant qui n'y est pour rien. Ce module lit ; l'écriture arrive avec le
routeur de soumission.
"""

import json
import os

import config
from services.catalogue import validate_files


def scan_jobs():
    """(job_id, horodatage, terminé) pour chaque job du spool.

    L'horodatage vient du mtime de job.json, que le worker ne touche jamais --
    donc l'ordre vu ici est celui que le worker consomme, et le rang affiché à
    l'étudiant est vrai.
    """
    jobs = []
    try:
        entries = list(os.scandir(config.SPOOL))
    except OSError:
        return jobs
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            stamp = os.stat(os.path.join(entry.path, "job.json")).st_mtime
        except OSError:
            continue  # répertoire en cours d'écriture : pas encore un job
        done = os.path.exists(os.path.join(entry.path, "result.json"))
        jobs.append((entry.name, stamp, done))
    return jobs


def queue_position(jobs, job_id):
    """Rang 1-based du job parmi ceux qui attendent encore. 0 s'il n'attend plus."""
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    for rank, (_, name) in enumerate(pending, 1):
        if name == job_id:
            return rank
    return 0


def job_metadata(job_id):
    """The server-owned exercise and optional OIDC subject for one spool job.

    `owner` is written after validating the bearer token at submission time;
    it is never accepted from browser JSON.  Malformed/old jobs simply have no
    owner so the anonymous judge keeps its historical behaviour.
    """
    try:
        with open(os.path.join(config.SPOOL, job_id, "job.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", None
    if not isinstance(data, dict):
        return "", None
    tp = str(data.get("tp", ""))
    owner = data.get("owner")
    if not isinstance(owner, str) or not 0 < len(owner) <= 128:
        owner = None
    return tp, owner


def job_sources(job_id, entry):
    """The submitted source snapshot needed by the legacy exercise state.

    It is read only for a job whose owner was fixed by the API at submission.
    Quiz answers are not source files and intentionally keep the existing empty
    snapshot; compiled submissions use the same catalogue whitelist as every
    other path.
    """
    if entry.get("mode") == "quiz":
        return {}
    try:
        with open(os.path.join(config.SPOOL, job_id, "files.json"), encoding="utf-8") as fh:
            submitted = json.load(fh)
    except (OSError, ValueError):
        return {}
    files, message, _ = validate_files(entry, submitted)
    return files if message is None else {}
