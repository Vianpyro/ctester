#!/usr/bin/env python3
"""ctester -- the host worker, launched from the git clone.

Runs as root on the Dell, in N instances (ctester-runner@1..N), and does the
only things the web container is not allowed to do: launch Docker, and read
the tests. It READS the spool, it never executes it -- nothing coming from
the web tier is ever passed to a shell, and `subprocess` receives a list of
arguments, never a string.

In Python and not bash for this precise reason: building a docker command
line around an exercise name coming from the network is exactly the kind of
thing one gets right in shell only half the time. Here there is no shell to
escape, and parsing verdicts becomes testable (test_ctester.py).

THREE MODES, DEDUCED FROM THE CONTENTS OF THE EXERCISE DIRECTORY -- not from
a configuration field that would need to be kept in sync with reality:

  quiz.json   paper exercises. No compilation, no container.
  io.json     a complete program with main(), run against inputs.
  test_*.c    functions linked against Unity, with no main().
"""

import datetime
# ponytail: `flock` est POSIX, et le worker ne tourne QUE sur le Dell -- mais
# `publish_content` importe ce module, et l'API importe `publish_content`. Sans
# ce garde-fou, `test_api.py` et `test_ctester.py` ne s'importent plus sur une
# machine de développement Windows. Juger une session sans fcntl lève ;
# importer, non.
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import uuid

import content_catalog

SPOOL = os.environ.get("CTESTER_SPOOL", "/opt/ctester/spool")

# THE PRIVATE CONTENT AND ITS RELEASES. Since phase 8 there is no more
# historical `tpN/exN` tree: the worker resolves exercises through
# `content_catalog.load_exercise()` and always publishes a release. The
# rollback is a `current.json` pointer to rewrite, not a variable to empty.
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

# --- LA CONSOLE : une session interactive, et UNE SEULE ---------------------
# Un job de console est un job de spool ordinaire portant `"kind": "console"`,
# donc il attend dans LA MÊME FILE que les exercices, avec la même position et
# le même ETA. Ce qui change est ce que le worker en fait : au lieu d'appeler
# `_juger()` et de rendre un verdict, il ouvre un conteneur interactif et
# relaie des octets jusqu'à ce que l'étudiant referme sa page.
#
# PLUS SERRÉ QUE LA CORRECTION, ET CE N'EST PAS DE LA PRUDENCE DÉCORATIVE.
# La fenêtre d'exposition passe de 5 s par cas à CONSOLE_SESSION_MAX, soit
# trente-six fois. Ces plafonds DOIVENT rester sous ceux de la correction ; un
# test le vérifie par comparaison plutôt que sur les littéraux, précisément
# pour qu'une future « harmonisation » échoue au lieu de les relâcher.
BUILD_SCRATCH = os.environ.get("CTESTER_BUILD_SCRATCH",
                               "/opt/ctester/build-scratch.sh")
CONSOLE_MEMORY = os.environ.get("CTESTER_CONSOLE_MEMORY", "192m")
# ÉGAL À LA CORRECTION, ET PAS PLUS SERRÉ -- le seul plafond de la Console qui
# ne soit pas en dessous, parce que le serrer ne protégeait de RIEN et cassait
# tout. Sous `runsc`, les processus créés dans le bac à sable sont internes à
# gVisor : ce cgroup ne les compte pas, il compte les tâches de l'HÔTE, donc
# les threads du sentry. À 32, le sentry n'arrive pas à démarrer et docker rend
# « cannot create sandbox: cannot read client sync file: waiting for sandbox to
# start: EOF » -- avant le premier octet compilé. Ce qui arrête vraiment un
# `while (1) fork();` ici, c'est le plafond mémoire et `ulimit -t`.
#
# Il reste posé pour le chemin `runc`, où il compte bien les processus du
# conteneur : le retirer relâcherait ce chemin-là sans rien gagner ici.
CONSOLE_PIDS = os.environ.get("CTESTER_CONSOLE_PIDS", "64")
# Une demi-part de cœur, et `--cpu-shares` bas : SOUS CONTENTION, LA CORRECTION
# GAGNE. La correction est le cours, la console est un agrément.
CONSOLE_CPUS = os.environ.get("CTESTER_CONSOLE_CPUS", "0.5")
CONSOLE_SHARES = os.environ.get("CTESTER_CONSOLE_SHARES", "512")

# LES TROIS HORLOGES, ET ELLES NE MESURENT PAS LA MÊME CHOSE.
#   - le mur borne le coût d'une session (et DOIT rester très en dessous de
#     SWEEP_AFTER : sweep() efface un répertoire de spool sur son mtime, et le
#     mtime d'un répertoire ne bouge plus une fois ses fichiers créés) ;
#   - l'inactivité libère la place qu'un étudiant parti laisse occupée ;
#   - le temps CPU, lui, vit dans build-scratch.sh (`ulimit -t`) parce que
#     c'est la seule horloge capable de distinguer « il réfléchit » de « le
#     programme tourne en rond ».
CONSOLE_SESSION_MAX = int(os.environ.get("CTESTER_CONSOLE_SESSION_MAX", "180"))
CONSOLE_IDLE_MAX = int(os.environ.get("CTESTER_CONSOLE_IDLE_MAX", "90"))
# Le seul plafond qui arrête `while (1) puts("x");` : il n'est jamais inactif.
CONSOLE_OUT_MAX = int(os.environ.get("CTESTER_CONSOLE_OUT_MAX", "1048576"))
# Ce que l'API a le droit d'accumuler dans `in`, lu par le worker.
CONSOLE_IN_MAX = int(os.environ.get("CTESTER_CONSOLE_IN_MAX", "65536"))

# LE VERROU DE SESSION UNIQUE. Il y a deux workers ; si les deux ouvraient un
# terminal, la correction s'arrêterait. Un worker qui ne l'obtient pas SAUTE le
# job sans le réclamer -- la console attend, la correction continue.
CONSOLE_LOCK = ".console"

# LA CLÉ RÉSERVÉE DE `durees.json`. Une session de console n'a pas d'exercice,
# et `enregistrer_duree()` refuse un identifiant vide -- donc sans cette clé une
# console en cours compterait pour la moyenne des autres (une quinzaine de
# secondes) alors qu'elle peut tenir trois minutes. Quelqu'un en file derrière
# verrait « ~15 s » pour une attente réelle de 180, et annoncer plus court que
# le réel est la seule erreur d'estimation qui se remarque.
#
# Un deux-points en tête : aucun répertoire d'exercice ne peut porter ce nom,
# donc la clé ne peut pas entrer en collision avec un vrai identifiant.
CONSOLE_DUREE = ":console"

# AN ABANDONED LOCK IS NOT A LOCK. `claim()` sets a `.lock` that a killed
# worker -- deploy, OOM, reboot -- does not take with it: the job stays
# listed by pending_jobs(), refused by claim() forever, and the student
# stares at "queued" until sweep() erases the directory SWEEP_AFTER later.
# Ten minutes of silence for a submission that never failed.
#
# THE THRESHOLD IS DERIVED, NOT CHOSEN, and that is what makes reclaiming
# safe with N workers: a LIVE worker cannot hold a lock longer than the job
# it is running, since `sandbox()` is capped at JOB_TIMEOUT by subprocess.
# Three times that bound covers the rest of run_job() -- writing cases,
# extracting warnings -- with a margin nothing makes tight. A lock older than
# that belongs to nobody.
#
# AND IT STAYS WELL UNDER SWEEP_AFTER: order is everything, a job must be
# reclaimable BEFORE being swept, or reclaiming never happens.
LOCK_STALE = int(os.environ.get("CTESTER_LOCK_STALE", str(3 * JOB_TIMEOUT)))

# ONE reclaim, not infinite. A job that kills its worker every single time --
# OOM, a bug, a hardware fault -- would be reclaimed in a loop by each worker
# in turn, which would die on it in turn: the whole queue would stall on a
# single submission. Past that, an error verdict is written, which the
# student sees on the next poll and can retry.
LOCK_RETRIES = int(os.environ.get("CTESTER_LOCK_RETRIES", "1"))

# PREVIEW BEFORE OPENING, for the instructor's machine. Setting CTESTER_PREVIEW
# to anything other than "" or "0" drops the `available_from` filter: the
# published catalog AND tp_path then see everything, including what opens in
# November. This is the only way to exercise an exercise end to end -- paste
# its reference solution into the real page and read the real verdict --
# before students have access.
#
# THE TWO FALL TOGETHER, AND THAT IS THE POINT: the flag becomes a DATE (the
# year 9999) that `access()` reads at publish time the same way `tp_path`
# reads it before running anything. Opening the menu without opening tp_path
# would give an exercise one can select but not submit, which looks like an
# outage.
#
# THIS IS NOT A PRODUCTION SETTING. The deployment does not set it, and
# publish_catalogue() says so in the log when it is active: a worker that
# inherited it by accident would open the whole term at once.
PREVIEW = os.environ.get("CTESTER_PREVIEW", "") not in ("", "0")

