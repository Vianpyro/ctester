#!/usr/bin/env python3
"""Validate the v2 content contract before publishing it.

Usage: ``python3 validate_content.py /path/to/content``.
Schema only: reference solutions are exercised by `verify_content.py`. It is
deliberately dependency-free so it can run in CI and on the controller.
"""

import argparse
import sys

import content_catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description="validate ctester v2 content")
    parser.add_argument("root", help="root containing catalog.json and exercises/")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
    except content_catalog.ContentValidationError as exc:
        print("invalid content:", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("valid content: %d exercise(s), %d collection(s)" %
          (len(model["exercises"]), len(model["collections"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
