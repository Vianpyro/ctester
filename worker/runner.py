#!/usr/bin/env python3
"""Host worker: runs as root, reads the spool and judges jobs in gVisor containers.

Nothing read from the spool reaches a shell: subprocess always gets argument lists.
"""

import datetime
import errno
# The worker only runs on Linux, but publish_content imports this module on dev machines.
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import uuid

import content_catalog

HERE = os.path.dirname(os.path.abspath(__file__))

SPOOL = os.environ.get("CTESTER_SPOOL", "/opt/ctester/spool")

# Root-owned and never mounted into the API container: the only place mounts and the verdict
# cache come from, because the API can rewrite anything under SPOOL.
WORK = os.environ.get("CTESTER_WORK", "/var/lib/ctester-judge")
JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")
MAX_LECTURE = 4 * 1024 * 1024

CONTENT = os.environ.get("CTESTER_CONTENT", "/opt/ctester/content")
PUBLISHED = os.environ.get("CTESTER_PUBLISHED", "/opt/ctester/published")
BUILD_UNITY = os.environ.get("CTESTER_BUILD_UNITY", os.path.join(HERE, "build-unity.sh"))
BUILD_IO = os.environ.get("CTESTER_BUILD_IO", os.path.join(HERE, "build-io.sh"))
IMAGE = os.environ.get("CTESTER_IMAGE", "gcc:14-bookworm")
RUNTIME = os.environ.get("CTESTER_RUNTIME", "runsc")
JOB_TIMEOUT = int(os.environ.get("CTESTER_JOB_TIMEOUT", "60"))
MEMORY = os.environ.get("CTESTER_MEMORY", "256m")
PIDS = os.environ.get("CTESTER_PIDS", "64")
CPUS = os.environ.get("CTESTER_CPUS", "1")
SWEEP_AFTER = int(os.environ.get("CTESTER_SWEEP_AFTER", "600"))

BUILD_SCRATCH = os.environ.get("CTESTER_BUILD_SCRATCH",
                               os.path.join(HERE, "build-scratch.sh"))
CONSOLE_MEMORY = os.environ.get("CTESTER_CONSOLE_MEMORY", "192m")
# Not lower than PIDS: under runsc this cgroup counts the gVisor sentry's own threads,
# and at 32 the sandbox fails to start.
CONSOLE_PIDS = os.environ.get("CTESTER_CONSOLE_PIDS", "64")
CONSOLE_CPUS = os.environ.get("CTESTER_CONSOLE_CPUS", "0.5")
CONSOLE_SHARES = os.environ.get("CTESTER_CONSOLE_SHARES", "512")

# Must stay well under SWEEP_AFTER: sweep() goes by directory mtime, which a running
# session does not update. The CPU limit lives in build-scratch.sh (ulimit -t).
CONSOLE_SESSION_MAX = int(os.environ.get("CTESTER_CONSOLE_SESSION_MAX", "180"))
CONSOLE_IDLE_MAX = int(os.environ.get("CTESTER_CONSOLE_IDLE_MAX", "90"))
CONSOLE_OUT_MAX = int(os.environ.get("CTESTER_CONSOLE_OUT_MAX", "1048576"))
CONSOLE_IN_MAX = int(os.environ.get("CTESTER_CONSOLE_IN_MAX", "65536"))

CONSOLE_LOCK = ".console"

CONSOLE_DUREE = ":console"

# A live worker can't hold a lock longer than its job, so older locks are abandoned.
# Must stay under SWEEP_AFTER, or jobs get swept before they can be reclaimed.
LOCK_STALE = int(os.environ.get("CTESTER_LOCK_STALE", str(3 * JOB_TIMEOUT)))

# A job that kills its worker every time would otherwise take down each worker in turn.
LOCK_RETRIES = int(os.environ.get("CTESTER_LOCK_RETRIES", "1"))

PREVIEW = os.environ.get("CTESTER_PREVIEW", "") not in ("", "0")

# Read here rather than trusted from job.json: the role is recomputed from the owner.
MODERATEURS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)

