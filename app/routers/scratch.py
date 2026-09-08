"""La Console : une session, une socket. La frontière HTTP, rien de plus.

AUCUNE RÈGLE MÉTIER ICI. Le protocole vit dans `services/scratch.py`, et ce qui
compile vit sur l'hôte. Ce fichier décide qui a le droit d'ouvrir une session,
borne ce qui traverse, et relaie.

L'ORDRE DES REFUS EST LOAD-BEARING, et c'est le même que celui du forum :
« la Console n'est pas offerte ici » se dit AVANT « ton jeton est refusé ».
Un étudiant sur un déploiement sans Console ne doit pas croire que sa session a
expiré.

LE JETON ARRIVE DANS LA PREMIÈRE TRAME, JAMAIS DANS L'URL -- la règle de
`/team/live`, pour la raison qui n'a pas changé : un navigateur ne peut pas
poser d'`Authorization` sur une WebSocket, et un jeton en paramètre d'URL est un
jeton dans tous les journaux de proxy du chemin.
"""

import asyncio
import json
import time

import config
import deps
import headers
import security
import state
from deps import Sub, freiner_ecriture
from fastapi import APIRouter, Request, WebSocket
from schemas import ScratchIn
from services import scratch, spool
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["console"])

# Ce que la page a le droit d'envoyer. Tout le reste est ignoré, pas refusé :
# une page plus récente que l'API ne doit pas faire tomber la session.
RELAYES = ("stdin", "eof")

# Le rythme du suivi de fichiers. 50 ms est en dessous du seuil où l'on
# perçoit un décalage en tapant, et bien au-dessus du coût d'un `pread` sur des
# pages déjà en cache.
TIC = 0.05


@router.get("/scratch/draft")
def lire_bloc_notes(sub: Sub):
    """Le bloc-notes de ce compte, pour le retrouver d'une machine à l'autre.

    UN BLOC-NOTES ABSENT N'EST PAS UNE ERREUR (`code: ""`), et une base muette
    en est une (503). Les confondre effacerait le travail de quelqu'un au
    premier hoquet de Postgres -- c'est la leçon déjà payée par le thème.
    """
    code = state.read_scratch(sub)
    if code is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"code": code}


