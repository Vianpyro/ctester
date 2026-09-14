#!/usr/bin/env python3
"""Relays public Discord messages into the site's chat. Standard library only."""

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
    paires = {}
    for morceau in str(brut or "").replace("\n", ",").split(","):
        morceau = morceau.strip()
        if not morceau or "=" not in morceau:
            continue
        salon, fil = morceau.split("=", 1)
        salon, fil = salon.strip(), fil.strip()
        # Only public chat threads: the bridge must never reach private questions.
        if salon.isdigit() and fil.startswith("@chat:"):
            paires[salon] = fil
    return paires


SALONS = salons(os.environ.get("CTESTER_DISCORD_CHANNELS", ""))


def a_relayer(message):
    if not isinstance(message, dict):
        return False
    # Messages posted by the site's own webhook would loop back.
    if message.get("webhook_id"):
        return False
    auteur = message.get("author") or {}
    if auteur.get("bot"):
        return False
    return bool(str(message.get("content") or "").strip())


def nom_affiche(message):
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
        # The position moves even past a refused message, or it would be retried forever.
        for message in lot:
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
    # Without a saved position, start from the latest message instead of replaying history.
    etat = lire_etat()
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
        # REST polling instead of the gateway: a few seconds of latency is fine for a course chat.
        time.sleep(INTERVAL)


def autotest():
    assert salons("111=@chat:general") == {"111": "@chat:general"}
    assert salons("111=@chat:general, 222=@chat:tp2-ex3") == {
        "111": "@chat:general", "222": "@chat:tp2-ex3"}
    assert salons("111=tp2-ex3") == {}
    assert salons("abc=@chat:general") == {}
    assert salons("") == {} and salons(None) == {}

    humain = {"content": "salut", "author": {"id": "9", "username": "Lea"}}
    assert a_relayer(humain) is True
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
