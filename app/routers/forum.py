"""The peer help forum: six routes, all behind `SubForum`.

NONE OF THEM TAKES A USER ID IN THE REQUEST, and none scans every student's
data: we read ONE exercise thread, or the report queue.

NO `sub` EVER CROSSES THE BOUNDARY. `forum_vue()` translates the author into
"Vous" / "Enseignant" / the chosen name, else "Participant". The moderation
queue copies what is displayed (name, group, message handle) and never the
`account` column used to join.

THE FORUM MUST NEVER PREVENT DOING AN EXERCISE. Disabled, down, or a mute
database: 503 saying so, and "Tester" keeps working.
"""

import asyncio
import hmac
import json
import re
import secrets
import uuid

import config
import deps
import policy
import state
import headers
import security
from deps import SubForum, SubModerateur, freiner_forum
from fastapi import APIRouter, Query, Request, WebSocket
from schemas import (DiscordBridgeIn, ForumTargetIn, ForumMessageIn, ForumModerationIn,
                     ForumProfilIn, ForumSignalementIn, ForumVoteIn)
from services.catalog import find_exercise
from services import discord
from services import forum as forum_service
from services import forum_live
from services import leaderboard
from starlette.concurrency import run_in_threadpool

# Message and action ids have the same shape as a job (hex uuid4), but they
# are not the same thing: folding them into a single constant would mean that
# the day one of the two shapes changes, the other would change silently
# along with it.
MSG_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["forum"])


def _entree(brut):
    """The named thread, or None -- a catalog entry, or a chat.

    `find_exercise` IS STILL THE ONLY CATALOG GATE: there is no thread for an
    exercise absent from the catalog, so no thread to create with a made-up
    id, and no path to traverse. What is added here is a second NAMED entry
    that does not come from the catalog at all -- the chat.

    A CHAT KEY IS NEVER A PATH. `@` cannot appear in a catalog id, so
    `find_exercise` resolves none of these for anybody; the value is only ever
    a thread key in a column. The exercise chat still has to name a REAL
    exercise: `@chat:tp2-ex3` resolves only if `tp2-ex3` does, which is what
    keeps a made-up chat from being conjured by writing to it.
    """
    cle = str(brut or "")
    if not forum_service.est_chat(cle):
        return find_exercise(cle)
    if cle == forum_service.CHAT_GENERAL:
        return {"id": cle, "label": "Questions générales", "chat": True}
    entree = find_exercise(cle[len(forum_service.CHAT_PREFIX):])
    if entree is None:
        return None
    return {"id": cle, "label": entree.get("label") or cle, "chat": True}


def _assurer_alias(sub):
    """Draw this account a masked handle if it has none. Best effort, always.

    AN ANONYMOUS AUTHOR MUST STILL BE FOLLOWABLE: "Participant" for everyone
    makes a conversation unreadable -- one cannot tell who is answering whom.
    The alias comes from a CLOSED vocabulary (`policy.possible_aliases()`), so
    nothing a student typed can reach it, and there is no alias to moderate.

    IT NEVER REFUSES A POST. A mute database, an exhausted vocabulary: we
    return and the message goes out signed "Participant". A chat that stopped
    accepting messages because a NAME could not be drawn would be the worst
    possible trade.
    """
    profil = state.forum_profil(sub)
    if not profil or profil.get("alias"):
        return
    taken = state.forum_taken_aliases()
    if taken is None:
        return
    alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    if not alias:
        return
    # THE WHOLE PROFILE IS REWRITTEN, as everywhere: the latest row IS the
    # profile, so omitting a field would reset it -- and the one that would be
    # reset most often is a visibility checkbox.
    state.forum_profil_ecrire(
        uuid.uuid4().hex, sub, profil.get("display_name"),
        profil.get("group_number"), bool(profil.get("display_name_public")),
        bool(profil.get("group_number_public")), alias=alias,
        plate_frame=profil.get("plate_frame"),
        badges_public=profil.get("badges_public"),
        leaderboard_opt_in=profil.get("leaderboard_opt_in"))


