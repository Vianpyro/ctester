"""Qui appelle : jetons OIDC, identité, rôle de modération, client de quota.

DEUX CHOSES DIFFÉRENTES VIVENT ICI, et il ne faut pas les confondre :

  * `current_user()` rend le `sub` d'un compte AUTHENTIFIÉ -- le jeton est validé
    en appelant `/userinfo` chez l'émetteur, jamais décodé sur parole. C'est la
    SEULE source d'identité de toute l'application : aucune route ne lit un
    identifiant d'utilisateur dans un corps de requête.
  * `client_id()` rend une étiquette pour compter les quotas. Elle est
    falsifiable si on tape l'origine sans passer par Cloudflare : c'est un
    régulateur de charge, PAS un contrôle d'accès. La clé de session est le
    contrôle d'accès.

`is_moderator()` est recalculé à chaque appel depuis le `sub` validé et la liste
de l'environnement, JAMAIS depuis un claim du jeton : un rôle dérivé d'un claim
non vérifié se réclame depuis n'importe quel compte.
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from threading import Lock

import config
import etat


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib replays request headers on a redirect target.

    A student's bearer token would then be handed to whoever wrote the Location
    header. We never follow one.
    """

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url, headers=None):
    """One JSON GET, bounded in time and in size. Raises on anything unexpected."""
    request = urllib.request.Request(url, headers=headers or {})
    with _OPENER.open(request, timeout=5) as response:
        raw = response.read(65536)
    return json.loads(raw)


def oidc_enabled():
    """True when signing in can be offered.

    All three are required: an issuer, a client id, and a database. Offering a
    login with nowhere to store the result would only disappoint. HTTPS is part
    of the test -- a bearer token over cleartext is a token given away.
    """
    return (config.OIDC_ISSUER.startswith("https://")
            and bool(config.OIDC_CLIENT_ID) and etat.enabled())


_discovery = {"until": 0.0, "userinfo": ""}


def userinfo_url():
    """Rauthy's userinfo endpoint, read from its OIDC discovery document.

    Read rather than hardcoded: provider paths are not standardised, and a
    guessed URL breaks on the first upgrade.

    IT MUST LIVE UNDER THE CONFIGURED ISSUER. Without that check, anyone able to
    influence the discovery document -- a wrong environment variable is enough --
    would have our students' tokens delivered to a host of their choosing. This
    is an SSRF guard, and it is the reason this function exists at all.
    """
    now = time.time()
    if _discovery["until"] > now:
        return _discovery["userinfo"]
    url = ""
    try:
        document = _get_json(config.OIDC_ISSUER + "/.well-known/openid-configuration")
        candidate = document.get("userinfo_endpoint", "")
        if isinstance(candidate, str) and candidate.startswith(config.OIDC_ISSUER + "/"):
            url = candidate
    except Exception:
        url = ""
    # A failed discovery is cached briefly too: a provider that is down must not
    # turn every request into another call to it.
    _discovery.update(until=now + (600 if url else 30), userinfo=url)
    return url


# Token fingerprint -> (sub, expiry). THE config.KEY IS A SHA-256 OF THE TOKEN, not the
# token: this dict ends up in a core dump or a traceback sooner or later, and a
# raw access token found there would still be replayable.
_tokens = {}
_tokens_lock = Lock()
TOKENS_MAX = 500


def current_user(headers):
    """The `sub` behind the Authorization header, or None.

    VALIDATED BY ASKING RAUTHY (/userinfo) instead of verifying a signature
    locally: that keeps a crypto library and its key rotation out of an image
    that serves 27 students. The price is one round trip per cold token, paid
    down by a few minutes of cache.

    FAILURES ARE CACHED TOO, briefly. Without that, a loop of made-up tokens
    would turn this API into a request amplifier aimed at Rauthy.
    """
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not oidc_enabled():
        return None
    token = header[7:].strip()
    if not token or len(token) > 4096:
        return None
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _tokens_lock:
        known = _tokens.get(fingerprint)
        if known and known[2] > now:
            return known[0]
    sub, nom = _ask_userinfo(token)
    with _tokens_lock:
        # ponytail: full flush rather than an LRU. The cache is a round-trip
        # saver, not a session store; losing it costs one call per student.
        if len(_tokens) >= TOKENS_MAX:
            _tokens.clear()
        _tokens[fingerprint] = (sub, nom, now + (config.OIDC_TTL if sub else 30))
    return sub


