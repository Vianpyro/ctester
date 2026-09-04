"""Les dépendances partagées par les routeurs : qui appelle, et à quel rythme.

TROIS PORTES, ET AUCUNE NE LIT UN IDENTIFIANT DANS LA REQUÊTE :

    Sub            un compte authentifié
    SubForum       idem, et le forum est activé sur ce déploiement
    SubModerateur  idem, et ce `sub` est dans la liste de modération

`security.current_user()` est la seule source d'identité de toute
l'application. Une route qui accepterait un `utilisateur` dans son corps
laisserait n'importe qui écrire dans l'état de n'importe qui -- c'est la
propriété que ces trois alias existent pour rendre difficile à contourner.

LES COMPTEURS SONT DES GLOBALES DE MODULE, exprès : les tests les remplacent
(`deps.forum_quota = quotas.Quota(...)`) pour éprouver un plafond sans attendre
une heure. Les fonctions ci-dessous les lisent par leur nom de module, jamais
par une copie capturée à l'import -- une copie rendrait ce remplacement muet.
"""

import time
from threading import Lock
from typing import Annotated

import config
import security
from fastapi import Depends, Request
from services import forum as forum_service
from services import quotas

# Le verrou des compteurs. UN SEUL, global, et ça suffit : ces opérations sont
# des accès à un `dict`, et l'API tourne avec un seul worker.
verrou = Lock()

# Le quota des SOUMISSIONS : une compilation coûte un cœur au Dell.
quota = quotas.Quota(config.COOLDOWN, config.HOURLY)

# Écrire un brouillon ou un thème ne compile rien -- pas de conteneur, pas de
# gcc -- donc son propre plafond, bien plus lâche. Il existe pour borner un
# abus, pas pour cadencer un étudiant qui tape.
state_quota = quotas.Quota(cooldown=1, hourly=1200)

# Le forum, compté PAR COMPTE et pas par IP : deux étudiants derrière le même
# NAT d'école n'ont pas à se gêner. Il ne couvre QUE les écritures -- un quota
# qui empêcherait de relire un fil empêcherait de suivre la réponse qu'on
# attend.
forum_quota = quotas.Quota(config.FORUM_COOLDOWN, config.FORUM_HOURLY)

# Le compteur de fenêtres ouvertes. Ni base, ni compte, ni jeton.
presence = quotas.Presence()


class Refus(Exception):
    """Une réponse d'erreur, portée par une exception.

    PAS `HTTPException` : celle-ci ne sait transporter qu'un `detail`, alors
    qu'un 429 doit aussi rendre `retry_after` -- la page s'en sert pour dire
    combien de temps attendre au lieu d'inviter à recliquer. Un dictionnaire
    dans `detail` produirait `{"error": {...}}`, que `app.js` ne sait pas lire.
    """

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def utilisateur(request: Request) -> str:
    """Le `sub` de l'appelant, ou 401/503.

    503 ET PAS 401 quand la connexion n'est pas configurée : « il n'y a pas de
    comptes ici » et « ton jeton a expiré » demandent deux gestes différents à
    l'étudiant, et la page les distingue.
    """
    if not security.oidc_enabled():
        raise Refus(503, "la persistance n'est pas configurée")
    sub = security.current_user(request.headers)
    if sub is None:
        raise Refus(401, "connexion requise ou expirée")
    return sub


def utilisateur_forum(request: Request) -> str:
    """Idem, mais le forum doit être activé -- et c'est vérifié EN PREMIER.

    L'ordre compte : un déploiement sans modérateur répond 503 « les discussions
    ne sont pas activées » même sans jeton. Enchaîner sur `utilisateur` d'abord
    répondrait 401 à un anonyme, ce qui laisserait croire que le forum existe et
    qu'il suffit de se connecter.
    """
    if not forum_service.forum_enabled():
        raise Refus(503, "les discussions ne sont pas activées sur ce déploiement")
    return utilisateur(request)


def moderateur(request: Request) -> str:
    """Un `sub` de modérateur, ou 403.

    LE RÔLE EST RECALCULÉ ICI, À CHAQUE APPEL, DEPUIS LE `sub` AUTHENTIFIÉ. La
    page reçoit bien un drapeau `moderateur`, mais il ne sert qu'à décider quoi
    dessiner : aucune route ne le croit sur parole.
    """
    sub = utilisateur_forum(request)
    if not security.is_moderator(sub):
        raise Refus(403, "réservé à l'enseignant")
    return sub


Sub = Annotated[str, Depends(utilisateur)]
SubForum = Annotated[str, Depends(utilisateur_forum)]
SubModerateur = Annotated[str, Depends(moderateur)]


def freiner_ecriture(request: Request) -> None:
    """Le régulateur des écritures d'état (brouillon, préférences), par IP."""
    qui = security.client_id(request.headers, pair_tcp(request))
    with verrou:
        attente = state_quota.check(qui, time.time())
    if attente:
        raise Refus(429, f"trop d'écritures -- réessaie dans {attente} s",
                    retry_after=attente)


def freiner_forum(sub: str) -> None:
    """Le régulateur du forum, par COMPTE. Appelé après validation du contenu.

    APRÈS la validation, comme dans la version précédente : un message refusé
    parce qu'il est vide ne doit pas consommer le quota de quelqu'un.
    """
    with verrou:
        attente = forum_quota.check(sub, time.time())
    if attente:
        raise Refus(429, f"trop de messages d'un coup -- réessaie dans {attente} s",
                    retry_after=attente)


def pair_tcp(request: Request) -> str:
    """L'adresse du pair TCP, ou "" -- `request.client` est None sous TestClient."""
    return request.client.host if request.client else ""
