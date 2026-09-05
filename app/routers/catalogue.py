"""Le catalogue public : la liste des exercices, une consigne, un quiz.

CES TROIS ROUTES SONT ANONYMES, et c'est le cœur de ctester : un étudiant colle
son code et soumet sans compte. Rien ici ne lit un jeton.

AUCUN CORRIGÉ NE PASSE PAR ICI. La release servie a déjà été reconstruite champ
à champ par `publish_content.py`, qui relit sa propre projection et refuse de
publier si une clé privée y apparaît -- et le runbook repasse un `grep` après
chaque déploiement.
"""

import headers
from fastapi import APIRouter, Request
from services import catalogue

router = APIRouter(tags=["catalogue"])


@router.get("/catalog.json")
def catalog(request: Request):
    """Le catalogue : collections, exercices, accès, cadenas et dates.

    RELU À CHAQUE FOIS, pas mis en cache au démarrage : publier un exercice est
    alors `--tags tests` et rien d'autre. Une valeur en cache voudrait dire
    recréer le conteneur pour ajouter une ligne à un menu, et c'est le genre
    d'étape qu'on oublie le soir où on ajoute le TP4.
    """
    release = catalogue.release_dir()
    if release is None:
        return headers.erreur(404, "catalogue absent")
    return headers.fichier_du_disque(request, release, "catalog.json",
                                     "application/json; charset=utf-8")


@router.get("/tp/{exercise_id}.json")
def detail(exercise_id: str, request: Request):
    """La consigne et les gabarits d'un exercice.

    `find_exercise` est la SEULE porte : elle refuse ce qui n'est pas un
    exercice ouvert du catalogue, donc `/tp/../catalog.json` n'est pas un chemin
    à traverser mais un identifiant qui n'existe pas.

    ponytail: l'URL garde son `/tp/` historique. Elle vit dans le cache des
    étudiants et ne coûte rien ; la renommer se fera avec `/exercises/<id>`,
    quand la page passera aux liens profonds `/exercise/<id>`.
    """
    entry = catalogue.find_exercise(exercise_id)
    if entry is None:
        return headers.erreur(404, "inconnu")
    base, nom = catalogue.source_publiee(entry, "detail")
    if base is None:
        return headers.erreur(404, "inconnu")
    return headers.fichier_du_disque(request, base, nom,
                                     "application/json; charset=utf-8")


@router.get("/quiz/{exercise_id}.json")
def quiz(exercise_id: str, request: Request):
    """Les questions d'un quiz, telles que le worker les a publiées.

    Le chemin est reconstruit à partir du catalogue, jamais concaténé depuis
    l'URL. Le mode est vérifié en plus de l'existence : un exercice de code
    n'expose pas de fichier de quiz.
    """
    entry = catalogue.find_exercise(exercise_id)
    if entry is None or entry.get("mode") != "quiz":
        return headers.erreur(404, "pas un quiz")
    base, nom = catalogue.source_publiee(entry, "quiz")
    if base is None:
        return headers.erreur(404, "pas un quiz")
    return headers.fichier_du_disque(request, base, nom,
                                     "application/json; charset=utf-8")
