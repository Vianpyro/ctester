#!/usr/bin/env python3
"""ctester -- le worker de l'hôte. Fichier géré par Ansible : éditer le rôle.

Tourne en root sur le Dell, en N instances (ctester-runner@1..N), et fait les
seules choses que le conteneur web n'a pas le droit de faire : lancer Docker, et
lire les tests. Il LIT le spool, il ne l'exécute jamais -- rien de ce qui vient
du web n'est passé à un shell, et `subprocess` reçoit une liste d'arguments,
jamais une chaîne.

En Python et pas en bash pour cette raison précise : construire une ligne de
commande docker autour d'un nom de TP venu du réseau est exactement le genre de
chose qu'on écrit correctement une fois sur deux en shell. Ici il n'y a pas de
shell à échapper, et le parsing des verdicts devient testable (test_ctester.py).

TROIS MODES, DÉDUITS DU CONTENU DU RÉPERTOIRE DE TP -- pas d'un champ de
configuration qu'il faudrait tenir synchronisé avec la réalité :

  quiz.json   exercices sur papier. Aucune compilation, aucun conteneur.
  io.json     un programme complet avec main(), exécuté sur des entrées.
  test_*.c    des fonctions liées à Unity, sans main().
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid

SPOOL = os.environ.get("CTESTER_SPOOL", "/opt/ctester/spool")
TESTS = os.environ.get("CTESTER_TESTS", "/opt/ctester/tests")
APP = os.environ.get("CTESTER_APP", "/opt/ctester/app")
BUILD_UNITY = os.environ.get("CTESTER_BUILD_UNITY", "/opt/ctester/build-unity.sh")
BUILD_IO = os.environ.get("CTESTER_BUILD_IO", "/opt/ctester/build-io.sh")
IMAGE = os.environ.get("CTESTER_IMAGE", "gcc:14-bookworm")
RUNTIME = os.environ.get("CTESTER_RUNTIME", "runsc")
JOB_TIMEOUT = int(os.environ.get("CTESTER_JOB_TIMEOUT", "60"))
MEMORY = os.environ.get("CTESTER_MEMORY", "256m")
PIDS = os.environ.get("CTESTER_PIDS", "64")
CPUS = os.environ.get("CTESTER_CPUS", "1")
SWEEP_AFTER = int(os.environ.get("CTESTER_SWEEP_AFTER", "600"))

TP_RE = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
SUMMARY_RE = re.compile(r"^(\d+) Tests (\d+) Failures (\d+) Ignored", re.M)
FAIL_RE = re.compile(r"^[^\n:]*:\d+:([A-Za-z0-9_]{1,64}):FAIL", re.M)
INCLUDE_RE = re.compile(r"^[ \t]*#[ \t]*include[ \t]*[<\"]([^>\"\n]+)", re.M)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

# `inf` et `nan` tels que printf les écrit. Les gardes de part et d'autre sont
# des « pas une lettre », pas des \b : \b considère `é` comme une lettre selon
# les cas, et « inférieur » ou « nanomètre » dans une invite ne doivent pas
# déclencher le message. [^\W\d_] = une lettre, Unicode compris.
NONFINITE_RE = re.compile(
    r"(?<![^\W\d_])-?(?:inf(?:inity)?|nan)(?![^\W\d_])", re.I)

MAX_GCC_CHARS = 8000
MAX_FAILED_NAMES = 50
MAX_CASE_OUTPUT = 600
DEFAULT_TOLERANCE = 0.005


# --------------------------------------------------------------------------
# Mode d'un TP
# --------------------------------------------------------------------------

MODE_FILES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))


def detect_mode(tp_dir):
    """quiz / io / unity / None, d'après le fichier de configuration présent.

    UN SEUL MÉCANISME POUR LES TROIS MODES. Unity était détecté autrement --
    par la présence d'un test_*.c -- et ça n'avait pas d'endroit où déclarer un
    libellé ni la liste des fichiers attendus. Uniformiser coûte un fichier
    unity.json par TP et supprime une exception.
    """
    for mode, conf in MODE_FILES:
        if os.path.exists(os.path.join(tp_dir, conf)):
            return mode
    return None


def config_name(mode):
    return dict(MODE_FILES)[mode]


# Les noms de fichiers viennent de la CONFIGURATION DES TESTS, écrite par
# l'enseignant, jamais de l'étudiant. Ils sont quand même validés : une faute de
# frappe qui produirait « ../../etc/passwd » ne doit pas devenir un chemin.
FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")


def declared_files(conf):
    """Les fichiers que l'étudiant doit fournir, [{name, template}].

    Le nom est IMPOSÉ PAR L'ÉNONCÉ et pas choisi par l'étudiant : à partir du
    laboratoire 5, il écrit un module `calendrier.h` + `calendrier.c`, et le
    `#include "calendrier.h"` de son propre code comme celui du fichier de test
    ne tombent juste que si le fichier porte exactement ce nom. Laisser
    l'étudiant nommer ses fichiers ne serait pas de la liberté, ce serait une
    classe d'erreur de plus.

    Par défaut, un seul fichier `submission.c` -- la forme des laboratoires 2 à
    4, un programme complet dans un seul fichier.
    """
    files = conf.get("files")
    if not files:
        return [{"name": "submission.c", "template": ""}]
    out = []
    for item in files:
        name = str(item.get("name", "")) if isinstance(item, dict) else str(item)
        if not FILE_RE.match(name):
            continue
        template = item.get("template", "") if isinstance(item, dict) else ""
        out.append({"name": name, "template": str(template)})
    return out or [{"name": "submission.c", "template": ""}]


def load_config(tp_dir, name):
    with open(os.path.join(tp_dir, name), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Catalogue public -- LA FRONTIÈRE
# --------------------------------------------------------------------------

def public_quiz(quiz):
    """Le quiz débarrassé de son corrigé, tel que le navigateur peut le voir.

    C'EST LA FONCTION QUI GARDE LE SECRET, et c'est pour ça qu'elle reconstruit
    un dictionnaire champ par champ au lieu de retirer `answer` d'une copie. Une
    clé ajoutée au corrigé demain (un commentaire, une variante acceptée) ne
    fuit donc pas par défaut : elle est simplement absente tant que personne ne
    l'ajoute ici. test_ctester.py vérifie qu'aucune clé 'answer' ne survit.
    """
    return {
        "label": quiz.get("label", ""),
        "questions": [
            {
                "id": str(q.get("id", "")),
                "group": str(q.get("group", "")),
                "label": str(q.get("label", "")),
                "type": str(q.get("type", "int")),
            }
            for q in quiz.get("questions", [])
        ],
    }


# Le nom du répertoire porte la structure du cours : tp<N> ou tp<N>-ex<M>. C'est
# de là que sortent le regroupement du menu et l'ordre d'affichage.
ORDER_RE = re.compile(r"\Atp(\d+)(?:-ex(\d+))?")
# Le libellé répète souvent « TP2 : » que le premier menu affiche déjà. On le
# retire pour le second menu, avec repli sur le libellé entier s'il n'y est pas.
PREFIX_RE = re.compile(r"\A\s*TP\s*\d+\s*[:—\-]\s*", re.I)


CONFORME_RE = re.compile(r"\Atp\d", re.I)
CHUNKS_RE = re.compile(r"(\d+)")


def sort_key(name):
    """Ordre du menu. NUMÉRIQUE, et pas seulement au premier niveau.

    Trié comme du texte, `tp10` passe avant `tp2` -- invisible avec deux
    laboratoires, et le menu part en désordre au dixième. Le même piège attend
    un cran plus bas avec `ex10` avant `ex2`, d'où un tri naturel générique
    plutôt qu'une expression rationnelle sur `tp<N>-ex<M>` : il découpe le nom
    en morceaux de chiffres et de lettres, et compare les chiffres comme des
    nombres. Il vaut donc à tous les niveaux, quel que soit le préfixe.

    Les noms hors convention finissent à la fin plutôt que de s'insérer
    n'importe où.
    """
    morceaux = [(1, "", int(c)) if c.isdigit() else (0, c, 0)
                for c in CHUNKS_RE.split(name.lower()) if c]
    return (0 if CONFORME_RE.match(name) else 1, morceaux)


def group_of(name):
    match = ORDER_RE.match(name)
    return "TP " + match.group(1) if match else "Autres"


def sous_dossiers(chemin):
    try:
        return sorted((n for n in os.listdir(chemin)
                       if os.path.isdir(os.path.join(chemin, n))), key=sort_key)
    except OSError:
        return []


def entrees_brutes():
    """(identifiant, chemin) pour chaque exercice publiable, dans l'ordre.

    DEUX NIVEAUX : `tp6/ex1/unity.json`. Un dossier par TP, un sous-dossier par
    exercice -- à 13 laboratoires de 8 exercices, une racine plate ferait 104
    dossiers et personne ne retrouverait rien.

    Un TP dont la configuration est directement à sa racine (`tp1/quiz.json`)
    reste une entrée à lui seul : c'est le cas du quiz, qui n'a pas d'exercices.

    L'IDENTIFIANT RESTE PLAT -- `tp6-ex1` et jamais `tp6/ex1`. Il voyage jusqu'au
    navigateur, revient dans une soumission, et est ensuite joint à un chemin
    racine : y autoriser une barre oblique rouvrirait exactement la traversée de
    répertoire que `TP_RE` existe pour fermer. Le chemin, lui, est porté par
    l'entrée du catalogue, donc il n'y a jamais à le reconstruire par analyse du
    nom.
    """
    entrees = []
    for tp in sous_dossiers(TESTS):
        if not TP_RE.match(tp):
            continue  # écarte .git, unity, et tout nom qu'un TP ne peut porter
        chemin_tp = os.path.join(TESTS, tp)
        if detect_mode(chemin_tp):
            entrees.append((tp, chemin_tp))
            continue
        for exercice in sous_dossiers(chemin_tp):
            identifiant = tp + "-" + exercice
            if not TP_RE.match(identifiant):
                continue
            chemin = os.path.join(chemin_tp, exercice)
            if detect_mode(chemin):
                entrees.append((identifiant, chemin))
    return entrees


def catalogue():
    """[{id, mode, label, group, short, files, path}] dans l'ordre du cours.

    `path` est un chemin du SERVEUR : il sert au worker et il est retiré avant
    publication vers le conteneur web (voir publish_catalogue).
    """
    entries = []
    for name, tp_dir in entrees_brutes():
        mode = detect_mode(tp_dir)
        label, files = name, declared_files({})
        try:
            conf = load_config(tp_dir, config_name(mode))
            label = conf.get("label") or name
            files = declared_files(conf)
        except (OSError, ValueError):
            pass  # fichier cassé : le nom du répertoire et un fichier par défaut
        entries.append({
            "id": name,
            "path": tp_dir,
            "mode": mode,
            "label": label,
            # Les noms de fichiers attendus voyagent jusqu'au navigateur : ils
            # sont dans l'énoncé, ils ne sont pas secrets, et ce sont eux qui
            # deviennent les onglets de l'éditeur ET la liste blanche que l'API
            # oppose à une soumission.
            "files": files,
            "group": group_of(name),
            # Libellé pour le second menu, sans le « TP2 : » que le premier
            # affiche déjà. Purement cosmétique : si le préfixe n'est pas là, on
            # garde le libellé entier et rien n'est perdu.
            "short": PREFIX_RE.sub("", label) or label,
        })
    return entries


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def publish_catalogue():
    """Écrit ce que le conteneur web a le droit de savoir, et rien de plus.

    Publié par LE WORKER et pas par Ansible : c'est lui qui a le droit de lire
    les tests, et surtout « le corrigé ne franchit jamais la frontière »
    devient une fonction Python qu'un test vérifie, au lieu d'une boucle Jinja
    que personne ne relit.

    Les N workers écrivent le même contenu au démarrage. La course est sans
    conséquence : les écritures sont atomiques et le contenu est identique.
    """
    entries = catalogue()
    quiz_dir = os.path.join(APP, "quiz")
    os.makedirs(quiz_dir, exist_ok=True)
    for entry in entries:
        if entry["mode"] != "quiz":
            continue
        quiz = load_config(entry["path"], "quiz.json")
        write_json(os.path.join(quiz_dir, entry["id"] + ".json"), public_quiz(quiz))
    # `path` NE FRANCHIT PAS LA FRONTIÈRE. C'est un chemin du serveur : il
    # n'apprend rien d'utile au navigateur et il décrit l'arborescence des
    # secrets. Même discipline que public_quiz -- on reconstruit ce qui sort,
    # on ne retire pas d'une copie.
    write_json(os.path.join(APP, "tps.json"), [
        {k: v for k, v in e.items() if k != "path"} for e in entries])
    return entries


def tp_path(tp_id):
    """Le répertoire d'un exercice, d'après le catalogue. None s'il n'existe pas.

    LA SEULE FAÇON DE PASSER D'UN IDENTIFIANT À UN CHEMIN. Reconstruire
    `tp6-ex1` en `tp6/ex1` par découpage marcherait, jusqu'au jour où un nom
    contient un tiret de plus. Surtout, passer par le catalogue veut dire qu'un
    exercice non publié n'est pas exécutable, ce qui est plus strict que « le
    répertoire existe ».
    """
    for entry in catalogue():
        if entry["id"] == tp_id:
            return entry["path"]
    return None


# --------------------------------------------------------------------------
# Mode quiz
# --------------------------------------------------------------------------

def norm_bin(text):
    """Chiffres binaires, ou None. Accepte les espaces, les _ et le préfixe 0b."""
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0b", "", s)
    return s if s and set(s) <= {"0", "1"} else None


def norm_hex(text):
    """Valeur d'un hexadécimal écrit 1F, 0x1f, 1Fh ou 001f. None si illisible."""
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0x", "", s)
    s = re.sub(r"h\Z", "", s)
    try:
        return int(s, 16)
    except ValueError:
        return None


