"""Le catalogue public : la liste des exercices, une consigne, un quiz.

CES TROIS ROUTES SONT ANONYMES, et c'est le cœur de ctester : un étudiant colle
son code et soumet sans compte. Rien ici ne lit un jeton.

AUCUN CORRIGÉ NE PASSE PAR ICI. Ce que le worker publie sous `config.STATIC` a
déjà été filtré par `publish_catalogue()` / `public_quiz()` dans `runner.py` --
la clé `answer` d'un quiz ne franchit pas cette frontière, et le runbook le
vérifie par un `grep` après chaque déploiement.
"""

import json
import os

import config
import headers
from fastapi import APIRouter, Request
from services import catalogue

router = APIRouter(tags=["catalogue"])


@router.get("/tps.json")
def tps(request: Request):
    """La liste des exercices ouverts.

    RELUE À CHAQUE FOIS, pas mise en cache au démarrage : publier un nouveau TP
    est alors `--tags tests` et rien d'autre. Une valeur en cache voudrait dire
    recréer le conteneur pour ajouter une ligne à un menu déroulant, et c'est le
    genre d'étape qu'on oublie le soir où on ajoute le TP4.
    """
    return headers.fichier(request, json.dumps(catalogue.load_tps()).encode(),
                           "application/json; charset=utf-8")


@router.get("/tp/{tp}.json")
def detail(tp: str, request: Request):
    """La consigne et les gabarits d'un exercice.

    `find_tp` est la SEULE porte : il refuse ce qui n'est pas un TP du
    catalogue, donc `/tp/../tps.json` n'est pas un chemin à traverser mais un
    identifiant qui n'existe pas.
    """
    entry = catalogue.find_tp(tp)
    if entry is None:
        return headers.erreur(404, "inconnu")
    return headers.fichier_du_disque(
        request, config.STATIC, os.path.join("tp", entry["id"] + ".json"),
        "application/json; charset=utf-8")


@router.get("/quiz/{tp}.json")
def quiz(tp: str, request: Request):
    """Les questions d'un quiz, telles que le worker les a publiées.

    Le chemin est reconstruit à partir du catalogue, jamais concaténé depuis
    l'URL. Le mode est vérifié en plus de l'existence : un exercice de code
    n'expose pas de fichier de quiz.
    """
    entry = catalogue.find_tp(tp)
    if entry is None or entry.get("mode") != "quiz":
        return headers.erreur(404, "pas un quiz")
    return headers.fichier_du_disque(
        request, config.STATIC, os.path.join("quiz", entry["id"] + ".json"),
        "application/json; charset=utf-8")