@router.put("/scratch/draft")
def ecrire_bloc_notes(sub: Sub, corps: ScratchIn, request: Request):
    """Enregistrer le bloc-notes. Le frein est appelé APRÈS la validation.

    Comme pour `/brouillon` : un `Depends` s'exécuterait avant le corps, donc
    une requête refusée pour un code trop long consommerait le quota de
    quelqu'un qui n'a rien écrit.
    """
    if len(corps.code.encode("utf-8")) > config.MAX_CODE:
        return headers.erreur(413, "bloc-notes > %d Ko" % (config.MAX_CODE // 1024))
    freiner_ecriture(request)
    if not state.write_scratch(sub, corps.code):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.websocket("/scratch/live")
async def live(socket: WebSocket):
    """Une session, de la file jusqu'à la sortie du programme.

    La séquence est fixe et courte : origine, accept, trame `hello`,
    autorisation, quota, écriture du job, puis deux boucles -- l'une qui lit ce
    que l'étudiant tape, l'autre qui suit ce que le programme écrit.

    LA SOCKET EST LA DURÉE DE VIE. Il n'y a pas de trame « arrête » : fermer la
    page EST l'arrêt, et c'est un seul chemin de code au lieu de deux. Le
    `finally` relâche le verrou, le noyau le dit au worker, le conteneur meurt.
    """
    # L'ORIGINE D'ABORD, comme pour /team/live : une WebSocket n'est pas
    # soumise au CORS, le navigateur l'ouvre vers n'importe quel hôte et
    # n'envoie qu'`Origin`. Le jeton de la première trame reste la vraie
    # barrière ; refuser ici coûte une comparaison et ferme la porte plus tôt.
    # Une origine ABSENTE est acceptée : c'est un client non-navigateur, qui
    # doit de toute façon connaître un jeton valide.
    origine = socket.headers.get("origin", "").strip().rstrip("/")
    if origine and origine not in config.ORIGINS:
        await socket.close(code=deps.CLOSE_FORBIDDEN)
        return
    await socket.accept()
    try:
        hello = await asyncio.wait_for(socket.receive_text(), timeout=10)
    except Exception:
        await socket.close(code=deps.CLOSE_BAD)
        return
    # BORNÉ AVANT D'ÊTRE ANALYSÉ. Le middleware borne les corps HTTP, mais une
    # trame WebSocket ne passe pas par lui : la même enveloppe est donc reposée
    # ici à la main, sinon la Console serait la seule porte non bornée.
    if len(hello) > config.MAX_CODE + 4096:
        await socket.close(code=deps.CLOSE_BAD)
        return
    try:
        ouverture = json.loads(hello)
    except ValueError:
        ouverture = None
    if not isinstance(ouverture, dict) or ouverture.get("t") != "hello":
        await socket.close(code=deps.CLOSE_BAD)
        return

    jeton, code = ouverture.get("token"), ouverture.get("code")
    if not isinstance(jeton, str) or not jeton or not isinstance(code, str):
        await socket.close(code=deps.CLOSE_BAD)
        return
    if len(code.encode("utf-8")) > config.MAX_CODE:
        await socket.close(code=deps.CLOSE_BAD)
        return

    # « La Console n'est pas offerte » AVANT « ton jeton est refusé ».
    if not config.SCRATCH:
        await socket.close(code=deps.CLOSE_UNAVAILABLE)
        return

    # `current_user` APPELLE L'ÉMETTEUR et bloque : dans le threadpool, comme
    # tous les endpoints HTTP de cette application. L'attendre sur la boucle
    # d'événements gèlerait toutes les autres sockets le temps d'un jeton froid.
    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + jeton})
    if not sub:
        await socket.close(code=deps.CLOSE_UNAUTHORIZED)
        return

    # UNE SESSION VIVANTE PAR COMPTE, plus le quota horaire. Les deux sont ici
    # et pas dans le worker : c'est le seul côté qui a une identité, et le
    # worker ne doit pas en avoir.
    with deps.verrou:
        if sub in _ouvertes:
            await socket.close(code=deps.CLOSE_BUSY)
            return
        attente = deps.scratch_quota.check(sub, time.time())
        if attente:
            await socket.close(code=deps.CLOSE_BUSY)
            return
        _ouvertes.add(sub)

    session = None
    try:
        session = await run_in_threadpool(scratch.ouvrir, code)
        lecteur = asyncio.create_task(_ecouter(socket, session))
        await _suivre(socket, session, lecteur)
    except Exception:
        # Socket fermée, réseau coupé, navigateur endormi : la même chose ici,
        # et aucune n'est une panne à signaler.
        pass
    finally:
        with deps.verrou:
            _ouvertes.discard(sub)
        if session is not None:
            # LE VERROU RELÂCHÉ EST LE SIGNAL D'ARRÊT. Le worker le voit en
            # 25 ms et détruit le conteneur ; il n'y a rien d'autre à envoyer,
            # et surtout rien à écrire depuis un processus qui vient peut-être
            # d'être tué.
            session.fermer()
        try:
            await socket.close()
        except Exception:
            pass


# Les comptes ayant une session ouverte. En mémoire de processus, comme les
# quotas, la présence et les salles de collaboration -- UNE RAISON DE PLUS POUR
# UN SEUL WORKER : deux processus laisseraient chacun ouvrir une session au
# même compte, et le plafond annoncé vaudrait le double en silence.
_ouvertes = set()