def norm_int(text):
    # Le signe moins Unicode arrive par copier-coller depuis le PDF de l'énoncé,
    # où il est écrit "-45". Le refuser serait punir un copier-coller réussi.
    s = re.sub(r"[\s_]", "", str(text)).replace("\u2212", "-")
    try:
        return int(s)
    except ValueError:
        return None


def check_answer(kind, given, expected):
    """(juste, indice). L'indice explique une erreur de FORME, jamais la réponse."""
    if kind == "bin8":
        got, want = norm_bin(given), norm_bin(expected)
        if got is None:
            return False, "ce n'est pas une suite de 0 et de 1"
        if got == want:
            return True, ""
        if want is not None and int(got, 2) == int(want, 2):
            # La valeur est bonne, l'écriture ne l'est pas. Le dire : l'énoncé
            # demande 8 bits, et un étudiant qui répond 10111 a compris la
            # conversion mais pas la consigne. Les deux méritent d'être
            # distingués, sans donner la réponse pour autant.
            return False, "bonne valeur, mais l'énoncé demande 8 bits"
        return False, ""
    if kind == "hex8":
        got, want = norm_hex(given), norm_hex(expected)
        if got is None:
            return False, "ce n'est pas un nombre hexadécimal"
        return got == want, ""
    got, want = norm_int(given), norm_int(expected)
    if got is None:
        return False, "ce n'est pas un nombre entier"
    return got == want, ""


