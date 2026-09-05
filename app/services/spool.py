"""Le spool : le seul canal entre l'API et le worker de l'hôte.

L'API ÉCRIT ET LIT DES FICHIERS, elle n'exécute rien. Le worker tourne sur
l'hôte, en root, et ne lit ce répertoire que pour lancer un conteneur jetable
sous gVisor. C'est cette séparation qui permet d'exposer l'API à Internet sans
lui donner le socket Docker.

`job.json` EST ÉCRIT EN DERNIER, par rename atomique : le worker ne déclenche
que sur sa présence, et sans cet ordre il lirait un `submission.c` à moitié
écrit et rendrait une erreur de compilation fantôme, une fois sur cent, à
l'étudiant qui n'y est pour rien.
"""

import json
import math
import os
import uuid

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


# Écrit par le worker (`runner.enregistrer_duree`), lu ici : {id: [moyenne, n]}.
# Absent tant qu'aucun job n'a tourné, et effaçable sans rien casser -- l'ETA
# retombe alors sur DUREE_INCONNUE.
DUREES = "durees.json"
# Ce que coûte un job dont on n'a encore rien mesuré, quand aucun autre
# exercice n'a de moyenne non plus. Volontairement pessimiste : compilation
# (10 s) plus une exécution (5 s). Annoncer plus court que le réel est la seule
# erreur qui se remarque.
DUREE_INCONNUE = 15.0


def durees_moyennes():
    try:
        with open(os.path.join(config.SPOOL, DUREES), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: float(v[0]) for k, v in data.items()
            if isinstance(v, list) and len(v) == 2
            and isinstance(v[0], (int, float)) and v[0] > 0}


def eta_secondes(jobs, job_id):
    """Secondes avant le verdict : la somme des jobs DEVANT, plus le sien.

    Pas un rang multiplié par une constante : un quiz se corrige instantanément
    et un TP de dix cas paie dix exécutions, donc deux files du même rang
    n'attendent pas la même chose. Un exercice jamais mesuré prend la moyenne
    des autres, et à défaut DUREE_INCONNUE.
    """
    devant = sorted((stamp, name) for name, stamp, done in jobs if not done)
    moyennes = durees_moyennes()
    defaut = (sum(moyennes.values()) / len(moyennes)) if moyennes else DUREE_INCONNUE
    total = 0.0
    for _, name in devant:
        exercise_id, _owner = job_metadata(name)
        total += moyennes.get(exercise_id, defaut)
        if name == job_id:
            break
    else:
        return 0
    # Les workers dépilent en parallèle. `CTESTER_WORKERS` doit refléter le
    # nombre d'unités `ctester-runner@` actives : trop haut, on promet plus vite
    # que le service ne peut tenir.
    return int(math.ceil(total / max(1, config.WORKERS)))


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
    exercise_id = str(data.get("exercise_id", ""))
    owner = data.get("owner")
    if not isinstance(owner, str) or not 0 < len(owner) <= 128:
        owner = None
    return exercise_id, owner


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


def ecrire_job(exercise_id, nom, blob, owner=None):
    """Écrit le job et rend son identifiant. `job.json` EN DERNIER, par rename.

    Le worker ne déclenche que sur la présence de `job.json`. Sans cet ordre il
    lirait un `submission.c` à moitié écrit et rendrait une erreur de
    compilation fantôme, une fois sur cent, à l'étudiant qui n'y est pour rien.

    `owner` VIENT DU JETON VALIDÉ, jamais du corps de la requête -- c'est ce qui
    rattache une tentative à un compte sans qu'on puisse se rattacher à celui
    d'un autre. Borné ici aussi : il devient la moitié d'une clé primaire.
    """
    job_id = uuid.uuid4().hex
    chemin = os.path.join(config.SPOOL, job_id)
    os.mkdir(chemin, 0o755)
    with open(os.path.join(chemin, nom), "wb") as fh:
        fh.write(blob)
    tmp = os.path.join(chemin, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        job = {"exercise_id": exercise_id}
        if isinstance(owner, str) and 0 < len(owner) <= 128:
            job["owner"] = owner
        json.dump(job, fh)
    os.replace(tmp, os.path.join(chemin, "job.json"))
    return job_id