def _vers_discord(entree, sub, texte):
    """Recopie un message du chat public dans le salon Discord du cours.

    APRÈS L'ÉCRITURE ET APRÈS LA SONNETTE, jamais avant : ce qui part vers
    Discord doit être ce que la base a accepté, et un webhook lent ne doit pas
    retarder le message pour ceux qui sont déjà sur la page.

    L'AUTEUR EST CELUI QUE LES AUTRES VOIENT, pas le `sub`. On repasse par
    `forum_identite()`, la seule fonction qui traduit un compte en nom
    affichable : lui écrire un second traducteur ici serait le second endroit
    où la visibilité d'un nom peut diverger de ce que la base dit.
    """
    if not discord.actif() or not forum_service.est_chat(entree["id"]):
        return
    profils = state.forum_profils([sub]) or {}
    auteur, _groupe, _signalable = forum_service.forum_identite(
        profils.get(sub), None, sub, False)
    discord.annoncer(entree["id"], sub, auteur, texte,
                     entree.get("label", ""))


def _message_id(brut):
    """A well-formed message id, or None."""
    valeur = str(brut or "")
    return valeur if MSG_RE.match(valeur) else None


@router.get("/forum")
def fil(sub: SubForum, ex: str = Query("")):
    """An exercise's thread, as THIS caller is allowed to see it."""
    entree = _entree(ex)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    messages = state.forum_fil(entree["id"], config.FORUM_MAX_FIL, sub)
    if messages is None:
        return headers.erreur(503, "la base ne répond pas")
    moderateur = security.is_moderator(sub)
    # THE READER'S OWN PROFILE IS READ WITH THE OTHERS, because the visibility
    # rule needs their group number: a `group` message is for people in the
    # author's group, and "my group" is a fact on my profile, not something
    # the request can claim.
    profils = state.forum_profils(
        [m["account"] for m in messages] + [sub]) or {}
    views = forum_service.forum_vue(messages, sub, moderateur, profils)
    return {
        "exercise_id": entree["id"],
        # THE PAGE HAS TO KNOW WHICH SPACE IT IS DRAWING: a chat has no
        # privacy control to offer (everything in it is public), the forum
        # does. The server says which, rather than the page re-deriving it
        # from the key -- one prefix, parsed in one place.
        "chat": bool(entree.get("chat")),
        "moderator": moderateur,
        "max": config.FORUM_MAX_CHARS,
        "messages": views,
        # The thread's state, derived from what THIS caller can see (design
        # 1f): a private question nobody else reads must not inflate anyone
        # else's "sans réponse".
        "state": forum_service.thread_state(views),
        # The two closed lists, sent as a legend so the page never has its own
        # copy to drift from -- same split as the mastery bands.
        "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
        "blocked_kinds": [{"id": k, "title": v}
                          for k, v in forum_service.BLOCKED_KINDS.items()],
    }