def grade_quiz(quiz, answers):
    """Corrige un quiz. `answers` est {id: texte} tel que soumis."""
    wrong, total = [], 0
    for question in quiz.get("questions", []):
        total += 1
        qid = str(question.get("id", ""))
        given = answers.get(qid, "")
        ok, hint = check_answer(question.get("type", "int"), given,
                                question.get("answer", ""))
        if not ok:
            wrong.append({
                "id": qid,
                "label": str(question.get("label", qid)),
                "hint": ("non répondu" if not str(given).strip() else hint),
            })
    return {
        "status": "ok",
        "kind": "quiz",
        "total": total,
        "passed": total - len(wrong),
        "wrong": wrong,
    }


# --------------------------------------------------------------------------
# Mode io
# --------------------------------------------------------------------------

def extract_numbers(text):
    """Tous les nombres d'une sortie libre, dans l'ordre.

    La virgule décimale est acceptée : `printf("%.2f")` produit un point, mais
    un étudiant qui formate à la main peut produire une virgule.
    """
    out = []
    for match in NUMBER_RE.findall(text):
        try:
            out.append(float(match.replace(",", ".")))
        except ValueError:
            continue
    return out


def close_enough(got, want, tol):
    return abs(got - want) <= max(abs(want) * tol, 1e-9)


