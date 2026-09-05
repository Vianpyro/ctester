#!/usr/bin/env python3
"""ctester -- le worker de l'hôte, lancé depuis le clone git.

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

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid

import content_catalogue

SPOOL = os.environ.get("CTESTER_SPOOL", "/opt/ctester/spool")

# LE CONTENU PRIVÉ ET SES RELEASES. Depuis la phase 8 il n'y a plus
# d'arborescence historique `tpN/exN` : le worker résout les exercices par
# `content_catalogue.load_exercise()` et publie une release, toujours. Le
# rollback est un pointeur `current.json` à réécrire, pas une variable à vider.
CONTENT = os.environ.get("CTESTER_CONTENT", "/opt/ctester/content")
PUBLISHED = os.environ.get("CTESTER_PUBLISHED", "/opt/ctester/published")
BUILD_UNITY = os.environ.get("CTESTER_BUILD_UNITY", "/opt/ctester/build-unity.sh")
BUILD_IO = os.environ.get("CTESTER_BUILD_IO", "/opt/ctester/build-io.sh")
IMAGE = os.environ.get("CTESTER_IMAGE", "gcc:14-bookworm")
RUNTIME = os.environ.get("CTESTER_RUNTIME", "runsc")
JOB_TIMEOUT = int(os.environ.get("CTESTER_JOB_TIMEOUT", "60"))
MEMORY = os.environ.get("CTESTER_MEMORY", "256m")
PIDS = os.environ.get("CTESTER_PIDS", "64")
CPUS = os.environ.get("CTESTER_CPUS", "1")
SWEEP_AFTER = int(os.environ.get("CTESTER_SWEEP_AFTER", "600"))

# UN VERROU ABANDONNÉ N'EST PAS UN VERROU. `claim()` pose un `.lock` qu'un worker
# tué -- déploiement, OOM, reboot -- n'emporte pas avec lui : le job reste listé
# par pending_jobs(), refusé par claim() pour toujours, et l'étudiant regarde
# « en file d'attente » jusqu'à ce que sweep() efface le répertoire SWEEP_AFTER
# plus tard. Dix minutes de silence pour une soumission qui n'a jamais échoué.
#
# LE SEUIL SE DÉDUIT, IL NE SE CHOISIT PAS, et c'est ce qui rend la reprise sûre
# à N workers : un worker VIVANT ne peut pas tenir un verrou plus longtemps que
# le job qu'il exécute, or `sandbox()` est plafonné à JOB_TIMEOUT par
# subprocess. Trois fois cette borne couvre le reste de run_job() -- écriture
# des cas, extraction des avertissements -- avec une marge que rien ne rend
# serrée. Un verrou plus vieux que ça n'appartient à personne.
#
# ET IL RESTE BIEN EN DEÇÀ DE SWEEP_AFTER : l'ordre est tout, un job doit
# pouvoir être repris AVANT d'être balayé, sinon la reprise n'arrive jamais.
LOCK_STALE = int(os.environ.get("CTESTER_LOCK_STALE", str(3 * JOB_TIMEOUT)))

# UNE reprise, pas une infinité. Un job qui tue son worker à tous les coups --
# OOM, bogue, panne matérielle -- serait repris en boucle par chaque worker à
# son tour, qui mourrait dessus à son tour : toute la file s'arrêterait sur une
# seule soumission. Au-delà, on écrit un verdict d'erreur, que l'étudiant voit
# au sondage suivant et peut relancer.
LOCK_RETRIES = int(os.environ.get("CTESTER_LOCK_RETRIES", "1"))

# APERÇU AVANT OUVERTURE, pour la machine de l'enseignant. Mettre CTESTER_APERCU
# à autre chose que "" ou "0" fait tomber le filtre `available_from` : le
# catalogue publié ET tp_path voient alors tout, y compris ce qui ouvre en
# novembre. C'est la seule façon d'éprouver un exercice de bout en bout -- coller son
# corrigé dans la vraie page et lire le vrai verdict -- avant que les étudiants
# n'y aient accès.
#
# LES DEUX TOMBENT ENSEMBLE, ET C'EST LE POINT : le drapeau devient une DATE
# (l'an 9999) que `access()` lit à la publication comme `tp_path` la lit avant
# d'exécuter. Ouvrir le menu sans ouvrir tp_path donnerait un exercice qu'on
# peut choisir et pas soumettre, ce qui ressemble à une panne.
#
# CE N'EST PAS UN RÉGLAGE DE PRODUCTION. Le déploiement ne le définit pas, et
# publish_catalogue() le dit dans le journal quand il est actif : un worker qui
# l'aurait hérité par accident ouvrirait le semestre entier d'un coup.
APERCU = os.environ.get("CTESTER_APERCU", "") not in ("", "0")

# Les réglages de compilation, RELAYÉS et non interprétés : leur sens est dans
# build-unity.sh / build-io.sh, qui portent aussi leurs valeurs par défaut. Ce
# qui est passé ici prime, et `docker run` ne propage rien tout seul.
#
# ABSENT VEUT DIRE « défaut du script ». Une variable non définie ici n'est pas
# transmise, plutôt que transmise vide -- vider CTESTER_SANITIZERS est le repli
# explicite qui désactive les sanitizers, et confondre les deux les couperait
# par accident dès qu'un worker démarrerait sans son unité systemd.
SANDBOX_ENV = {
    k: os.environ[k]
    for k in ("CTESTER_C_STD", "CTESTER_SANITIZERS", "CTESTER_ASAN_OPTIONS",
              "CTESTER_COMPILE_TIMEOUT", "CTESTER_RUN_TIMEOUT")
    if k in os.environ
}

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

# Le code de sortie qu'ASan reçoit par ctester_asan_options. Choisi hors de la
# plage d'Unity, qui retourne SON NOMBRE D'ÉCHECS : un abandon d'ASan sortirait
# sinon en 1, indistinguable de « un test raté ». Garder les deux en accord.
ASAN_EXIT = 86

# Plus large que MAX_CASE_OUTPUT : un rapport d'ASan tient en une vingtaine
# de lignes, et sa PREMIÈRE ligne -- celle qui nomme le fichier et la ligne
# -- serait perdue si on coupait à la taille d'une sortie de programme.
MAX_STDERR = 2000
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


def declared_files(conf, tp_dir=None):
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
    if not files and tp_dir:
        # CONTENU V2 : les gabarits sont PUBLICS, donc rangés à côté de la
        # configuration de correction (`public/files.json`) et pas dedans. Le
        # worker les relit ici -- jamais depuis le réseau, où un nom choisi par
        # l'étudiant deviendrait un chemin.
        try:
            with open(os.path.join(tp_dir, os.pardir, "public", "files.json"),
                      encoding="utf-8") as fh:
                files = json.load(fh).get("files")
        except (OSError, ValueError, AttributeError):
            files = None
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


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def publish_catalogue():
    """Projette le contenu privé en une release, et bascule le pointeur.

    Publié par LE WORKER et pas par Ansible : c'est lui qui a le droit de lire
    les tests, et surtout « le corrigé ne franchit jamais la frontière »
    devient une fonction Python qu'un test vérifie, au lieu d'une boucle Jinja
    que personne ne relit.

    Les N workers écrivent le même contenu au démarrage. La course est sans
    conséquence : une révision EST le hachage de son contenu, donc deux workers
    écrivent le même répertoire et le même pointeur.

    LÈVE PLUTÔT QUE DE PUBLIER À VIDE si les deux variables manquent. Depuis la
    phase 8 il n'y a plus d'arborescence historique à lire : un worker mal
    configuré doit s'arrêter en le disant, pas servir un catalogue vide.
    """
    if APERCU:
        print("ctester: APERÇU ACTIF -- les exercices pas encore ouverts sont publiés",
              file=sys.stderr, flush=True)
    if not (CONTENT and PUBLISHED):
        raise RuntimeError(
            "CTESTER_CONTENT et CTESTER_PUBLISHED sont requis pour publier")
    # Import LOCAL : publish_content lit `public_quiz` ici même, et un import
    # en tête de fichier fermerait le cycle.
    import publish_content
    model = content_catalogue.discover(CONTENT)
    # L'aperçu est une DATE, pas un second filtre : `access()` reste la seule
    # lecture d'une release, et se placer en l'an 9999 ouvre tout ce qui est
    # daté sans toucher à ce qui est archivé.
    maintenant = datetime.datetime(9999, 1, 1, tzinfo=datetime.timezone.utc) if APERCU else None
    publish_content.publish(model, PUBLISHED, now=maintenant)
    return list(model["exercises"].values())


def tp_path(exercise_id):
    """Le répertoire d'assessment d'un exercice. None s'il n'existe pas.

    LA SEULE FAÇON DE PASSER D'UN IDENTIFIANT À UN CHEMIN, et elle réapplique la
    release : le web l'a déjà fait, ce processus est root et ne fait confiance à
    personne, y compris à notre propre conteneur web.

    Le répertoire rendu est `exercises/<id>/assessment` : la même forme qu'un
    répertoire de TP historique -- configuration, `test_*.c` et
    `allowed_includes.txt` côte à côte -- donc `detect_mode`, `read_allowed`,
    `docker_argv` et le bac à sable n'ont jamais eu à changer.
    """
    entry = content_catalogue.load_exercise(CONTENT, exercise_id, tout=APERCU)
    return entry["path"] if entry else None


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
                # Sa propre réponse : avec 40 questions paginées, se rappeler ce
                # qu'on a tapé demande sinon un aller-retour de deux écrans.
                "given": str(given)[:64],
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
    # Intervalle plutôt que valeur : pour un programme qui tire au hasard, la
    # sortie n'a pas de valeur attendue, seulement des bornes. « au moins N
    # nombres dans [min, max] » et pas « tous », parce qu'une invite comme
    # « Lancer 100 fois » ajoute un 100 que la borne rejetterait sur un
    # programme parfaitement correct.
    borne = case.get("in_range")
    if borne:
        combien = int(case.get("count", 1))
        dedans = sum(1 for n in extract_numbers(output)
                     if borne[0] <= n <= borne[1])
        if dedans < combien:
            return ("ta sortie contient %d valeur%s entre %g et %g, il en faut "
                    "au moins %d" % (dedans, "" if dedans == 1 else "s",
                                     borne[0], borne[1], combien))

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
    runs, name, buf, err, dans_err = {}, None, [], [], False
    for line in output.splitlines():
        if line.startswith(nonce + " BEGIN "):
            name, buf, err, dans_err = (line[len(nonce) + 7:].strip(),
                                        [], [], False)
        elif line.startswith(nonce + " ERR ") and name is not None:
            dans_err = True
        elif line.startswith(nonce + " END ") and name is not None:
            parts = line[len(nonce) + 5:].split()
            code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            runs[name] = ("\n".join(buf).strip(), "\n".join(err).strip(), code)
            name, dans_err = None, False
        elif name is not None:
            (err if dans_err else buf).append(line)
    return runs


def avec_avertissements(resultat, avertissements):
    """Attache les avertissements du compilateur au verdict, s'il y en a.

    Attachés MÊME EN CAS DE RÉUSSITE : c'est là qu'ils sont les plus utiles, et
    c'est aussi le seul moment où l'étudiant a le temps de les lire. La page se
    charge de ne pas les faire passer pour un échec.

    Pas attachés à une erreur de compilation : la stderr complète est déjà dans
    le champ `gcc`, les répéter n'ajouterait rien.
    """
    if avertissements and resultat.get("status") != "compile_error":
        resultat["warnings"] = avertissements
    return resultat


def extraire_avertissements(output, nonce):
    """Sépare le bloc d'avertissements gcc du reste de la sortie.

    Rend (avertissements, reste). Le bloc est RETIRÉ du reste : les parseurs
    suivants lisent le résumé Unity et les cas avec des expressions
    rationnelles, et un avertissement contenant `:FAIL` ou un nombre les
    tromperait.
    """
    debut, fin = nonce + " WARN\n", nonce + " ENDWARN"
    i = output.find(debut)
    if i < 0:
        return "", output
    j = output.find(fin, i)
    if j < 0:
        return "", output
    texte = output[i + len(debut):j].strip()
    return texte[:MAX_GCC_CHARS], output[:i] + output[j + len(fin):]


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
        text, err, code = runs[name]
        if code in (124, 137):
            reason = ("le programme a été interrompu : boucle infinie, ou il "
                      "attend plus de valeurs qu'il n'en reçoit")
        elif code == ASAN_EXIT:
            # ICI le rapport EST montré, par la stderr du cas juste en dessous :
            # ce conteneur-là ne monte aucun test, il n'a rien à taire. ASan
            # nomme le fichier et la ligne de l'étudiant.
            reason = ("le programme a débordé de la mémoire qu'il a réservée "
                      "(voir le rapport ci-dessous : il nomme la ligne)")
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
                # LES NOMBRES QUE LE JUGE A VUS. L'appariement en sous-suite
                # était une boîte noire : un étudiant qui écrit « 1 234 » ou
                # « 3,5 » ne pouvait pas deviner comment sa ligne avait été
                # découpée. C'est sa sortie, relue à voix haute.
                "nombres": extract_numbers(text)[:20],
                "stderr": err[:MAX_STDERR],
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


def unity_dir():
    """Unity est PARTAGÉ par tous les exercices, donc hors de l'un d'eux."""
    return os.path.join(CONTENT, "shared", "unity")


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
    # Le nonce est passé DANS LES DEUX MODES : il séparait les cas en io, il
    # encadre aussi le bloc d'avertissements du compilateur, qui existe partout.
    argv += ["-e", "CTESTER_NONCE=" + nonce]
    # Les mêmes dans les deux modes : le dialecte, les sanitizers et les
    # chronomètres ne dépendent pas de la présence de secrets dans /in.
    for key, value in SANDBOX_ENV.items():
        argv += ["-e", key + "=" + value]
    if mode == "io":
        argv += [
            "-v", job_dir + "/cases:/in/cases:ro",
            "-v", BUILD_IO + ":/in/build.sh:ro",
        ]
    else:
        argv += [
            "-v", tp_dir + ":/in/tests:ro",
            "-v", unity_dir() + ":/in/unity:ro",
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
    if rc == ASAN_EXIT:
        # LE FAIT SANS LE RAPPORT. build-unity.sh a jeté la sortie d'ASan parce
        # que sa pile d'appels nomme la fonction de test appelante. Il reste
        # qu'un débordement mémoire est infiniment plus actionnable qu'un
        # « segfault » : on nomme la CLASSE d'erreur et les endroits où la
        # chercher, sans une ligne ni un nom qui vienne des tests.
        return {
            "status": "memory_error",
            "message": (
                "Ton code sort des limites de la mémoire qu'il a le droit "
                "d'utiliser : un indice hors des bornes d'un tableau, une "
                "chaîne sans son '\\0', ou un pointeur qui ne pointe plus sur "
                "rien. Revois tes conditions de boucle (< et non <=) et la "
                "taille que tu réserves."
            ),
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
        # gcc cite ses fichiers par leur chemin DANS le conteneur. L'étudiant
        # n'a jamais vu /in/src et n'a pas à le voir : il reconnaît son fichier
        # par son nom, « submission.c:9:13 ».
        return done.returncode, done.stdout.replace("/in/src/", "")
    except subprocess.TimeoutExpired:
        # `docker run --rm` ne suffit pas : tuer le CLIENT docker laisse le
        # conteneur tourner. Sans ce rm -f, un job pathologique garde un coeur
        # du Dell jusqu'au prochain redémarrage du démon.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       check=False)
        return 137, ""


# --------------------------------------------------------------------------
# Cache de verdicts -- LA FILE NE PAIE PAS DEUX FOIS LE MÊME CODE
# --------------------------------------------------------------------------
#
# Pendant un TP, beaucoup de jobs recompilent un code déjà jugé : le même
# étudiant qui resoumet, le gabarit non modifié, le copier-coller. Un verdict
# déjà calculé est rendu ici en quelques millisecondes, donc la file se vide au
# lieu de se remplir. Le job passe toujours par le spool -- `/submit`, les
# quotas et QUEUE_MAX ne changent pas, et le conteneur web ne gagne aucune
# surface.
#
# LE CACHE VIT DANS LE WORKER, ET C'EST STRUCTUREL. La révision publiée
# (`publish_content.revision()`) ne hache que la PROJECTION PUBLIQUE : corriger
# un `test_*.c` ou un `case` de io.json ne la change pas. Une clé fondée dessus
# servirait l'ancien verdict après une correction de test. Seul ce processus
# monte CTESTER_CONTENT et peut empreindre `assessment/` lui-même.
#
# LA NORMALISATION NE TOUCHE QUE LA CLÉ, jamais la valeur ni ce qui est
# compilé : le juge écrit toujours les octets exacts de l'étudiant dans `src/`.
# Un bogue de `normaliser_c()` ne peut donc produire qu'un mauvais hit de cache
# -- jamais une compilation faussée, jamais un code d'étudiant mutilé.
#
# CTESTER_CACHE_MAX=0 l'éteint sans redéployer : c'est le rollback.

CACHE_DIR = "cache"
CACHE_MAX = int(os.environ.get("CTESTER_CACHE_MAX", "5000"))

# CE QUI NE SE MET JAMAIS EN CACHE, parce que ce n'est pas une fonction du
# code. Les trois plafonds (JOB_TIMEOUT, COMPILE_TIMEOUT, RUN_TIMEOUT) sont du
# temps mural sous gVisor : un code limite passe ou échoue selon la charge du
# Dell. Geler un ÉCHEC de malchance enfermerait l'étudiant, qui ne pourrait
# plus jamais passer. `error` est une panne du juge, pas un verdict.
JAMAIS_EN_CACHE = frozenset(("timeout", "compile_timeout", "error"))


# UN LEXEUR C, PAS UN FORMATEUR ET PAS UN PARSEUR. clang-format ne retire pas
# les commentaires et garde les lignes vides : il ne peut pas rendre la même
# clé pour un code espacé autrement. Un AST demanderait un vrai parseur C sur
# une entrée hostile, et n'ajouterait au flux de jetons que l'insensibilité aux
# parenthèses redondantes -- deux étudiants indépendants diffèrent de toute
# façon par leurs identifiants.
#
# L'ORDRE DES ALTERNATIVES EST LA CORRECTION : chaîne et caractère AVANT le
# reste, sans quoi le `//` de `printf("http://x")` couperait la ligne en
# commentaire et deux programmes distincts pourraient partager une clé.
_LEX = re.compile(r"""
      (?P<bloc>/\*.*?\*/)
    | (?P<ligne>//(?:[^\n\\]|\\.)*)
    | (?P<chaine>"(?:[^"\\\n]|\\.)*")
    | (?P<car>'(?:[^'\\\n]|\\.)*')
    | (?P<mot>[A-Za-z_][A-Za-z0-9_]*|\.?[0-9](?:[A-Za-z0-9_.]|[eEpP][-+])*)
    | (?P<blanc>\s+)
    | (?P<autre>.)
