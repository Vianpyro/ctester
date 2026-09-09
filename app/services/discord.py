"""Le pont Discord, moitié SORTANTE : un message du chat public part vers un
salon Discord.

POURQUOI CE PONT EXISTE. Le cours a déjà un Discord, et c'est là que la
cohorte est. Un chat vide reste vide : le problème n'est pas l'interface, c'est
la masse critique. Le pont met les deux endroits en contact plutôt que de
demander aux étudiants d'en surveiller deux.

CE QUI SORT, ET RIEN D'AUTRE : un message d'un fil `@chat:…`, c'est-à-dire un
message que le serveur a DÉJÀ forcé public (`forum_visibility()` ne laisse pas
le choix dans un chat). Ne sortent JAMAIS : une question privée, un `sub`, un
code d'étudiant. La garde est `est_chat()`, et c'est le seul `if` que la
propriété coûte -- voir `D-013`, qui révise `D-008`.

ÉTEINT PAR L'ABSENCE D'UNE VARIABLE, comme le forum lui-même. Sans
`CTESTER_DISCORD_WEBHOOK`, `annoncer()` sort immédiatement et rien ne part.

STDLIB SEULEMENT. Le tier web n'a que fastapi, uvicorn, pydantic, starlette,
h11, psycopg et wsproto ; `urllib.request` fait déjà les appels OIDC de
`security.py`, et un webhook est un POST JSON. Ajouter une dépendance pour ça
serait une CVE de plus à suivre pour trente lignes.
"""

import json
import threading
import urllib.request

import config
from services.forum import est_chat


def actif():
    """Vrai quand un message peut partir. Une seule variable le décide."""
    return bool(config.DISCORD_WEBHOOK)


def vient_de_discord(compte):
    """L'anti-boucle, MOITIÉ SERVEUR.

    Un message importé de Discord ne doit pas y retourner. L'autre moitié est
    dans le bot, qui ignore les messages portant un `webhook_id` -- c'est-à-dire
    ceux que ce module vient d'écrire. Il faut LES DEUX : celle-ci arrête la
    boucle à la source, celle-là rattrape tout ce qui serait publié dans le
    salon par un autre chemin.
    """
    return str(compte or "").startswith(config.DISCORD_ACCOUNT_PREFIX)


def charge(auteur, texte, canal):
    """Le corps du webhook. Séparé pour être éprouvable sans réseau.

    `allowed_mentions` VIDE N'EST PAS OPTIONNEL. Sans lui, un étudiant tape
    `@everyone` dans CTester et réveille tout le serveur Discord -- depuis une
    page où il n'a jamais consenti à faire ça. Discord ne mentionne que ce
    qu'on l'autorise à mentionner, et ici la réponse est : rien.
    """
    nom = str(auteur or "Participant")
    if canal:
        nom = nom + " — " + str(canal)
    return {
        "username": nom[:80],
        "content": str(texte or "")[:1900],
        "allowed_mentions": {"parse": []},
    }


def _poster(corps):
    donnees = json.dumps(corps).encode("utf-8")
    requete = urllib.request.Request(
        config.DISCORD_WEBHOOK, data=donnees,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=config.DISCORD_TIMEOUT):
            pass
    except Exception:
        # UNE PANNE DE DISCORD N'EST PAS UNE PANNE DE CTESTER. Le message est
        # déjà écrit en base et déjà servi au fil ; ce qui échoue ici, c'est
        # une copie de confort.
        pass


def annoncer(fil, compte, auteur, texte, canal=""):
    """Relaie un message vers Discord. Ne lève jamais, n'attend jamais.

    Appelée depuis `routers/forum.py`, sur le chemin d'un `POST /forum` que
    l'étudiant attend. D'où le fil démon : un webhook lent ne doit pas ajouter
    sa latence à celle d'un message publié.

    ponytail: un fil par message, borné par le quota du forum (20/h/compte).
    Une file le jour où ça se voit -- pas avant, et ce jour-là ce sera la même
    file que pour tout le reste.
    """
    if not actif():
        return False
    # LA GARDE QUI PORTE TOUTE LA PROMESSE. Un fil qui n'est pas un chat est
    # un fil qui peut contenir une question privée ; il ne sort pas.
    if not est_chat(fil):
        return False
    if vient_de_discord(compte):
        return False
    if not str(texte or "").strip():
        return False
    corps = charge(auteur, texte, canal)
    threading.Thread(target=_poster, args=(corps,), daemon=True).start()
    return True
