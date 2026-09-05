"""Le forum d'entraide : six routes, toutes derrière `SubForum`.

AUCUNE NE PREND D'IDENTIFIANT D'UTILISATEUR DANS LA REQUÊTE, et aucune ne balaye
les données de tous les étudiants : on lit UN fil d'exercice, ou la file des
signalements.

AUCUN `sub` NE FRANCHIT LA FRONTIÈRE. `forum_vue()` traduit l'auteur en « Vous »
/ « Enseignant » / le nom choisi, sinon « Participant ». La file de modération
recopie ce qui s'affiche (nom, groupe, poignée du message) et jamais la colonne
`utilisateur` qui a servi à joindre.

LE FORUM NE DOIT JAMAIS EMPÊCHER DE FAIRE UN EXERCICE. Éteint, en panne, ou base
muette : 503 en le disant, et « Tester » continue de marcher.
"""

import re
import uuid

import config
import etat
import headers
import security
from deps import SubForum, SubModerateur, freiner_forum
from fastapi import APIRouter, Query, Request
from schemas import (ForumMessageIn, ForumModerationIn, ForumProfilIn,
                     ForumSignalementIn)
from services import catalogue
from services import forum as forum_service

# Les identifiants de message et d'action ont la même forme qu'un job (uuid4
# hexadécimal), mais ce n'est pas la même chose : les confondre dans une seule
# constante ferait qu'un jour où l'une des deux formes change, l'autre changerait
# en silence avec elle.
MSG_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["forum"])


def _entree(brut):
    """L'entrée de catalogue nommée, ou None.

    `find_tp` est la SEULE porte : il n'existe pas de fil pour un exercice
    absent du catalogue, donc pas de fil à créer avec un identifiant fabriqué,
    et pas de chemin à traverser.
    """
    return catalogue.find_tp(str(brut or ""))


def _message_id(brut):
    """Un identifiant de message bien formé, ou None."""
    valeur = str(brut or "")
    return valeur if MSG_RE.match(valeur) else None


@router.get("/forum")
def fil(sub: SubForum, ex: str = Query("")):
    """Le fil d'un exercice, tel que CET appelant a le droit de le voir."""
    entree = _entree(ex)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    messages = etat.forum_fil(entree["id"], config.FORUM_MAX_FIL)
    if messages is None:
        return headers.erreur(503, "la base ne répond pas")
    moderateur = security.is_moderator(sub)
    profils = etat.forum_profils([m["utilisateur"] for m in messages]) or {}
    return {
        "exercice_id": entree["id"],
        "moderateur": moderateur,
        "max": config.FORUM_MAX_CHARS,
        "messages": forum_service.forum_vue(messages, sub, moderateur, profils),
    }


@router.post("/forum")
def publier(sub: SubForum, corps: ForumMessageIn):
    """Publier dans le fil d'un exercice publié."""
    entree = _entree(corps.exercice())
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    texte, message = forum_service.forum_texte(corps.texte)
    if message:
        return headers.erreur(400, message)
    freiner_forum(sub)
    if not etat.forum_publier(uuid.uuid4().hex, entree["id"], sub, texte):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.delete("/forum")
