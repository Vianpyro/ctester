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


def load_tps():
    """Les TP disponibles : [{id, mode, label}], publiés par le worker.

    Le web connaît le NOM, le MODE et le LIBELLÉ d'un TP, jamais son contenu --
    le répertoire des tests n'est pas monté dans ce conteneur, et le corrigé
    d'un quiz est retiré avant publication (publish_catalogue dans runner.py).
    """
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
