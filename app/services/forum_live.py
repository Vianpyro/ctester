"""Les salles du chat : une sonnette par fil, et RIEN D'AUTRE.

LA SOCKET NE TRANSPORTE AUCUN MESSAGE. Une trame dit `{"t": "new"}` ; le
client relance `GET /forum?ex=…`, qui applique `can_see()` par lecteur comme
il le fait déjà. C'est la décision centrale de ce module, et elle achète tout
le reste :

  * la règle de visibilité reste à UN SEUL ENDROIT -- la relayer voudrait dire
    la réimplémenter par destinataire, sur le chemin le plus difficile à
    éprouver ;
  * le quota (`freiner_forum`), la borne de texte, les listes fermées, la
    charte et le tirage d'alias restent sur `POST /forum`, inchangés ;
  * un lecteur qui n'a pas le droit de voir un message reçoit une sonnette et
    redessine la même chose : même l'EXISTENCE du message ne fuit pas.

Le coût est un `GET /forum` de plus par participant et par écriture. À une
cohorte de trente sur un fil, c'est moins que le sondage qu'on aurait écrit
sinon, et c'est événementiel plutôt que périodique.

ponytail: un `dict` en mémoire de processus, comme les quotas, la présence et
`collab.py`. Une salle meurt avec le processus, et la base réamorce la
suivante -- il n'y a aucun état à perdre, une salle n'étant qu'une liste de
sockets. UNE RAISON DE PLUS POUR UN SEUL WORKER : deux processus mettraient
deux lecteurs du même fil dans deux salles, et l'un des deux ne verrait jamais
arriver les messages de l'autre. Redis le jour où il en faut deux, et ce
jour-là les quotas partent avec.
"""

import asyncio
import json

import config

# fil -> [Connection]. Touché UNIQUEMENT depuis la boucle d'événements (le
# handler WebSocket), jamais depuis le threadpool où tournent les endpoints
# HTTP -- d'où l'absence de verrou, et pourquoi il ne doit pas y avoir de
# raison d'en ajouter un. `notify()` est la seule porte d'entrée depuis le
# threadpool, et elle repasse par la boucle plutôt que de toucher ce dict.
_rooms = {}

# LA BOUCLE, MÉMORISÉE À LA PREMIÈRE CONNEXION. Les endpoints du forum sont
# `def`, donc synchrones dans le threadpool : ils ne peuvent pas toucher une
# structure de la boucle d'événements sans passer par elle.
_loop = None


class Connection:
    """Une socket ouverte sur un fil. Elle ne porte aucune identité.

    Pas de `handle`, pas de `sub`, contrairement à `collab.Connection` : rien
    de ce qui circule ici ne nomme personne, puisque rien ne circule qu'une
    sonnette. Le compte n'est vérifié qu'à l'ouverture, pour savoir s'il a le
    droit d'écouter -- il n'est pas gardé ensuite.
    """

    def __init__(self, socket, key):
        self.socket = socket
        self.key = key

    async def send(self, payload):
        """Une trame JSON. Une socket morte n'est pas une erreur à propager.

        Un lecteur dont le navigateur est parti ne doit pas emporter la
        sonnette des autres.
        """
        try:
            await self.socket.send_text(json.dumps(payload))
        except Exception:
            pass


def full(key):
    """La salle est-elle pleine ? Un plafond par fil, pas par service."""
    return len(_rooms.get(key, ())) >= config.FORUM_LIVE_MAX


def join(connection):
    """Ajoute une socket à sa salle et mémorise la boucle."""
    global _loop
    if _loop is None:
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:            # pas de boucle : rien à mémoriser
            _loop = None
    _rooms.setdefault(connection.key, []).append(connection)


def leave(connection):
    """Retire une socket. Une salle vide disparaît -- il n'y a rien à garder."""
    room = _rooms.get(connection.key)
    if not room:
        return
    if connection in room:
        room.remove(connection)
    if not room:
        _rooms.pop(connection.key, None)


def notify(key):
    """Sonne le fil `key`. APPELÉE DEPUIS LE THREADPOOL, donc via la boucle.

    ELLE NE PEUT PAS FAIRE ÉCHOUER UNE ÉCRITURE. Tout est avalé : sans boucle
    mémorisée (aucune socket n'a jamais été ouverte, ou nous sommes dans un
    test), sans salle, ou si la boucle est en train de mourir, elle ne fait
    rien. Un message publié dont la sonnette se perd est un message que le
    prochain chargement montrera ; un `POST /forum` qui rendrait 500 parce
    qu'une socket a disparu serait une panne pour rien.
    """
    if _loop is None or key not in _rooms:
        return
    try:
        _loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_ring(key)))
    except Exception:
        pass


async def _ring(key):
    """La sonnette elle-même, sur la boucle. Aucun contenu, par dessin."""
    for member in list(_rooms.get(key, ())):
        await member.send({"t": "new", "thread": key})


def reset():
    """Vide toutes les salles. POUR LES TESTS -- en production elles meurent avec le processus."""
    _rooms.clear()