def supprimer(sub: SubForum, id: str = Query("")):
    """Supprimer SON message, jamais celui d'un autre.

    LE MÊME 404 pour « ce message n'existe pas » et « il n'est pas à toi » : les
    distinguer dirait à qui essaie qu'un identifiant existe.
    """
    message_id = _message_id(id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    efface = etat.forum_supprimer(message_id, sub)
    if efface is None:
        return headers.erreur(503, "la base ne répond pas")
    if not efface:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


@router.post("/forum/signalement")
def signaler(sub: SubForum, corps: ForumSignalementIn):
    """Signaler un message, ou le nom affiché de son auteur.

    LA MÊME RÉPONSE pour un signalement neuf, un doublon et un identifiant
    inconnu : c'est déjà ce que la base impose, et l'étudiant n'a pas besoin
    d'apprendre lequel des trois cas s'applique. Il a signalé ; quelqu'un lira.

    DEUX CIBLES, UNE ROUTE. Signaler un nom, c'est le même geste et la même
    file : le message sert de poignée parce que le navigateur n'a aucun
    identifiant de compte, et il n'en aura pas.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    if corps.quoi == "nom":
        if etat.forum_nom_signaler(message_id, sub) is None:
            return headers.erreur(503, "la base ne répond pas")
        return {"ok": True}
    if etat.forum_signaler(message_id, sub) is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/moderation")
def file_moderation(sub: SubModerateur):
    """Les signalements. Réservé, et le rôle est recalculé serveur."""
    signales = etat.forum_signalements(config.FORUM_MAX_FIL)
    noms = etat.forum_noms_signales(config.FORUM_MAX_FIL)
    if signales is None or noms is None:
        return headers.erreur(503, "la base ne répond pas")
    # LE `sub` NE TRAVERSE PAS ICI NON PLUS : on recopie ce qui s'affiche (le
    # nom signalé, le groupe, la poignée du message), jamais la colonne
    # `utilisateur` qui a servi à les joindre.
    return {"signalements": signales, "noms": [
        {"id": n["id"], "pseudo": n["pseudo"], "groupe": n["groupe"],
         "cree_le": n["cree_le"], "signalements": n["signalements"]}
        for n in noms]}


@router.post("/forum/moderation")
def moderer(sub: SubModerateur, corps: ForumModerationIn):
    """Masquer, rétablir, ou effacer un nom. Trois actions, pas une de plus.

    Éditer un message n'en fait pas partie : un message est immuable, et un
    modérateur qui pourrait le corriger pourrait aussi faire dire autre chose à
    quelqu'un.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    if corps.action == "effacer-nom":
        return _effacer_nom(message_id)
    if corps.action not in ("masquer", "retablir"):
        return headers.erreur(400, "action inconnue")
    fait = etat.forum_moderer(uuid.uuid4().hex, message_id, sub, corps.action)
    if fait is None:
        return headers.erreur(503, "la base ne répond pas")
    if not fait:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


def _effacer_nom(message_id):
    """Efface le NOM de l'auteur d'un message signalé. Rien d'autre.

    Le numéro de groupe et sa visibilité restent : ce qui est signalé, c'est le
    nom. Et on ÉCRIT UNE LIGNE de plus, on n'en corrige aucune -- le journal
    garde ce que le nom était, ce qu'une modération veut relire.

    PAS DE LIGNE DANS `forum_moderation` : ce journal-là porte l'état `masque`
    d'un message, et y écrire « masquer-nom » rétablirait un message caché au
    passage. La ligne de profil `par_moderateur` EST le journal de cette action.
    """
    auteur = etat.forum_auteur(message_id)
    if not auteur:
        return headers.erreur(404, "message introuvable")
    profil = etat.forum_profil(auteur)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    if not etat.forum_profil_ecrire(
            uuid.uuid4().hex, auteur, None, profil.get("groupe"), False,
            bool(profil.get("groupe_public")), par_moderateur=True):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/profil")
def lire_profil(sub: SubForum, request: Request):
    """SON profil, en entier. Jamais celui d'un autre.

    Il n'y a pas de route pour lire le profil de quelqu'un d'autre : ce qui est
    public d'un profil arrive déjà par le fil, déjà filtré.
    """
    profil = etat.forum_profil(sub)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    # LA SUGGESTION N'EST PAS LE PROFIL. Elle n'accompagne un profil que tant
    # qu'il n'a pas de nom : une fois choisi, le nom de l'étudiant a préséance
    # sur celui du fournisseur d'identité, toujours.
    return dict(profil, max_pseudo=config.FORUM_PSEUDO_MAX,
                groupes=list(config.FORUM_GROUPES),
                suggestion=("" if profil.get("pseudo")
                            else security.current_name(request.headers)))


@router.post("/forum/profil")
def ecrire_profil(sub: SubForum, corps: ForumProfilIn):
    """Choisir son nom, son groupe, et ce qui s'affiche.

    UN CHAMP VIDE N'EST PAS UN CHAMP VISIBLE : sans ça, cocher la case sans rien
    écrire afficherait « Participant » en croyant s'être nommé.
    """
    pseudo, message = forum_service.forum_pseudo(corps.pseudo)
    if message:
        return headers.erreur(400, message)
    groupe, message = forum_service.forum_groupe(corps.groupe)
    if message:
        return headers.erreur(400, message)
    freiner_forum(sub)
    if not etat.forum_profil_ecrire(
            uuid.uuid4().hex, sub, pseudo, groupe,
            corps.pseudo_public and pseudo is not None,
            corps.groupe_public and groupe is not None):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}
