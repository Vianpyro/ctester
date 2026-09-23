#!/usr/bin/env python3
"""Write a small demo content root and publish it with the production pipeline.

CI's Lighthouse run needs real content to render, and it also gives a working local site:

    python3 scripts/demo_content.py --out /tmp/ctester-demo
    CTESTER_KEY=dev CTESTER_PUBLISHED=/tmp/ctester-demo/published \
    CTESTER_PAGE=frontend/dist CTESTER_SPOOL=/tmp/ctester-demo/spool \
    CTESTER_RESULTS=/tmp/ctester-demo/results python3 app/main.py
"""

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "worker"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from demo_content_data import (  # noqa: E402
    CARDS, COLLECTIONS, EXERCISES, QUIZ_ASKED, QUIZ_ID, QUIZ_QUESTIONS,
    SKILLS, STATEMENT, UNITY_STATEMENT,
)

# The engine's stand-in for Unity, so the demo base builds from a bare clone. A real
# content base vendors the framework itself at shared/unity.
UNITY_SOURCE = os.path.join(ROOT, "tests", "fixture", "unity")

DEFAULT_FILES = [{"name": "main.c", "template":
                  "#include <stdio.h>\n\nint main(void) {\n"
                  "    // Écris ton code ici\n    return 0;\n}\n"}]


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_content(root):
    write(os.path.join(root, "catalog.json"), {"schema_version": 1, "skills": SKILLS})
    write(os.path.join(root, "cards.json"), {"schema_version": 1, "cards": CARDS})

    for exercise in EXERCISES:
        ident, mode = exercise["id"], exercise["mode"]
        directory = os.path.join(root, "exercises", ident)
        write(os.path.join(directory, "exercise.json"),
              {"schema_version": 1, "id": ident, "title": exercise["title"],
               "skills": exercise["skills"], "difficulty": exercise["difficulty"],
               "release": {"state": "available"}})
        assessment = os.path.join(directory, "assessment")

        if mode == "quiz":
            write_text(os.path.join(directory, "statement.md"), STATEMENT % QUIZ_ASKED)
            write(os.path.join(assessment, "quiz.json"), {"questions": QUIZ_QUESTIONS})
            continue

        # Every exercise carries its reference solution: verify_content.py compiles each
        # against its own tests, the only proof that a test accepts a correct answer.
        if mode == "unity":
            write_text(os.path.join(directory, "statement.md"), UNITY_STATEMENT)
            write(os.path.join(assessment, "unity.json"), {})
            for name, text in exercise["tests"].items():
                write_text(os.path.join(assessment, name), text)
            for name, text in exercise["solution"].items():
                write_text(os.path.join(directory, "solution", name), text)
        else:
            write_text(os.path.join(directory, "statement.md"),
                       STATEMENT % exercise["asked"])
            write(os.path.join(assessment, "io.json"), {"cases": exercise["cases"]})
            write_text(os.path.join(directory, "solution", "main.c"),
                       exercise["solution"])
        write(os.path.join(directory, "public", "files.json"),
              {"files": exercise.get("files", DEFAULT_FILES)})

    if any(e["mode"] == "unity" for e in EXERCISES):
        unity = os.path.join(root, "shared", "unity")
        os.makedirs(unity, exist_ok=True)
        for name in sorted(os.listdir(UNITY_SOURCE)):
            shutil.copyfile(os.path.join(UNITY_SOURCE, name), os.path.join(unity, name))

    for ident, title, items in COLLECTIONS:
        write(os.path.join(root, "collections", ident + ".json"),
              {"schema_version": 1, "id": ident, "title": title, "items": items,
               "release": {"state": "available"}})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "demo"),
                        help="directory to hold content/ and published/")
    args = parser.parse_args(argv)

    import publish_content

    root = os.path.join(args.out, "content")
    dest = os.path.join(args.out, "published")
    write_content(root)
    # --no-render: every statement here is Markdown, so there is nothing for Typst to do
    # and no reason to need its binary.
    code = publish_content.main([root, dest, "--no-render"])
    if code:
        return code
    print("demo content published to %s (quiz: %s)" % (dest, QUIZ_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
