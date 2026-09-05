#!/usr/bin/env python3
"""Publier le contenu v2 : une projection allowlistée, datée, réversible.

CE FICHIER NE COPIE RIEN. `publish_catalogue()` de runner.py écrivait dans le
clone de l'application des fichiers dérivés du contenu privé ; ici on construit
un dictionnaire en mémoire à partir du MODÈLE VALIDÉ (content_catalogue), on le
relit à la recherche de clés qui n'ont rien à faire dehors, puis on l'écrit dans
un répertoire nommé par son propre hachage. Une copie récursive, elle, publie
tout ce que quelqu'un aura posé dans le dossier un mardi soir.

DEUX PROPRIÉTÉS QUI FONT TOUT LE RESTE :

- La révision EST le hachage de ce qui est publié. Republier un contenu
  inchangé ne crée rien, republier un contenu changé crée un répertoire de plus,
  et les deux coexistent -- un rollback est un pointeur à réécrire, pas une
  restauration.
- Le pointeur est un petit fichier remplacé par `os.replace`. Un lien
  symbolique aurait été plus élégant, mais un montage Docker résout le lien à
  l'attache : rebasculer `current` ne se verrait qu'au redémarrage du conteneur.
  ponytail: pointeur JSON relu à chaque requête, symlink le jour où le web ne
  lit plus le répertoire parent.

Un contenu invalide ne remplace jamais la publication active : `discover()` lève
avant qu'une seule ligne ne soit écrite, et le pointeur ne bouge qu'en dernier.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys

import content_catalogue
from runner import public_quiz

POINTER = "current.json"

# LES CLÉS QUI NE SORTENT PAS, vérifiées SUR LA PROJECTION et pas sur la source.
# public_catalogue / public_detail / public_quiz reconstruisent déjà champ à
# champ ; ce contrôle-ci est la ceinture qui attrape le champ ajouté demain à
# l'une des trois. Il porte sur les CLÉS : un énoncé qui contient le mot
# « note » est du texte, pas une fuite.
INTERDIT = frozenset((
    "answer", "answers", "expect", "expected", "stdin", "cases", "tolerance",
    "note", "notes", "path", "paths", "seed", "solution", "solutions",
    "allowed_includes", "config",
))


def _cles(value):
    """Toutes les clés d'une structure JSON, à toute profondeur."""
    if isinstance(value, dict):
        for key, sub in value.items():
            yield key
            for found in _cles(sub):
                yield found
    elif isinstance(value, list):
        for item in value:
            for found in _cles(item):
                yield found


def projection(model, now=None):
    """{chemin relatif: objet JSON} -- exactement ce que le navigateur peut voir.

    Le catalogue porte TOUS les exercices, ouverts ou non (un cadenas et une
    date). Le détail et le quiz ne sont écrits que pour ce qui est ouvert :
    `find_exercise` est la porte, ici comme dans l'API et le worker.
    """
    files = {"catalog.json": content_catalogue.public_catalogue(model, now)}
    for exercise_id, entry in model["exercises"].items():
        detail = content_catalogue.public_detail(model, exercise_id, now)
        if detail is None:
            continue
        files["exercises/%s.json" % exercise_id] = detail
        if entry["mode"] == "quiz":
            files["quiz/%s.json" % exercise_id] = public_quiz(entry["config"])
    fuites = sorted({key for value in files.values() for key in _cles(value)}
                    & INTERDIT)
    if fuites:
        raise content_catalogue.ContentValidationError(
            ["clé privée dans la projection publique : " + ", ".join(fuites)])
    return files


def revision(files):
    """Le hachage du contenu publié, donc le nom de sa release."""
    payload = json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def current(dest):
    """Le répertoire de la publication active, ou None. Relu à chaque appel."""
    try:
        with open(os.path.join(dest, POINTER), encoding="utf-8") as fh:
            rev = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    path = os.path.join(dest, rev)
    return path if os.path.isdir(path) else None


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def publish(model, dest, now=None, keep=3):
    """Écrit la release, bascule le pointeur, garde les `keep` dernières.

    L'ordre est l'invariant : tout est écrit AVANT que le pointeur ne bouge, et
    le pointeur bouge d'un seul `os.replace`. Une publication interrompue
    laisse un répertoire orphelin que personne ne lit.
    """
    files = projection(model, now)
    rev = revision(files)
    release = os.path.join(dest, rev)
    if not os.path.isdir(release):
        temporaire = release + ".tmp"
        shutil.rmtree(temporaire, ignore_errors=True)
        for relatif, value in files.items():
            _write(os.path.join(temporaire, relatif.replace("/", os.sep)), value)
        # Le manifeste est HORS du hachage : sa date changerait la révision d'un
        # contenu identique, et deux publications du même contenu doivent porter
        # le même nom pour que republier ne coûte rien.
        _write(os.path.join(temporaire, "manifest.json"), {
            "schema_version": content_catalogue.SCHEMA_VERSION, "revision": rev,
            "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "exercises": len(model["exercises"]),
            "collections": len(model["collections"])})
        os.replace(temporaire, release)
    pointeur = os.path.join(dest, POINTER)
    _write(pointeur + ".tmp", {"revision": rev,
                               "published_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    os.replace(pointeur + ".tmp", pointeur)
    _elaguer(dest, rev, keep)
    return rev


def _elaguer(dest, garder, keep):
    """Les anciennes releases sont le rollback : on en garde quelques-unes."""
    releases = [(os.path.getmtime(os.path.join(dest, name)), name)
                for name in os.listdir(dest)
                if name != garder and os.path.isdir(os.path.join(dest, name))]
    for _, name in sorted(releases, reverse=True)[max(keep - 1, 0):]:
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="publie le contenu ctester v2")
    parser.add_argument("root", help="racine contenant catalog.json et exercises/")
    parser.add_argument("dest", help="répertoire des releases (published/)")
    parser.add_argument("--keep", type=int, default=3, help="releases conservées")
    args = parser.parse_args(argv)
    try:
        model = content_catalogue.discover(args.root)
        rev = publish(model, args.dest, keep=args.keep)
    except content_catalogue.ContentValidationError as exc:
        print("publication refusée, la release active est intacte :", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("publié : révision %s (%d exercice(s), %d collection(s))"
          % (rev, len(model["exercises"]), len(model["collections"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
