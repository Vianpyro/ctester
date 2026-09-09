#!/usr/bin/env python3
"""Le pont Discord, moitié ENTRANTE : un message du salon entre dans le chat.

CE PROCESSUS EST UN CONTENEUR, PAS UNE UNITÉ SYSTEMD. Il ne pilote ni Docker
ni gVisor, il n'est pas root, il n'a besoin d'aucun accès à l'hôte : il n'y a
donc aucune raison qu'il vive à côté du système plutôt que dedans. Il tourne
sur l'image officielle `python:3.13-slim` lancée telle quelle sur ce fichier
monté, comme le tier web -- rien à construire.

ponytail: PAS DE GATEWAY DISCORD, UN SONDAGE REST.
La gateway (identify, heartbeat, resume, intents, reconnexion) c'est cent
cinquante lignes et une machine à états à déboguer, pour faire passer la
latence de cinq secondes à deux dixièmes -- dans un cours dont le compteur de
présence sonde déjà à SOIXANTE secondes. Le plafond est connu et le chemin de
reprise est écrit : `discord.py` et la gateway le jour où cinq secondes se
voient, et ce jour-là ce sera aussi le jour où il faudra une dépendance.

ZÉRO DÉPENDANCE, DONC. `urllib.request` fait déjà les appels OIDC du tier web.

L'ANTI-BOUCLE A DEUX MOITIÉS, et il faut les deux : ici on saute les messages
portant un `webhook_id` (ceux que CTester vient d'écrire), et côté serveur
`discord.annoncer()` refuse un message dont le compte commence par
`@discord:`. La première rattrape ce qui est publié dans le salon par un autre
chemin, la seconde arrête la boucle à la source.

Réglage, tout par variables d'environnement :

    CTESTER_DISCORD_TOKEN       le jeton du bot (vault)
    CTESTER_DISCORD_CHANNELS    "<salon>=@chat:general", séparés par des virgules
    CTESTER_BRIDGE_URL          http://ctester-web-1:8000
    CTESTER_DISCORD_BRIDGE_KEY  le secret partagé avec l'API (vault)
    CTESTER_BRIDGE_STATE        où retenir le dernier message lu
    CTESTER_BRIDGE_INTERVAL     secondes entre deux sondages (5)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"

TOKEN = os.environ.get("CTESTER_DISCORD_TOKEN", "").strip()
BRIDGE_URL = os.environ.get("CTESTER_BRIDGE_URL", "").strip().rstrip("/")
BRIDGE_KEY = os.environ.get("CTESTER_DISCORD_BRIDGE_KEY", "").strip()
STATE_PATH = os.environ.get("CTESTER_BRIDGE_STATE", "/state/bridge.json")
INTERVAL = int(os.environ.get("CTESTER_BRIDGE_INTERVAL", "5") or 5)


def salons(brut):
    """"<id>=<fil>,<id>=<fil>" -> {id: fil}.

    UN SALON PAR FIL, ET LA CORRESPONDANCE EST UNE VARIABLE. En ajouter un par
    exercice est une entrée de plus, jamais du code -- c'est ce qui permet de
    n'en câbler qu'un aujourd'hui sans avoir à revenir ici demain.
    """
    paires = {}
    for morceau in str(brut or "").replace("\n", ",").split(","):
        morceau = morceau.strip()
        if not morceau or "=" not in morceau:
            continue
        salon, fil = morceau.split("=", 1)
        salon, fil = salon.strip(), fil.strip()
        # ON N'ACCEPTE QUE DES CLÉS DE CHAT. Une entrée mal tapée qui viserait
        # un fil de forum ferait entrer Discord dans les questions privées ;
        # l'API le refuse aussi, mais un pont qui essaie est un pont à corriger.
        if salon.isdigit() and fil.startswith("@chat:"):
            paires[salon] = fil
    return paires


SALONS = salons(os.environ.get("CTESTER_DISCORD_CHANNELS", ""))


def a_relayer(message):
    """Ce message doit-il entrer dans CTester ?

    Trois refus, et le premier est l'anti-boucle : un message posté par un
    webhook est un message que CTester vient d'écrire.
    """
    if not isinstance(message, dict):
        return False
    if message.get("webhook_id"):
        return False
    auteur = message.get("author") or {}
    if auteur.get("bot"):
        return False
    return bool(str(message.get("content") or "").strip())


def nom_affiche(message):
    """Le pseudo à montrer : celui du serveur s'il existe, sinon le global."""
    auteur = message.get("author") or {}
    membre = message.get("member") or {}
    return (membre.get("nick") or auteur.get("global_name")
            or auteur.get("username") or "Discord")


def lire_etat():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            valeur = json.load(fh)
        return valeur if isinstance(valeur, dict) else {}
    except Exception:
        # LE PERDRE NE COÛTE QU'UNE RELECTURE : au premier tour on repart du
        # dernier message, donc on ne réimporte pas l'historique du salon.
        return {}


