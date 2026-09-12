"""Rendu des énoncés Typst : SVG au build, jamais à la requête.

POURQUOI CE FICHIER N'IMPORTE QUE LA BIBLIOTHÈQUE STANDARD. `test_ctester.py`
l'importe (par `content_catalog`), et cette suite tourne sur le Dell avec le
python de l'HÔTE -- sans `PYTHONPATH=/deps`, donc sans fastapi, sans pydantic,
sans rien. Un import de trop ici ne casse pas un test : il bloque le déploiement
automatique toutes les cinq minutes sur un `ImportError`, sans que rien ne soit
déployé. Même règle que `app/csp.py` et `app/services/source.py`.
`test_le_controle_de_l_hote_ne_depend_d_aucun_tiers` monte la garde.

OÙ ÇA TOURNE. Dans le tick `ctester-tests` du Dell, qui appelle
`runner.publish_catalogue()`. Le moteur est un CONTENEUR jetable
(`ghcr.io/typst/typst:0.15.1`), sur le modèle de la tâche `ctester-deps-install`
du rôle Ansible : le Dell n'a ni Node, ni npm, ni typst, et c'est une propriété
qu'on garde. En CI et sur un poste de dev, `CTESTER_TYPST_BIN` désigne un
binaire et le conteneur n'est pas utilisé -- c'est le même typst 0.15.1.

CE QUI N'EST PAS ICI, ET NE DOIT PAS Y VENIR : aucune compilation à la requête.
Le conteneur web ne monte pas `CTESTER_CONTENT`, ne voit pas ce module, et n'a
aucune raison de changer. Un étudiant reçoit un SVG déjà écrit.

LA FRONTIÈRE DE FICHIERS A DEUX COUCHES, et les deux sont éprouvées :
  1. on compile depuis une COPIE de l'exercice qui ne porte ni `assessment/`
     ni `exercise.json` -- un corrigé n'est pas sur le disque que typst voit ;
  2. `--root` est posé sur cette copie, donc `#include "/etc/passwd"` et
     `read("../../secret")` sont refusés par typst lui-même.
`test_typst_root_refuse_de_sortir_du_repertoire_de_l_exercice` le prouve plutôt
que de le supposer.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# LES PAQUETS TYPST SONT VENDORÉS, donc le rendu ne touche jamais le réseau :
# `merman` (Mermaid, 7,6 Mo de WebAssembly) et notre propre bibliothèque
# `@local/ctester`. Le conteneur tourne en `--network=none`, ce qui rend la
# propriété vérifiable au lieu d'être une intention.
PACKAGES = os.path.join(HERE, "typst", "packages")
LIB = os.path.join(PACKAGES, "local", "ctester", "1.0.0")

# L'IMAGE EST ÉPINGLÉE PAR VERSION, jamais `latest` : un énoncé pédagogique doit
# se rendre pareil dans six mois. Le rôle Ansible pose la même valeur sur le
# tick (`ctester_typst_image`).
IMAGE = os.environ.get("CTESTER_TYPST_IMAGE", "ghcr.io/typst/typst:0.15.1")
# Le binaire, quand il y en a un (CI, poste de dev). Prioritaire sur l'image :
# c'est le chemin rapide, et c'est celui qui permet de rendre sans Docker.
BIN = os.environ.get("CTESTER_TYPST_BIN", "")

# LA VERSION ATTENDUE, ET LE BUILD ÉCHOUE SI CE N'EST PAS ELLE. Deux versions de
# typst ne rendent pas identiquement ; servir un SVG rendu par une autre serait
# exactement ce que le cache doit interdire.
VERSION = "0.15.1"
_VERSION_RE = re.compile(r"\btypst\s+(\d+\.\d+\.\d+)")

# LES DEUX THÈMES, ET L'ORDRE EST CELUI DES FICHIERS PUBLIÉS. Le SVG est peint
# une fois pour toutes : il ne peut pas suivre `prefers-color-scheme` tout seul,
# donc on rend les deux et la page choisit.
THEMES = ("dark", "light")

# CE QUI N'EST PAS COPIÉ DANS LE RÉPERTOIRE DE COMPILATION. `assessment/` porte
# les corrigés, `exercise.json` les métadonnées, `public/files.json` les
# gabarits : rien de tout ça n'est un énoncé.
EXCLUS = frozenset(("assessment", "public", "exercise.json", "statement.md"))

# UN ÉNONCÉ TIENT EN QUELQUES PAGES. La borne existe pour qu'un `#pagebreak()`
# dans une boucle ne publie pas deux mille fichiers ; elle n'a jamais été
# atteinte.
MAX_PAGES = 16

# MESURÉ, PAS DEVINÉ. Le document le plus lourd du dépôt -- la fixture, qui
# porte un diagramme Mermaid (instanciation d'un WebAssembly de 7,6 Mo), une
# image, un tableau calculé et des maths -- compile en 0,47 s avec le binaire et
# 0,62 s par conteneur, démarrage compris ; un énoncé ordinaire prend 0,10 s.
# 30 s laissent donc un facteur cinquante, et le Dell est plus lent que la
# machine qui a mesuré. Ce que ce plafond garde n'est PAS une boucle infinie --
# typst refuse `while true` et borne la profondeur d'appel lui-même -- mais un
# document lourd-mais-fini qui bloquerait le tick de cinq minutes.
TIMEOUT = 30


class TypstError(Exception):
    """Un échec de rendu, avec de quoi le corriger.

    Porte l'exercice, le fichier et la sortie de typst TELLE QUELLE : typst
    écrit déjà `statement.typ:12:5: error: ...`, et la réécrire ne ferait que
    perdre la ligne et la colonne.
    """


def statement_of(exercise_dir):
    """`("md", texte)` ou `("typ", chemin)`. Lève si les deux, ou aucun.

    LES DEUX PRÉSENTS EST UNE ERREUR, PAS UN CHOIX À FAIRE. Choisir en silence
    voudrait dire qu'un auteur qui migre un énoncé et oublie d'effacer l'ancien
    corrige un fichier que personne ne lit -- et ne comprend pas pourquoi sa
    correction n'arrive jamais à l'écran.
    """
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
    """La version de typst, telle que le moteur configuré la rapporte.

    ON PARSE LE NUMÉRO, ON NE GARDE PAS LA CHAÎNE. Le binaire musl officiel dit
    `typst 0.15.1 (9dfd3a08)` et l'image Docker `typst 0.15.1 (unknown commit)` :
    la même version, deux chaînes. Fingerprinter la chaîne brute donnerait deux
    caches pour un seul rendu -- la CI réchaufferait un cache que le Dell
    n'utiliserait jamais.
    """
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
    """Ajoute au hachage le CONTENU d'un arbre, chemins compris, trié.

    DU CONTENU, JAMAIS UN MTIME. C'est la leçon déjà payée par `_publie_le` dans
    `publish_content.py` : la granularité d'un mtime est celle que le système de
    fichiers veut bien lui donner, et deux écritures d'un même tick la
    partagent.
    """
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
    """La clé de cache d'un énoncé : tout ce dont son rendu dépend.

    CE QUI ENTRE : la version de typst, la bibliothèque `@local/ctester` (donc
    le gabarit, la palette ET les deux `.tmTheme`), les paquets vendorés (donc
    merman et son WebAssembly), et l'arbre de l'exercice sans `assessment/`
    (donc le `statement.typ` et ses images).

    Un `.tmTheme` retouché, une macro corrigée, une image remplacée, une montée
    de typst ou de merman : la clé change et tout se recalcule. Il n'y a donc
    AUCUN numéro de version de cache à incrémenter à la main -- celui-là serait
    oublié exactement le jour où il compte, comme `empreinte_juge()` le dit déjà
    pour le cache de verdicts.
    """
    h = hashlib.sha256()
    h.update(b"ctester-typst-1\0")
    h.update((version or _version()).encode())
    h.update(b"\0")
    _hacher_arbre(h, PACKAGES)
    h.update(b"\0")
    _hacher_arbre(h, exercise_dir, EXCLUS)
    return h.hexdigest()[:16]


def cache_dir():
    """Le magasin de rendus. JAMAIS SOUS `published/`.

    `publish_content._elaguer()` supprime tout répertoire de `published/` qui
    n'est pas une des dernières révisions : un cache posé là serait effacé à la
    publication suivante, et chaque tick recompilerait tout le semestre.
    """
    dit = os.environ.get("CTESTER_TYPST_CACHE", "")
    if dit:
        return dit
    publie = os.environ.get("CTESTER_PUBLISHED", "")
    if publie:
        return os.path.join(os.path.dirname(os.path.abspath(publie)), "typst-cache")
    return os.path.join(tempfile.gettempdir(), "ctester-typst-cache")


def _preparer(exercise_dir, travail):
    """Copie l'énoncé et ses ressources, et écrit le `main.typ` qui les enrobe.

    UNE COPIE, ET C'EST LA PREMIÈRE DES DEUX COUCHES. Ce qui n'est pas copié ne
    peut pas être lu, quoi que fasse le document -- `assessment/` reste sur le
    disque de l'hôte, jamais sur celui que typst voit.

    L'ENSEIGNANT N'ÉCRIT AUCUN PRÉAMBULE. C'est ce `main.typ` qui applique le
    gabarit, donc un `statement.typ` réduit à deux lignes est déjà stylé. La
    ligne `#import` que la documentation montre ne sert qu'aux helpers : les
    portées de Typst sont par fichier, un import ici ne les rendrait pas
    visibles là-bas.
    """
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
    """La ligne de commande du moteur configuré.

    LE CONTENEUR NE MONTE QUE TROIS CHOSES, et deux le sont en lecture seule :
    les paquets, le répertoire de travail (qui reçoit les SVG), et rien d'autre.
    `--network=none` parce qu'un rendu ne parle à personne ; `--read-only` sur
    le système de fichiers de l'image ; l'uid de l'appelant pour que les SVG ne
    sortent pas root.
    """
    commun = ["compile", "--ignore-system-fonts", "--root", ".",
              "--input", "theme=" + theme, "--format", "svg"]
    if BIN:
        return [BIN] + commun + ["main.typ", theme + "-{p}.svg"], dict(
            os.environ, TYPST_PACKAGE_PATH=PACKAGES), travail
    return ["docker", "run", "--rm", "--network=none", "--read-only",
            "--user", "%d:%d" % (os.getuid(), os.getgid()),
            "-e", "TYPST_PACKAGE_PATH=/pkg",
            "-v", PACKAGES + ":/pkg:ro",
            "-v", travail + ":/work",
            "-w", "/work", IMAGE] + commun + ["main.typ", theme + "-{p}.svg"], \
        dict(os.environ), None


def render(exercise_dir, exercise_id, version=None):
    """`{"dark": [octets, ...], "light": [...]}` -- les pages, dans l'ordre.

    Servi depuis le cache quand la clé est déjà là. Lève une `TypstError`
    portant l'exercice, le fichier et la sortie de typst sinon.
    """
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
        # LES DEUX THÈMES DOIVENT DONNER LE MÊME NOMBRE DE PAGES. Le document
        # est le même, seules les couleurs changent -- si les comptes diffèrent,
        # c'est que le thème a fait déborder une page, et la page servirait un
        # 404 à l'étudiant qui bascule. Mieux vaut le dire au build.
        if len(rendu["dark"]) != len(rendu["light"]):
            raise TypstError(
                "%s: %d page(s) en sombre contre %d en clair. Le thème ne doit "
                "pas changer la pagination : vérifie un tableau ou une image "
                "qui déborde." % (exercise_id, len(rendu["dark"]),
                                  len(rendu["light"])))
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
            return None  # un cache à moitié écrit n'est pas un cache
        rendu[theme] = pages
    return rendu


def _ecrire_cache(magasin, rendu):
    """Écrit le rendu, puis le renomme en place.

    LE RENOMMAGE EST CE QUI REND LE CACHE SÛR À DEUX WORKERS. Il y en a deux sur
    le Dell, et ils publient le même contenu au démarrage : un répertoire à
    moitié écrit, lu par l'autre, servirait une consigne amputée.
    """
    temporaire = magasin + ".tmp.%d" % os.getpid()
    shutil.rmtree(temporaire, ignore_errors=True)
    try:
        os.makedirs(temporaire, exist_ok=True)
        for theme, pages in rendu.items():
            for numero, octets in enumerate(pages, 1):
                with open(os.path.join(temporaire, "%s-%d.svg" % (theme, numero)),
                          "wb") as fh:
                    fh.write(octets)
        os.replace(temporaire, magasin)
    except OSError:
        # UN CACHE QUI N'ÉCRIT PAS N'EST PAS UNE PANNE : on recompilera. Ce qui
        # serait une panne, c'est de refuser de publier pour autant.
        shutil.rmtree(temporaire, ignore_errors=True)


def render_all(model):
    """`{exercise_id: {"dark": [...], "light": [...]}}` pour tout énoncé Typst.

    Lève à la PREMIÈRE erreur, en la nommant. C'est le contrat que
    `publish_content` tient déjà : un contenu invalide ne remplace jamais la
    publication active, parce que rien n'est écrit avant que tout soit rendu.
    """
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