# WHO MAY RUN A NOT-YET-OPEN EXERCISE, and it is not a process-wide flag but a
# LIST OF ACCOUNTS -- the same one the API reads, from the same variable. Dates
# are for students: the instructor has to be able to submit against the real
# tests before the class does, and CTESTER_PREVIEW would open the whole term to
# everybody to get it.
#
# READ HERE, NOT TAKEN FROM `job.json`. This process is root and trusts nobody,
# including our own web container: `job.json` already carries the `owner` the
# API validated, and the ROLE is recomputed from it here. A compromised web
# tier can lie about who submitted, which it could already do; it cannot hand
# itself a "run this anyway" flag.
#
# EMPTY MEANS THE FEATURE DOES NOT EXIST, exactly like the forum. Missing on
# the systemd unit while the API has it = statements visible, every verdict
# "Exercice inconnu."
MODERATEURS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)

# Compilation settings, RELAYED and not interpreted: their meaning lives in
# build-unity.sh / build-io.sh, which also carry their own defaults. What is
# passed here takes precedence, and `docker run` propagates nothing on its
# own.
#
# ABSENT MEANS "the script's default". A variable not set here is not passed
# through at all, rather than passed through empty -- emptying
# CTESTER_SANITIZERS is the explicit fallback that disables sanitizers, and
# confusing the two would cut them by accident the moment a worker started
# without its systemd unit.
SANDBOX_ENV = {
    k: os.environ[k]
    for k in ("CTESTER_C_STD", "CTESTER_SANITIZERS", "CTESTER_ASAN_OPTIONS",
              "CTESTER_COMPILE_TIMEOUT", "CTESTER_RUN_TIMEOUT",
              # Lu par build-scratch.sh SEUL : le plafond de temps CPU, qui est
              # la réponse à `while (1);` là où il n'y a pas de chronomètre par
              # cas. Il voyage ici pour que les trois scripts prennent leurs
              # réglages au même endroit.
              "CTESTER_CPU_SECONDS")
    if k in os.environ
}

SUMMARY_RE = re.compile(r"^(\d+) Tests (\d+) Failures (\d+) Ignored", re.M)
FAIL_RE = re.compile(r"^[^\n:]*:\d+:([A-Za-z0-9_]{1,64}):FAIL", re.M)
INCLUDE_RE = re.compile(r"^[ \t]*#[ \t]*include[ \t]*[<\"]([^>\"\n]+)", re.M)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

# `inf` and `nan` as printf writes them. The guards on either side are "not a
# letter", not \b: \b treats "é" as a letter inconsistently, and "inférieur"
# or "nanomètre" in a prompt must not trigger the message. [^\W\d_] = a
# letter, Unicode included.
NONFINITE_RE = re.compile(
    r"(?<![^\W\d_])-?(?:inf(?:inity)?|nan)(?![^\W\d_])", re.I)

MAX_GCC_CHARS = 8000
MAX_FAILED_NAMES = 50
MAX_CASE_OUTPUT = 600

# The exit code ASan gets via ctester_asan_options. Chosen outside Unity's
# range, since Unity returns ITS OWN FAILURE COUNT: an ASan abort would
# otherwise exit 86... er, exit 1, indistinguishable from "one failed test".
# Keep the two in agreement.
ASAN_EXIT = 86

# Wider than MAX_CASE_OUTPUT: an ASan report fits in about twenty lines, and
# its FIRST line -- the one naming the file and line -- would be lost if cut
# to the size of a program's output.
MAX_STDERR = 2000
DEFAULT_TOLERANCE = 0.005


# --------------------------------------------------------------------------
# Exercise mode
# --------------------------------------------------------------------------

MODE_FILES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))


def detect_mode(tp_dir):
    """quiz / io / unity / None, based on which configuration file is present.

    ONE MECHANISM FOR ALL THREE MODES. Unity used to be detected differently
    -- by the presence of a test_*.c -- and that left nowhere to declare a
    label or the list of expected files. Unifying costs one unity.json file
    per exercise and removes an exception.
    """
    for mode, conf in MODE_FILES:
        if os.path.exists(os.path.join(tp_dir, conf)):
            return mode
    return None


def config_name(mode):
    return dict(MODE_FILES)[mode]


# File names come from the TEST CONFIGURATION, written by the instructor,
# never from the student. They are still validated: a typo that produced
# "../../etc/passwd" must not become a path.
FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")


def declared_files(conf, tp_dir=None):
    """The files the student must provide, [{name, template}].

    The name is IMPOSED BY THE ASSIGNMENT and not chosen by the student:
    starting at lab 5, they write a `calendrier.h` + `calendrier.c` module,
    and the `#include "calendrier.h"` in their own code, as in the test
    file's, only resolves if the file carries exactly that name. Letting the
    student name their own files would not be freedom, it would be one more
    error class.

    By default, a single `submission.c` file -- the shape of labs 2 to 4, a
    complete program in a single file.
    """
    files = conf.get("files")
    if not files and tp_dir:
        # V2 CONTENT: templates are PUBLIC, so kept next to the grading
        # configuration (`public/files.json`) rather than inside it. The
        # worker reads them back here -- never from the network, where a name
        # chosen by the student would become a path.
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
# Public catalog -- THE BOUNDARY
# --------------------------------------------------------------------------

def public_quiz(quiz):
    """The quiz with its answer key stripped, as the browser may see it.

    THIS IS THE FUNCTION THAT KEEPS THE SECRET, and that is why it rebuilds a
    dict field by field instead of removing `answer` from a copy. A key added
    to the answer key tomorrow (a comment, an accepted variant) therefore does
    not leak by default: it is simply absent until someone adds it here.
    test_ctester.py checks that no 'answer' key survives.
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


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def publish_catalogue():
    """Projects private content into a release, and switches the pointer.

    Published by THE WORKER and not by Ansible: it is the one allowed to read
    the tests, and above all "the reference solution never crosses the
    boundary" becomes a Python function a test checks, instead of a Jinja
    loop nobody rereads.

    The N workers write the same content at startup. The race has no
    consequence: a revision IS the hash of its content, so two workers write
    the same directory and the same pointer.

    RAISES RATHER THAN PUBLISHING EMPTY if both variables are missing. Since
    phase 8 there is no more historical tree to fall back on: a misconfigured
    worker must stop and say so, not serve an empty catalog.
    """
    if PREVIEW:
        print("ctester: PREVIEW ACTIVE -- exercises not yet open are being published",
              file=sys.stderr, flush=True)
    if not (CONTENT and PUBLISHED):
        raise RuntimeError(
            "CTESTER_CONTENT and CTESTER_PUBLISHED are required to publish")
    # LOCAL import: publish_content reads `public_quiz` right here, and an
    # import at the top of the file would close the cycle.
    import publish_content
    model = content_catalog.discover(CONTENT)
    # Preview is a DATE, not a second filter: `access()` stays the only read
    # of a release, and setting the clock to the year 9999 opens everything
    # that is dated without touching what is archived.
    maintenant = datetime.datetime(9999, 1, 1, tzinfo=datetime.timezone.utc) if PREVIEW else None
    # LES ÉNONCÉS TYPST SONT RENDUS AVANT LA PREMIÈRE ÉCRITURE, et c'est la même
    # propriété que `discover()` tient pour un contenu invalide : ce qui ne
    # compile pas ne remplace jamais la release active. Le rendu est un
    # conteneur jetable, mis en cache par hachage de contenu -- un tick qui ne
    # trouve rien de changé ne lance pas typst.
    import typst_build
    renders, (total, du_cache) = typst_build.render_all(model)
    if total:
        print("ctester: %d énoncé(s) Typst rendu(s), dont %d depuis le cache"
              % (total, du_cache), file=sys.stderr, flush=True)
    publish_content.publish(model, PUBLISHED, now=maintenant, renders=renders)
    return list(model["exercises"].values())


def tp_path(exercise_id, owner=None):
    """An exercise's assessment directory. None if it does not exist.

    THE ONLY WAY TO GO FROM AN ID TO A PATH, and it re-applies the release:
    the web tier already did it, this process is root and trusts nobody,
    including our own web container.

    `owner` IS AN ACCOUNT, NOT A PERMISSION. It is the `sub` the API wrote into
    `job.json`; whether it opens a not-yet-published exercise is decided HERE,
    against `MODERATEURS`. A job with no owner -- every anonymous submission,
    and every Console session -- behaves exactly as before.

    The directory returned is `exercises/<id>/assessment`: the same shape as
    a historical exercise directory -- configuration, `test_*.c` and
    `allowed_includes.txt` side by side -- so `detect_mode`, `read_allowed`,
    `docker_argv` and the sandbox never had to change.
    """
    tout = PREVIEW or (bool(owner) and owner in MODERATEURS)
    entry = content_catalog.load_exercise(CONTENT, exercise_id, tout=tout)
    return entry["path"] if entry else None


# --------------------------------------------------------------------------
# Quiz mode
# --------------------------------------------------------------------------

def norm_bin(text):
    """Binary digits, or None. Accepts spaces, underscores and the 0b prefix."""
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0b", "", s)
    return s if s and set(s) <= {"0", "1"} else None


def norm_hex(text):
    """The value of a hex number written 1F, 0x1f, 1Fh or 001f. None if unreadable."""
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0x", "", s)
    s = re.sub(r"h\Z", "", s)
    try:
        return int(s, 16)
    except ValueError:
        return None


def norm_int(text):
    # The Unicode minus sign arrives via copy-paste from the statement's PDF,
    # where it is written "-45". Refusing it would punish a successful
    # copy-paste.
    s = re.sub(r"[\s_]", "", str(text)).replace("−", "-")
    try:
        return int(s)
    except ValueError:
        return None


def check_answer(kind, given, expected):
    """(correct, hint). The hint explains a FORM error, never the answer."""
    if kind == "bin8":
        got, want = norm_bin(given), norm_bin(expected)
        if got is None:
            return False, "ce n'est pas une suite de 0 et de 1"
        if got == want:
            return True, ""
        if want is not None and int(got, 2) == int(want, 2):
            # The value is right, the notation is not. Say so: the statement
            # asks for 8 bits, and a student who answers 10111 understood the
            # conversion but not the instructions. The two deserve to be told
            # apart, without giving away the answer.
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
    """Grades a quiz. `answers` is {id: text} as submitted."""
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
                # One's own answer: with 40 questions across pages,
                # remembering what one typed would otherwise take a
                # round trip across two screens.
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
# io mode
# --------------------------------------------------------------------------

def extract_numbers(text):
    """Every number in a free-form output, in order.

    The decimal comma is accepted: `printf("%.2f")` produces a dot, but a
    student formatting by hand may produce a comma.
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
    """Do the expected values appear in order among the numbers?

    SUBSEQUENCE AND NOT EQUALITY, because the statement never dictates
    exactly what to print: "Surface = 15 cm2" and "15" must both pass, and a
    prompt like "Enter the length: " must break nothing. The price is a
    possible false positive if a prompt happens to contain the expected value
    -- acceptable for a feedback tool.
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
    """Lowercase without accents, to compare a word against a student's output."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def check_case(case, output, tol):
    """'' if the case passes, else the reason, in French, for the student."""
    folded = fold(output)
    for word in case.get("absent", []):
        if fold(word) in folded:
            return "la sortie mentionne « " + word + " », qui ne devrait pas y etre"
    wanted = case.get("contains")
    if wanted and fold(wanted) not in folded:
        return "la sortie ne contient pas le mot attendu"
    # A range rather than a value: for a program that draws at random, the
    # output has no expected value, only bounds. "at least N numbers in
    # [min, max]" and not "all", because a prompt like "Rolling 100 times"
    # adds a 100 that the bound would reject on a perfectly correct program.
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
        # TWO VERY COMMON FAILURES DESERVE THEIR OWN MESSAGE. "the output does
        # not contain the expected values" is true but useless when the
        # output is `inf` or has no digits at all: the student is then not
        # making a math error, they are reading an uninitialized variable, or
        # testing the wrong exercise.
        if NONFINITE_RE.search(output):
            return ("ta sortie contient inf ou nan : division par zéro, ou une "
                    "variable utilisée alors que sa lecture a échoué. Vérifie "
                    "que ton programme lit exactement autant de valeurs que le "
                    "cas lui en fournit")
        if not numbers:
            return ("ta sortie ne contient aucun nombre : vérifie que tu "
                    "affiches bien le résultat, et que c'est le bon exercice")
        if len(numbers) < len(expected):
            # A SAFE DEDUCTION, not a heuristic: a subsequence of M values
            # cannot fit in fewer than M numbers. When an exercise expects
            # three and the program prints two, it is almost always a correct
            # computation and an incomplete printf -- saying so avoids
            # hunting for a formula error that does not exist.
            #
            # The NUMBER of expected values is not a secret: it is in the
            # statement. Their values, though, still never leave here.
            return ("ta sortie ne contient que %d nombre%s, or ce cas en attend "
                    "%d : vérifie que tu affiches TOUTES les valeurs demandées "
                    "par l'énoncé" % (len(numbers),
                                      "" if len(numbers) == 1 else "s",
                                      len(expected)))
        return "la sortie ne contient pas les valeurs attendues, dans l'ordre"
    return ""


