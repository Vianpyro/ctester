#!/usr/bin/env python3

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
import content_catalog  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="validate ctester v2 content")
    parser.add_argument("root", nargs="+",
                        help="root(s) containing catalog.json and exercises/")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
    except content_catalog.ContentValidationError as exc:
        print("invalid content:", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("valid content: %d exercise(s), %d collection(s), %d assignment(s)" %
          (len(model["exercises"]), len(model["collections"]),
           len(model.get("assignments", {}))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
