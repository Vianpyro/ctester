"""Le catalogue des exercices, et la liste blanche des fichiers.

`find_tp()` EST LA SEULE PORTE VERS UN TP. Le mode, le nom du fichier déposé
dans le spool, le chemin d'un quiz servi : tout part d'ici. Un TP absent du
catalogue n'existe pas, quel que soit le contenu du disque -- c'est ce qui fait
qu'il n'y a aucun chemin à traverser dans `/tp/<id>.json`.

Le catalogue lui-même est écrit par le worker (`publish_catalogue()` dans
`runner.py`), qui retire le corrigé d'un quiz avant publication. Ce module ne
fait que le lire.
"""

import json
import os
import re

import config

TP_RE = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
# Le nom d'une release EST le hachage de son contenu. Validé avant d'être joint
# à un chemin : ce fichier est écrit par le worker, mais rien qui devienne un
# chemin ne se lit sans être vérifié.
REVISION_RE = re.compile(r"\A[0-9a-f]{8,64}\Z")


def release_dir():
    """Le répertoire de la publication v2 active, ou None (déploiement v1).

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
    """Le catalogue v2 publié -- collections, accès, exercices. None en v1."""
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
    """(base, nom) du fichier publié pour cet exercice. Reconstruit, jamais reçu.

    Un seul endroit sait où vivent le détail et le quiz : la v2 les range sous
    la release (`exercises/`, `quiz/`), la v1 sous `STATIC` (`tp/`, `quiz/`).
    """
    release = release_dir()
    if release is not None:
        dossier = "exercises" if quoi == "detail" else "quiz"
        return release, os.path.join(dossier, entry["id"] + ".json")
    return config.STATIC, os.path.join("tp" if quoi == "detail" else "quiz",
                                       entry["id"] + ".json")


def _v1(catalog):
    """Le catalogue v2 rendu dans la FORME v1, le temps de la bascule de l'UI.

    La page affiche encore deux menus déroulants groupe/exercice : elle reçoit
    donc `group`, `short` et `learning` comme avant, dérivés des collections et
    des métadonnées v2. C'est cette fonction que la phase 5 supprime, quand la
    page lira `/catalog.json` directement.

    SEULS LES EXERCICES OUVERTS EN SORTENT -- `access` est calculé à la
    publication, et un exercice verrouillé n'a de toute façon ni détail ni quiz
    publiés. La v1 les faisait disparaître du catalogue ; ici ils y sont, mais
    seule la page v2 saura dessiner leur cadenas.
    """
    groupes = {}
    for collection in catalog.get("collections") or ():
        if not isinstance(collection, dict):
            continue
        for item in collection.get("items") or ():
            groupes.setdefault(item, str(collection.get("title", "")))
    entries = []
    for exercice in catalog.get("exercises") or ():
        if not isinstance(exercice, dict) or exercice.get("access") != "available":
            continue
        titre = str(exercice.get("title", ""))
        learning = {}
        if exercice.get("skills"):
            learning["skills"] = list(exercice["skills"])
        if exercice.get("contexts"):
            learning["context"] = exercice["contexts"][0]
        if exercice.get("difficulty"):
            learning["difficulty"] = exercice["difficulty"]
        entries.append({
            "id": exercice.get("id"), "mode": exercice.get("mode"),
            "label": titre, "short": titre,
            "group": groupes.get(exercice.get("id"), "Autres"),
            "files": [{"name": f["name"]} for f in exercice.get("files") or ()
                      if isinstance(f, dict) and "name" in f],
            "learning": learning,
        })
    return [e for e in entries if isinstance(e["id"], str)]


def load_tps():
    """Les TP disponibles : [{id, mode, label}], publiés par le worker.

    Le web connaît le NOM, le MODE et le LIBELLÉ d'un TP, jamais son contenu --
    le répertoire des tests n'est pas monté dans ce conteneur, et le corrigé
    d'un quiz est retiré avant publication (publish_catalogue dans runner.py).
    """
    catalog = load_catalog()
    if catalog is not None:
        return _v1(catalog)
    try:
        with open(os.path.join(config.STATIC, "tps.json"), encoding="utf-8") as fh:
            entries = json.load(fh)
        return [e for e in entries if isinstance(e, dict) and "id" in e]
    except (OSError, ValueError):
        return []


def find_tp(tp):
    """L'entrée de catalogue de ce TP, ou None. La seule porte vers un TP.

    Tout ce qui suit -- le mode, le nom de fichier écrit dans le spool, le
    chemin d'un quiz servi -- part d'ici. Un TP absent du catalogue n'existe pas,
    quel que soit le contenu du disque.
    """
    if not TP_RE.match(tp):
        return None
    for entry in load_tps():
        if entry["id"] == tp:
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