# Unset variables are not passed at all, because an empty CTESTER_SANITIZERS
# explicitly disables the sanitizers.
SANDBOX_ENV = {
    k: os.environ[k]
    for k in ("CTESTER_C_STD", "CTESTER_SANITIZERS", "CTESTER_ASAN_OPTIONS",
              "CTESTER_COMPILE_TIMEOUT", "CTESTER_RUN_TIMEOUT",
              "CTESTER_CPU_SECONDS")
    if k in os.environ
}

SUMMARY_RE = re.compile(r"^(\d+) Tests (\d+) Failures (\d+) Ignored", re.M)
FAIL_RE = re.compile(r"^[^\n:]*:\d+:([A-Za-z0-9_]{1,64}):FAIL", re.M)
INCLUDE_RE = re.compile(r"^[ \t]*#[ \t]*include[ \t]*[<\"]([^>\"\n]+)", re.M)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

# Not \b: it treats accented letters inconsistently ("inférieur" must not match).
NONFINITE_RE = re.compile(
    r"(?<![^\W\d_])-?(?:inf(?:inity)?|nan)(?![^\W\d_])", re.I)

MAX_GCC_CHARS = 8000
MAX_FAILED_NAMES = 50
MAX_CASE_OUTPUT = 600

# Outside Unity's range: Unity exits with its number of failed tests.
ASAN_EXIT = 86

MAX_STDERR = 2000
DEFAULT_TOLERANCE = 0.005


MODE_FILES = (("quiz", "quiz.json"), ("io", "io.json"), ("unity", "unity.json"))


def detect_mode(tp_dir):
    for mode, conf in MODE_FILES:
        if os.path.exists(os.path.join(tp_dir, conf)):
            return mode
    return None


def config_name(mode):
    return dict(MODE_FILES)[mode]


FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")


def declared_files(conf, tp_dir=None):
    files = conf.get("files")
    if not files and tp_dir:
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


def public_quiz(quiz):
    """Rebuilt field by field, so an answer key can never leak into the release."""
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


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def plateforme_sure():
    """Without these the helpers below would silently follow links, so the worker refuses to start."""
    return (fcntl is not None and _NOFOLLOW != 0 and _DIRECTORY != 0
            and {os.open, os.mkdir, os.rmdir, os.stat, os.unlink, os.rename}
            <= os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks
            and shutil.rmtree.avoids_symlink_attacks)