@router.post("/forum")
def publier(sub: SubForum, corps: ForumMessageIn):
    """Post into a thread: a question, a "bloqué ici", or a REPLY to either.

    ONE ROUTE FOR ALL THREE, and the differences are two optional fields.
    `step` makes it a "bloqué ici", private by default in the forum; `reply_to`
    makes it an answer. Separate routes would mean separate places to bound a
    message's length, and the one that drifted would be the one that stopped
    bounding it.

    A REPLY CARRIES NO VISIBILITY OF ITS OWN -- it is refused if it tries.
    In a chat everything is public anyway; in the forum a reply belongs to the
    conversation it joins, and letting a body set it would be a way to publish
    a line into a thread under the wrong audience.

    NO CODE IS EVER TRANSMITTED. The form asks what was observed, not what was
    written -- that is what keeps the charter tenable, and there is no field
    here that could carry a source file.
    """
    entree = _entree(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    texte, message = forum_service.forum_texte(corps.text)
    if message:
        return headers.erreur(400, message)

    reponse_a = None
    if corps.reply_to:
        reponse_a = _message_id(corps.reply_to)
        if reponse_a is None:
            return headers.erreur(400, "identifiant invalide")
        if corps.visibility:
            return headers.erreur(
                400, "une réponse hérite de la visibilité de sa question")

    # THE QUOTA FIRST, THEN THE HANDLE. `freiner_forum` raises, so a throttled
    # request does no database work at all -- drawing a name for someone we
    # are about to refuse would be a read per rejected burst message.
    freiner_forum(sub)
    # THE MASKED HANDLE IS DRAWN BEFORE THE MESSAGE IS WRITTEN, so the message
    # comes out already signed. Doing it after would show the first post of
    # every new account as "Participant" until they wrote a second one.
    _assurer_alias(sub)

    if reponse_a is not None:
        # None = mute, [] = the target does not exist or lives in another
        # thread. The SAME 404 for both refusals, as everywhere in this file:
        # telling them apart would tell whoever is trying that an id exists.
        ecrit = state.forum_repondre(uuid.uuid4().hex, entree["id"], sub,
                                     texte, reponse_a)
        if ecrit is None:
            return headers.erreur(503, "la base ne répond pas")
        if not ecrit:
            return headers.erreur(404, "message introuvable")
        forum_live.notify(entree["id"])
        _vers_discord(entree, sub, texte)
        return {"ok": True}

    step, message = forum_service.forum_step(corps.step)
    if message:
        return headers.erreur(400, message)
    blocked_kind, message = forum_service.forum_blocked_kind(corps.blocked_kind)
    if message:
        return headers.erreur(400, message)
    visibility, message = forum_service.forum_visibility(
        corps.visibility, step is not None, entree["id"])
    if message:
        return headers.erreur(400, message)
    if not state.forum_publier(uuid.uuid4().hex, entree["id"], sub, texte,
                               step, blocked_kind, visibility):
        return headers.erreur(503, "la base ne répond pas")
    forum_live.notify(entree["id"])
    _vers_discord(entree, sub, texte)
    return {"ok": True}


# UN IDENTIFIANT DISCORD EST UN ENTIER (un « snowflake »). On le borne parce
# qu'il devient une valeur de colonne `account` : rien d'exotique n'a de raison
# d'y entrer, et `@` y est déjà interdit par construction.
_DISCORD_ID_RE = re.compile(r"\A[0-9]{1,24}\Z")


@router.post("/forum/bridge")
def pont_discord(corps: DiscordBridgeIn, request: Request):
    """Un message venu de Discord entre dans le chat public.

    IL N'Y A AUCUNE TABLE DISCORD↔`sub`, ET IL NE DOIT PAS Y EN AVOIR. Chaque
    Discordien devient un COMPTE DE SERVICE `@discord:<id>`, avec une ligne
    `forum_profile` portant son pseudo Discord. Ça donne gratuitement, sans un
    seul `if` de plus :

      - `forum_identite()` rend son pseudo -- c'est déjà sa troisième branche ;
      - `is_moderator()` est faux, sauf si l'enseignant y met son propre
        identifiant Discord, auquel cas il est « Enseignant » des deux côtés ;
      - `freiner_forum()` donne un quota PAR DISCORDIEN, la fonction ne lisant
        qu'une chaîne ;
      - `forget()` n'est pas concerné : aucun étudiant ne possède ces lignes.

    Et surtout : l'enseignant ne gagne aucun moyen de relier un pseudonyme
    CTester à un visage. C'est `D-013`, qui révise `D-008`.

    LA GARDE EST UN SECRET PARTAGÉ, comparé en temps constant. Ce n'est pas un
    compte OIDC : le bot n'est pas une personne, et lui faire porter un jeton
    d'étudiant serait un jeton d'étudiant dans un conteneur de plus.
    """
    # PAS DE CLÉ, PAS DE PONT. Un 404 et non un 403 : de l'extérieur, la route
    # n'existe pas, et il n'y a donc rien à deviner.
    if not config.DISCORD_BRIDGE_KEY:
        return headers.erreur(404, "inconnu")
    presente = request.headers.get("authorization", "")
    attendu = "Bearer " + config.DISCORD_BRIDGE_KEY
    if not hmac.compare_digest(presente, attendu):
        return headers.erreur(401, "clé du pont invalide")

    entree = _entree(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    # DISCORD N'ÉCRIT QUE DANS LE PUBLIC. Une question privée est adressée à
    # l'enseignant seul ; un pont qui pourrait y répondre serait un pont qui
    # pourrait la lire. Le refus est ici, en plus de celui de `annoncer()` :
    # les deux sens sont bornés séparément.
    if not forum_service.est_chat(entree["id"]):
        return headers.erreur(400, "le pont n'écrit que dans le chat public")

    if not _DISCORD_ID_RE.match(str(corps.discord_id or "")):
        return headers.erreur(400, "identifiant Discord invalide")
    texte, message = forum_service.forum_texte(corps.text)
    if message:
        return headers.erreur(400, message)
    # LE PSEUDO DISCORD PASSE PAR LA VALIDATION DES ÉTUDIANTS, noms réservés
    # compris : sans ça, quelqu'un se nomme « Enseignant » sur Discord et sa
    # réponse passe pour celle du cours, ce qu'aucune couleur ne rattrape.
    pseudo, message = forum_service.forum_pseudo(corps.display_name)
    if message:
        return headers.erreur(400, message)

    compte = config.DISCORD_ACCOUNT_PREFIX + str(corps.discord_id)
    freiner_forum(compte)

    profil = state.forum_profil(compte)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    # LE PROFIL EST RÉÉCRIT EN ENTIER, comme partout : la dernière ligne EST le
    # profil. Seulement quand le pseudo a changé -- une ligne par message
    # ferait grossir la table au rythme du salon.
    if (pseudo or None) != profil.get("display_name"):
        state.forum_profil_ecrire(
            uuid.uuid4().hex, compte, pseudo, profil.get("group_number"),
            True, bool(profil.get("group_number_public")),
            alias=profil.get("alias"), plate_frame=profil.get("plate_frame"),
            badges_public=profil.get("badges_public"),
            leaderboard_opt_in=profil.get("leaderboard_opt_in"))

    if not state.forum_publier(uuid.uuid4().hex, entree["id"], compte, texte,
                               None, None, "thread"):
        return headers.erreur(503, "la base ne répond pas")
    forum_live.notify(entree["id"])
    return {"ok": True}


@router.get("/forum/search")
def rechercher(sub: SubForum, q: str = Query("")):
    """Search the archive -- and propose duplicates. THE SAME QUERY for both.

    Typed into the compose box it answers "someone already asked this"; typed
    into the search bar it answers "what was the reply I got last week". Two
    routes would be two places for the privacy clause to drift, and the one
    that drifted would be the one that stopped protecting.

    THE PRIVACY RULE IS THE `WHERE` in `state.forum_search`, not a filter
    here: a private forum question never surfaces to anyone but its author,
    moderators included.

    NO `freiner_forum`: this is a read, and a ten-second cooldown would make
    it useless mid-typing -- which is precisely when it prevents a duplicate.
    The page debounces, and the LIMIT bounds the cost.
    """
    resultats = state.forum_search(q, sub, config.FORUM_SEARCH_MAX)
    if resultats is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"results": resultats}


@router.get("/forum/message")
def permalien(sub: SubForum, id: str = Query("")):
    """One question and ALL its replies, wherever it is in the archive.

    WITHOUT THIS, SEARCH IS A LIST OF EXCERPTS ONE CANNOT OPEN: a message
    three thousand posts back is inside no thread window, so `GET /forum`
    would never return it.

    IT GOES THROUGH THE SAME `forum_vue()`/`can_see()` as a thread -- same
    rules, same identity translation, same single 404 for "does not exist" and
    "not for you".
    """
    message_id = _message_id(id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    fil, messages = state.forum_conversation(message_id, sub)
    if messages is None:
        return headers.erreur(503, "la base ne répond pas")
    if not messages:
        return headers.erreur(404, "message introuvable")
    moderateur = security.is_moderator(sub)
    profils = state.forum_profils(
        [m["account"] for m in messages] + [sub]) or {}
    views = forum_service.forum_vue(messages, sub, moderateur, profils)
    if not views:
        return headers.erreur(404, "message introuvable")
    return {"exercise_id": fil, "chat": forum_service.est_chat(fil),
            "moderator": moderateur, "messages": views}


@router.post("/forum/visibility")
def open_to_group(sub: SubForum, corps: ForumTargetIn):
    """Open one's OWN private question to one's group. The only transition.

    PRIVATE -> GROUP, and never the reverse: the reverse would hide what
    others have already read, and that is the immutability social.md sets out.
    The rule is the `WHERE` in `state.forum_open_to_group`, not an `if`
    here -- so two simultaneous clicks cannot race past it.

    THE SAME 404 for "does not exist", "is not yours" and "is not private":
    telling them apart would tell whoever is trying that an id exists.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    opened = state.forum_open_to_group(message_id, sub)
    if opened is None:
        return headers.erreur(503, "la base ne répond pas")
    if not opened:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


@router.post("/forum/helpful")
def voter(sub: SubForum, corps: ForumVoteIn):
    """The vote: +1, -1 on a reply, or 0 to take it back. NOT a popularity score.

    THE URL DOES NOT CHANGE, and the body is a superset of the old one: a page
    still in a student's cache sends `{id}`, `value` defaults to 1, and it
    means exactly what "ça m'a aidé" meant. A new route would have been a
    second place to bound the same gesture, for nothing.

    ON A QUESTION, +1 READS AS "MOI AUSSI" -- that is what tells the
    instructor what is actually being asked, without counting anybody. -1 IS
    REFUSED ON A QUESTION, and the refusal is the `WHERE` of
    `state.forum_voter`, not this router and not the page's choice of buttons:
    a question cannot be buried by a vote, which is the whole promise of a
    place built for people who are afraid to ask.

    IT GRANTS NOTHING: no XP, no achievement, no card. A message written to be
    upvoted is a message written for the counter.

    THE SAME 404 for a made-up id, one's own message, and a -1 aimed at a
    question: telling them apart would tell whoever is trying which is which.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    if int(corps.value) == 0:
        marked = state.forum_devoter(message_id, sub)
    else:
        marked = state.forum_voter(message_id, sub, corps.value)
    if marked is None:
        return headers.erreur(503, "la base ne répond pas")
    if not marked:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


@router.delete("/forum")
def supprimer(sub: SubForum, id: str = Query("")):
    """Delete THEIR OWN message, never someone else's.

    THE SAME 404 for "this message does not exist" and "it is not yours":
    telling them apart would tell whoever is trying that an id exists.
    """
    message_id = _message_id(id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    # READ THE THREAD BEFORE THE ROW GOES AWAY: after the DELETE there is
    # nothing left to ask which room to ring.
    fil = state.forum_fil_de(message_id)
    efface = state.forum_supprimer(message_id, sub)
    if efface is None:
        return headers.erreur(503, "la base ne répond pas")
    if not efface:
        return headers.erreur(404, "message introuvable")
    forum_live.notify(fil)
    return {"ok": True}


@router.post("/forum/signalement")
def signaler(sub: SubForum, corps: ForumSignalementIn):
    """Report a message, or its author's displayed name.

    THE SAME RESPONSE for a fresh report, a duplicate and an unknown id: that
    is already what the database enforces, and the student does not need to
    learn which of the three cases applies. They reported; someone will read.

    TWO TARGETS, ONE ROUTE. Reporting a name is the same gesture and the same
    queue: the message serves as the handle because the browser has no
    account id, and never will.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    if corps.kind == "name":
        if state.forum_nom_signaler(message_id, sub) is None:
            return headers.erreur(503, "la base ne répond pas")
        return {"ok": True}
    if state.forum_signaler(message_id, sub) is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/moderation")
def file_moderation(sub: SubModerateur):
    """Reports. Restricted, and the role is recomputed server-side."""
    signales = state.forum_signalements(config.FORUM_MAX_FIL)
    noms = state.forum_noms_signales(config.FORUM_MAX_FIL)
    if signales is None or noms is None:
        return headers.erreur(503, "la base ne répond pas")
    # THE `sub` DOES NOT CROSS HERE EITHER: we copy what is displayed (the
    # reported name, the group, the message handle), never the `account`
    # column used to join them.
    return {"reports": signales, "reported_names": [
        {"id": n["id"], "display_name": n["display_name"], "group_number": n["group_number"],
         "created_at": n["created_at"], "report_count": n["report_count"]}
        for n in noms]}


@router.post("/forum/moderation")
def moderer(sub: SubModerateur, corps: ForumModerationIn):
    """Hide, restore, or clear a name. Three actions, not one more.

    Editing a message is not among them: a message is immutable, and a
    moderator who could correct it could also make someone say something
    else.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    if corps.action == "clear-name":
        return _effacer_nom(message_id)
    # `retain`/`unretain` MARK THE ANSWER THE COURSE STANDS BEHIND, and they
    # edit nothing: the action goes into the append-only journal, and the
    # latest one for a message is the answer (see `state.forum_fil`).
    # Epingler n'edite rien -- a message stays immutable, which is what keeps
    # a report readable.
    if corps.action not in ("hide", "restore", "retain", "unretain"):
        return headers.erreur(400, "action inconnue")
    fil = state.forum_fil_de(message_id)
    fait = state.forum_moderer(uuid.uuid4().hex, message_id, sub, corps.action)
    if fait is None:
        return headers.erreur(503, "la base ne répond pas")
    if not fait:
        return headers.erreur(404, "message introuvable")
    # HIDING MUST REACH THE ROOM. Without the bell, a message hidden because
    # it had to be stays on every screen already open until each reader
    # happens to navigate -- precisely the case where hiding it fast was the
    # whole point.
    forum_live.notify(fil)
    return {"ok": True}


# HOURS, NOT DAYS: this is a live view of a lab session. A window of a week
# would mix Tuesday's group with Thursday's and count nobody's room.
HELP_WINDOW_HOURS = 8


@router.get("/forum/help")
def who_needs_help(sub: SubModerateur):
    """"Qui a besoin d'aide", aggregated by exercise and step (design 1h).

    COUNTS AND STEPS, NEVER PEOPLE. No `sub`, no name, no text, no code: a
    number is what says where to walk in the room, and six people on the same
    conversion is one explanation at the board rather than six replies.

    PRIVATE QUESTIONS ARE COUNTED, NOT REVEALED. They stay unreadable -- only
    their author can open one to their group -- and this row says only that a
    number exists. That is the whole compromise, and it is written on the
    student's form: "seulement le chargé de lab".

    RESTRICTED, and the role is recomputed server-side from the token on every
    call, like every other moderator route.
    """
    rows = state.forum_help_rows(config.FORUM_MAX_FIL, HELP_WINDOW_HOURS)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"rows": rows, "hours": HELP_WINDOW_HOURS,
            "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
            "blocked_kinds": [{"id": k, "title": v}
                              for k, v in forum_service.BLOCKED_KINDS.items()]}


@router.get("/forum/top")
def top(sub: SubModerateur):
    """"Questions du moment": the most upvoted roots of the window.

    A SEPARATE ROUTE FROM `/forum/help`, ON PURPOSE. That one's contract is
    written in its docstring -- "COUNTS AND STEPS, NEVER PEOPLE. No `sub`, no
    name, no text, no code" -- and a ranking needs the text. Widening a
    promise already written down costs more than a second route carrying a
    different one.

    STILL NO `sub` AND NO NAME. What comes out is a handle, a text, a thread
    and two numbers -- the same discipline as everywhere else in this file.

    STUDENTS SEE NO RANKING AT ALL. A public counter on what each person asked
    is the opposite of what this whole feature is for.
    """
    rows = state.forum_top(HELP_WINDOW_HOURS, config.FORUM_MAX_FIL)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"rows": rows, "hours": HELP_WINDOW_HOURS}


def _effacer_nom(message_id):
    """Clear the NAME of a reported message's author. Nothing else.

    The group number and its visibility stay: what was reported is the name.
    And we WRITE ONE MORE ROW, we correct none -- the journal keeps what the
    name was, which is what a moderator wants to read back.

    NO ROW IN `forum_moderation`: that journal carries a message's `hidden`
    state, and writing "hide-name" there would restore a hidden message as a
    side effect. The profile row's `set_by_moderator` IS this action's
    journal.
    """
    auteur = state.forum_auteur(message_id)
    if not auteur:
        return headers.erreur(404, "message introuvable")
    profil = state.forum_profil(auteur)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    # EVERY OTHER FIELD IS CARRIED OVER, and that is not optional: the latest
    # row IS the profile, so a write that left out the alias, the frame or the
    # leaderboard opt-in would silently reset them. Clearing a name must clear
    # the name and nothing else -- the group number is the case that was
    # already written down, and the three added since behave the same way.
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, auteur, None, profil.get("group_number"), False,
            bool(profil.get("group_number_public")), set_by_moderator=True,
            alias=profil.get("alias"), plate_frame=profil.get("plate_frame"),
            badges_public=profil.get("badges_public"),
            leaderboard_opt_in=profil.get("leaderboard_opt_in")):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/profil")