def current_name(headers):
    """Le `preferred_username` de Rauthy pour ce jeton, ou "".

    UNE SUGGESTION, PAS UNE IDENTITÉ. Elle ne sert qu'à pré-remplir le champ
    « Nom affiché » d'un compte qui n'en a pas encore choisi : rien n'est
    enregistré, rien n'est affiché aux autres tant que l'étudiant n'a pas
    enregistré ET coché la case. Synchroniser pour de bon publierait le nom
    d'ouverture de session de quelqu'un dans un forum de classe sans qu'il l'ait
    demandé -- et ce nom-là, chez Rauthy, est souvent le code d'accès de
    l'école.

    LIT LE CACHE, N'APPELLE RIEN : `current_user` vient de le remplir sur la
    même requête. Un cache vide (ou un `current_user` remplacé par un test) rend
    "", et le champ s'ouvre vide comme avant.
    """
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return ""
    fingerprint = hashlib.sha256(header[7:].strip().encode()).hexdigest()
    with _tokens_lock:
        known = _tokens.get(fingerprint)
    return known[1] if known and known[2] > time.time() and known[1] else ""


def _ask_userinfo(token):
    """(sub, preferred_username) -- (None, "") quand le jeton ne vaut rien.

    Le second sert UNIQUEMENT de suggestion de nom (voir `current_name`), et il
    passe par la même validation que ce qu'un étudiant taperait : un claim n'est
    pas plus digne de confiance parce qu'il vient d'un fournisseur d'identité.
    """
    url = userinfo_url()
    if not url:
        return None, ""
    try:
        claims = _get_json(url, {"Authorization": "Bearer " + token})
    except Exception:
        return None, ""
    sub = claims.get("sub") if isinstance(claims, dict) else None
    # This value becomes half of a primary key: bound it, and refuse anything
    # that is not a string. Rauthy issues a UUID, but we do not assume it.
    if not isinstance(sub, str) or not 0 < len(sub) <= 128:
        return None, ""
    # IMPORT LOCAL, POUR CASSER UN CYCLE : `services.forum` a besoin de
    # `is_moderator` et `oidc_enabled` d'ici, et ce seul appel a besoin de sa
    # validation de nom. Le cycle est réel, il est minuscule, et le résoudre en
    # déplaçant la validation chez l'appelant ferait qu'un jour quelqu'un
    # oublierait de valider. Un claim n'est pas plus digne de confiance parce
    # qu'il vient d'un fournisseur d'identité.
    from services.forum import forum_pseudo

    propose = claims.get("preferred_username")
    nom, _ = forum_pseudo(propose if isinstance(propose, str) else None)
    return sub, nom or ""


def client_id(headers, peer, poste=None):
    """Qui compte comme « un étudiant » pour les quotas.

    CF-Connecting-IP d'abord : Cloudflare l'ÉCRASE toujours, donc un client ne
    peut pas le forger tant qu'il passe par Cloudflare. X-Forwarded-For ne donne
    pas cette garantie (Cloudflare y AJOUTE l'IP client à une valeur que le
    client contrôle), il n'est là que pour un accès direct depuis le LAN.

    ponytail: falsifiable en tapant l'origine sans passer par Cloudflare. C'est
    un régulateur de charge, pas un contrôle d'accès -- la clé de session est le
    contrôle d'accès.
    """
    # LE COMPTE D'ABORD, L'IP EN REPLI. En labo, 27 étudiants sortent par une
    # seule IP NATée : compter par IP y fait qu'un seul étudiant bloque toute la
    # salle. Un `sub` validé est plus juste ET moins falsifiable que l'IP.
    # L'anonyme, lui, n'a que son IP -- et il n'a pas de compte à protéger.
    sub = current_user(headers)
    if sub:
        return "u:" + sub[:62]
    cf = headers.get("CF-Connecting-IP")
    if cf:
        adresse = cf.strip()[:64]
    else:
        xff = headers.get("X-Forwarded-For")
        adresse = xff.split(",")[0].strip()[:64] if xff else peer
    # L'ANONYME EST COMPTÉ PAR POSTE, PAS PAR SALLE. Aux premiers labos personne
    # n'est encore connecté : 27 postes sortent par une seule IP NATée, et le
    # compteur d'IP les fait tous attendre à cause d'un seul. Le jeton vient du
    # navigateur (localStorage), donc il ne prouve rien -- mais l'IP seule ne
    # prouvait rien non plus dès qu'on tape l'origine.
    #
    # L'IP RESTE DANS LA CLÉ : un jeton rejoué ne peut pas emprunter le
    # compteur d'un autre réseau, et un poste sans jeton retombe exactement sur
    # l'ancien comportement.
    #
    # ponytail: rejouable en vidant son localStorage. C'est un régulateur de
    # charge, et `QUEUE_MAX` borne déjà le pire cas ; un plafond par IP
    # par-dessus le jour où quelqu'un en fait un jeu.
    if poste:
        return (adresse + "/" + str(poste))[:128]
    return adresse


def is_moderator(sub):
    """Le contrôle de rôle, et il est ICI -- jamais dans le navigateur.

    La page reçoit bien un drapeau `moderateur`, mais c'est un drapeau
    d'AFFICHAGE : chaque route de modération le recalcule à partir du `sub`
    authentifié. Un booléen retourné par un client n'est pas une autorisation.
    """
    return bool(sub) and sub in config.FORUM_MODERATORS