""", re.S | re.X)

_CARACTERE_DE_MOT = re.compile(r"[A-Za-z0-9_]")


def normaliser_c(source):
    """Le code réduit à ses jetons : même clé quel que soit l'habillage.

    Commentaires retirés, indentation et lignes vides sans effet. Un espace
    n'est gardé que là où il SÉPARE deux jetons (`int x` ne doit pas devenir
    `intx`), et un commentaire compte comme un tel séparateur.

    LES DIRECTIVES GARDENT LEUR FIN DE LIGNE : sans elle, `#define A 1` et
    `#define B 2` fusionneraient en une seule ligne, et deux programmes
    distincts pourraient se retrouver sur la même clé.
    """
    out = []
    espace = False     # un blanc ou un commentaire attend d'être peut-être émis
    directive = False  # on est dans une ligne `#...`
    debut = True       # rien d'émis encore sur cette ligne source
    for m in _LEX.finditer(source):
        genre, texte = m.lastgroup, m.group()
        if genre in ("bloc", "ligne", "blanc"):
            if genre == "blanc" and "\n" in texte and directive:
                out.append("\n")
                espace, directive = False, False
            else:
                espace = True
            if "\n" in texte:
                debut = True
            continue
        if (espace and out
                and _CARACTERE_DE_MOT.match(out[-1][-1])
                and _CARACTERE_DE_MOT.match(texte[0])):
            out.append(" ")
        if texte == "#" and debut:
            directive = True
        out.append(texte)
        espace, debut = False, False
    return "".join(out)


def _hacher_octets(condensat, blob):
    """Longueur PUIS contenu : sans le préfixe, `ab` + `c` et `a` + `bc`
    donneraient le même condensat, et deux jeux de fichiers distincts
    pourraient partager une clé."""
    condensat.update(str(len(blob)).encode("ascii") + b":")
    condensat.update(blob)


def _hacher_fichier(condensat, chemin):
    try:
        with open(chemin, "rb") as fh:
            _hacher_octets(condensat, fh.read())
    except OSError:
        condensat.update(b"absent:")


def _hacher_arbre(condensat, racine):
    for dossier, sous, fichiers in os.walk(racine):
        sous.sort()  # l'ordre de os.walk n'est pas garanti, la clé doit l'être
        for nom in sorted(fichiers):
            chemin = os.path.join(dossier, nom)
            rel = os.path.relpath(chemin, racine).replace(os.sep, "/")
            _hacher_octets(condensat, rel.encode("utf-8"))
            _hacher_fichier(condensat, chemin)


def empreinte_juge(exercise_id, tp_dir, mode):
    """Tout ce qui décide du verdict SAUF le code de l'étudiant.

    C'est ce qui rend l'invalidation automatique : un `test_*.c` corrigé par le
    tick de cinq minutes change l'empreinte, donc la clé, donc le verdict est
    recalculé sans que personne n'ait à vider quoi que ce soit.

    `runner.py` s'y hache LUI-MÊME : `verdict_io`, `parse_unity` et la
    tolérance par défaut vivent ici, et une version de cache à incrémenter à la
    main serait oubliée exactement le jour où elle compte.
    """
    condensat = hashlib.sha256()
    _hacher_octets(condensat, ("%s|%s" % (exercise_id, mode)).encode("utf-8"))
    _hacher_arbre(condensat, tp_dir)
    if mode == "unity":
        # Unity est PARTAGÉ : monter sa version change tous les verdicts.
        _hacher_arbre(condensat, unity_dir())
    # Les gabarits sont publics donc HORS de assessment/, et ils décident des
    # noms écrits sur disque (`declared_files`).
    _hacher_fichier(condensat,
                    os.path.join(tp_dir, os.pardir, "public", "files.json"))
    _hacher_fichier(condensat, BUILD_UNITY if mode == "unity" else BUILD_IO)
    _hacher_fichier(condensat, os.path.abspath(__file__))
    _hacher_octets(condensat, IMAGE.encode("utf-8"))
    _hacher_octets(condensat,
                   json.dumps(SANDBOX_ENV, sort_keys=True).encode("utf-8"))
    return condensat


def signature(exercise_id, tp_dir, mode, conf, sent):
    """La clé de cache : l'empreinte du juge, plus le code normalisé."""
    condensat = empreinte_juge(exercise_id, tp_dir, mode)
    for declared in declared_files(conf, tp_dir):
        nom = declared["name"]
        _hacher_octets(condensat, nom.encode("utf-8"))
        _hacher_octets(condensat,
                       normaliser_c(str(sent.get(nom, ""))).encode("utf-8"))
    return condensat.hexdigest()