def lire_profil(sub: SubForum, request: Request):
    """THEIR OWN profile, in full. Never someone else's.

    There is no route to read someone else's profile: what is public about a
    profile already arrives through the thread, already filtered.
    """
    profil = state.forum_profil(sub)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    # THE SUGGESTION IS NOT THE PROFILE. It only accompanies a profile as long
    # as it has no name: once chosen, the student's name always takes
    # precedence over the identity provider's.
    #
    # THE UNLOCKED FRAMES ARE COMPUTED HERE, from the level the account
    # actually reached: the form must offer what is available, and "what is
    # available" is a fact about the account, never something the browser
    # asserts. A mute progression is not an error here -- the identity form
    # must keep working when the ranking cannot be read -- so it falls back to
    # the first frame, which is always open.
    facts = state.read_progress(sub)
    rank = policy.niveau(facts["xp"])["rank"] if facts else 1
    return dict(profil, max_display_name=config.FORUM_PSEUDO_MAX,
                group_numbers=list(config.FORUM_GROUPES),
                frames=policy.unlocked_frames(rank),
                suggestion=("" if profil.get("display_name")
                            else security.current_name(request.headers)))


@router.post("/forum/profil")
def ecrire_profil(sub: SubForum, corps: ForumProfilIn):
    """Choose a name, a group, and what is shown.

    AN EMPTY FIELD IS NOT A VISIBLE FIELD: without this, checking the box
    without writing anything would display "Participant" while believing
    one had named oneself.
    """
    pseudo, message = forum_service.forum_pseudo(corps.display_name)
    if message:
        return headers.erreur(400, message)
    groupe, message = forum_service.forum_groupe(corps.group_number)
    if message:
        return headers.erreur(400, message)
    previous = state.forum_profil(sub)
    if previous is None:
        return headers.erreur(503, "la base ne répond pas")
    facts = state.read_progress(sub)
    frame, message = forum_service.forum_frame(
        corps.plate_frame,
        policy.unlocked_frames(policy.niveau(facts["xp"])["rank"] if facts else 1))
    if message:
        return headers.erreur(400, message)
    # JOINING A RANKING NEEDS AN ALIAS, and it is drawn here rather than
    # refused: someone who ticks the box must land in the ranking, not in an
    # error telling them to go press another button first. Redrawing it stays
    # available, as often as they like.
    alias = previous.get("alias")
    if corps.leaderboard_opt_in and not alias:
        taken = state.forum_taken_aliases()
        if taken is None:
            return headers.erreur(503, "la base ne répond pas")
        alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    freiner_forum(sub)
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, sub, pseudo, groupe,
            corps.display_name_public and pseudo is not None,
            corps.group_number_public and groupe is not None,
            alias=alias, plate_frame=frame,
            badges_public=corps.badges_public,
            leaderboard_opt_in=corps.leaderboard_opt_in):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


