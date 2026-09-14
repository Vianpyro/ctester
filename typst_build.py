"""Renders Typst statements to SVG and HTML at publish time, never per request.

Standard library only: test_ctester.py imports it on the host.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

PACKAGES = os.path.join(HERE, "typst", "packages")
LIB = os.path.join(PACKAGES, "local", "ctester", "1.0.0")

FONTS = os.path.join(HERE, "typst", "fonts")

IMAGE = os.environ.get("CTESTER_TYPST_IMAGE", "ghcr.io/typst/typst:0.15.1")
BIN = os.environ.get("CTESTER_TYPST_BIN", "")

# Checked against the engine: the binary and the image report the version differently,
# so only the number is compared.
VERSION = "0.15.1"
_VERSION_RE = re.compile(r"\btypst\s+(\d+\.\d+\.\d+)")

# An SVG cannot follow prefers-color-scheme, so each statement is rendered twice.
THEMES = ("dark", "light")

# Never copied next to the source, so typst cannot read the tests even through --root.
EXCLUS = frozenset(("assessment", "public", "exercise.json", "statement.md"))

MAX_PAGES = 16

TIMEOUT = 30


class TypstError(Exception):
    pass


def statement_of(exercise_dir):
    md = os.path.join(exercise_dir, "statement.md")
    typ = os.path.join(exercise_dir, "statement.typ")
    a, b = os.path.isfile(md), os.path.isfile(typ)
    if a and b:
        raise TypstError(
            "statement.md ET statement.typ sont présents : il en faut "
            "exactement un. Efface celui que tu n'utilises plus.")
    if b:
        return "typ", typ
    if a:
        with open(md, encoding="utf-8") as fh:
            return "md", fh.read()
    raise TypstError("il manque statement.md ou statement.typ")


def _version():
    argv = [BIN, "--version"] if BIN else ["docker", "run", "--rm", IMAGE, "--version"]
    try:
        sortie = subprocess.run(argv, capture_output=True, timeout=TIMEOUT,
                                text=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise TypstError(
            "typst est introuvable (%s). Pose CTESTER_TYPST_BIN sur un binaire, "
            "ou laisse Docker tirer %s." % (exc, IMAGE))
    trouve = _VERSION_RE.search(sortie or "")
    if trouve is None:
        raise TypstError("typst n'annonce pas sa version : %r" % (sortie,))
    if trouve.group(1) != VERSION:
        raise TypstError(
            "typst %s attendu, %s trouvé. La version est épinglée dans "
            "typst_build.py (VERSION) et dans le rôle Ansible "
            "(ctester_typst_image) : un énoncé doit se rendre pareil dans six "
            "mois." % (VERSION, trouve.group(1)))
    return trouve.group(1)


def _hacher_arbre(h, racine, exclus=frozenset()):
    for dossier, sous, noms in os.walk(racine):
        sous[:] = sorted(nom for nom in sous if nom not in exclus)
        for nom in sorted(noms):
            if nom in exclus:
                continue
            chemin = os.path.join(dossier, nom)
            h.update(os.path.relpath(chemin, racine).replace(os.sep, "/").encode())
            h.update(b"\0")
            with open(chemin, "rb") as fh:
                h.update(fh.read())
            h.update(b"\0")


def fingerprint(exercise_dir, version=None):
    h = hashlib.sha256()
    h.update(b"ctester-typst-1\0")
    h.update((version or _version()).encode())
    h.update(b"\0")
    _hacher_arbre(h, PACKAGES)
    h.update(b"\0")
    _hacher_arbre(h, FONTS)
    h.update(b"\0")
    _hacher_arbre(h, exercise_dir, EXCLUS)
    return h.hexdigest()[:16]


def cache_dir():
    # Outside published/, which keeps only the latest releases and would wipe the cache.
    dit = os.environ.get("CTESTER_TYPST_CACHE", "")
    if dit:
        return dit
    publie = os.environ.get("CTESTER_PUBLISHED", "")
    if publie:
        return os.path.join(os.path.dirname(os.path.abspath(publie)), "typst-cache")
    return os.path.join(tempfile.gettempdir(), "ctester-typst-cache")


def _preparer(exercise_dir, travail):
    for nom in sorted(os.listdir(exercise_dir)):
        if nom in EXCLUS:
            continue
        source = os.path.join(exercise_dir, nom)
        cible = os.path.join(travail, nom)
        if os.path.isdir(source):
            shutil.copytree(source, cible)
        else:
            shutil.copy2(source, cible)
    with open(os.path.join(travail, "main.typ"), "w", encoding="utf-8") as fh:
        fh.write('#import "@local/ctester:1.0.0": enonce\n'
                 "#show: enonce\n"
                 '#include "statement.typ"\n')


def _argv(travail, theme):
    if theme == "html":
        return _commande(travail, ["--features", "html", "--format", "html"],
                         "statement.html")
    return _commande(travail, ["--input", "theme=" + theme, "--format", "svg"],
                     theme + "-{p}.svg")


def _commande(travail, options, sortie):
    commun = ["compile", "--ignore-system-fonts", "--root", "."] + options
    if BIN:
        return [BIN] + commun + ["--font-path", FONTS,
                                 "main.typ", sortie], dict(
            os.environ, TYPST_PACKAGE_PATH=PACKAGES), travail
    return ["docker", "run", "--rm", "--network=none", "--read-only",
            "--user", "%d:%d" % (os.getuid(), os.getgid()),
            "-e", "TYPST_PACKAGE_PATH=/pkg",
            "-v", PACKAGES + ":/pkg:ro",
            "-v", FONTS + ":/fonts:ro",
            "-v", travail + ":/work",
            "-w", "/work", IMAGE] + commun + ["--font-path", "/fonts",
                                              "main.typ", sortie], \
        dict(os.environ), None


def render(exercise_dir, exercise_id, version=None):
    cle = fingerprint(exercise_dir, version)
    magasin = os.path.join(cache_dir(), cle)
    garde = _lire_cache(magasin)
    if garde is not None:
        return garde, True

    travail = tempfile.mkdtemp(prefix="ctester-typst-")
    try:
        _preparer(exercise_dir, travail)
        rendu = {}
        for theme in THEMES:
            argv, env, cwd = _argv(travail, theme)
            try:
                fin = subprocess.run(argv, capture_output=True, text=True,
                                     timeout=TIMEOUT, env=env, cwd=cwd)
            except subprocess.TimeoutExpired:
                raise TypstError(
                    "%s: statement.typ n'a pas compilé en %d s. Un énoncé du "
                    "dépôt prend 0,6 s ; c'est un document pathologique, pas "
                    "une machine lente." % (exercise_id, TIMEOUT))
            except OSError as exc:
                raise TypstError("%s: le moteur typst est injoignable (%s)"
                                 % (exercise_id, exc))
            if fin.returncode != 0:
                raise TypstError("%s/statement.typ n'a pas compilé :\n%s"
                                 % (exercise_id, (fin.stderr or fin.stdout).strip()))
            rendu[theme] = _relire_pages(travail, theme, exercise_id)
        if len(rendu["dark"]) != len(rendu["light"]):
            raise TypstError(
                "%s: %d page(s) en sombre contre %d en clair. Le thème ne doit "
                "pas changer la pagination : vérifie un tableau ou une image "
                "qui déborde." % (exercise_id, len(rendu["dark"]),
                                  len(rendu["light"])))
        # HTML export is experimental: a failure or a lossy export falls back to SVG only.
        argv, env, cwd = _argv(travail, "html")
        try:
            fin = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=TIMEOUT, env=env, cwd=cwd)
            chemin = os.path.join(travail, "statement.html")
            pertes = [l for l in (fin.stderr or "").splitlines()
                      if "ignored during HTML export" in l
                      and "pagebreak" not in l]
            if pertes:
                print("ctester: %s: rendu HTML incomplet, SVG seul :\n%s"
                      % (exercise_id, "\n".join(pertes)))
            elif fin.returncode == 0 and os.path.isfile(chemin):
                with open(chemin, "rb") as fh:
                    rendu["html"] = fh.read()
            else:
                print("ctester: %s: rendu HTML ignoré :\n%s"
                      % (exercise_id, (fin.stderr or fin.stdout).strip()))
        except (OSError, subprocess.SubprocessError) as exc:
            print("ctester: %s: rendu HTML ignoré (%s)" % (exercise_id, exc))
        _ecrire_cache(magasin, rendu)
        return rendu, False
    finally:
        shutil.rmtree(travail, ignore_errors=True)


def _relire_pages(travail, theme, exercise_id):
    pages = []
    for numero in range(1, MAX_PAGES + 2):
        chemin = os.path.join(travail, "%s-%d.svg" % (theme, numero))
        if not os.path.isfile(chemin):
            break
        if numero > MAX_PAGES:
            raise TypstError("%s: plus de %d pages d'énoncé"
                             % (exercise_id, MAX_PAGES))
        with open(chemin, "rb") as fh:
            pages.append(fh.read())
    if not pages:
        raise TypstError("%s: typst n'a écrit aucune page" % exercise_id)
    return pages


def _lire_cache(magasin):
    if not os.path.isdir(magasin):
        return None
    rendu = {}
    for theme in THEMES:
        pages = []
        for numero in range(1, MAX_PAGES + 1):
            chemin = os.path.join(magasin, "%s-%d.svg" % (theme, numero))
            if not os.path.isfile(chemin):
                break
            with open(chemin, "rb") as fh:
                pages.append(fh.read())
        if not pages:
            return None
        rendu[theme] = pages
    html = os.path.join(magasin, "statement.html")
    if os.path.isfile(html):
        with open(html, "rb") as fh:
            rendu["html"] = fh.read()
    return rendu


def _ecrire_cache(magasin, rendu):
    temporaire = magasin + ".tmp.%d" % os.getpid()
    shutil.rmtree(temporaire, ignore_errors=True)
    try:
        os.makedirs(temporaire, exist_ok=True)
        if rendu.get("html"):
            with open(os.path.join(temporaire, "statement.html"), "wb") as fh:
                fh.write(rendu["html"])
        for theme in THEMES:
            for numero, octets in enumerate(rendu[theme], 1):
                with open(os.path.join(temporaire, "%s-%d.svg" % (theme, numero)),
                          "wb") as fh:
                    fh.write(octets)
        # Renamed into place so two workers never read a half-written entry.
        os.replace(temporaire, magasin)
    except OSError:
        shutil.rmtree(temporaire, ignore_errors=True)


def render_all(model):
    typst = [(cle, entree) for cle, entree in sorted(model["exercises"].items())
             if entree.get("statement_format") == "typ"]
    if not typst:
        return {}, (0, 0)
    version = _version()
    rendus, servis = {}, 0
    for exercise_id, entree in typst:
        pages, du_cache = render(entree["path"], exercise_id, version)
        rendus[exercise_id] = pages
        servis += 1 if du_cache else 0
    return rendus, (len(typst), servis)