def match_subsequence(numbers, expected, tol):
    """Les valeurs attendues apparaissent-elles dans l'ordre parmi les nombres ?

    SOUS-SUITE ET PAS ÉGALITÉ, parce que l'énoncé ne dit jamais quoi afficher :
    « Surface = 15 cm2 » et « 15 » doivent passer tous les deux, et une
    invite « Entrez la longueur : » ne doit rien casser. Le prix est un faux
    positif possible si une invite contient par hasard la valeur attendue --
    acceptable pour un outil de feedback.
    """
    index = 0
    for want in expected:
        while index < len(numbers) and not close_enough(numbers[index], want, tol):
            index += 1
        if index >= len(numbers):
            return False
        index += 1
    return True


def fold(text):
    """Minuscules sans accents, pour comparer un mot à une sortie d'étudiant."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def check_case(case, output, tol):
    """'' si le cas passe, sinon la raison, en français, pour l'étudiant."""
    folded = fold(output)
    for word in case.get("absent", []):
        if fold(word) in folded:
            return "la sortie mentionne « " + word + " », qui ne devrait pas y etre"
    wanted = case.get("contains")
    if wanted and fold(wanted) not in folded:
        return "la sortie ne contient pas le mot attendu"
    expected = case.get("expect")
    if expected:
        numbers = extract_numbers(output)
        if match_subsequence(numbers, expected, tol):
            return ""
        # DEUX ÉCHECS TRÈS FRÉQUENTS MÉRITENT LEUR PROPRE MESSAGE. « la sortie
        # ne contient pas les valeurs attendues » est vrai mais inutile quand la
        # sortie vaut `inf` ou ne contient aucun chiffre : l'étudiant ne fait
        # alors pas une erreur de calcul, il lit une variable qui n'a jamais été
        # remplie, ou il teste le mauvais exercice.
        if NONFINITE_RE.search(output):
            return ("ta sortie contient inf ou nan : division par zéro, ou une "
                    "variable utilisée alors que sa lecture a échoué. Vérifie "
                    "que ton programme lit exactement autant de valeurs que le "
                    "cas lui en fournit")
        if not numbers:
            return ("ta sortie ne contient aucun nombre : vérifie que tu "
                    "affiches bien le résultat, et que c'est le bon exercice")
        if len(numbers) < len(expected):
            # DÉDUCTION SÛRE, pas une heuristique : une sous-suite de M valeurs
            # ne peut pas tenir dans moins de M nombres. Quand un exercice en
            # demande trois et que le programme en affiche deux, c'est presque
            # toujours un calcul juste et un printf incomplet -- le dire évite
            # de chercher une erreur de formule qui n'existe pas.
            #
            # Le NOMBRE de valeurs attendues n'est pas un secret : il est dans
            # l'énoncé. Leurs valeurs, elles, ne sortent toujours pas d'ici.
            return ("ta sortie ne contient que %d nombre%s, or ce cas en attend "
                    "%d : vérifie que tu affiches TOUTES les valeurs demandées "
                    "par l'énoncé" % (len(numbers),
                                      "" if len(numbers) == 1 else "s",
                                      len(expected)))
        return "la sortie ne contient pas les valeurs attendues, dans l'ordre"
    return ""


