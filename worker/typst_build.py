"""Renders Typst statements to SVG and HTML at publish time, never per request.

Standard library only: test_ctester.py imports it on the host.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PACKAGES = os.path.join(ROOT, "typst", "packages")
LIB = os.path.join(PACKAGES, "local", "ctester", "1.0.0")

FONTS = os.path.join(ROOT, "typst", "fonts")

IMAGE = os.environ.get("CTESTER_TYPST_IMAGE", "ghcr.io/typst/typst:0.15.1")
BIN = os.environ.get("CTESTER_TYPST_BIN", "")

# Checked against the engine: the binary and the image report the version differently,
# so only the number is compared.
VERSION = "0.15.1"
_VERSION_RE = re.compile(r"\btypst\s+(\d+\.\d+\.\d+)")

# An SVG cannot follow prefers-color-scheme, so each statement is rendered twice.
THEMES = ("dark", "light")

# Never copied next to the source, so typst cannot read the tests even through --root.
EXCLUDED = frozenset(("assessment", "public", "exercise.json", "statement.md"))

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
            "statement.md AND statement.typ are both present: exactly one "
            "is allowed. Delete the one you no longer use.")
    if b:
        return "typ", typ
    if a:
        with open(md, encoding="utf-8") as fh:
            return "md", fh.read()
    raise TypstError("statement.md or statement.typ is missing")


def _version():
    argv = [BIN, "--version"] if BIN else ["docker", "run", "--rm", IMAGE, "--version"]
    try:
        output = subprocess.run(argv, capture_output=True, timeout=TIMEOUT,
                                text=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise TypstError(
            "typst was not found (%s). Point CTESTER_TYPST_BIN at a binary, "
            "or let Docker pull %s." % (exc, IMAGE))
    found = _VERSION_RE.search(output or "")
    if found is None:
        raise TypstError("typst does not report its version: %r" % (output,))
    if found.group(1) != VERSION:
        raise TypstError(
            "typst %s expected, %s found. The version is pinned in "
            "worker/typst_build.py (VERSION) and in the Ansible role "
            "(ctester_typst_image): a statement must render the same in six "
            "months." % (VERSION, found.group(1)))
    return found.group(1)


def _hash_tree(h, root, excluded=frozenset()):
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in excluded)
        for name in sorted(names):
            if name in excluded:
                continue
            path = os.path.join(directory, name)
            h.update(os.path.relpath(path, root).replace(os.sep, "/").encode())
            h.update(b"\0")
            with open(path, "rb") as fh:
                h.update(fh.read())
            h.update(b"\0")


def fingerprint(exercise_dir, version=None):
    h = hashlib.sha256()
    h.update(b"ctester-typst-1\0")
    h.update((version or _version()).encode())
    h.update(b"\0")
    _hash_tree(h, PACKAGES)
    h.update(b"\0")
    _hash_tree(h, FONTS)
    h.update(b"\0")
    _hash_tree(h, exercise_dir, EXCLUDED)
    return h.hexdigest()[:16]


def cache_dir(published=""):
    # Outside published/, which keeps only the latest releases and would wipe the cache.
    cache_setting = os.environ.get("CTESTER_TYPST_CACHE", "")
    if cache_setting:
        return cache_setting
    published_dir = published or os.environ.get("CTESTER_PUBLISHED", "")
    if published_dir:
        return os.path.join(os.path.dirname(os.path.abspath(published_dir)), "typst-cache")
    return os.path.join(tempfile.gettempdir(), "ctester-typst-cache")


def _prepare(exercise_dir, workdir):
    for name in sorted(os.listdir(exercise_dir)):
        if name in EXCLUDED:
            continue
        source = os.path.join(exercise_dir, name)
        target = os.path.join(workdir, name)
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    with open(os.path.join(workdir, "main.typ"), "w", encoding="utf-8") as fh:
        fh.write('#import "@local/ctester:1.0.0": statement\n'
                 "#show: statement\n"
                 '#include "statement.typ"\n')


def _argv(workdir, theme):
    if theme == "html":
        return _command(workdir, ["--features", "html", "--format", "html"],
                         "statement.html")
    return _command(workdir, ["--input", "theme=" + theme, "--format", "svg"],
                     theme + "-{p}.svg")


def _command(workdir, options, output):
    common = ["compile", "--ignore-system-fonts", "--root", "."] + options
    if BIN:
        return [BIN] + common + ["--font-path", FONTS,
                                 "main.typ", output], dict(
            os.environ, TYPST_PACKAGE_PATH=PACKAGES), workdir
    return ["docker", "run", "--rm", "--network=none", "--read-only",
            "--user", "%d:%d" % (os.getuid(), os.getgid()),
            "-e", "TYPST_PACKAGE_PATH=/pkg",
            "-v", PACKAGES + ":/pkg:ro",
            "-v", FONTS + ":/fonts:ro",
            "-v", workdir + ":/work",
            "-w", "/work", IMAGE] + common + ["--font-path", "/fonts",
                                              "main.typ", output], \
        dict(os.environ), None


def render(exercise_dir, exercise_id, version=None, published=""):
    key = fingerprint(exercise_dir, version)
    cache = cache_dir(published)
    store = os.path.join(cache, key)
    saved = _read_cache(store)
    if saved is not None:
        return saved, True

    os.makedirs(cache, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="ctester-typst-", dir=cache)
    try:
        _prepare(exercise_dir, workdir)
        rendered = {}
        for theme in THEMES:
            argv, env, cwd = _argv(workdir, theme)
            try:
                done = subprocess.run(argv, capture_output=True, text=True,
                                     timeout=TIMEOUT, env=env, cwd=cwd)
            except subprocess.TimeoutExpired:
                raise TypstError(
                    "%s: statement.typ did not compile within %d s. A statement in the "
                    "repository takes 0.6 s; this is a pathological document, not "
                    "a slow machine." % (exercise_id, TIMEOUT))
            except OSError as exc:
                raise TypstError("%s: the typst engine is unreachable (%s)"
                                 % (exercise_id, exc))
            if done.returncode != 0:
                raise TypstError("%s/statement.typ did not compile:\n%s"
                                 % (exercise_id, (done.stderr or done.stdout).strip()))
            rendered[theme] = _reread_pages(workdir, theme, exercise_id)
        if len(rendered["dark"]) != len(rendered["light"]):
            raise TypstError(
                "%s: %d page(s) in dark against %d in light. The theme must "
                "not change the pagination: look for a table or an image "
                "that overflows." % (exercise_id, len(rendered["dark"]),
                                  len(rendered["light"])))
        # HTML export is experimental: a failure or a lossy export falls back to SVG only.
        argv, env, cwd = _argv(workdir, "html")
        try:
            done = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=TIMEOUT, env=env, cwd=cwd)
            path = os.path.join(workdir, "statement.html")
            lost = [l for l in (done.stderr or "").splitlines()
                      if "ignored during HTML export" in l
                      and "pagebreak" not in l]
            if lost:
                print("ctester: %s: incomplete HTML render, SVG only:\n%s"
                      % (exercise_id, "\n".join(lost)))
            elif done.returncode == 0 and os.path.isfile(path):
                with open(path, "rb") as fh:
                    rendered["html"] = fh.read()
            else:
                print("ctester: %s: HTML render skipped:\n%s"
                      % (exercise_id, (done.stderr or done.stdout).strip()))
        except (OSError, subprocess.SubprocessError) as exc:
            print("ctester: %s: HTML render skipped (%s)" % (exercise_id, exc))
        _write_cache(store, rendered)
        return rendered, False
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _reread_pages(workdir, theme, exercise_id):
    pages = []
    for number in range(1, MAX_PAGES + 2):
        path = os.path.join(workdir, "%s-%d.svg" % (theme, number))
        if not os.path.isfile(path):
            break
        if number > MAX_PAGES:
            raise TypstError("%s: more than %d statement pages"
                             % (exercise_id, MAX_PAGES))
        with open(path, "rb") as fh:
            pages.append(fh.read())
    if not pages:
        raise TypstError("%s: typst wrote no page" % exercise_id)
    return pages


def _read_cache(store):
    if not os.path.isdir(store):
        return None
    rendered = {}
    for theme in THEMES:
        pages = []
        for number in range(1, MAX_PAGES + 1):
            path = os.path.join(store, "%s-%d.svg" % (theme, number))
            if not os.path.isfile(path):
                break
            with open(path, "rb") as fh:
                pages.append(fh.read())
        if not pages:
            return None
        rendered[theme] = pages
    html = os.path.join(store, "statement.html")
    if os.path.isfile(html):
        with open(html, "rb") as fh:
            rendered["html"] = fh.read()
    return rendered


def _write_cache(store, rendered):
    temporary = store + ".tmp.%d" % os.getpid()
    shutil.rmtree(temporary, ignore_errors=True)
    try:
        os.makedirs(temporary, exist_ok=True)
        if rendered.get("html"):
            with open(os.path.join(temporary, "statement.html"), "wb") as fh:
                fh.write(rendered["html"])
        for theme in THEMES:
            for number, data in enumerate(rendered[theme], 1):
                with open(os.path.join(temporary, "%s-%d.svg" % (theme, number)),
                          "wb") as fh:
                    fh.write(data)
        # Renamed into place so two workers never read a half-written entry.
        os.replace(temporary, store)
    except OSError:
        shutil.rmtree(temporary, ignore_errors=True)


def render_all(model, published=""):
    typst = [(key, entry) for key, entry in sorted(model["exercises"].items())
             if entry.get("statement_format") == "typ"]
    if not typst:
        return {}, (0, 0)
    version = _version()
    renders, served = {}, 0
    for exercise_id, entry in typst:
        pages, cached = render(entry["path"], exercise_id, version, published)
        renders[exercise_id] = pages
        served += 1 if cached else 0
    return renders, (len(typst), served)