async def _ecouter(socket, session):
    """Ce que l'étudiant tape, jusqu'à ce qu'il ferme."""
    while True:
        brut = await socket.receive_text()
        if len(brut) > config.SCRATCH_FRAME + 256:
            break
        try:
            trame = json.loads(brut)
        except ValueError:
            continue
        if not isinstance(trame, dict) or trame.get("t") not in RELAYES:
            continue
        if trame.get("t") == "eof":
            # FERMER L'ENTRÉE EST UNE OPÉRATION À PART ENTIÈRE : c'est ainsi
            # qu'un `while (scanf(...) == 1)` se termine. Sans elle, le seul
            # moyen d'en sortir serait de tuer la session, ce qui n'est pas la
            # même chose et ne rend pas le même code de sortie.
            await run_in_threadpool(session.fermer_entree)
            continue
        donnee = trame.get("d")
        if not isinstance(donnee, str) or not donnee:
            continue
        if len(donnee.encode("utf-8")) > config.SCRATCH_FRAME:
            continue
        if not await run_in_threadpool(session.ecrire_entree, donnee):
            break


async def _suivre(socket, session, lecteur):
    """Ce que le programme écrit, plus la file d'attente avant qu'il ne tourne."""
    attente, prise, fini, tours = 0.0, False, False, 0
    try:
        while True:
            if not prise:
                prise = await run_in_threadpool(session.prise_en_charge)
                if prise:
                    await _envoyer(socket, {"t": "ready"})
                else:
                    attente += TIC
                    # PERSONNE NE RÉCLAME : c'est le worker qui est arrêté, pas
                    # le programme qui est silencieux. Le dire, sinon une unité
                    # systemd morte ressemble à un programme qui n'imprime rien.
                    if attente > config.SCRATCH_START_TIMEOUT:
                        await socket.close(code=deps.CLOSE_UNAVAILABLE)
                        return
                    # LE PREMIER TOUR ANNONCE, puis toutes les deux
                    # secondes. Attendre le premier intervalle laisserait
                    # l'étudiant devant un écran muet au moment exact où il
                    # veut savoir s'il s'est passé quelque chose.
                    if tours % 40 == 0:
                        await _envoyer(socket, _file(session))
                    tours += 1
                    await asyncio.sleep(TIC)
                    continue

            etat = await run_in_threadpool(session.etat)
            # L'ORDRE EST L'INVARIANT : on lit l'état D'ABORD, on vide les
            # fichiers ENSUITE. Le worker écrit les octets avant l'état, donc un
            # état lu avant une vidange ne peut jamais être plus récent que les
            # octets que cette vidange rend. Sans ça, la dernière ligne d'un
            # programme se perdrait derrière son propre `exit`.
            for nom in ("build", "out"):
                texte = await run_in_threadpool(session.lire_sortie, nom)
                if texte:
                    await _envoyer(socket, {"t": nom, "d": texte})

            if fini:
                await _envoyer(socket, {"t": "exit",
                                        "code": etat.get("code", -1),
                                        "reason": etat.get("reason", "exited")})
                return
            if etat and etat.get("state") == "exited":
                # UN TOUR DE PLUS avant de partir : c'est la seconde vidange que
                # l'invariant d'ordre demande.
                fini = True
            elif not await run_in_threadpool(session.worker_vivant):
                await _envoyer(socket, {"t": "exit", "code": -1,
                                        "reason": "worker"})
                return
            await asyncio.sleep(TIC)
    finally:
        lecteur.cancel()


def _file(session):
    """La position et l'ETA, ceux de la file existante -- rien de neuf."""
    jobs = spool.scan_jobs()
    return {"t": "queued",
            "position": spool.queue_position(jobs, session.job_id),
            "eta": spool.eta_secondes(jobs, session.job_id)}


async def _envoyer(socket, charge):
    """Une trame JSON. Une socket morte remonte, elle : c'est la fin de la
    session, pas un incident à avaler comme dans `collab.broadcast()` -- là-bas
    un coéquipier parti ne doit pas emporter les trois qui tapent encore, ici il
    n'y a qu'une personne et son départ EST l'événement."""
    await socket.send_text(json.dumps(charge))