def split_runs(output, nonce):
    """Decoupe la sortie du bac a sable en {nom du cas: (texte, code de sortie)}.

    Le séparateur est un nonce tiré par job, invisible de l'étudiant : sans ça,
    un programme qui imprime le marqueur se fabriquerait des cas réussis.
    """
    runs, name, buf = {}, None, []
    for line in output.splitlines():
        if line.startswith(nonce + " BEGIN "):
            name, buf = line[len(nonce) + 7:].strip(), []
        elif line.startswith(nonce + " END ") and name is not None:
            parts = line[len(nonce) + 5:].split()
            code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            runs[name] = ("\n".join(buf), code)
            name = None
        elif name is not None:
            buf.append(line)
    return runs


def verdict_io(rc, output, cases, nonce, tol):
    # Compilation (10/11/12) et plafond du conteneur entier (124/137) : mêmes
    # codes que le mode unity, et un seul message. Le 137 ne peut venir que du
    # chronomètre EXTERNE -- build-io.sh sort toujours 0 après sa boucle, et le
    # dépassement d'un cas isolé se lit dans son marqueur de fin, pas ici.
    if rc in (10, 11, 12, 124, 137):
        return verdict(rc, output)
    runs = split_runs(output, nonce)
    failed = []
    for number, case in enumerate(cases, 1):
        name = "%02d" % number
        if name not in runs:
            failed.append({"case": number, "stdin": case.get("stdin", ""),
                           "stdout": "", "reason": "le programme n'a pas terminé"})
            continue
        text, code = runs[name]
        if code in (124, 137):
            reason = ("le programme a été interrompu : boucle infinie, ou il "
                      "attend plus de valeurs qu'il n'en reçoit")
        elif code != 0:
            reason = "le programme s'est terminé anormalement (code %d)" % code
        else:
            reason = check_case(case, text, tol)
        if reason:
            failed.append({
                "case": number,
                # Les ENTRÉES sont montrées (l'étudiant a la formule, elles lui
                # servent à déboguer), la valeur ATTENDUE ne l'est jamais : elle
                # inviterait à écrire un printf de constantes.
                "stdin": case.get("stdin", ""),
                "stdout": text[:MAX_CASE_OUTPUT],
                "reason": reason,
            })
    return {
        "status": "ok",
        "kind": "io",
        "total": len(cases),
        "passed": len(cases) - len(failed),
        "cases": failed,
    }


