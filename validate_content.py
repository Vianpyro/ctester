#!/usr/bin/env python3
"""Valider le contrat de contenu v2 avant de le publier.

Usage : ``python3 validate_content.py /chemin/vers/content``.
Cette commande ne compile pas encore les solutions : cette étape sera raccordée
au validateur existant pendant la migration des contenus historiques. Elle est
volontairement sans dépendance tierce pour tourner en CI et sur le contrôleur.
"""

import argparse
import sys

import content_catalogue


def main(argv=None):
    parser = argparse.ArgumentParser(description="valide le contenu ctester v2")
    parser.add_argument("root", help="racine contenant catalog.json et exercises/")
    args = parser.parse_args(argv)
    try:
        model = content_catalogue.discover(args.root)
    except content_catalogue.ContentValidationError as exc:
        print("contenu invalide :", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("contenu valide : %d exercice(s), %d collection(s)" %
          (len(model["exercises"]), len(model["collections"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