def _ouvrir_dossier(dossier, *sous):
    # `dossier` itself may be planted by the API (a job directory), so no component is followed.
    fd = os.open(dossier, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    for nom in sous:
        try:
            suivant = os.open(nom, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=fd)
        finally:
            os.close(fd)
        fd = suivant
    return fd


def _ouvrir(dossier, nom, flags, mode=0o644):
    """Opens a plain file below `dossier`; links, FIFOs and hard links are refused."""
    *sous, nom = nom.split("/")
    dfd = _ouvrir_dossier(dossier, *sous)
    try:
        fd = os.open(nom, flags | _NOFOLLOW | _NONBLOCK, mode, dir_fd=dfd)
    finally:
        os.close(dfd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError(errno.EPERM, "not a plain file", nom)
    except BaseException:
        os.close(fd)
        raise
    return fd


def lire_octets(dossier, nom, limite=MAX_LECTURE):
    with os.fdopen(_ouvrir(dossier, nom, os.O_RDONLY), "rb") as fh:
        data = fh.read(limite + 1)
    if len(data) > limite:
        raise OSError(errno.EFBIG, "too large", nom)
    return data


def lire_json(dossier, nom):
    return json.loads(lire_octets(dossier, nom).decode("utf-8"))


def existe(dossier, nom):
    try:
        dfd = _ouvrir_dossier(dossier)
    except OSError:
        return False
    try:
        os.stat(nom, dir_fd=dfd, follow_symlinks=False)
        return True
    except OSError:
        return False
    finally:
        os.close(dfd)


def write_json(dossier, nom, payload):
    # A random name opened O_EXCL: a predictable temporary name could be planted as a link.
    tmp = "." + nom + "." + secrets.token_hex(8)
    dfd = _ouvrir_dossier(dossier)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o644,
                     dir_fd=dfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.rename(tmp, nom, src_dir_fd=dfd, dst_dir_fd=dfd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
            raise
    finally:
        os.close(dfd)


def publish_catalogue():
    if PREVIEW:
        print("ctester: PREVIEW ACTIVE -- exercises not yet open are being published",
              file=sys.stderr, flush=True)
    if not (CONTENT and PUBLISHED):
        raise RuntimeError(
            "CTESTER_CONTENT and CTESTER_PUBLISHED are required to publish")
    import publish_content
    model = content_catalog.discover(CONTENT)
    maintenant = datetime.datetime(9999, 1, 1, tzinfo=datetime.timezone.utc) if PREVIEW else None
    import typst_build
    renders, (total, du_cache) = typst_build.render_all(model, PUBLISHED)
    if total:
        print("ctester: %d énoncé(s) Typst rendu(s), dont %d depuis le cache"
              % (total, du_cache), file=sys.stderr, flush=True)
    publish_content.publish(model, PUBLISHED, now=maintenant, renders=renders)
    return list(model["exercises"].values())


def tp_path(exercise_id, owner=None):
    """The only way from an exercise id to a path. Closed exercises need a moderator owner."""
    tout = PREVIEW or (bool(owner) and owner in MODERATEURS)
    entry = content_catalog.load_exercise(CONTENT, exercise_id, tout=tout)
    return entry["path"] if entry else None


def norm_bin(text):
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0b", "", s)
    return s if s and set(s) <= {"0", "1"} else None


def norm_hex(text):
    s = re.sub(r"[\s_]", "", str(text)).lower()
    s = re.sub(r"\A0x", "", s)
    s = re.sub(r"h\Z", "", s)
    try:
        return int(s, 16)
    except ValueError:
        return None


def norm_int(text):
    s = re.sub(r"[\s_]", "", str(text)).replace("−", "-")
    try:
        return int(s)
    except ValueError:
        return None


def check_answer(kind, given, expected):
    if kind == "bin8":
        got, want = norm_bin(given), norm_bin(expected)
        if got is None:
            return False, "ce n'est pas une suite de 0 et de 1"
        if got == want:
            return True, ""
        if want is not None and int(got, 2) == int(want, 2):
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


def extract_numbers(text):
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
    index = 0
    for want in expected:
        while index < len(numbers) and not close_enough(numbers[index], want, tol):
            index += 1
        if index >= len(numbers):
            return False
        index += 1
    return True


def fold(text):
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def check_case(case, output, tol):
    folded = fold(output)
    for word in case.get("absent", []):
        if fold(word) in folded:
            return "la sortie mentionne « " + word + " », qui ne devrait pas y etre"
    wanted = case.get("contains")
    if wanted and fold(wanted) not in folded:
        return "la sortie ne contient pas le mot attendu"
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
        if NONFINITE_RE.search(output):
            return ("ta sortie contient inf ou nan : division par zéro, ou une "
                    "variable utilisée alors que sa lecture a échoué. Vérifie "
                    "que ton programme lit exactement autant de valeurs que le "
                    "cas lui en fournit")
        if not numbers:
            return ("ta sortie ne contient aucun nombre : vérifie que tu "
                    "affiches bien le résultat, et que c'est le bon exercice")
        if len(numbers) < len(expected):
            return ("ta sortie ne contient que %d nombre%s, or ce cas en attend "
                    "%d : vérifie que tu affiches TOUTES les valeurs demandées "
                    "par l'énoncé" % (len(numbers),
                                      "" if len(numbers) == 1 else "s",
                                      len(expected)))
        return "la sortie ne contient pas les valeurs attendues, dans l'ordre"
    return ""


def split_runs(output, nonce):
    # Markers carry a per-job nonce, so a program cannot print fake case boundaries.
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
    if avertissements and resultat.get("status") != "compile_error":
        resultat["warnings"] = avertissements
    return resultat


def extraire_avertissements(output, nonce):
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
            reason = ("le programme a débordé de la mémoire qu'il a réservée "
                      "(voir le rapport ci-dessous : il nomme la ligne)")
        elif code != 0:
            reason = "le programme s'est terminé anormalement (code %d)" % code
        else:
            reason = check_case(case, text, tol)
        if reason:
            failed.append({
                "case": number,
                "stdin": case.get("stdin", ""),
                "stdout": text[:MAX_CASE_OUTPUT],
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


def forbidden_includes(code, allowed):
    # A course rule, not a security boundary: the regex also sees includes in comments.
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
    return os.path.join(CONTENT, "shared", "unity")


def _argv_durci(name, memory, pids, cpus, work, tmp, extra=()):
    # The two tmpfs mounts are the only writable surface. There is no seccomp profile:
    # write() cannot be filtered, so the read-only filesystem is the boundary.
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


def docker_argv(stage, tp_dir, name, mode, nonce=""):
    argv = _argv_durci(name, MEMORY, PIDS, CPUS, "32m", "16m") + [
        "-v", stage + "/src:/in/src:ro",
    ]
    argv += ["-e", "CTESTER_NONCE=" + nonce]
    for key, value in SANDBOX_ENV.items():
        argv += ["-e", key + "=" + value]
    # In io mode the tests are never mounted: inputs were extracted on the host.
    if mode == "io":
        argv += [
            "-v", stage + "/cases:/in/cases:ro",
            "-v", BUILD_IO + ":/in/build.sh:ro",
        ]
    else:
        argv += [
            "-v", tp_dir + ":/in/tests:ro",
            "-v", unity_dir() + ":/in/unity:ro",
            "-v", BUILD_UNITY + ":/in/build.sh:ro",
        ]
    return argv + [IMAGE, "bash", "/in/build.sh"]


def docker_argv_console(stage, name, nonce):
    argv = _argv_durci(name, CONSOLE_MEMORY, CONSOLE_PIDS, CONSOLE_CPUS,
                       "24m", "8m",
                       # -i only (docker refuses -t without a terminal); no log driver,
                       # or docker would record everything the student types.
                       extra=("--cpu-shares", CONSOLE_SHARES,
                              "--log-driver", "none", "-i"))
    argv += ["-e", "CTESTER_NONCE=" + nonce]
    for key, value in SANDBOX_ENV.items():
        argv += ["-e", key + "=" + value]
    argv += [
        "-v", stage + "/src:/in/src:ro",
        "-v", BUILD_SCRATCH + ":/in/build.sh:ro",
    ]
    return argv + [IMAGE, "bash", "/in/build.sh"]


def parse_unity(out):
    # Untrusted: student code shares the process and could print a fake summary.
    match = None
    for match in SUMMARY_RE.finditer(out):
        pass
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
    if rc == 10:
        return {
            "status": "compile_error",
            "message": "Ton fichier ne compile pas.",
            "gcc": out[:MAX_GCC_CHARS],
        }
    if rc == 11:
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


def stage_dir(job_dir):
    # Docker resolves -v paths itself, after any check the worker could make, so nothing is
    # mounted from the spool: sources are copied here first.
    stage = os.path.join(WORK, "jobs", os.path.basename(job_dir))
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, "src"))
    return stage


def sandbox(stage, tp_dir, mode, nonce=""):
    name = "ctester-" + os.path.basename(stage)[:16]
    try:
        done = subprocess.run(
            docker_argv(stage, tp_dir, name, mode, nonce),
            capture_output=True, text=True, errors="replace",
            timeout=JOB_TIMEOUT, check=False,
        )
        return done.returncode, done.stdout.replace("/in/src/", "")
    except subprocess.TimeoutExpired:
        # Killing the docker client leaves the container running.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       check=False)
        return 137, ""


CACHE_DIR = "cache"
CACHE_MAX = int(os.environ.get("CTESTER_CACHE_MAX", "20000"))

# Wall-clock limits depend on load, not on the code: caching them would freeze bad luck.
JAMAIS_EN_CACHE = frozenset(("timeout", "compile_timeout", "error"))


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
    out = []
    espace = False
    directive = False
    debut = True
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
    # Length prefix, so "ab" + "c" and "a" + "bc" hash differently.
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
        sous.sort()
        for nom in sorted(fichiers):
            chemin = os.path.join(dossier, nom)
            rel = os.path.relpath(chemin, racine).replace(os.sep, "/")
            _hacher_octets(condensat, rel.encode("utf-8"))
            _hacher_fichier(condensat, chemin)


def empreinte_juge(exercise_id, tp_dir, mode):
    condensat = hashlib.sha256()
    _hacher_octets(condensat, ("%s|%s" % (exercise_id, mode)).encode("utf-8"))
    _hacher_arbre(condensat, tp_dir)
    if mode == "unity":
        _hacher_arbre(condensat, unity_dir())
    _hacher_fichier(condensat,
                    os.path.join(tp_dir, os.pardir, "public", "files.json"))
    _hacher_fichier(condensat, BUILD_UNITY if mode == "unity" else BUILD_IO)
    # This file holds the grading logic, so editing it invalidates every cached verdict.
    _hacher_fichier(condensat, os.path.abspath(__file__))
    _hacher_octets(condensat, IMAGE.encode("utf-8"))
    _hacher_octets(condensat,
                   json.dumps(SANDBOX_ENV, sort_keys=True).encode("utf-8"))
    return condensat


def signature(exercise_id, tp_dir, mode, conf, sent, empreinte=None):
    condensat = (empreinte or empreinte_juge(exercise_id, tp_dir, mode)).copy()
    for declared in declared_files(conf, tp_dir):
        nom = declared["name"]
        _hacher_octets(condensat, nom.encode("utf-8"))
        _hacher_octets(condensat,
                       normaliser_c(str(sent.get(nom, ""))).encode("utf-8"))
    return condensat.hexdigest()


def cache_lire(sig):
    if CACHE_MAX <= 0:
        return None
    chemin = os.path.join(WORK, CACHE_DIR, sig + ".json")
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
        pass
    return verdict


def _elaguer_cache(dossier):
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


CACHE_PRUNE_EVERY = int(os.environ.get("CTESTER_CACHE_PRUNE_EVERY", "500"))
_ecritures = [0]


def cache_ecrire(sig, verdict):
    if CACHE_MAX <= 0:
        return
    dossier = os.path.join(WORK, CACHE_DIR)
    try:
        os.makedirs(dossier, exist_ok=True)
        write_json(dossier, sig + ".json", verdict)
    except OSError:
        return
    _ecritures[0] += 1
    if _ecritures[0] >= CACHE_PRUNE_EVERY:
        _ecritures[0] = 0
        _elaguer_cache(dossier)


def cachable(conf, verdict):
    return (bool(conf.get("cache", True))
            and isinstance(verdict, dict)
            and verdict.get("status") not in JAMAIS_EN_CACHE)


_SIGS = {}


def _sig_du_job(job_dir, exercise_id, tp_dir, mode, conf, empreinte):
    marque = empreinte.hexdigest()
    connu = _SIGS.get(job_dir)
    if connu is not None and connu[0] == marque:
        return connu[1]
    try:
        sent = lire_json(job_dir, "files.json")
    except (OSError, ValueError):
        return None
    if not isinstance(sent, dict):
        return None
    sig = signature(exercise_id, tp_dir, mode, conf, sent, empreinte)
    _SIGS[job_dir] = (marque, sig)
    return sig


def servir_les_connus():
    """Serves every already-known verdict before compiling anything."""
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
        try:
            write_result(job_dir, dict(verdict))
        except OSError:
            continue
        servis += 1
    for parti in set(_SIGS) - vivants:
        del _SIGS[parti]
    return servis


def _contexte(exercise_id):
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


def verrou_tenu(dossier, nom):
    # Read-only on purpose: flock needs no write access, and the lock files belong to
    # different users (the API runs as nobody, the worker as root). No O_CREAT: the API
    # creates `alive`, and a missing one means the session is gone.
    try:
        fd = _ouvrir(dossier, nom, os.O_RDONLY)
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


def _job_champ(job_dir, champ):
    try:
        return str(lire_json(job_dir, "job.json").get(champ, ""))
    except (OSError, ValueError, AttributeError):
        return ""


def job_kind(job_dir):
    return _job_champ(job_dir, "kind")


def console_lock():
    # One console session for the whole service, so the other worker keeps grading.
    chemin = os.path.join(SPOOL, CONSOLE_LOCK)
    try:
        os.mkdir(chemin)
        return True
    except FileExistsError:
        try:
            age = time.time() - os.lstat(chemin).st_mtime
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
    payload = {"state": etat}
    payload.update(extra)
    try:
        write_json(job_dir, "state.json", payload)
    except OSError:
        pass


def _pompe_sortie(proc, job_dir, nonce, compteur):
    separateur = (nonce + " RUN\n").encode()
    # The buffer keeps a tail between reads, so a marker split across two reads is still found.
    garde = len(separateur) - 1
    tampon, en_build = b"", True
    ajout = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    try:
        build = os.fdopen(_ouvrir(job_dir, "build", ajout), "ab", buffering=0)
    except OSError:
        # Only a planted entry gets here; flagging the cap ends the session at once.
        compteur["trop"] = True
        return
    try:
        sortie = os.fdopen(_ouvrir(job_dir, "out", ajout), "ab", buffering=0)
    except OSError:
        build.close()
        compteur["trop"] = True
        return

    def ecrire(fh, octets):
        if not octets:
            return
        if fh is sortie:
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
    nom = "ctester-sbx-" + os.path.basename(job_dir)[:16]
    nonce = uuid.uuid4().hex
    compteur = {"octets": 0, "trop": False, "vu": time.time(), "compile": False}

    if not os.path.isfile(BUILD_SCRATCH):
        print("ctester: console: CTESTER_BUILD_SCRATCH introuvable (%s)"
              % BUILD_SCRATCH, file=sys.stderr, flush=True)
        console_etat(job_dir, "exited", code=-1, reason="build_missing")
        return {"status": "console", "code": -1, "reason": "build_missing"}

    if not verrou_tenu(job_dir, "alive"):
        console_etat(job_dir, "exited", code=-1, reason="api")
        return {"status": "console", "code": -1, "reason": "api"}

    try:
        revendication = _ouvrir(job_dir, "claim", os.O_RDWR | os.O_CREAT)
    except OSError:
        console_etat(job_dir, "exited", code=-1, reason="worker")
        return {"status": "console", "code": -1, "reason": "worker"}
    pris = False
    for _ in range(100):
        try:
            fcntl.flock(revendication, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pris = True
            break
        except OSError:
            time.sleep(0.01)
    if not pris:
        print("ctester: console: claim deja tenu sur %s" % job_dir,
              file=sys.stderr, flush=True)
        os.close(revendication)
        console_etat(job_dir, "exited", code=-1, reason="worker")
        return {"status": "console", "code": -1, "reason": "worker"}

    try:
        stage = stage_dir(job_dir)
        with open(os.path.join(stage, "src", "main.c"), "wb") as fh:
            fh.write(lire_octets(job_dir, "src/main.c"))
    except OSError as exc:
        print("ctester: console: %s: %s" % (job_dir, exc), file=sys.stderr,
              flush=True)
        shutil.rmtree(os.path.join(WORK, "jobs", os.path.basename(job_dir)),
                      ignore_errors=True)
        os.close(revendication)
        console_etat(job_dir, "exited", code=-1, reason="worker")
        return {"status": "console", "code": -1, "reason": "worker"}

    console_etat(job_dir, "compiling", ttl=CONSOLE_SESSION_MAX)
    proc = subprocess.Popen(docker_argv_console(stage, nom, nonce),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    pompe = threading.Thread(target=_pompe_sortie,
                             args=(proc, job_dir, nonce, compteur), daemon=True)
    pompe.start()

    debut, lu, raison, annonce = time.time(), 0, "exited", False
    ferme = False
    try:
        while proc.poll() is None:
            paquet = b""
            if lu < CONSOLE_IN_MAX:
                try:
                    fd = _ouvrir(job_dir, "in", os.O_RDONLY)
                    try:
                        paquet = os.pread(fd, min(65536, CONSOLE_IN_MAX - lu), lu)
                    finally:
                        os.close(fd)
                except OSError:
                    paquet = b""
            if paquet:
                lu += len(paquet)
                compteur["vu"] = time.time()
                try:
                    proc.stdin.write(paquet)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            if not ferme and existe(job_dir, "eof"):
                ferme = True
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if not verrou_tenu(job_dir, "alive"):
                raison = "api"
                break
            if time.time() - debut > CONSOLE_SESSION_MAX:
                raison = "timeout"
                break
            if time.time() - compteur["vu"] > CONSOLE_IDLE_MAX:
                raison = "idle"
                break
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
        # proc.kill() alone would only kill the docker client.
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
        shutil.rmtree(stage, ignore_errors=True)

    code = proc.returncode if proc.returncode is not None else -1
    if raison == "exited" and not compteur["compile"]:
        raison = "compile_timeout" if code == 12 else "compile_error"
    console_etat(job_dir, "exited", code=code, reason=raison)
    try:
        os.close(revendication)
    except OSError:
        pass
    return {"status": "console", "code": code, "reason": raison}


def job_exercice(job_dir):
    return _job_champ(job_dir, "exercise_id")


def job_owner(job_dir):
    return _job_champ(job_dir, "owner")


def run_job(job_dir):
    exercise_id = job_exercice(job_dir)
    tp_dir = tp_path(exercise_id, job_owner(job_dir))
    if tp_dir is None:
        return {"status": "error", "message": "Exercice inconnu."}
    mode = detect_mode(tp_dir)
    if mode is None:
        return {"status": "error", "message": "Ce TP n'a pas de tests publiés."}

    if mode == "quiz":
        answers = lire_json(job_dir, "answers.json")
        return grade_quiz(load_config(tp_dir, "quiz.json"), answers)

    conf = load_config(tp_dir, config_name(mode))
    sent = lire_json(job_dir, "files.json")

    empreinte = empreinte_juge(exercise_id, tp_dir, mode)
    sig = signature(exercise_id, tp_dir, mode, conf, sent, empreinte)
    connu = cache_lire(sig)
    if connu is not None:
        print("ctester: cache servi %s %s [dépilé]" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
        return connu

    resultat = _juger(job_dir, tp_dir, mode, conf, sent)
    if cachable(conf, resultat):
        cache_ecrire(sig, resultat)
        print("ctester: cache écrit %s %s" % (exercise_id, sig[:12]),
              file=sys.stderr, flush=True)
    elif isinstance(resultat, dict):
        resultat["rejouer"] = True
    return resultat


def _juger(job_dir, tp_dir, mode, conf, sent):
    stage = stage_dir(job_dir)
    try:
        return _juger_dans(stage, tp_dir, mode, conf, sent)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _juger_dans(stage, tp_dir, mode, conf, sent):
    src_dir = os.path.join(stage, "src")
    code = ""
    for declared in declared_files(conf, tp_dir):
        contenu = str(sent.get(declared["name"], ""))
        code += contenu + "\n"
        with open(os.path.join(src_dir, declared["name"]), "w",
                  encoding="utf-8") as fh:
            fh.write(contenu)

    allowed = read_allowed(tp_dir)
    if allowed is not None:
        allowed = allowed | {f["name"] for f in declared_files(conf, tp_dir)}

    bad = forbidden_includes(code, allowed)
    if bad:
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
        case_dir = os.path.join(stage, "cases")
        os.makedirs(case_dir)
        for number, case in enumerate(cases, 1):
            with open(os.path.join(case_dir, "%02d.in" % number), "w",
                      encoding="utf-8") as fh:
                fh.write(case.get("stdin", ""))
        nonce = uuid.uuid4().hex
        rc, out = sandbox(stage, tp_dir, mode, nonce)
        avertissements, out = extraire_avertissements(out, nonce)
        resultat = verdict_io(rc, out, cases, nonce, tol)
        return avec_avertissements(resultat, avertissements)

    nonce = uuid.uuid4().hex
    rc, out = sandbox(stage, tp_dir, mode, nonce)
    avertissements, out = extraire_avertissements(out, nonce)
    return avec_avertissements(verdict(rc, out), avertissements)


def write_result(job_dir, payload):
    payload["state"] = "done"
    write_json(job_dir, "result.json", payload)


DURATIONS = "durees.json"

DUREE_FENETRE = 20
DUREE_MIN = 0.5


def lire_durees():
    try:
        data = lire_json(SPOOL, DURATIONS)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enregistrer_duree(exercise_id, secondes):
    # Jobs rejected before a container starts are skipped: they would drag the average to zero.
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
        write_json(SPOOL, DURATIONS, durees)
    except OSError:
        pass


def _dans_le_job(job_dir, action):
    try:
        dfd = _ouvrir_dossier(job_dir)
    except OSError:
        return None
    try:
        return action(dfd)
    except OSError:
        return None
    finally:
        os.close(dfd)


def claim(job_dir):
    # mkdir is atomic, which is all the locking workers on a single host need.
    return _dans_le_job(job_dir, lambda dfd: os.mkdir(".lock", dir_fd=dfd) or True) is True


def reprises(job_dir):
    try:
        return int(lire_json(job_dir, "reprises.json").get("n", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def reclaim(job_dir, now):
    age = _dans_le_job(job_dir, lambda dfd: os.stat(
        ".lock", dir_fd=dfd, follow_symlinks=False).st_mtime)
    if age is None or age > now - LOCK_STALE:
        return False

    essai = reprises(job_dir) + 1
    try:
        if essai > LOCK_RETRIES:
            print("ctester: %s: abandoned after %d reclaim(s)" % (job_dir, essai - 1),
                  file=sys.stderr, flush=True)
            write_result(job_dir, {
                "status": "error",
                "message": "Le juge a été interrompu pendant ce test. Relance-le.",
            })
            return False

        # Counted before the rmdir, so a worker dying in between still uses up the attempt.
        write_json(job_dir, "reprises.json", {"n": essai})
    except OSError:
        return False
    if _dans_le_job(job_dir, lambda dfd: os.rmdir(".lock", dir_fd=dfd) or True) is not True:
        return False
    print("ctester: %s: stale lock reclaimed (attempt %d)" % (job_dir, essai),
          file=sys.stderr, flush=True)
    return True


def pending_jobs():
    jobs = []
    for entry in os.scandir(SPOOL):
        try:
            if not (JOB_RE.match(entry.name) and entry.is_dir(follow_symlinks=False)):
                continue
            job = os.lstat(os.path.join(entry.path, "job.json"))
        except OSError:
            continue
        if not stat.S_ISREG(job.st_mode) or os.path.lexists(
            os.path.join(entry.path, "result.json")
        ):
            continue
        jobs.append((job.st_mtime, entry.path))
    jobs.sort()
    return [path for _, path in jobs]


def sweep(now):
    for racine in (SPOOL, os.path.join(WORK, "jobs")):
        try:
            entries = list(os.scandir(racine))
        except OSError:
            continue
        for entry in entries:
            try:
                if (entry.is_dir(follow_symlinks=False)
                        and entry.stat(follow_symlinks=False).st_mtime < now - SWEEP_AFTER):
                    shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:
                continue


def main():
    if not plateforme_sure():
        raise SystemExit("ctester: refusing to start: this platform cannot open the spool "
                         "without following links (need Linux, dir_fd, O_NOFOLLOW)")
    os.makedirs(SPOOL, exist_ok=True)
    os.makedirs(os.path.join(WORK, "jobs"), exist_ok=True)
    try:
        published = publish_catalogue()
        print("ctester: %d exercises published" % len(published), file=sys.stderr,
              flush=True)
    except (OSError, ValueError) as exc:
        print("ctester: catalog: %s" % exc, file=sys.stderr, flush=True)
    jour = datetime.date.today()
    while True:
        if datetime.date.today() != jour:
            jour = datetime.date.today()
            try:
                publish_catalogue()
            except (OSError, ValueError) as exc:
                print("ctester: catalog: %s" % exc, file=sys.stderr, flush=True)
        # Known verdicts first, then a single compilation per pass.
        worked = bool(servir_les_connus())
        for job_dir in pending_jobs():
            console = job_kind(job_dir) == "console"
            if console and not console_lock():
                continue
            if not claim(job_dir):
                if not (reclaim(job_dir, time.time()) and claim(job_dir)):
                    if console:
                        console_unlock()
                    continue
            worked = True
            debut = time.time()
            try:
                if console:
                    write_result(job_dir, run_console(job_dir))
                    enregistrer_duree(CONSOLE_DUREE, time.time() - debut)
                else:
                    write_result(job_dir, run_job(job_dir))
                    enregistrer_duree(job_exercice(job_dir), time.time() - debut)
            except Exception as exc:  # noqa: BLE001 -- a job must not kill the worker
                print("ctester: %s: %s" % (job_dir, exc), file=sys.stderr,
                      flush=True)
                try:
                    write_result(job_dir, {
                        "status": "error",
                        "message": "Erreur interne du juge. Réessaie.",
                    })
                except OSError:
                    pass
                if console:
                    console_etat(job_dir, "exited", code=-1, reason="worker")
            finally:
                if console:
                    console_unlock()
            break
        sweep(time.time())
        if not worked:
            time.sleep(0.5)


if __name__ == "__main__":
    main()