# --------------------------------------------------------------------------
# Bac a sable
# --------------------------------------------------------------------------

def forbidden_includes(code, allowed):
    """Les #include de la soumission qui ne sont pas dans la liste blanche.

    `allowed` à None (pas de fichier allowed_includes.txt pour ce TP) désactive
    la vérification.

    ponytail: une regex sur le texte brut. Elle voit un #include dans un
    commentaire ou une chaîne, et ne voit pas un #include produit par macro.
    Les deux sont hors de portée d'un étudiant de première session, et un faux
    positif coûte un message d'erreur clair, pas une mauvaise note.
    """
    if allowed is None:
        return []
    return sorted({h for h in INCLUDE_RE.findall(code) if h not in allowed})


def read_allowed(tp_dir):
    path = os.path.join(tp_dir, "allowed_includes.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return None


def docker_argv(job_dir, tp_dir, name, mode, nonce=""):
    """La ligne de commande du bac à sable.

    Chaque option ferme une porte, et aucune n'est décorative :
      --network=none      rien à exfiltrer, rien à scanner, pas de relais de spam
      --pids-limit        la fork bomb est LE classique du TP de C
      --read-only + tmpfs le conteneur ne survit à rien, y compris à lui-même
      --cap-drop=ALL      aucune capability, même pas celles par défaut
      --user 65534        jamais root, même à l'intérieur
      --rm                un conteneur = un job = jetable, jamais réutilisé
      --runtime=runsc     le code natif tape sur un noyau réimplémenté en
                          espace utilisateur, pas sur celui du Dell

    EN MODE io, LE RÉPERTOIRE DES TESTS N'EST PAS MONTÉ DU TOUT. Les entrées ont
    déjà été extraites dans le répertoire du job ; io.json, qui contient les
    valeurs attendues, n'entre jamais dans le conteneur.
    """
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--runtime", RUNTIME,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/work:rw,exec,size=32m,mode=0777",
        "--tmpfs", "/tmp:rw,size=16m",
        "--memory", MEMORY, "--memory-swap", MEMORY,
        "--pids-limit", PIDS,
        "--cpus", CPUS,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "--ulimit", "fsize=8388608",
        "--ulimit", "nofile=64",
        # LE RÉPERTOIRE, PAS UN FICHIER. Depuis le laboratoire 5 une soumission
        # est un module -- calendrier.h ET calendrier.c -- et `#include
        # "calendrier.h"` ne résout que si les deux sont côte à côte. Un montage
        # par fichier ne donnerait pas ça.
        "-v", job_dir + "/src:/in/src:ro",
    ]
    if mode == "io":
        argv += [
            "-e", "CTESTER_NONCE=" + nonce,
            "-v", job_dir + "/cases:/in/cases:ro",
            "-v", BUILD_IO + ":/in/build.sh:ro",
        ]
    else:
        argv += [
            "-v", tp_dir + ":/in/tests:ro",
            "-v", os.path.join(TESTS, "unity") + ":/in/unity:ro",
            "-v", BUILD_UNITY + ":/in/build.sh:ro",
        ]
    return argv + [IMAGE, "bash", "/in/build.sh"]


def parse_unity(out):
    """Extrait le verdict de la sortie Unity. None si elle n'a pas de résumé.

    CETTE ENTRÉE N'EST PAS FIABLE. Le code étudiant tourne dans le même
    processus que les tests et peut écrire ce qu'il veut sur stdout, y compris
    imiter Unity. On ne renvoie donc que ce que les expressions rationnelles
    ci-dessus acceptent : des entiers, et des noms de test réduits à
    [A-Za-z0-9_] -- jamais le champ MESSAGE d'une ligne FAIL, qui contient la
    valeur attendue par le test et donc le test lui-même.

    ponytail: un `printf` bien placé peut fabriquer un faux « 0 Failures ».
    C'est inhérent au fait de lier le code étudiant aux tests, ce service est du
    feedback et pas de la notation, et le README le dit. Ne pas essayer de
    durcir ça ici.
    """
    match = None
    for match in SUMMARY_RE.finditer(out):
        pass  # le DERNIER résumé : celui qu'Unity écrit en sortant
    if match is None:
        return None
    total, failures, ignored = (int(g) for g in match.groups())
    names = FAIL_RE.findall(out)[:MAX_FAILED_NAMES]
    return {
        "total": total,
        "passed": max(total - failures - ignored, 0),
        "ignored": ignored,
        "failed": names,
    }