def split_runs(output, nonce):
    """Splits the sandbox's output into {case name: (text, exit code)}.

    The separator is a nonce drawn per job, invisible to the student: without
    it, a program that prints the marker would manufacture passing cases for
    itself.
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
    """Attaches the compiler's warnings to the verdict, if any.

    Attached EVEN ON SUCCESS: that is when they are most useful, and also the
    only time the student has the leisure to read them. The page takes care
    not to make them look like a failure.

    Not attached to a compile error: the full stderr is already in the `gcc`
    field, repeating it would add nothing.
    """
    if avertissements and resultat.get("status") != "compile_error":
        resultat["warnings"] = avertissements
    return resultat


def extraire_avertissements(output, nonce):
    """Splits the gcc warnings block off from the rest of the output.

    Returns (warnings, rest). The block is REMOVED from the rest: downstream
    parsers read the Unity summary and the cases with regular expressions,
    and a warning containing `:FAIL` or a number would fool them.
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
    # Compilation (10/11/12) and the whole container's cap (124/137): the
    # same codes as unity mode, and a single message. 137 can only come from
    # the EXTERNAL timer -- build-io.sh always exits 0 after its loop, and a
    # single case's timeout is read from its own end marker, not here.
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
            # HERE the report IS shown, through the case's own stderr right
            # below: this particular container mounts no test, it has
            # nothing to hide. ASan names the student's file and line.
            reason = ("le programme a débordé de la mémoire qu'il a réservée "
                      "(voir le rapport ci-dessous : il nomme la ligne)")
        elif code != 0:
            reason = "le programme s'est terminé anormalement (code %d)" % code
        else:
            reason = check_case(case, text, tol)
        if reason:
            failed.append({
                "case": number,
                # INPUTS are shown (the student has the formula, they use
                # them to debug), the EXPECTED value never is: it would
                # invite writing a printf of constants.
                "stdin": case.get("stdin", ""),
                "stdout": text[:MAX_CASE_OUTPUT],
                # THE NUMBERS THE JUDGE SAW. Subsequence matching used to be
                # a black box: a student writing "1 234" or "3,5" could not
                # guess how their line had been split. This is their own
                # output, read back aloud.
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
# Sandbox
# --------------------------------------------------------------------------

def forbidden_includes(code, allowed):
    """The submission's #include directives that are not on the allow-list.

    `allowed` set to None (no allowed_includes.txt file for this exercise)
    disables the check.

    ponytail: a regex over the raw text. It sees a #include inside a comment
    or a string, and misses one produced by a macro. Both are out of reach of
    a first-term student, and a false positive costs a clear error message,
    not a bad grade.
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
    """Unity is SHARED by every exercise, hence kept outside any one of them."""
    return os.path.join(CONTENT, "shared", "unity")


def _argv_durci(name, memory, pids, cpus, work, tmp, extra=()):
    """Le durcissement du bac à sable, ÉCRIT UNE SEULE FOIS.

    Les trois modes de correction et la Console partagent exactement ces
    portes ; ce qui les distingue est ce qu'ils MONTENT, jamais ce qu'ils
    verrouillent. Les tenir dans deux listes garantirait qu'un jour l'une des
    deux perde une option sans que personne ne le voie -- et celle qui la
    perdrait est celle qu'on relit le moins.

    Chaque option ferme une porte, et aucune n'est décorative :
      --network=none      rien à exfiltrer, rien à scanner, pas de relais
      --pids-limit        la bombe à fork est LE classique du labo de C
      --read-only + tmpfs le conteneur ne survit à rien, à commencer par lui
      --cap-drop=ALL      aucune capacité, pas même celles par défaut
      --user 65534        jamais root, pas même à l'intérieur
      --rm                un conteneur = un job = jetable, jamais réutilisé
      --runtime=runsc     le code natif tape dans un noyau réimplémenté en
                          espace utilisateur, pas dans celui du Dell

    LA SURFACE INSCRIPTIBLE TIENT EN DEUX LIGNES, ET C'EST LA GARANTIE.
    `--read-only` rend tout le reste du système de fichiers immuable, et les
    deux seuls points inscriptibles sont des tmpfs -- de la MÉMOIRE, comptée
    dans `--memory`, détruite avec le conteneur. Un programme qui remplit
    /work ne remplit donc rien : il se fait OOM-killer. Vérifié depuis
    l'intérieur : /etc, /usr et / répondent EROFS, un montage `:ro` répond
    EROFS, et `--ulimit fsize` coupe un fichier de /work à 8 Mo.

    IL N'Y A PAS DE FILTRE D'APPELS SYSTÈME, et ce n'est pas un oubli :
    `write` ne peut pas être bloqué -- c'est par lui que sort printf -- et
    distinguer « écrire sur stdout » d'« écrire un fichier » demande de
    raisonner sur la cible d'un descripteur, ce que seccomp ne sait pas faire.
    La frontière est le système de fichiers, qui se lit dans cet argv, plutôt
    qu'un profil qu'il faudrait auditer.
    """
    return [
        "docker", "run", "--rm", "--name", name,
        "--runtime", RUNTIME,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/work:rw,exec,size=" + work + ",mode=0777",
        "--tmpfs", "/tmp:rw,size=" + tmp,
        "--memory", memory, "--memory-swap", memory,
        "--pids-limit", pids,
        "--cpus", cpus,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "--ulimit", "fsize=8388608",
        "--ulimit", "nofile=64",
    ] + list(extra)


def docker_argv(job_dir, tp_dir, name, mode, nonce=""):
    """The sandbox's command line.

    Each option closes a door, and none is decorative:
      --network=none      nothing to exfiltrate, nothing to scan, no spam relay
      --pids-limit        a fork bomb is THE classic C-lab mistake
      --read-only + tmpfs the container survives nothing, including itself
      --cap-drop=ALL      no capability, not even the default ones
      --user 65534        never root, not even inside
      --rm                one container = one job = disposable, never reused
      --runtime=runsc     native code hits a kernel reimplemented in user
                          space, not the Dell's own

    IN io MODE, THE TEST DIRECTORY IS NOT MOUNTED AT ALL. Inputs have already
    been extracted into the job's own directory; io.json, which holds the
    expected values, never enters the container.
    """
    argv = _argv_durci(name, MEMORY, PIDS, CPUS, "32m", "16m") + [
        # THE DIRECTORY, NOT A FILE. Since lab 5 a submission is a module --
        # calendrier.h AND calendrier.c -- and `#include "calendrier.h"` only
        # resolves if both sit side by side. A per-file mount would not give
        # that.
        "-v", job_dir + "/src:/in/src:ro",
    ]
    # The nonce is passed IN BOTH MODES: it used to only separate io cases, it
    # now also frames the compiler warnings block, which exists everywhere.
    argv += ["-e", "CTESTER_NONCE=" + nonce]
    # The same in both modes: the dialect, the sanitizers and the timers do
    # not depend on whether /in holds secrets.
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


def docker_argv_console(job_dir, name, nonce):
    """La ligne de commande d'une SESSION INTERACTIVE.

    LA CONSOLE NE MONTE RIEN DU CONTENU PRIVÉ, et c'est plus fort que ce que
    le mode io promet déjà. Le mode io ne monte pas le répertoire de l'exercice
    mais reçoit ses ENTRÉES ; ici il n'y a ni exercice, ni cas, ni test, ni
    `shared/unity` : les DEUX seuls montages sont le `main.c` de l'étudiant et
    le script de construction, tous les deux en lecture seule. Un test balaie
    cet argv et refuse tout `-v` sans suffixe `:ro`.

    LE SPOOL N'EST PAS MONTÉ NON PLUS. Le programme ne peut donc pas voir --
    encore moins écrire -- `in`, `out`, `state.json`, ni le répertoire d'un
    autre job. Le seul chemin de l'hôte qu'il peut lire est son propre source.

    `-i` ET JAMAIS `-t`. `docker run -t` refuse quand le stdin du client n'est
    pas un terminal : il faudrait donc que le worker ouvre son propre pty, le
    passe au CLI, laisse docker mettre le maître en mode brut, et parle à
    travers son proxy à un SECOND pty alloué par dockerd dans un sentry gVisor
    qui réimplémente la discipline de ligne en Go. Trois implémentations de
    terminal sur le chemin, sur le seul runtime dont l'intérêt est de ne pas
    être le noyau de l'hôte -- pour un tampon de LIGNE, qui ne vide toujours
    pas un `printf` sans saut de ligne. Le constructeur de build-scratch.sh
    fait mieux, en pur gcc : voir son en-tête.

    `--log-driver none` N'EST PAS UNE OPTION DE CONFORT. Avec `-i`, docker
    recopie chaque octet de stdout dans
    `/var/lib/docker/containers/*/*-json.log`. Un job noté imprime pendant 5 s
    par cas ; une session interactive peut imprimer à la vitesse du tube
    pendant CONSOLE_SESSION_MAX. C'est le chemin le plus rapide vers un disque
    plein sur le Dell, et c'est un drapeau.
    """
    argv = _argv_durci(name, CONSOLE_MEMORY, CONSOLE_PIDS, CONSOLE_CPUS,
                       "24m", "8m",
                       # `--cpu-shares` bas : sous contention, la correction
                       # gagne. Voir CONSOLE_CPUS.
                       extra=("--cpu-shares", CONSOLE_SHARES,
                              "--log-driver", "none", "-i"))
    argv += ["-e", "CTESTER_NONCE=" + nonce]
    for key, value in SANDBOX_ENV.items():
        argv += ["-e", key + "=" + value]
    argv += [
        "-v", job_dir + "/src:/in/src:ro",
        "-v", BUILD_SCRATCH + ":/in/build.sh:ro",
    ]
    return argv + [IMAGE, "bash", "/in/build.sh"]


def parse_unity(out):
    """Extracts the verdict from Unity's output. None if it has no summary.

    THIS INPUT IS NOT TRUSTED. Student code runs in the same process as the
    tests and can write whatever it wants to stdout, including imitating
    Unity. So only what the regular expressions above accept is ever
    returned: integers, and test names reduced to [A-Za-z0-9_] -- never a
    FAIL line's MESSAGE field, which carries the value the test expected and
    therefore the test itself.

    ponytail: a well-placed `printf` can manufacture a fake "0 Failures".
    That is inherent to running student code linked with the tests, this
    service is feedback and not grading, and the README says so. Do not try
    to harden this here.
    """
    match = None
    for match in SUMMARY_RE.finditer(out):
        pass  # the LAST summary: the one Unity writes on its way out
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
    """Translates one of build.sh's exit codes into a response for the student."""
    if rc == 10:
        return {
            "status": "compile_error",
            "message": "Ton fichier ne compile pas.",
            "gcc": out[:MAX_GCC_CHARS],
        }
    if rc == 11:
        # Deliberately vague: the detail would quote the tests. The two by
        # far most frequent causes are named, which is enough to unblock
        # without revealing anything about the test cases.
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
        # THE FACT WITHOUT THE REPORT. build-unity.sh discarded ASan's output
        # because its call stack names the calling test function. Still, a
        # memory overflow is infinitely more actionable than a bare
        # "segfault": the error CLASS is named along with where to look for
        # it, without a single line or name coming from the tests.
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
    """Launches the container and returns (exit code, standard output)."""
    name = "ctester-" + os.path.basename(job_dir)[:16]
    try:
        done = subprocess.run(
            docker_argv(job_dir, tp_dir, name, mode, nonce),
            capture_output=True, text=True, errors="replace",
            timeout=JOB_TIMEOUT, check=False,
        )
        # gcc cites its files by their path INSIDE the container. The student
        # never saw /in/src and does not need to: they recognize their file
        # by its name, "submission.c:9:13".
        return done.returncode, done.stdout.replace("/in/src/", "")
    except subprocess.TimeoutExpired:
        # `docker run --rm` is not enough: killing the docker CLIENT leaves
        # the container running. Without this rm -f, a pathological job holds
        # onto a Dell core until the daemon's next restart.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       check=False)
        return 137, ""


# --------------------------------------------------------------------------
# Verdict cache -- THE QUEUE DOES NOT PAY TWICE FOR THE SAME CODE
# --------------------------------------------------------------------------
#
# During a lab, many jobs recompile code that has already been graded: the
# same student resubmitting, the unmodified template, copy-paste. An
# already-computed verdict is returned here in a few milliseconds, so the
# queue empties instead of filling up. The job still always goes through the
# spool -- `/submit`, quotas and QUEUE_MAX are unchanged, and the web
# container gains no extra surface.
#
# THE CACHE LIVES IN THE WORKER, AND THAT IS STRUCTURAL. The published
# revision (`publish_content.revision()`) only hashes the PUBLIC PROJECTION:
# fixing a `test_*.c` or a `case` in io.json does not change it. A key based
# on it would serve the old verdict after a test fix. Only this process
# mounts CTESTER_CONTENT and can fingerprint `assessment/` itself.
#
# NORMALIZATION ONLY TOUCHES THE KEY, never the value nor what gets compiled:
# the judge always writes the student's exact bytes to `src/`. A bug in
# `normaliser_c()` can therefore only produce a bad cache hit -- never a
# miscompiled build, never mangled student code.
#
# THE STORE NEVER GOES STALE, IT FILLS UP. An entry whose key carries the
# judge's fingerprint cannot become wrong -- a fixed test makes it
# unreachable, not misleading. So eviction never happens by age, only for
# space, and then the least recently SERVED entries are dropped.

CACHE_DIR = "cache"
# THE STORE MUST LAST A SEMESTER, not one session: in week 4, week 1's
# exercises reopen to review for the midterm, and an entry written in
# September is still correct as long as its test has not moved. Order of
# magnitude: 80 students x 73 exercises x ~10 distinct submissions. A verdict
# is a few kilobytes (output is bounded by MAX_GCC_CHARS / MAX_CASE_OUTPUT /
# MAX_STDERR), so ~40 MB, ~200 MB worst case. CTESTER_CACHE_MAX=0 turns it off
# without redeploying: that is the rollback.
CACHE_MAX = int(os.environ.get("CTESTER_CACHE_MAX", "20000"))

# WHAT NEVER GOES INTO THE CACHE, because it is not a function of the code.
# The three caps (JOB_TIMEOUT, COMPILE_TIMEOUT, RUN_TIMEOUT) are wall-clock
# time under gVisor: borderline code passes or fails depending on the Dell's
# load. Freezing a FAILURE born of bad luck would lock the student out,
# unable to ever pass. `error` is a judge malfunction, not a verdict.
JAMAIS_EN_CACHE = frozenset(("timeout", "compile_timeout", "error"))


# A C LEXER, NOT A FORMATTER AND NOT A PARSER. clang-format does not strip
# comments and keeps blank lines: it cannot produce the same key for code
# spaced differently. An AST would require a real C parser over hostile
# input, and would only add insensitivity to redundant parentheses to the
# token stream -- two independent students differ by their identifiers
# regardless.
#
# THE ORDER OF ALTERNATIVES IS THE CORRECTNESS: string and character BEFORE
# the rest, or the `//` in `printf("http://x")` would cut the line into a
# comment and two distinct programs could share a key.
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
    """Code reduced to its tokens: the same key regardless of formatting.

    Comments removed, indentation and blank lines have no effect. A space is
    only kept where it SEPARATES two tokens (`int x` must not become `intx`),
    and a comment counts as such a separator.

    DIRECTIVES KEEP THEIR LINE ENDING: without it, `#define A 1` and
    `#define B 2` would merge into a single line, and two distinct programs
    could end up sharing the same key.
    """
    out = []
    espace = False     # a blank or a comment is waiting to possibly be emitted
    directive = False  # currently inside a `#...` line
    debut = True       # nothing emitted yet on this source line
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
    """Length THEN content: without the prefix, `ab` + `c` and `a` + `bc`
    would produce the same digest, and two distinct file sets could share a
    key."""
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
        sous.sort()  # os.walk's order is not guaranteed, the key must be
        for nom in sorted(fichiers):
            chemin = os.path.join(dossier, nom)
            rel = os.path.relpath(chemin, racine).replace(os.sep, "/")
            _hacher_octets(condensat, rel.encode("utf-8"))
            _hacher_fichier(condensat, chemin)


def empreinte_juge(exercise_id, tp_dir, mode):
    """Everything that decides the verdict EXCEPT the student's code.

    This is what makes invalidation automatic: a `test_*.c` fixed by the
    five-minute tick changes the fingerprint, therefore the key, therefore
    the verdict gets recomputed with nobody having to clear anything.

    `runner.py` hashes ITSELF here: `verdict_io`, `parse_unity` and the
    default tolerance live in it, and a cache version to bump by hand would
    be forgotten on exactly the day it matters.
    """
    condensat = hashlib.sha256()
    _hacher_octets(condensat, ("%s|%s" % (exercise_id, mode)).encode("utf-8"))
    _hacher_arbre(condensat, tp_dir)
    if mode == "unity":
        # Unity is SHARED: mounting a different version changes every verdict.
        _hacher_arbre(condensat, unity_dir())
    # Templates are public so kept OUTSIDE of assessment/, and they decide the
    # names written to disk (`declared_files`).
    _hacher_fichier(condensat,
                    os.path.join(tp_dir, os.pardir, "public", "files.json"))
    _hacher_fichier(condensat, BUILD_UNITY if mode == "unity" else BUILD_IO)
    _hacher_fichier(condensat, os.path.abspath(__file__))
    _hacher_octets(condensat, IMAGE.encode("utf-8"))
    _hacher_octets(condensat,
                   json.dumps(SANDBOX_ENV, sort_keys=True).encode("utf-8"))
    return condensat


def signature(exercise_id, tp_dir, mode, conf, sent, empreinte=None):
    """The cache key: the judge's fingerprint, plus the normalized code.

    `empreinte` is that of a previous call, COPIED rather than consumed: it
    does not depend on the submitted code, and recomputing it for every job
    in a burst would redo the same walk of `assessment/` fifty times in a
    row.
    """
    condensat = (empreinte or empreinte_juge(exercise_id, tp_dir, mode)).copy()
    for declared in declared_files(conf, tp_dir):
        nom = declared["name"]
        _hacher_octets(condensat, nom.encode("utf-8"))
        _hacher_octets(condensat,
                       normaliser_c(str(sent.get(nom, ""))).encode("utf-8"))
    return condensat.hexdigest()


def cache_lire(sig):
    """The verdict stored under this key, and MARKS IT AS SERVED.

    The `utime` call is what makes eviction fair: without it, an entry's age
    would be that of its WRITE, and week 1's exercise, which thirty students
    reopen to review for the midterm in week 4, would be the first dropped --
    precisely because it is old, when it is in fact the one being served.
    "Recently served" and "often served" cannot be told apart here: what
    serves often is always recent.
    """
    if CACHE_MAX <= 0:
        return None
    chemin = os.path.join(SPOOL, CACHE_DIR, sig + ".json")
    try:
        with open(chemin, encoding="utf-8") as fh:
            verdict = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(verdict, dict):
        return None
    try:
        os.utime(chemin)
    except OSError:
        pass  # a date not set costs one entry dropped too early, nothing more
    return verdict


def _elaguer_cache(dossier):
    """Drops the least recently SERVED entries until back under the cap.

    NO TTL, AND THAT IS INTENTIONAL: an entry does not expire. Its key
    carries the judge's fingerprint, so a fixed test makes it unreachable on
    its own rather than wrong. Eviction only happens for space, never for
    age -- an October entry still correct in December is a compilation saved.

    Drops one notch BELOW the cap (a margin of `CACHE_PRUNE_EVERY`) to avoid
    re-pruning on the very next write.
    """
    try:
        entrees = [(entree.stat().st_mtime, entree.path)
                   for entree in os.scandir(dossier) if entree.is_file()]
    except OSError:
        return
    surplus = len(entrees) - CACHE_MAX + CACHE_PRUNE_EVERY
    if surplus <= 0:
        return
    entrees.sort()
    for _, chemin in entrees[:surplus]:
        try:
            os.remove(chemin)
        except OSError:
            pass
    print("ctester: cache pruned %d entries (%d left)"
          % (surplus, len(entrees) - surplus), file=sys.stderr, flush=True)


# How many writes between two size checks. `os.scandir` over tens of
# thousands of files costs too much to pay on EVERY cached verdict -- that
# was the flaw of the old `len(os.listdir())`, invisible at 5,000 entries and
# would have shown at 50,000. The store therefore overshoots its cap by at
# most this margin, per worker.
CACHE_PRUNE_EVERY = int(os.environ.get("CTESTER_CACHE_PRUNE_EVERY", "500"))
_ecritures = [0]


def cache_ecrire(sig, verdict):
    if CACHE_MAX <= 0:
        return
    dossier = os.path.join(SPOOL, CACHE_DIR)
    try:
        os.makedirs(dossier, exist_ok=True)
        write_json(os.path.join(dossier, sig + ".json"), verdict)
    except OSError:
        return  # a cache that fails to write is not a judge failure
    _ecritures[0] += 1
    if _ecritures[0] >= CACHE_PRUNE_EVERY:
        _ecritures[0] = 0
        _elaguer_cache(dossier)


def cachable(conf, verdict):
    """`"cache": false` in io.json / unity.json for an exercise whose PROGRAM
    is randomized (tp6-ex1 rolls dice, tp6-ex2 is a statistical test over a
    million rolls): without it, a failure born of bad luck would be frozen
    and the student could never pass again."""
    return (bool(conf.get("cache", True))
            and isinstance(verdict, dict)
            and verdict.get("status") not in JAMAIS_EN_CACHE)


# A pending job's signature, computed once. A job is immutable once
# `job.json` is written -- but the judge's fingerprint is not: a test fixed
# while the job waits must change its key. The memo therefore carries both,
# and shrinks on every pass to the jobs still in the queue.
_SIGS = {}


def _sig_du_job(job_dir, exercise_id, tp_dir, mode, conf, empreinte):
    marque = empreinte.hexdigest()
    connu = _SIGS.get(job_dir)
    if connu is not None and connu[0] == marque:
        return connu[1]
    try:
        with open(os.path.join(job_dir, "files.json"), encoding="utf-8") as fh:
            sent = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(sent, dict):
        return None
    sig = signature(exercise_id, tp_dir, mode, conf, sent, empreinte)
    _SIGS[job_dir] = (marque, sig)
    return sig


def servir_les_connus():
    """Returns EVERY already-known verdict FIRST, before compiling a single one.

    THE FIFO IS WHAT COSTS, not the hashing. Without this pass, a duplicate
    at rank 42 waits behind forty-one compilations -- five minutes -- for a
    verdict already on disk, occupying a slot QUEUE_MAX counts the whole
    time. It costs one signature per pending job, under a millisecond,
    against the fifteen seconds it avoids.

    THIS IS ALSO WHAT COVERS THE BURST. Twenty students submitting the
    unmodified template within the same minute do not see each other --
    none has finished when the others are dequeued. As soon as the first one
    finishes, the next pass releases all of them at once.

    `claim()` CLOSES THE RACE, and it is the same lock as everywhere else: a
    job another worker just took is left untouched, it is the one that will
    answer. A job claimed here keeps its `.lock` just as after a normal
    grading run.

    The verdict is shared, THE ATTRIBUTION IS NOT: each job keeps its own
    `owner` in its `job.json`, and nothing the worker writes is specific to
    an account.
    """
    connus, vivants, servis = {}, set(), 0
    for job_dir in pending_jobs():
        vivants.add(job_dir)
        exercise_id = job_exercice(job_dir)
        contexte = connus.get(exercise_id)
        if contexte is None:
            contexte = connus[exercise_id] = _contexte(exercise_id)
        if contexte is False:
            continue
        tp_dir, mode, conf, empreinte = contexte
        sig = _sig_du_job(job_dir, exercise_id, tp_dir, mode, conf, empreinte)
        if sig is None:
            continue
        verdict = cache_lire(sig)
        if verdict is None:
            continue
        if not claim(job_dir):
            continue
        print("ctester: cache servi %s %s [file]" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
        write_result(job_dir, dict(verdict))  # dict(): write_result sets `state` on it
        servis += 1
    for parti in set(_SIGS) - vivants:
        del _SIGS[parti]
    return servis


def _contexte(exercise_id):
    """(tp_dir, mode, conf, fingerprint) for this exercise, or False if there
    is nothing to serve from the cache -- closed exercise, no mode, or a
    quiz, which spends no container and therefore has nothing to save.

    ponytail: NO OWNER HERE, so a moderator's preview job on a closed exercise
    is never pre-served by the priority pass -- it falls through to ordinary
    judging, which is the right degradation. Threading the owner down into
    `servir_les_connus()` would cost a `job.json` read per queued job to save
    one instructor one compilation."""
    tp_dir = tp_path(exercise_id)
    if tp_dir is None:
        return False
    mode = detect_mode(tp_dir)
    if mode is None or mode == "quiz":
        return False
    try:
        conf = load_config(tp_dir, config_name(mode))
    except (OSError, ValueError):
        return False
    return tp_dir, mode, conf, empreinte_juge(exercise_id, tp_dir, mode)


# --------------------------------------------------------------------------
# Processing one job
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# La Console : une session interactive
# --------------------------------------------------------------------------
# LE CANAL EST LE SPOOL, COMME PARTOUT. L'API écrit `src/main.c` puis
# `job.json` en dernier (rename atomique) ; ce processus-ci ouvre le conteneur
# et relaie des octets. L'API ne compile ni n'exécute rien, exactement comme
# pour une soumission notée -- c'est ce qui permet de l'exposer à Internet.
#
# CE QUI CIRCULE EST UN FLUX D'OCTETS, SANS CADRAGE, et ça n'est tenable que
# parce que PERSONNE NE L'INTERPRÈTE. `in` et `out` sont des fichiers en ajout
# seul relus par décalage : un lecteur peut voir un préfixe d'une écriture, ce
# qui pour un flux d'octets n'est pas une erreur. Un FIFO demanderait des
# sémantiques bloquantes des deux côtés d'un bind mount, pour ne rien gagner.
#
# LES DEUX VERROUS SONT DES `flock`, ET PAS DES `mkdir`. Un mkdir n'a pas de
# propriétaire : c'est pour ça que `claim()` a besoin de LOCK_STALE, reclaim()
# et reprises.json pour décider qu'un verrou est mort. Trois minutes d'attente
# sont acceptables pour un job en file ; elles ne le sont pas pour un terminal
# qu'un humain regarde. Le noyau, lui, relâche un flock à la mort du processus
# qui le tient -- y compris sur un SIGKILL du conteneur web -- et le fait à
# travers un bind mount, puisque c'est le même noyau et le même inode.
#
#   `alive` : tenu par l'API. Relâché = le navigateur est parti, on tue.
#   `claim` : tenu par ce worker. Relâché = le worker est mort, l'API le dit.


def verrou_tenu(chemin):
    """Quelqu'un tient-il encore le `flock` de ce fichier ?

    On le teste EN L'ESSAYANT : réussir à le prendre, c'est constater que le
    tenant n'est plus là. Le descripteur est refermé aussitôt, ce qui relâche
    le verrou qu'on vient éventuellement de prendre -- on sonde, on ne prend
    pas la place.
    
    L'OUVERTURE EST EN LECTURE SEULE, ET C'EST LOAD-BEARING. Les deux verrous
    ne sont pas crees par le meme utilisateur : `alive` l'est par l'API (uid
    65534 dans le conteneur), `claim` par le worker (root sur l'hote), et tous
    les deux en 0644. Ouvrir en O_RDWR pour SONDER demandait donc le droit
    d'ecriture sur le fichier de l'autre -- l'API prenait un EACCES sur
    `claim`, le `except OSError` le traduisait en « personne ne le tient », et
    la session mourait en annoncant « le service s'est interrompu » sur un
    worker parfaitement vivant. Une panne parfaitement asymetrique : root
    pouvait ouvrir `alive`, nobody ne pouvait pas ouvrir `claim`.

    `flock` NE DEMANDE AUCUN DROIT D'ECRITURE -- contrairement aux verrous
    POSIX de `fcntl.lockf` -- parce qu'il porte sur la description de fichier
    ouverte et pas sur son contenu. Sonder en lecture seule est donc la
    correction complete : rien a changer aux modes, rien a aligner entre deux
    utilisateurs.
    """
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_CREAT, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def job_kind(job_dir):
    """`"console"` pour une session, `""` pour une soumission notée."""
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("kind", ""))
    except (OSError, ValueError):
        return ""


def console_lock():
    """UNE SEULE SESSION SUR TOUT LE SERVICE. `mkdir`, atomique.

    Il y a deux workers ; si les deux ouvraient un terminal, plus personne ne
    corrigerait. Celui qui n'obtient pas ce verrou SAUTE le job sans le
    réclamer : la console attend son tour, la correction continue.

    Un `mkdir` suffit ici -- contrairement aux deux verrous de session -- parce
    que ce verrou n'a pas à détecter une mort en une seconde : il est repris
    après une session entière plus une marge, ce qui ne peut arriver que si un
    worker a été tué en tenant un terminal.
    """
    chemin = os.path.join(SPOOL, CONSOLE_LOCK)
    try:
        os.mkdir(chemin)
        return True
    except FileExistsError:
        try:
            age = time.time() - os.stat(chemin).st_mtime
        except OSError:
            return False
        if age <= CONSOLE_SESSION_MAX + 60:
            return False
        try:
            os.rmdir(chemin)
            os.mkdir(chemin)
        except OSError:
            return False
        print("ctester: console: verrou perime repris", file=sys.stderr,
              flush=True)
        return True
    except OSError:
        return False


def console_unlock():
    try:
        os.rmdir(os.path.join(SPOOL, CONSOLE_LOCK))
    except OSError:
        pass


def console_etat(job_dir, etat, **extra):
    """L'état lisible par l'API. Réécrit ATOMIQUEMENT, parce que lui a une forme.

    C'est le seul fichier de la session qui ne soit pas un flux : `write_json`
    fait tmp + rename, donc l'API ne peut jamais en lire une moitié.
    """
    payload = {"state": etat}
    payload.update(extra)
    try:
        write_json(os.path.join(job_dir, "state.json"), payload)
    except OSError:
        pass


def _pompe_sortie(proc, job_dir, nonce, compteur):
    """Draine la sortie du conteneur et la RANGE EN DEUX FICHIERS.

    `os.read` BLOQUANT, dans son propre fil : la latence de sortie est donc
    celle du tube, et il n'y a rien à sonder. C'est ce qui fait qu'une invite
    apparaît en quelques millisecondes plutôt qu'au prochain tour de boucle.

    LA BASCULE DE PHASE EST LE MARQUEUR À NONCE, l'idiome que build-io.sh
    utilise déjà : ce qui précède `<nonce> RUN` est un diagnostic de
    compilation, ce qui suit appartient au programme. Le flux est coupé UNE
    FOIS, sur un préfixe court -- pas analysé bloc par bloc. L'étudiant ne voit
    jamais le nonce, donc ne peut pas forger le marqueur et faire passer sa
    propre sortie pour du gcc.

    LA QUEUE DU TAMPON EST GARDÉE entre deux lectures : sans ça, un marqueur
    tombant à cheval sur deux `os.read` ne serait jamais reconnu, et toute la
    session s'écrirait dans `build`.
    """
    separateur = (nonce + " RUN\n").encode()
    garde = len(separateur) - 1
    tampon, en_build = b"", True
    build = open(os.path.join(job_dir, "build"), "ab", buffering=0)
    sortie = open(os.path.join(job_dir, "out"), "ab", buffering=0)

    def ecrire(fh, octets):
        if not octets:
            return
        if fh is sortie:
            # LE SEUL PLAFOND QUI ARRÊTE `while (1) puts("x");` : il n'est
            # jamais inactif et il consomme du CPU, mais il inonde bien avant
            # d'épuiser `ulimit -t`.
            reste = CONSOLE_OUT_MAX - compteur["octets"]
            if reste <= 0:
                compteur["trop"] = True
                return
            octets, compteur["octets"] = octets[:reste], compteur["octets"] + len(octets[:reste])
            if len(octets) >= reste:
                compteur["trop"] = True
        try:
            fh.write(octets)
        except OSError:
            pass
        compteur["vu"] = time.time()

    try:
        while True:
            try:
                chunk = os.read(proc.stdout.fileno(), 65536)
            except OSError:
                break
            if not chunk:
                break
            if not en_build:
                ecrire(sortie, chunk)
                continue
            tampon += chunk
            index = tampon.find(separateur)
            if index >= 0:
                ecrire(build, tampon[:index])
                apres = tampon[index + len(separateur):]
                tampon, en_build = b"", False
                compteur["compile"] = True
                ecrire(sortie, apres)
            elif len(tampon) > garde:
                ecrire(build, tampon[:-garde] if garde else tampon)
                tampon = tampon[-garde:] if garde else b""
    finally:
        if tampon:
            ecrire(build if en_build else sortie, tampon)
        for fh in (build, sortie):
            try:
                fh.close()
            except OSError:
                pass


def run_console(job_dir):
    """Une session interactive, du conteneur à sa mort. Rend le `result.json`.

    Le fil appelant est le superviseur : il verse `in` dans l'entrée du
    conteneur et surveille les trois raisons de s'arrêter. Un second fil pompe
    la sortie. Deux fils, de la bibliothèque standard, et rien d'autre.

    RIEN DE CE QUI EST ÉCRIT ICI N'EST SPÉCIFIQUE À UN COMPTE. `job.json` ne
    porte ni `owner`, ni `exercise_id`, ni `sub` : ce processus ne sait jamais
    qui est au clavier, et c'est « aucun modèle ne porte de champ d'identité »
    étendu jusqu'au canal du worker.
    """
    nom = "ctester-sbx-" + os.path.basename(job_dir)[:16]
    nonce = uuid.uuid4().hex
    alive = os.path.join(job_dir, "alive")
    entree = os.path.join(job_dir, "in")
    compteur = {"octets": 0, "trop": False, "vu": time.time(), "compile": False}

    # LE CONSTRUCTEUR AVANT TOUT LE RESTE, et ce controle existe parce que son
    # absence se deguisait en panne de service. `CTESTER_BUILD_SCRATCH` est
    # pose par l'unite systemd ; un worker converge AVANT que le role ne porte
    # cette variable retombe sur un defaut qui ne designe aucun fichier, docker
    # bind-monte alors un repertoire vide sur /in/build.sh, et l'etudiant lit
    # « le service s'est interrompu » -- un message qui accuse le SERVICE la ou
    # c'est la CONFIGURATION qui manque, et qui n'aide donc personne.
    #
    # AVANT MEME LA SONDE D'`alive`, pour deux raisons : ca ne coute qu'un
    # `stat`, et une session abandonnee doit quand meme laisser cette ligne
    # dans le journal -- c'est precisement quand personne ne regarde que
    # l'operateur a besoin d'apprendre que son unite est mal configuree.
    if not os.path.isfile(BUILD_SCRATCH):
        print("ctester: console: CTESTER_BUILD_SCRATCH introuvable (%s) --"
              " l'unite ctester-runner@ ne la pose pas ; rejouer le playbook"
              % BUILD_SCRATCH, file=sys.stderr, flush=True)
        console_etat(job_dir, "exited", code=-1, reason="build_missing")
        return {"status": "console", "code": -1, "reason": "build_missing"}

    # LE NAVIGATEUR EST-IL ENCORE LA, AVANT DE DEPENSER UN CONTENEUR ? Une
    # session peut avoir attendu son tour derriere douze soumissions ; si
    # l'etudiant a ferme l'onglet pendant ce temps, lancer gcc puis tuer le
    # conteneur une seconde plus tard coute un demarrage de conteneur pour
    # rien -- sur la machine dont on compte les coeurs.
    if not verrou_tenu(alive):
        console_etat(job_dir, "exited", code=-1, reason="api")
        return {"status": "console", "code": -1, "reason": "api"}

    # LE VERROU DE VIVACITE DU WORKER, tenu pendant TOUTE la session. C'est le
    # pendant exact d'`alive` : l'API le sonde, et le noyau le relache si ce
    # processus meurt -- unite arretee, OOM, redemarrage. Sans lui, un worker
    # tue laisserait un terminal s'arreter sans rien dire, et l'etudiant ne
    # saurait pas si c'est son programme ou le service.
    #
    # PRIS AVANT LE PREMIER OCTET, pour qu'il n'existe aucune fenetre pendant
    # laquelle `.lock` est pose mais le verrou pas encore tenu : l'API y
    # conclurait « worker mort » sur une session parfaitement vivante.
    revendication = os.open(os.path.join(job_dir, "claim"),
                            os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(revendication, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # ON ECRIT L'ETAT AVANT DE PARTIR. Sans ca, ce retour etait MUET : le
        # job restait sans etat, l'API finissait par sonder `claim`, le trouvait
        # libre et concluait « worker » elle-meme -- le meme mot pour deux
        # causes differentes, dont celle-ci est la seule vraie course.
        print("ctester: console: claim deja tenu sur %s" % job_dir,
              file=sys.stderr, flush=True)
        os.close(revendication)
        console_etat(job_dir, "exited", code=-1, reason="worker")
        return {"status": "console", "code": -1, "reason": "worker"}

    console_etat(job_dir, "compiling", ttl=CONSOLE_SESSION_MAX)
    proc = subprocess.Popen(docker_argv_console(job_dir, nom, nonce),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    pompe = threading.Thread(target=_pompe_sortie,
                             args=(proc, job_dir, nonce, compteur), daemon=True)
    pompe.start()

    debut, lu, raison, annonce = time.time(), 0, "exited", False
    ferme = False
    try:
        while proc.poll() is None:
            # 1. Ce que l'étudiant a tapé depuis le dernier tour.
            try:
                with open(entree, "rb") as fh:
                    paquet = os.pread(fh.fileno(), 65536, lu)
            except OSError:
                paquet = b""
            if paquet:
                lu += len(paquet)
                compteur["vu"] = time.time()
                try:
                    proc.stdin.write(paquet)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    # Le programme a pu sortir pendant que l'étudiant tapait :
                    # ce n'est pas une panne, c'est la course normale.
                    pass
            # « Plus rien ne viendra » : un TÉMOIN à côté du flux, parce
            # qu'aucune séquence d'octets ne pourrait le dire sans qu'un
            # étudiant puisse la taper. C'est ce qui termine un
            # `while (scanf(...) == 1)` autrement qu'en tuant la session.
            if not ferme and os.path.exists(os.path.join(job_dir, "eof")):
                ferme = True
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            # 2. Le navigateur est-il toujours là ? Le noyau répond.
            if not verrou_tenu(alive):
                raison = "api"
                break
            # 3. Les deux horloges du worker (la troisième, le CPU, vit dans
            #    build-scratch.sh -- c'est la seule qui distingue « il
            #    réfléchit » de « le programme tourne en rond »).
            if time.time() - debut > CONSOLE_SESSION_MAX:
                raison = "timeout"
                break
            if time.time() - compteur["vu"] > CONSOLE_IDLE_MAX:
                raison = "idle"
                break
            # 4. Le plafond d'octets, posé par la pompe.
            if compteur["trop"]:
                raison = "output"
                break
            if not annonce and compteur["compile"]:
                annonce = True
                console_etat(job_dir, "running", ttl=CONSOLE_SESSION_MAX)
            time.sleep(0.025)
        else:
            raison = "exited"
    finally:
        # JAMAIS `proc.kill()` SEUL : tuer le CLIENT docker laisse le conteneur
        # vivant, leçon déjà payée par sandbox(). C'est `docker rm -f` qui
        # arrête un conteneur.
        subprocess.run(["docker", "rm", "-f", nom], capture_output=True,
                       check=False)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not ferme:
            try:
                proc.stdin.close()
            except OSError:
                pass
        pompe.join(timeout=5)

    code = proc.returncode if proc.returncode is not None else -1
    if raison == "exited" and not compteur["compile"]:
        # Le marqueur n'est jamais arrivé : gcc a refusé, et `build` porte son
        # texte. 12 = la compilation a dépassé son chronomètre.
        raison = "compile_timeout" if code == 12 else "compile_error"
    console_etat(job_dir, "exited", code=code, reason=raison)
    # RELACHE APRES l'etat final, et pas avant : l'API sonde ce verrou a chaque
    # tour, et le relacher trop tot lui ferait annoncer « le service s'est
    # interrompu » sur une session qui vient de se terminer normalement.
    try:
        os.close(revendication)
    except OSError:
        pass
    return {"status": "console", "code": code, "reason": raison}


def job_exercice(job_dir):
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("exercise_id", ""))
    except (OSError, ValueError):
        return ""


def job_owner(job_dir):
    """The account that submitted, or "" -- the only other field `job.json` has.

    READ FOR ONE DECISION AND ONE ONLY: is this a moderator, who may run an
    exercise that is not open yet (`tp_path`). Nothing this worker WRITES is
    specific to an account, and that stays true -- the verdict is shared, the
    attribution is not.
    """
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("owner", ""))
    except (OSError, ValueError):
        return ""


def run_job(job_dir):
    """A job's verdict. Serves the cache when it has one, judges otherwise.

    THE QUIZ IS NEVER CACHED: it spends no container, `grade_quiz` returns in
    a few milliseconds, and one more key would save nothing.
    """
    exercise_id = job_exercice(job_dir)
    # RE-VALIDATED HERE, even though the web tier already did. This process
    # is root and builds a path from this value: it trusts nobody, including
    # our own web container. `load_exercise` bounds the id (EXERCISE_RE)
    # before joining it, and re-applies the release -- against the OWNER, so
    # a moderator's preview submission runs and everybody else's does not.
    tp_dir = tp_path(exercise_id, job_owner(job_dir))
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

    empreinte = empreinte_juge(exercise_id, tp_dir, mode)
    sig = signature(exercise_id, tp_dir, mode, conf, sent, empreinte)
    connu = cache_lire(sig)
    if connu is not None:
        # THE HIT RATE IS READ FROM journalctl, already the runbook's tool.
        # No counter, no table. THE SAME WORD ON BOTH SIDES --
        # `grep -c 'cache servi'` counts both paths, and the bracket says
        # which: [file] the priority pass, the normal case; [dépilé] a job
        # the grading loop picked up first, which is a race.
        print("ctester: cache servi %s %s [dépilé]" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
        return connu

    resultat = _juger(job_dir, tp_dir, mode, conf, sent)
    if cachable(conf, resultat):
        # Duplicates already in the queue are released by
        # `servir_les_connus()` on the next pass, which finds them all at
        # once -- not here, where only this exercise's would be seen.
        cache_ecrire(sig, resultat)
        print("ctester: cache écrit %s %s" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
    elif isinstance(resultat, dict):
        # THE PAGE CANNOT GUESS THIS ON ITS OWN, which is why the server says
        # so. It redisplays the verdict for identical code instead of
        # retaking a queue slot -- except on this flag, which it must never
        # keep: a `timeout` depends on load, and an exercise whose PROGRAM is
        # randomized (`"cache": false`) deserves a fresh roll. One rule,
        # here, rather than two that would drift apart.
        resultat["rejouer"] = True
    return resultat


def _juger(job_dir, tp_dir, mode, conf, sent):
    """The compilation and execution themselves, with no cache and no catalog."""
    # Files are written HERE, under the names DECLARED by the test
    # configuration -- never under whatever the submission proposes. The web
    # tier already refused the others, but this process is root and does not
    # delegate this check: whatever is not declared is not written.
    #
    # AND THESE ARE THE STUDENT'S EXACT BYTES: `normaliser_c()` only ever
    # builds a cache key, never what gets compiled, or a lexer bug would
    # become a phantom compile error.
    src_dir = os.path.join(job_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    code = ""
    for declared in declared_files(conf, tp_dir):
        contenu = str(sent.get(declared["name"], ""))
        code += contenu + "\n"
        with open(os.path.join(src_dir, declared["name"]), "w",
                  encoding="utf-8") as fh:
            fh.write(contenu)

    # A module including its own header is not a forbidden dependency:
    # `#include "calendrier.h"` is exactly what the assignment asks for.
    # Declared files are therefore automatically added to the allow-list.
    allowed = read_allowed(tp_dir)
    if allowed is not None:
        allowed = allowed | {f["name"] for f in declared_files(conf, tp_dir)}

    bad = forbidden_includes(code, allowed)
    if bad:
        # Rejected without spending a container.
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


# DURATIONS LIVE IN THE SPOOL, NOT IN POSTGRES. The worker is root on the
# host and has no database connection; the spool is already the only channel
# between it and the API, and a display statistic is not a fact to keep --
# losing it at a sweep only costs the first estimate.
DUREES = "durees.json"

# Every exercise has its own cost: a quiz is instant, a ten-case io exercise
# pays for ten runs. The average is therefore PER EXERCISE, and sliding over
# the last DUREE_FENETRE jobs -- a test case added mid-session must show up
# in the estimate, not get drowned under the semester's history.
DUREE_FENETRE = 20
# A job rejected before the container (forbidden header, unknown exercise)
# costs a few milliseconds and is not representative: including it would pull
# the average toward zero precisely because students make mistakes often.
DUREE_MIN = 0.5


def lire_durees():
    try:
        with open(os.path.join(SPOOL, DUREES), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enregistrer_duree(exercise_id, secondes):
    """Per-exercise sliding average: {id: [average, n]}.

    ponytail: read-modify-write with no lock. `write_json` renames, so the
    file is never half-written; two workers finishing at the same
    millisecond lose one sample out of the window's twenty. A lock for this
    would cost more than the error it avoids.
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
        pass  # a lost estimate is not a judge failure


def claim(job_dir):
    """Reserves a job. mkdir fails if the directory exists, and that is atomic.

    ponytail: this is the whole lock N workers on ONE host need. A real
    distributed lock the day there is a second host, which will probably
    never happen.
    """
    try:
        os.mkdir(os.path.join(job_dir, ".lock"))
        return True
    except OSError:
        return False


def reprises(job_dir):
    """How many times this job has already been reclaimed from a dead worker."""
    try:
        with open(os.path.join(job_dir, "reprises.json"), encoding="utf-8") as fh:
            return int(json.load(fh).get("n", 0))
    except (OSError, ValueError, TypeError):
        return 0


def reclaim(job_dir, now):
    """Releases a dead worker's lock. True if the job can be reoffered.

    THE RACE BETWEEN TWO WORKERS HAS NO CONSEQUENCE, and that is what allows
    adding nothing stronger: both may judge the lock stale, one of the two
    `rmdir` calls fails, and it is claim()'s `mkdir` -- atomic -- that then
    settles it, exactly as for a fresh job.

    A lock that is still fresh belongs to a live worker: nothing is touched.
    """
    lock = os.path.join(job_dir, ".lock")
    try:
        if os.stat(lock).st_mtime > now - LOCK_STALE:
            return False
    except OSError:
        # The lock just disappeared -- sweep(), or another worker. The next
        # loop pass will see the real state.
        return False

    essai = reprises(job_dir) + 1
    if essai > LOCK_RETRIES:
        # THE LOCK STAYS IN PLACE: nobody reclaims this job any more, and the
        # verdict below is what the student reads on the next poll, instead
        # of waiting for the sweep.
        print("ctester: %s: abandoned after %d reclaim(s)" % (job_dir, essai - 1),
              file=sys.stderr, flush=True)
        write_result(job_dir, {
            "status": "error",
            "message": "Le juge a été interrompu pendant ce test. Relance-le.",
        })
        return False

    # BEFORE the rmdir: if the counter were written after, a worker killed in
    # between would leave the job reclaimed with no trace of it, and the
    # retry loop LOCK_RETRIES exists to prevent would become possible again.
    write_json(os.path.join(job_dir, "reprises.json"), {"n": essai})
    try:
        os.rmdir(lock)
    except OSError:
        return False
    print("ctester: %s: stale lock reclaimed (attempt %d)" % (job_dir, essai),
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
    jobs.sort()  # FIFO: the rank shown to the student must be true
    return [path for _, path in jobs]


def sweep(now):
    """Erases jobs older than SWEEP_AFTER, locked or not.

    THE SAFETY NET, AND ALSO THE FIRST RESORT. A job whose worker died is
    reclaimed by reclaim() well before this deadline (LOCK_STALE); what makes
    it this far is what nobody could reclaim -- a job abandoned after
    LOCK_RETRIES, or a directory the web tier wrote only halfway.
    """
    for entry in os.scandir(SPOOL):
        # THE CACHE IS NOT A JOB. Without this line, ten quiet minutes -- a
        # break, an evening -- would empty it, and it would only ever serve
        # during a burst instead of lasting a whole session.
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
        print("ctester: %d exercises published" % len(published), file=sys.stderr,
              flush=True)
    except (OSError, ValueError) as exc:
        # An unreadable catalog must not stop jobs already in the queue from
        # being processed: the service degrades to "empty menu", not an
        # outage.
        print("ctester: catalog: %s" % exc, file=sys.stderr, flush=True)
    jour = datetime.date.today()
    while True:
        if datetime.date.today() != jour:
            # The catalog is published ONCE at startup: without this, an
            # exercise whose date arrives tonight would only appear at the
            # worker's next restart. Republishing on day change is the only
            # deadline that exists -- no scheduler, no timer.
            jour = datetime.date.today()
            try:
                publish_catalogue()
            except (OSError, ValueError) as exc:
                print("ctester: catalog: %s" % exc, file=sys.stderr, flush=True)
        # ALREADY-KNOWN VERDICTS GO FIRST. Without this line, a duplicate at
        # rank 42 would wait behind forty-one compilations for a result
        # already written, occupying a queue slot the whole time.
        worked = bool(servir_les_connus())
        for job_dir in pending_jobs():
            # UNE SESSION DE CONSOLE SE DÉCIDE AVANT `claim()`, et l'ordre
            # compte : un worker qui réclamait d'abord et découvrait ensuite
            # qu'une autre console tourne aurait posé un `.lock` sur un job
            # qu'il ne va pas servir -- l'étudiant y lirait « en cours » sans
            # que rien ne se passe. On regarde donc le genre du job, on prend le
            # verrou de session, ET SEULEMENT ALORS on réclame. Sans le verrou,
            # on saute ce job et on prend le suivant : la console attend son
            # tour, la correction continue de tourner sur l'autre worker.
            console = job_kind(job_dir) == "console"
            if console and not console_lock():
                continue
            if not claim(job_dir):
                # Lock held. By a live worker -- move on -- or by a dead one,
                # and reclaim() decides on the one criterion that does not
                # lie here: the lock's age.
                if not (reclaim(job_dir, time.time()) and claim(job_dir)):
                    if console:
                        console_unlock()
                    continue
            worked = True
            debut = time.time()
            try:
                if console:
                    write_result(job_dir, run_console(job_dir))
                    # Sous SA PROPRE clé : une session tient la file bien plus
                    # longtemps qu'une compilation, et quelqu'un derrière doit
                    # lire une attente vraie. Voir CONSOLE_DUREE.
                    enregistrer_duree(CONSOLE_DUREE, time.time() - debut)
                else:
                    write_result(job_dir, run_job(job_dir))
                    enregistrer_duree(job_exercice(job_dir), time.time() - debut)
            except Exception as exc:  # noqa: BLE001 -- a job must not kill the worker
                print("ctester: %s: %s" % (job_dir, exc), file=sys.stderr,
                      flush=True)
                write_result(job_dir, {
                    "status": "error",
                    "message": "Erreur interne du juge. Réessaie.",
                })
                if console:
                    console_etat(job_dir, "exited", code=-1, reason="worker")
            finally:
                # DANS UN `finally` : une exception ne doit pas laisser le
                # verrou de session derrière elle, sinon plus personne n'ouvre
                # de console jusqu'à sa péremption.
                if console:
                    console_unlock()
            # ONE COMPILATION PER PASS, then back to known verdicts: this one
            # just populated the cache, and twenty duplicates may be waiting
            # for exactly what it just wrote. Without this `break`, they
            # would wait for the whole queue to finish.
            break
        sweep(time.time())
        if not worked:
            # ponytail: polling at 0.5 s. A systemd .path unit the day this
            # latency shows, which would require jobs shorter than the
            # compilation itself.
            time.sleep(0.5)


if __name__ == "__main__":
    main()
