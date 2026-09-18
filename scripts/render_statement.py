#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
import typst_build  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="render one Typst statement")
    parser.add_argument("exercise", help="the exercise directory (the one with statement.typ)")
    parser.add_argument("--out", default="", help="where to write the pages")
    parser.add_argument("--png", action="store_true",
                        help="render PNG instead of SVG, to eyeball it")
    parser.add_argument("--theme", choices=typst_build.THEMES + ("both",),
                        default="both", help="which theme to render")
    args = parser.parse_args(argv)

    try:
        kind, _ = typst_build.statement_of(args.exercise)
    except typst_build.TypstError as exc:
        print("%s: %s" % (args.exercise, exc), file=sys.stderr)
        return 1
    if kind != "typ":
        print("%s has a statement.md: there is nothing to compile, the page "
              "renders it itself." % args.exercise, file=sys.stderr)
        return 1

    output = args.out or tempfile.mkdtemp(prefix="ctester-preview-")
    os.makedirs(output, exist_ok=True)
    themes = typst_build.THEMES if args.theme == "both" else (args.theme,)

    if args.png:
        return _png(args.exercise, output, themes)

    try:
        rendered, cached = typst_build.render(args.exercise,
                                             os.path.basename(os.path.abspath(args.exercise)))
    except typst_build.TypstError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    written = []
    for theme in themes:
        for number, data in enumerate(rendered[theme], 1):
            path = os.path.join(output, "%s-%d.svg" % (theme, number))
            with open(path, "wb") as fh:
                fh.write(data)
            written.append(path)
    if rendered.get("html"):
        path = os.path.join(output, "statement.html")
        with open(path, "wb") as fh:
            fh.write(rendered["html"])
        written.append(path)
    print("%d page(s) per theme%s" % (len(rendered[themes[0]]),
                                      " (from the cache)" if cached else ""))
    for path in written:
        print("  " + path)
    return 0


def _png(exercise, output, themes):
    workdir = tempfile.mkdtemp(prefix="ctester-typst-")
    try:
        typst_build._prepare(exercise, workdir)
        for theme in themes:
            argv, env, cwd = typst_build._argv(workdir, theme)
            argv = [a.replace("svg", "png") if a in ("svg", theme + "-{p}.svg") else a
                    for a in argv]
            argv += ["--ppi", "200"]
            done = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=typst_build.TIMEOUT, env=env, cwd=cwd)
            if done.returncode != 0:
                print((done.stderr or done.stdout).strip(), file=sys.stderr)
                return 1
        for name in sorted(os.listdir(workdir)):
            if name.endswith(".png"):
                shutil.copy2(os.path.join(workdir, name), os.path.join(output, name))
                print("  " + os.path.join(output, name))
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