def verdict(rc, out):
    """Traduit un code de sortie de build.sh en réponse pour l'étudiant."""
    if rc == 10:
        return {
            "status": "compile_error",
            "message": "Ton fichier ne compile pas.",
            "gcc": out[:MAX_GCC_CHARS],
        }
    if rc == 11:
        # Volontairement vague : le détail citerait les tests. Les deux causes
        # de loin les plus fréquentes sont nommées, ce qui suffit à débloquer
        # sans rien révéler des cas de test.
        return {
            "status": "link_error",
            "message": (
                "Ton code compile, mais l'édition de liens avec les tests a "
                "échoué. Vérifie que les fonctions demandées ont exactement le "
                "nom et la signature de l'énoncé, et que tu ne définis pas de "
                "fonction main()."
            ),
        }
    if rc == 12:
        return {
            "status": "compile_timeout",
            "message": "La compilation a été trop longue et a été abandonnée.",
        }
    if rc in (124, 137):
        return {
            "status": "timeout",
            "message": (
                "Le programme a été interrompu : boucle infinie, attente d'une "
                "entrée, ou trop de processus créés."
            ),
        }
    parsed = parse_unity(out)
    if parsed is None:
        return {
            "status": "error",
            "message": (
                "Les tests se sont arrêtés avant la fin (plantage probable : "
                "segfault, débordement, pointeur invalide)."
            ),
        }
    parsed["status"] = "ok"
    parsed["kind"] = "unity"
    return parsed


def sandbox(job_dir, tp_dir, mode, nonce=""):
    """Lance le conteneur et rend (code de sortie, sortie standard)."""
    name = "ctester-" + os.path.basename(job_dir)[:16]
    try:
        done = subprocess.run(
            docker_argv(job_dir, tp_dir, name, mode, nonce),
            capture_output=True, text=True, errors="replace",
            timeout=JOB_TIMEOUT, check=False,
        )
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired:
        # `docker run --rm` ne suffit pas : tuer le CLIENT docker laisse le
        # conteneur tourner. Sans ce rm -f, un job pathologique garde un coeur
        # du Dell jusqu'au prochain redémarrage du démon.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       check=False)
        return 137, ""


# --------------------------------------------------------------------------
# Traitement d'un job
# --------------------------------------------------------------------------