# --- Le chat en direct ---------------------------------------------------------


@router.websocket("/forum/live")
async def live(socket: WebSocket):
    """Une sonnette par fil. ELLE NE TRANSPORTE AUCUN MESSAGE.

    Une trame sortante dit `{"t": "new"}` et rien d'autre ; le client relance
    `GET /forum?ex=…`, qui applique `can_see()` par lecteur comme il le fait
    déjà. C'est ce qui garde la règle de visibilité, le quota, la borne de
    texte, les listes fermées et le tirage d'alias à UN SEUL ENDROIT -- la
    route HTTP. Relayer le texte voudrait dire réimplémenter tout ça par
    destinataire, sur le chemin le plus difficile à éprouver.

    Conséquence gratuite : un lecteur qui n'a pas le droit de voir un message
    reçoit la sonnette et redessine la même chose. Même l'EXISTENCE du message
    ne fuit pas.

    LA SÉQUENCE EST CELLE DES DEUX AUTRES SOCKETS (`/team/live`,
    `/scratch/live`), et c'est délibéré : origine, accept, `hello` borné puis
    analysé, autorisation, salle. Une quatrième façon d'ouvrir une socket
    serait une quatrième façon de se tromper d'ordre.
    """
    # L'ORIGINE D'ABORD : une WebSocket n'est pas soumise au CORS, le
    # navigateur l'ouvre vers n'importe quel hôte et n'envoie qu'`Origin`. Le
    # jeton de la première trame reste la vraie barrière ; refuser ici coûte
    # une comparaison et ferme la porte plus tôt. Une origine ABSENTE est
    # acceptée : c'est un client non-navigateur, qui doit de toute façon
    # connaître un jeton valide.
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
    # trame WebSocket ne passe pas par lui : la même enveloppe est reposée ici
    # à la main, sinon ce serait la seule porte non bornée de l'application.
    if len(hello) > config.FORUM_LIVE_FRAME:
        await socket.close(code=deps.CLOSE_BAD)
        return
    try:
        ouverture = json.loads(hello)
    except ValueError:
        ouverture = None
    if not isinstance(ouverture, dict) or ouverture.get("t") != "hello":
        await socket.close(code=deps.CLOSE_BAD)
        return
    jeton, fil = ouverture.get("token"), ouverture.get("thread")
    if not isinstance(jeton, str) or not jeton or not isinstance(fil, str):
        await socket.close(code=deps.CLOSE_BAD)
        return

    # « LES DISCUSSIONS NE SONT PAS ACTIVÉES » AVANT « TON JETON EST REFUSÉ »,
    # le même ordre que les routes HTTP (503 avant 401) et que la Console. Un
    # déploiement sans forum ne doit pas répondre « authentifie-toi » à une
    # fonctionnalité qu'il n'offre pas.
    if not forum_service.forum_enabled():
        await socket.close(code=deps.CLOSE_UNAVAILABLE)
        return

    # `current_user` APPELLE L'ÉMETTEUR et bloque : dans le threadpool, comme
    # tous les endpoints HTTP. L'attendre sur la boucle gèlerait toutes les
    # autres sockets le temps d'un jeton froid.
    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + jeton})
    if not sub:
        await socket.close(code=deps.CLOSE_UNAUTHORIZED)
        return

    # LA MÊME PORTE QUE LES ROUTES : `_entree` lit le catalogue (donc le
    # disque, donc le threadpool), et un fil inconnu n'ouvre rien. Il n'y a
    # aucun chemin par lequel une socket atteindrait un fil qu'un GET
    # refuserait.
    entree = await run_in_threadpool(_entree, fil)
    if entree is None:
        await socket.close(code=deps.CLOSE_BAD)
        return
    cle = entree["id"]
    if forum_live.full(cle):
        await socket.close(code=deps.CLOSE_BUSY)
        return

    connexion = forum_live.Connection(socket, cle)
    forum_live.join(connexion)
    try:
        await connexion.send({"t": "ready", "thread": cle})
        while True:
            entrant = await socket.receive_text()
            # ON JETTE TOUT CE QUI ENTRE, et ce n'est pas une omission : le
            # client n'a rien à dire ici, il écrit par HTTP où vivent le
            # quota et les bornes. Une socket qui accepterait un message
            # serait une seconde porte d'écriture, avec sa propre validation à
            # tenir synchronisée -- exactement ce que « une sonnette, pas un
            # transport » refuse. La borne reste, parce qu'un client qui pousse
            # un mégaoctet est un client à déconnecter.
            if len(entrant) > config.FORUM_LIVE_FRAME:
                await socket.close(code=deps.CLOSE_BAD)
                return
    except Exception:
        pass
    finally:
        forum_live.leave(connexion)
