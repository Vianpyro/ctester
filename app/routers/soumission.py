"""Soumettre du code, et lire le verdict. Le cœur de ctester.

CES DEUX ROUTES SONT ANONYMES : un étudiant colle son code, choisit son TP, et
reçoit un verdict, sans compte. La clé de session dans le lien est le contrôle
d'accès ; un compte, quand il y en a un, n'ajoute que la mémoire (progression,
brouillons) par-dessus.

RIEN N'EST COMPILÉ NI EXÉCUTÉ ICI. `POST /submit` écrit un répertoire dans le
spool et rend un identifiant ; un worker de l'hôte le ramasse, compile sous
gVisor dans un conteneur jetable sans réseau, et dépose `result.json`. C'est
cette séparation qui permet d'exposer ce processus à Internet.
"""

import hmac
import json
import os
import re
import time

import config
import deps
import etat
import headers
import security
from fastapi import APIRouter, Request
from schemas import SoumissionIn
from services import catalogue, progression, spool

JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["soumission"])


@router.post("/submit")
def submit(corps: SoumissionIn, request: Request):
    """Déposer une soumission dans la file.

    LA CLÉ D'ABORD, EN TEMPS CONSTANT, ET AVANT TOUT TRAVAIL : rien ne doit être
    mesurable depuis l'extérieur sans elle -- ni l'existence d'un TP, ni la
    longueur de la file, ni le temps que prend une validation.
    """
    if not config.KEY or not hmac.compare_digest(corps.key, config.KEY):
        return headers.erreur(403, "clé de session invalide ou expirée")

    entree = catalogue.find_tp(corps.tp)
    if entree is None:
        return headers.erreur(400, "TP inconnu")

    # LE MODE VIENT DU CATALOGUE, pas d'un champ que le client aurait choisi. Il
    # décide de ce qui est attendu et du nom du fichier déposé dans le spool ;
    # le worker le redéduit du répertoire de tests, et les deux côtés tombent
    # d'accord par le catalogue.
    if entree.get("mode") == "quiz":
        if not isinstance(corps.answers, dict):
            return headers.erreur(400, "réponses manquantes")
        # Bornées EN NOMBRE ET EN LONGUEUR : une réponse est une poignée de
        # caractères, et `Content-Length` ne suffit pas à empêcher un
        # dictionnaire de dix mille clés d'une lettre.
        reduit = {str(k)[:64]: str(v)[:64]
                  for k, v in list(corps.answers.items())[:500]}
        if not any(v.strip() for v in reduit.values()):
            return headers.erreur(400, "aucune réponse saisie")
        nom, blob = "answers.json", json.dumps(reduit).encode()
    else:
        # LA MÊME LISTE BLANCHE QUE LE BROUILLON (`validate_files`). Deux copies
        # de « quels noms sont autorisés » finiraient par diverger, et celle qui
        # dérive est celle qui laisse passer un nom inattendu.
        fichiers, message, code = catalogue.validate_files(entree, corps.files)
        if message:
            return headers.erreur(code, message)
        if not any(v.strip() for v in fichiers.values()):
            return headers.erreur(400, "soumission vide")
        nom, blob = "files.json", json.dumps(fichiers).encode()

    qui = security.client_id(request.headers, deps.pair_tcp(request))
    with deps.verrou:
        attente = deps.quota.check(qui, time.time())
        if attente:
            return headers.erreur(
                429, f"trop de soumissions -- réessaie dans {attente} s",
                retry_after=attente)
        en_attente = sum(1 for _, _, fini in spool.scan_jobs() if not fini)
        if en_attente >= config.QUEUE_MAX:
            return headers.erreur(503, "file pleine -- réessaie dans une minute")
        # L'ÉCRITURE RESTE SOUS LE VERROU : sinon le plafond de file se fait
        # dépasser par le nombre de requêtes concurrentes, ce qui est exactement
        # la situation qu'il existe pour couvrir. Écrire 64 Ko en tenant un
        # verrou global coûte moins que de raisonner sur la course.
        #
        # Le compte est FACULTATIF : un étudiant connecté obtient une tentative
        # rattachée à son compte, tous les autres gardent le parcours anonyme.
        job_id = spool.ecrire_job(entree["id"], nom, blob,
                                  security.current_user(request.headers))
    return {"id": job_id}


@router.get("/r/{job_id}")
def resultat(job_id: str):
    """Le verdict d'un job, ou son rang dans la file.

    C'EST ICI QUE LE SERVEUR LIT LE VERDICT ET EN TIRE LA VALEUR -- jamais le
    navigateur. La première réussite complète d'un exercice publié accorde de
    l'XP ; un échec ne rapporte rien, et refaire le même exercice non plus,
    parce que l'identifiant d'événement `reussite:<exercice>` a une clé primaire
    qui refuse le doublon.

    UNE PANNE DE BASE NE DOIT JAMAIS CACHER UN VERDICT ni arrêter le cœur
    anonyme de ctester : les écritures ci-dessous sont tentées, et le sondage
    suivant les rejouera sans risque grâce à l'unicité du `job_id`.
    """
    if not JOB_RE.match(job_id):
        return headers.erreur(400, "identifiant invalide")
    tp, owner = spool.job_metadata(job_id)
    chemin = os.path.join(config.SPOOL, job_id, "result.json")
    try:
        with open(chemin, encoding="utf-8") as fh:
            resultat = json.load(fh)
    except OSError:
        resultat = None
    except ValueError:
        # Le worker écrit `result.json` par rename atomique, donc ce cas ne
        # devrait pas exister. S'il arrive, c'est un bug du worker et pas une
        # course : le dire plutôt que de boucler indéfiniment.
        return headers.erreur(500, "verdict illisible", cle="message",
                              state="error")

    if resultat is not None:
        if owner is not None and tp and isinstance(resultat, dict):
            _enregistrer(owner, tp, job_id, resultat)
        return resultat

    # Le `.lock` est posé par le worker qui a pris le job. Sans ce test, un job
    # en cours de compilation s'afficherait « 1er dans la file » jusqu'au
    # verdict -- exact au sens du rang, faux au sens de ce qui se passe.
    if os.path.exists(os.path.join(config.SPOOL, job_id, ".lock")):
        return {"state": "running"}
    rang = spool.queue_position(spool.scan_jobs(), job_id)
    if rang:
        return {"state": "queued", "position": rang}
    # Balayé par le worker (dix minutes) ou n'a jamais existé.
    return headers.erreur(404, "gone", cle="state")


def _enregistrer(owner, tp, job_id, resultat):
    """Ce que le serveur retient d'un verdict, pour un compte connecté."""
    etat.write_practice_attempt(owner, job_id, tp, resultat)
    entree = catalogue.find_tp(tp)
    if entree is None:
        return
    reussi = (resultat.get("status") == "ok"
              and resultat.get("total", 0) > 0
              and resultat.get("passed") == resultat.get("total"))
    # `write_state` ne fait JAMAIS reculer un `valide`. Ceci remplace la
    # transition d'état que le navigateur déclarait tout seul.
    etat.write_state(owner, tp, "valide" if reussi else "essaye",
                     spool.job_sources(job_id, entree))
    if reussi:
        progression.recompenser(owner, entree, job_id)