def ecrire_etat(etat):
    try:
        os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
        provisoire = STATE_PATH + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as fh:
            json.dump(etat, fh)
        os.replace(provisoire, STATE_PATH)
    except Exception as erreur:
        print("ctester-bridge: état non écrit :", erreur, flush=True)


def _get(url):
    requete = urllib.request.Request(
        url, headers={"Authorization": "Bot " + TOKEN,
                      "User-Agent": "ctester-bridge/1.0"})
    with urllib.request.urlopen(requete, timeout=20) as reponse:
        return json.loads(reponse.read(1 << 20))


def messages(salon, apres):
    chemin = API + "/channels/" + salon + "/messages?limit=50"
    if apres:
        chemin += "&after=" + apres
    valeur = _get(chemin)
    # Discord rend du plus récent au plus ancien ; on relaie dans l'ordre.
    return list(reversed(valeur)) if isinstance(valeur, list) else []


def pousser(fil, message):
    corps = json.dumps({
        "exercise_id": fil,
        "discord_id": str((message.get("author") or {}).get("id") or ""),
        "display_name": nom_affiche(message),
        "text": message.get("content") or "",
    }).encode("utf-8")
    requete = urllib.request.Request(
        BRIDGE_URL + "/forum/bridge", data=corps,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + BRIDGE_KEY})
    try:
        with urllib.request.urlopen(requete, timeout=15):
            return True
    except urllib.error.HTTPError as erreur:
        # UN REFUS SE JOURNALISE ET NE BLOQUE PAS LA SUITE. Un pseudo réservé
        # ou un message trop long est le problème d'UN message, pas du pont :
        # s'arrêter là ferait qu'un seul Discordien gèle le salon entier.
        print("ctester-bridge: refuse (%s) : %s"
              % (erreur.code, erreur.read(400)), flush=True)
        return False
    except Exception as erreur:
        print("ctester-bridge: API injoignable :", erreur, flush=True)
        return False


def tour(etat):
    for salon, fil in SALONS.items():
        try:
            lot = messages(salon, etat.get(salon))
        except Exception as erreur:
            print("ctester-bridge: Discord injoignable :", erreur, flush=True)
            continue
        for message in lot:
            # L'ÉTAT AVANCE MÊME SUR UN MESSAGE SAUTÉ OU REFUSÉ : sans ça, un
            # message que l'API refuse toujours serait rejoué à chaque tour,
            # pour toujours.
            etat[salon] = str(message.get("id") or etat.get(salon) or "")
            if a_relayer(message):
                pousser(fil, message)
    return etat


def demarrer():
    if not (TOKEN and BRIDGE_URL and BRIDGE_KEY and SALONS):
        print("ctester-bridge: non configure (jeton, URL, cle ou salons "
              "manquants) -- rien a faire.", flush=True)
        return 0
    print("ctester-bridge: %d salon(s), sondage toutes les %d s"
          % (len(SALONS), INTERVAL), flush=True)
    etat = lire_etat()
    # PREMIER TOUR À VIDE quand on ne sait pas où on en était : on note le
    # dernier message sans le relayer, sinon un redémarrage rejouerait tout
    # l'historique du salon dans le chat du cours.
    for salon in SALONS:
        if etat.get(salon):
            continue
        try:
            lot = messages(salon, None)
            if lot:
                etat[salon] = str(lot[-1].get("id") or "")
        except Exception as erreur:
            print("ctester-bridge: amorcage impossible :", erreur, flush=True)
    ecrire_etat(etat)
    while True:
        ecrire_etat(tour(etat))
        time.sleep(INTERVAL)


def autotest():
    """Le contrôle qui tient l'anti-boucle et la lecture de la variable.

    Pur, sans réseau : `python3 bot/bridge.py --autotest` tourne partout, y
    compris sur le Dell dont le python n'a aucun paquet tiers.
    """
    assert salons("111=@chat:general") == {"111": "@chat:general"}
    assert salons("111=@chat:general, 222=@chat:tp2-ex3") == {
        "111": "@chat:general", "222": "@chat:tp2-ex3"}
    # Un salon mal tapé n'ouvre rien, et surtout pas un fil de forum : le
    # pont n'a rien à faire dans les questions privées.
    assert salons("111=tp2-ex3") == {}
    assert salons("abc=@chat:general") == {}
    assert salons("") == {} and salons(None) == {}

    humain = {"content": "salut", "author": {"id": "9", "username": "Lea"}}
    assert a_relayer(humain) is True
    # L'ANTI-BOUCLE : ce que CTester vient d'écrire porte un `webhook_id`.
    assert a_relayer(dict(humain, webhook_id="42")) is False
    assert a_relayer({"content": "x", "author": {"bot": True}}) is False
    assert a_relayer(dict(humain, content="   ")) is False
    assert a_relayer(None) is False

    assert nom_affiche(humain) == "Lea"
    assert nom_affiche(dict(humain, member={"nick": "Lea B."})) == "Lea B."
    assert nom_affiche({"author": {}}) == "Discord"
    print("ctester-bridge: autotest ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(autotest() if "--autotest" in sys.argv else demarrer())