def run_job(job_dir):
    with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
        tp = str(json.load(fh).get("tp", ""))
    # REVALIDÉ ICI, même si le web l'a déjà fait. Ce processus est root et
    # compose un chemin à partir de cette valeur : il ne fait confiance à
    # personne, y compris à notre propre conteneur web.
    tp_dir = tp_path(tp) if TP_RE.match(tp) else None
    if tp_dir is None:
        return {"status": "error", "message": "TP inconnu."}
    mode = detect_mode(tp_dir)
    if mode is None:
        return {"status": "error", "message": "Ce TP n'a pas de tests publiés."}

    if mode == "quiz":
        with open(os.path.join(job_dir, "answers.json"), encoding="utf-8") as fh:
            answers = json.load(fh)
        return grade_quiz(load_config(tp_dir, "quiz.json"), answers)

    conf = load_config(tp_dir, config_name(mode))

    # Les fichiers sont écrits ICI, sous les noms DÉCLARÉS par la configuration
    # des tests -- jamais sous ceux que la soumission propose. Le web a déjà
    # refusé les autres, mais ce processus est root et ne délègue pas cette
    # vérification : ce qui n'est pas déclaré n'est pas écrit.
    with open(os.path.join(job_dir, "files.json"), encoding="utf-8") as fh:
        sent = json.load(fh)
    src_dir = os.path.join(job_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    code = ""
    for declared in declared_files(conf):
        contenu = str(sent.get(declared["name"], ""))
        code += contenu + "\n"
        with open(os.path.join(src_dir, declared["name"]), "w",
                  encoding="utf-8") as fh:
            fh.write(contenu)

    # Un module qui inclut son propre en-tête n'est pas une dépendance interdite :
    # `#include "calendrier.h"` est précisément ce que l'énoncé demande. Les
    # fichiers déclarés s'ajoutent donc d'office à la liste blanche.
    allowed = read_allowed(tp_dir)
    if allowed is not None:
        allowed = allowed | {f["name"] for f in declared_files(conf)}

    bad = forbidden_includes(code, allowed)
    if bad:
        # Rejeté sans dépenser un conteneur.
        return {
            "status": "forbidden_include",
            "message": (
                "En-têtes non autorisés pour ce TP : "
                + ", ".join(bad)
                + ". Utilise seulement ce qui a été vu en cours."
            ),
        }

    if mode == "io":
        cases = conf.get("cases", [])
        tol = float(conf.get("tolerance", DEFAULT_TOLERANCE))
        case_dir = os.path.join(job_dir, "cases")
        os.makedirs(case_dir, exist_ok=True)
        for number, case in enumerate(cases, 1):
            with open(os.path.join(case_dir, "%02d.in" % number), "w",
                      encoding="utf-8") as fh:
                fh.write(case.get("stdin", ""))
        nonce = uuid.uuid4().hex
        rc, out = sandbox(job_dir, tp_dir, mode, nonce)
        return verdict_io(rc, out, cases, nonce, tol)

    rc, out = sandbox(job_dir, tp_dir, mode)
    return verdict(rc, out)


def write_result(job_dir, payload):
    payload["state"] = "done"
    write_json(os.path.join(job_dir, "result.json"), payload)


def claim(job_dir):
    """Réserve un job. mkdir échoue si le répertoire existe, et c'est atomique.

    ponytail: c'est tout le verrou dont N workers sur UN hôte ont besoin. Un
    vrai verrou distribué le jour où il y a un deuxième hôte, ce qui n'arrivera
    probablement jamais.
    """
    try:
        os.mkdir(os.path.join(job_dir, ".lock"))
        return True
    except OSError:
        return False


def pending_jobs():
    jobs = []
    for entry in os.scandir(SPOOL):
        if not entry.is_dir():
            continue
        job = os.path.join(entry.path, "job.json")
        if not os.path.exists(job) or os.path.exists(
            os.path.join(entry.path, "result.json")
        ):
            continue
        try:
            jobs.append((os.stat(job).st_mtime, entry.path))
        except OSError:
            continue
    jobs.sort()  # FIFO : le rang affiché à l'étudiant doit être vrai
    return [path for _, path in jobs]


def sweep(now):
    """Efface les jobs vieux de SWEEP_AFTER, verrouillés ou non.

    Y compris ceux d'un worker tué en plein travail : le .lock disparaît avec le
    répertoire, sinon un redémarrage malheureux laisserait un job coincé pour
    toujours.
    """
    for entry in os.scandir(SPOOL):
        try:
            if entry.is_dir() and entry.stat().st_mtime < now - SWEEP_AFTER:
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            continue


def main():
    os.makedirs(SPOOL, exist_ok=True)
    try:
        published = publish_catalogue()
        print("ctester: %d TP publiés" % len(published), file=sys.stderr,
              flush=True)
    except (OSError, ValueError) as exc:
        # Un catalogue illisible ne doit pas empêcher les jobs déjà en file
        # d'être traités : le service dégrade en « menu vide », pas en panne.
        print("ctester: catalogue: %s" % exc, file=sys.stderr, flush=True)
    while True:
        worked = False
        for job_dir in pending_jobs():
            if not claim(job_dir):
                continue
            worked = True
            try:
                write_result(job_dir, run_job(job_dir))
            except Exception as exc:  # noqa: BLE001 -- un job ne tue pas le worker
                print("ctester: %s: %s" % (job_dir, exc), file=sys.stderr,
                      flush=True)
                write_result(job_dir, {
                    "status": "error",
                    "message": "Erreur interne du juge. Réessaie.",
                })
        sweep(time.time())
        if not worked:
            # ponytail: sondage à 0,5 s. Une unité systemd .path le jour où
            # cette latence se voit, ce qui demanderait des jobs plus courts que
            # la compilation elle-même.
            time.sleep(0.5)


if __name__ == "__main__":
    main()
