"""L'état d'un compte : exercices, brouillons, préférences, effacement.

TOUTES CES ROUTES PASSENT PAR `Sub`, ET AUCUNE NE PREND D'IDENTIFIANT DANS LA
REQUÊTE. `security.current_user()` est la seule source de `utilisateur` : c'est
ce qui empêche un étudiant d'écrire dans l'état d'un autre.

UNE BASE MUETTE RÉPOND 503, JAMAIS 200. La page n'affiche « enregistré » que sur
une réponse vraie : un 200 sur une écriture qui n'a pas eu lieu ferait croire à
quelqu'un que son travail est en sécurité.
"""

import etat
import headers
from deps import Sub, freiner_ecriture
from fastapi import APIRouter, Query, Request
from schemas import BrouillonIn, PreferencesIn
from services import catalogue

router = APIRouter(tags=["compte"])


@router.get("/etats")
def etats(sub: Sub):
    """Les exercices que ce compte a essayés ou validés."""
    valeurs = etat.read_states(sub)
    if valeurs is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"etats": valeurs}


@router.get("/pratique")
def pratique(sub: Sub):
    """Le résumé des tentatives libres de ce compte."""
    resume = etat.read_practice_summary(sub)
    if resume is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"pratique": resume}


@router.get("/brouillon")
def lire_brouillon(sub: Sub, ex: str = Query("")):
    """Le code en cours pour UN exercice.

    UN BROUILLON ABSENT N'EST PAS UNE ERREUR : c'est un étudiant qui ouvre un
    exercice pour la première fois. `sources: null` le dit sans l'habiller.
    """
    if catalogue.find_exercise(ex) is None:
        return headers.erreur(400, "TP inconnu")
    return {"sources": etat.read_resume(sub, ex)}


@router.put("/brouillon")
def ecrire_brouillon(sub: Sub, corps: BrouillonIn, request: Request):
    """Enregistrer le code en cours, pour le retrouver d'un poste à l'autre.

    LE RÉGULATEUR EST APPELÉ APRÈS LA VALIDATION, et pas en `Depends` : une
    dépendance s'exécute avant le corps, donc une requête refusée pour un TP
    inconnu consommerait le quota de quelqu'un qui n'a rien écrit.
    """
    entree = catalogue.find_exercise(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    fichiers, message, code = catalogue.validate_files(entree, corps.files)
    if message:
        return headers.erreur(code, message)
    freiner_ecriture(request)
    if not etat.write_draft(sub, entree["id"], fichiers):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.put("/etat")
def ecrire_etat(sub: Sub, corps: BrouillonIn, request: Request):
    """Le statut qu'un exercice a pour ce compte.

    ponytail: la page déclare son propre verdict, et un étudiant peut se marquer
    « validé » depuis la console. Sans note en jeu, il ne trompe que son propre
    tableau de bord -- et depuis la phase 1, `/r/<id>` écrit de toute façon le
    vrai statut à partir du verdict du juge. À dériver du serveur seul le jour
    où ça compte.
    """
    entree = catalogue.find_exercise(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    fichiers, message, code = catalogue.validate_files(entree, corps.files)
    if message:
        return headers.erreur(code, message)
    if corps.statut not in etat.STATUSES:
        return headers.erreur(400, "statut inconnu")
    freiner_ecriture(request)
    if not etat.write_state(sub, entree["id"], corps.statut, fichiers):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/preferences")
def lire_preferences(sub: Sub):
    """Le thème enregistré sur CE COMPTE, pas sur cet appareil.

    UN THÈME VIDE N'EST PAS UNE PANNE, et la page doit pouvoir les distinguer :
    « rien de choisi » (200, `theme: ""`) garde le réglage de l'appareil, « la
    base ne répond pas » (503) ne touche à rien. Les confondre écraserait le
    réglage de quelqu'un à la première panne.
    """
    theme = etat.read_theme(sub)
    if theme is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"theme": theme}


@router.put("/preferences")
def ecrire_preferences(sub: Sub, corps: PreferencesIn, request: Request):
    """Enregistrer le thème choisi, pour tous ses appareils.

    MÊME RÉGULATEUR QUE LE BROUILLON : c'est un bouton, et un bouton se clique.
    Le quota des soumissions serait absurde ici, et aucun quota du tout ferait
    d'un clic répété une écriture Postgres par clic.
    """
    if corps.theme not in etat.THEMES:
        return headers.erreur(400, "thème inconnu")
    freiner_ecriture(request)
    if not etat.write_theme(sub, corps.theme):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.delete("/moi")
def effacer(sub: Sub):
    """Effacer TOUT ce qui est gardé pour cet étudiant.

    La phrase de consentement montrée avant la redirection vers Rauthy promet
    que ça existe, donc ça existe -- pas « plus tard ». `forget()` efface chaque
    table du schéma, et un test le vérifie en relisant `schema.sql`.
    """
    if not etat.forget(sub):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}