def cache_lire(sig):
    if CACHE_MAX <= 0:
        return None
    try:
        with open(os.path.join(SPOOL, CACHE_DIR, sig + ".json"),
                  encoding="utf-8") as fh:
            verdict = json.load(fh)
    except (OSError, ValueError):
        return None
    return verdict if isinstance(verdict, dict) else None


def cache_ecrire(sig, verdict):
    """ponytail: purge complète quand plein, pas de LRU -- même raccourci et
    même raison que le cache de jetons de `app/security.py`. C'est un
    économiseur de CPU, pas un magasin : tout reperdre coûte une compilation
    par soumission distincte, ce que le service faisait avant que ce cache
    n'existe. Une éviction par ancienneté le jour où le taux de succès chute
    après chaque purge, ce qui demande plus de CACHE_MAX soumissions
    DISTINCTES entre deux corrections de test."""
    if CACHE_MAX <= 0:
        return
    dossier = os.path.join(SPOOL, CACHE_DIR)
    try:
        os.makedirs(dossier, exist_ok=True)
        if len(os.listdir(dossier)) >= CACHE_MAX:
            shutil.rmtree(dossier, ignore_errors=True)
            os.makedirs(dossier, exist_ok=True)
        write_json(os.path.join(dossier, sig + ".json"), verdict)
    except OSError:
        pass  # un cache qui n'écrit pas n'est pas une panne de juge


