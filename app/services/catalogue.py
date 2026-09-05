"""Le catalogue des exercices, et la liste blanche des fichiers.

`find_exercise()` EST LA SEULE PORTE VERS UN EXERCICE. Le mode, le nom du
fichier déposé dans le spool, le chemin d'un quiz servi : tout part d'ici. Un
exercice absent du catalogue publié n'existe pas, quel que soit le contenu du
disque -- et un exercice pas encore ouvert n'est pas « absent » mais « fermé »,
ce qui est la même réponse ici et un cadenas daté dans le menu.

Le catalogue lui-même est une RELEASE écrite par le worker (`publish_content.py`,
appelé par `publish_catalogue()` dans `runner.py`), qui reconstruit champ à champ
ce qui sort. Ce module ne fait que la lire.
"""

import json
import os
import re

import config

# Le nom d'une release EST le hachage de son contenu. Validé avant d'être joint
# à un chemin : ce fichier est écrit par le worker, mais rien qui devienne un
# chemin ne se lit sans être vérifié.
REVISION_RE = re.compile(r"\A[0-9a-f]{8,64}\Z")


def release_dir():
    """Le répertoire de la publication active, ou None (rien de publié).

    RELU À CHAQUE APPEL, comme le catalogue lui-même : republier ou revenir en
    arrière est un pointeur à réécrire, pas un conteneur à recréer.
    """
    if not config.PUBLISHED:
        return None
    try:
        with open(os.path.join(config.PUBLISHED, "current.json"), encoding="utf-8") as fh:
            revision = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(revision, str) or not REVISION_RE.match(revision):
        return None
    chemin = os.path.join(config.PUBLISHED, revision)
    return chemin if os.path.isdir(chemin) else None


def load_catalog():
    """Le catalogue publié -- collections, accès, exercices. None si rien n'est publié."""
    release = release_dir()
    if release is None:
        return None
    try:
        with open(os.path.join(release, "catalog.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def source_publiee(entry, quoi):
    """(base, nom) du fichier publié pour cet exercice, ou (None, None).

    Le nom est RECONSTRUIT depuis l'identifiant du catalogue, jamais reçu : il
    n'y a donc pas de chemin à traverser. `None` quand le pointeur a disparu
    entre la résolution et la lecture -- un rollback en pleine requête est un
    404, pas une trace.
    """
    release = release_dir()
    if release is None:
        return None, None
    dossier = "exercises" if quoi == "detail" else "quiz"
    return release, os.path.join(dossier, entry["id"] + ".json")


def exercices_ouverts():
    """Les exercices OUVERTS du catalogue publié, dans l'ordre de publication.

    La progression ne compte que ce qui est ouvert : un exercice verrouillé ne
    doit ni gonfler un dénominateur, ni être recommandé la veille de son
    ouverture. C'est la même liste que `find_exercise` interroge une entrée à la
    fois -- une seule définition de « publié et ouvert ».
    """
    return [entry for entry in (load_catalog() or {}).get("exercises") or ()
            if isinstance(entry, dict) and entry.get("access") == "available"
            and isinstance(entry.get("id"), str)]


def find_exercise(exercise_id):
    """L'entrée de catalogue de cet exercice OUVERT, ou None. La seule porte.

    Tout ce qui suit -- le mode, le nom de fichier écrit dans le spool, le
    chemin d'un quiz servi -- part d'ici. Un exercice verrouillé figure bien au
    catalogue (avec son cadenas et sa date), mais ne se résout pas : un lien
    profond partagé en avance ne contourne rien, il ne résout pas.
    """
    for entry in exercices_ouverts():
        if entry["id"] == exercise_id:
            return entry
    return None


def validate_files(entry, sent):
    """(files, message, status) -- THE SAME WHITELIST for a submission and a draft.

    File names come from the catalogue, never from the request. From lab 5 on, a
    submission is a module whose names the assignment imposes (calendrier.h,
    calendrier.c): a name that is not on the list is refused rather than dropped
    silently -- a student must know their file was not taken.

    Emptiness is NOT checked here: an empty submission is an error, an emptied
    draft is a legitimate thing to store. The caller decides.
    """
    if not isinstance(sent, dict):
        return None, "fichiers manquants", 400
    declared = [f["name"] for f in entry.get("files") or []] or ["submission.c"]
    unknown = sorted(k for k in sent if k not in declared)
    if unknown:
        return None, "fichier inattendu : " + ", ".join(unknown[:3]), 400
    files = {n: str(sent.get(n, "")) for n in declared}
    if len(json.dumps(files).encode()) > config.MAX_CODE:
        return None, f"soumission > {config.MAX_CODE // 1024} Ko", 413
    return files, None, 200