def cachable(conf, verdict):
    """`"cache": false` dans io.json / unity.json pour un exercice dont le
    PROGRAMME est aléatoire (tp4-ex1 tire des dés, tp4-ex2 est un test
    statistique sur un million de lancers) : sans ça, un échec de malchance
    serait gelé et l'étudiant ne pourrait plus jamais passer."""
    return (bool(conf.get("cache", True))
            and isinstance(verdict, dict)
            and verdict.get("status") not in JAMAIS_EN_CACHE)


# --------------------------------------------------------------------------
# Traitement d'un job
# --------------------------------------------------------------------------

def job_exercice(job_dir):
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("exercise_id", ""))
    except (OSError, ValueError):
        return ""


def run_job(job_dir):
    """Le verdict d'un job. Sert le cache quand il l'a, juge sinon.

    LE QUIZ N'EST PAS MIS EN CACHE : il ne dépense aucun conteneur, `grade_quiz`
    rend en quelques millisecondes, et une clé de plus n'économiserait rien.
    """
    exercise_id = job_exercice(job_dir)
    # REVALIDÉ ICI, même si le web l'a déjà fait. Ce processus est root et
    # compose un chemin à partir de cette valeur : il ne fait confiance à
    # personne, y compris à notre propre conteneur web. `load_exercise` borne
    # l'identifiant (EXERCISE_RE) avant de le joindre, et réapplique la release.
    tp_dir = tp_path(exercise_id)
    if tp_dir is None:
        return {"status": "error", "message": "Exercice inconnu."}
    mode = detect_mode(tp_dir)
    if mode is None:
        return {"status": "error", "message": "Ce TP n'a pas de tests publiés."}

    if mode == "quiz":
        with open(os.path.join(job_dir, "answers.json"), encoding="utf-8") as fh:
            answers = json.load(fh)
        return grade_quiz(load_config(tp_dir, "quiz.json"), answers)

    conf = load_config(tp_dir, config_name(mode))
    with open(os.path.join(job_dir, "files.json"), encoding="utf-8") as fh:
        sent = json.load(fh)

    sig = signature(exercise_id, tp_dir, mode, conf, sent)
    connu = cache_lire(sig)
    if connu is not None:
        # LE TAUX DE SUCCÈS SE LIT DANS journalctl, qui est déjà l'outil du
        # runbook. Pas de compteur, pas de table : `grep -c 'cache '` après une
        # séance dit si ce cache valait la peine d'exister.
        print("ctester: cache %s %s" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
        return connu

    resultat = _juger(job_dir, tp_dir, mode, conf, sent)
    if cachable(conf, resultat):
        cache_ecrire(sig, resultat)
    return resultat


def _juger(job_dir, tp_dir, mode, conf, sent):
    """La compilation et l'exécution elles-mêmes, sans cache ni catalogue."""
    # Les fichiers sont écrits ICI, sous les noms DÉCLARÉS par la configuration
    # des tests -- jamais sous ceux que la soumission propose. Le web a déjà
    # refusé les autres, mais ce processus est root et ne délègue pas cette
    # vérification : ce qui n'est pas déclaré n'est pas écrit.
    #
    # ET CE SONT LES OCTETS EXACTS DE L'ÉTUDIANT : `normaliser_c()` ne sert
    # qu'à fabriquer une clé de cache, jamais ce qui est compilé, sans quoi un
    # bogue de lexeur deviendrait une erreur de compilation fantôme.
    src_dir = os.path.join(job_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    code = ""
    for declared in declared_files(conf, tp_dir):
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
        allowed = allowed | {f["name"] for f in declared_files(conf, tp_dir)}

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
        avertissements, out = extraire_avertissements(out, nonce)
        resultat = verdict_io(rc, out, cases, nonce, tol)
        return avec_avertissements(resultat, avertissements)

    nonce = uuid.uuid4().hex
    rc, out = sandbox(job_dir, tp_dir, mode, nonce)
    avertissements, out = extraire_avertissements(out, nonce)
    return avec_avertissements(verdict(rc, out), avertissements)


def write_result(job_dir, payload):
    payload["state"] = "done"
    write_json(os.path.join(job_dir, "result.json"), payload)


# LES DURÉES SONT DANS LE SPOOL, PAS DANS POSTGRES. Le worker est root sur
# l'hôte et n'a pas de connexion à la base ; le spool est déjà le seul canal
# entre lui et l'API, et une statistique d'affichage n'est pas un fait à
# conserver -- la perdre au balayage ne coûte que la première estimation.
DUREES = "durees.json"

# Chaque exercice a son coût : un quiz est instantané, un TP de dix cas
# d'entrée/sortie paie dix exécutions. La moyenne est donc PAR EXERCICE, et
# glissante sur les DUREE_FENETRE derniers jobs -- un cas de test ajouté en
# cours de session doit se voir dans l'estimation, pas être noyé sous l'histoire.
DUREE_FENETRE = 20
# Un job rejeté avant le conteneur (en-tête interdit, exercice inconnu) coûte
# quelques millisecondes et n'est pas représentatif : l'inclure tirerait la
# moyenne vers zéro précisément parce que les étudiants se trompent souvent.
DUREE_MIN = 0.5


def lire_durees():
    try:
        with open(os.path.join(SPOOL, DUREES), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enregistrer_duree(exercise_id, secondes):
    """Moyenne glissante par exercice : {id: [moyenne, n]}.

    ponytail: lecture-modification-écriture sans verrou. `write_json` renomme,
    donc le fichier n'est jamais à moitié écrit ; deux workers qui finissent à
    la même milliseconde perdent un échantillon sur les vingt de la fenêtre.
    Un verrou pour ça coûterait plus cher que l'erreur qu'il évite.
    """
    if not exercise_id or secondes < DUREE_MIN:
        return
    durees = lire_durees()
    ancien = durees.get(exercise_id)
    if isinstance(ancien, list) and len(ancien) == 2:
        moyenne, n = float(ancien[0]), min(int(ancien[1]), DUREE_FENETRE)
    else:
        moyenne, n = 0.0, 0
    n += 1
    durees[exercise_id] = [round(moyenne + (secondes - moyenne) / n, 2), n]
    try:
        write_json(os.path.join(SPOOL, DUREES), durees)
    except OSError:
        pass  # une estimation perdue n'est pas une panne de juge


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


def reprises(job_dir):
    """Combien de fois ce job a déjà été repris à un worker mort."""
    try:
        with open(os.path.join(job_dir, "reprises.json"), encoding="utf-8") as fh:
            return int(json.load(fh).get("n", 0))
    except (OSError, ValueError, TypeError):
        return 0


def reclaim(job_dir, now):
    """Libère le verrou d'un worker mort. True si le job peut être reproposé.

    LA COURSE ENTRE DEUX WORKERS EST SANS CONSÉQUENCE, et c'est ce qui permet de
    ne rien ajouter de plus fort : les deux peuvent juger le verrou périmé, l'un
    des deux `rmdir` échoue, et c'est le `mkdir` de claim() -- atomique -- qui
    départage ensuite, exactement comme pour un job neuf.

    Un verrou encore frais appartient à un worker vivant : on ne touche à rien.
    """
    lock = os.path.join(job_dir, ".lock")
    try:
        if os.stat(lock).st_mtime > now - LOCK_STALE:
            return False
    except OSError:
        # Le verrou vient de disparaître -- sweep(), ou un autre worker. Le
        # prochain tour de boucle verra l'état réel.
        return False

    essai = reprises(job_dir) + 1
    if essai > LOCK_RETRIES:
        # LE VERROU RESTE EN PLACE : plus personne ne reprend ce job, et le
        # verdict ci-dessous est ce que l'étudiant lit au sondage suivant, au
        # lieu d'attendre le balayage.
        print("ctester: %s: abandonné après %d reprise(s)" % (job_dir, essai - 1),
              file=sys.stderr, flush=True)
        write_result(job_dir, {
            "status": "error",
            "message": "Le juge a été interrompu pendant ce test. Relance-le.",
        })
        return False

    # AVANT le rmdir : si le compteur s'écrivait après, un worker tué entre les
    # deux rendrait le job repris sans que ça se voie, et la boucle de reprise
    # que LOCK_RETRIES existe pour empêcher redeviendrait possible.
    write_json(os.path.join(job_dir, "reprises.json"), {"n": essai})
    try:
        os.rmdir(lock)
    except OSError:
        return False
    print("ctester: %s: verrou périmé repris (essai %d)" % (job_dir, essai),
          file=sys.stderr, flush=True)
    return True


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

    LE FILET DE SÉCURITÉ, PLUS LE PREMIER RECOURS. Un job dont le worker est
    mort est repris par reclaim() bien avant cette échéance (LOCK_STALE) ; ce
    qui arrive jusqu'ici est ce que personne n'a pu reprendre -- un job abandonné
    après LOCK_RETRIES, ou un répertoire que le web a écrit à moitié.
    """
    for entry in os.scandir(SPOOL):
        # LE CACHE N'EST PAS UN JOB. Sans cette ligne, dix minutes de calme --
        # une pause, une soirée -- le videraient, et il ne servirait plus que
        # pendant une rafale au lieu de tenir toute une séance.
        if entry.name == CACHE_DIR:
            continue
        try:
            if entry.is_dir() and entry.stat().st_mtime < now - SWEEP_AFTER:
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            continue


def main():
    os.makedirs(SPOOL, exist_ok=True)
    try:
        published = publish_catalogue()
        print("ctester: %d exercices publiés" % len(published), file=sys.stderr,
              flush=True)
    except (OSError, ValueError) as exc:
        # Un catalogue illisible ne doit pas empêcher les jobs déjà en file
        # d'être traités : le service dégrade en « menu vide », pas en panne.
        print("ctester: catalogue: %s" % exc, file=sys.stderr, flush=True)
    jour = datetime.date.today()
    while True:
        if datetime.date.today() != jour:
            # Le catalogue est publié UNE FOIS au démarrage : sans ça, un exercice
            # dont la date arrive cette nuit n'apparaîtrait qu'au prochain
            # redémarrage du worker. Republier au changement de jour est la seule
            # échéance qui existe -- pas de planificateur, pas de minuterie.
            jour = datetime.date.today()
            try:
                publish_catalogue()
            except (OSError, ValueError) as exc:
                print("ctester: catalogue: %s" % exc, file=sys.stderr, flush=True)
        worked = False
        for job_dir in pending_jobs():
            if not claim(job_dir):
                # Verrou tenu. Par un worker vivant -- on passe -- ou par un
                # worker mort, et reclaim() tranche sur le seul critère qui ne
                # ment pas ici : l'âge du verrou.
                if not (reclaim(job_dir, time.time()) and claim(job_dir)):
                    continue
            worked = True
            debut = time.time()
            try:
                write_result(job_dir, run_job(job_dir))
                enregistrer_duree(job_exercice(job_dir), time.time() - debut)
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
