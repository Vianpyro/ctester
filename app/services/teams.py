"""Team assignments: the gate, the team-visible identity, and the hand-in archive.

THREE THINGS LIVE HERE, AND THE FIRST ONE IS THE WHOLE FEATURE.

`workspace()` IS THE ONLY GATE. It answers one question -- "may THIS account
work on THIS assignment, and as part of which team?" -- from the authenticated
`sub` and the published catalog, and from nothing else. Every HTTP route and
the collaboration socket call it before touching a document, a revision, a
hand-in or a room. A team id in a body, a URL or a WebSocket frame is never
read: the chain is

    authenticated account -> team membership -> assignment -> exercise

and it is walked in that order, server-side, on every single request. There is
no hidden control anywhere in the page that authorizes anything.

NO `sub` CROSSES THE HTTP BOUNDARY, exactly as in `services/forum.py`.
`members_view()` turns the roster into what teammates are allowed to see: the
name someone CHOSE to display, else a position in the team ("Coéquipier 2").
Presence and cursors carry that position, never an account id -- a member
handle is meaningless outside the team it was built for.

THE ARCHIVE IS DRIVEN BY THE ASSIGNMENT FILE, never by a file name this
application happens to know. `handin_files()` reads `handin.files` from the
published assignment; "main.c and matrac_lib.c" is a fact about TCH009's
assignment, written in its content, and nothing here mentions it.
"""

import io
import re
import zipfile

import config
from services.catalog import load_catalog, validate_files

# THE TEAM PALETTE. Positions, not accounts: the fourth member of every team
# is the same colour, and that colour says nothing about who they are. Picked
# to stay apart in both themes and to remain distinguishable for the most
# common colour vision deficiencies -- a caret is a two-pixel line, and it is
# the only thing that says whose it is.
COLORS = ("#e0533d", "#2f8fd8", "#7d57c1", "#1f9d6a", "#c9821b", "#c2418f",
          "#3f7f8f", "#8a6b3d")

# What a teammate is called when they have not chosen a public display name.
# A POSITION, AND IT IS STABLE FOR THE TEAM'S LIFETIME: it comes from the
# roster's order, so "Coéquipier 2" is the same person all term -- which is
# what makes a cursor followable -- while telling nobody who that is.
ANONYMOUS_LABEL = "Coéquipier %d"


def assignments(now=None):
    """The published assignments that are OPEN, in catalog order.

    Same rule and same shape as `exercices_ouverts()`: a locked assignment is
    in the catalog with its date -- so the page can say "opens on the 16th"
    rather than showing nothing -- but it does not resolve, so nothing about
    it opens.
    """
    return [entry for entry in (load_catalog() or {}).get("assignments") or ()
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            and entry.get("access") == "available"]


def published_assignment(assignment_id):
    """This assignment's published entry, OPEN OR NOT. Never a gate.

    `find_assignment()` refuses what is not open, and every route that touches
    a document goes through it. This one exists for the single case where
    showing is not giving: telling a student which team they are on before the
    assignment opens -- the same rule the catalog already follows by carrying
    locked exercises with their date.
    """
    for entry in (load_catalog() or {}).get("assignments") or ():
        if isinstance(entry, dict) and entry.get("id") == assignment_id:
            return entry
    return None


def find_assignment(assignment_id):
    """This OPEN assignment's published entry, or None. The catalog gate."""
    for entry in assignments():
        if entry["id"] == assignment_id:
            return entry
    return None


def assignment_exercises(assignment):
    """The assignment's exercise ids, in the order the assignment declares.

    THE ORDER IS THE ASSIGNMENT'S, not the catalog's: it is the order the
    handout works through, and the workspace's `[1] [2] [3]` strip is that
    order. Sorting it here would silently renumber someone's handout.
    """
    return [item for item in assignment.get("items") or []
            if isinstance(item, str)]


def is_team_assignment(assignment):
    """True when the assignment declares a team requirement.

    THE ABSENCE OF `team` IS THE DEFAULT, and it is what makes the whole
    feature additive: every exercise published before this existed has no
    assignment at all, and an assignment with no `team` block is an ordinary
    individual one.
    """
    return bool(assignment) and isinstance(assignment.get("team"), dict)


def deadline_passed(assignment, now=None):
    """True when the assignment's deadline is behind us. False when there is none.

    Read from the release the same way `access()` reads an opening date: a
    deadline is data, not a job somebody has to run at midnight.
    """
    import datetime as dt

    raw = assignment.get("deadline")
    if not isinstance(raw, str):
        return False
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        return False
    return (now or dt.datetime.now(dt.timezone.utc)) > moment


# --- Se former une équipe -------------------------------------------------------
# LE LISTAGE DE L'ENSEIGNANT EST TOMBÉ SUR UN FAIT : CTester ne lui montre
# jamais un `sub` -- c'est le modèle de confidentialité du forum, et il n'est
# pas négociable pour ça. Il ne peut donc nommer personne dans un CSV, et un
# listage que personne ne peut écrire n'est pas une garantie.
#
# LES ÉQUIPES SE FORMENT DONC ELLES-MÊMES, sous protocole : on crée, on
# partage un code, on rejoint, et CHACUN CONFIRME. Quand tout le monde a
# confirmé -- et seulement là -- l'équipe est SCELLÉE et le devoir s'ouvre.
#
# CE QUI REMPLACE « un étudiant ne peut pas choisir son équipe » :
#   * une équipe non scellée n'a accès à RIEN, donc il n'y a rien à convoiter
#     en la rejoignant ;
#   * une équipe scellée ne se rejoint plus ;
#   * et le verrou de chacun EST son consentement -- les autres voient qui est
#     là avant de confirmer, ce qu'un listage ne demandait à personne.

# L'ALPHABET DU CODE, SANS LES CARACTÈRES QU'ON CONFOND. Pas de I ni de 1, pas
# de O ni de 0, pas de L. Ce code se lit à voix haute dans un laboratoire
# bruyant et se recopie d'un téléphone : chaque ambiguïté est un étudiant qui
# croit avoir le mauvais code et redemande.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
# Combien de tirages avant d'abandonner. Une collision sur 31^6 est déjà une
# curiosité ; cinq de suite est une base qui ne répond pas, pas de la malchance.
CODE_TRIES = 5

# Ce qu'un nom d'équipe peut valoir. Même esprit que `forum_pseudo` : on borne,
# on ne rend rien, et l'affichage échappe.
TEAM_LABEL_MAX = 40


def team_label(brut):
    """(nom|None, erreur) -- le nom que l'équipe se donne.

    IL EST OBLIGATOIRE, contrairement au pseudonyme du forum : une équipe sans
    nom est « e7f3c1... » dans une liste, et personne ne reconnaît la sienne.
    Les caractères de contrôle deviennent des espaces plutôt que de
    disparaître -- les retirer collerait deux mots.
    """
    if not isinstance(brut, str):
        return None, "nom d'équipe manquant"
    nom = " ".join("".join(c if c >= " " else " " for c in brut).split())
    if not nom:
        return None, "donne un nom à ton équipe"
    if len(nom) > TEAM_LABEL_MAX:
        return None, f"nom trop long (maximum {TEAM_LABEL_MAX} caractères)"
    return nom, None


def invite_code(hasard=None):
    """Un code d'invitation. Tiré, pas dérivé.

    DÉRIVÉ DU `team_id` OU DU COMPTE, il serait devinable par quiconque connaît
    l'un des deux -- et le `team_id` voyage dans le bandeau de l'équipe. Tiré,
    il ne dit rien de personne.
    """
    import random

    tirage = hasard or random.SystemRandom()
    return "".join(tirage.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def team_size(assignment):
    """(min, max) pour ce devoir. (1, TEAM_MAX) s'il ne dit rien.

    Le contenu décide : TCH009 demande trois ou quatre, un autre cours
    demanderait deux. Rien de ça n'est écrit dans l'application.
    """
    team = assignment.get("team") or {}
    low = team.get("min") if isinstance(team.get("min"), int) else 1
    high = team.get("max") if isinstance(team.get("max"), int) else low
    return low, high


def formation_state(assignment, team, locks):
    """Ce qui manque pour sceller. UNE fonction, lue par la page ET par l'API.

    L'ÉCRAN DOIT DIRE POURQUOI LE BOUTON NE SUFFIT PAS -- « il manque un
    coéquipier », « il manque le groupe », « il manque deux confirmations » --
    parce qu'une équipe bloquée sans explication est une équipe qui écrit à son
    enseignant. Les trois manques sont cumulables et se disent tous.
    """
    low, high = team_size(assignment)
    membres = len(locks)
    manque = []
    if membres < low:
        manque.append("il manque %d coéquipier%s (%d sur %d)"
                      % (low - membres, "s" if low - membres > 1 else "",
                         membres, low))
    if membres > high:
        manque.append("vous êtes %d, le maximum est %d" % (membres, high))
    if team.get("group_number") is None:
        manque.append("le groupe n'est pas choisi")
    reste = sum(1 for confirme in locks.values() if not confirme)
    if reste:
        manque.append("%d confirmation%s manquante%s"
                      % (reste, "s" if reste > 1 else "", "s" if reste > 1 else ""))
    return manque


def workspace(state, sub, assignment_id):
    """(assignment, team, refusal) -- THE GATE. Nothing opens without it.

    `refusal` is `(status, message)` or None, and the three refusals are
    deliberately different sentences: "this assignment does not exist or is
    not open yet", "this assignment is not team work" and "you are not on a
    team for it" send a student to three different places, and folding them
    into one 403 would send all three to their instructor.

    A DATABASE THAT DOES NOT ANSWER LOOKS LIKE NO TEAM, and that is the safe
    direction: without a proven membership, nothing opens. The caller says so
    honestly rather than showing an empty workspace.
    """
    assignment = find_assignment(assignment_id)
    if assignment is None:
        return None, None, (404, "devoir inconnu")
    if not is_team_assignment(assignment):
        return assignment, None, (400, "ce devoir n'est pas un travail d'équipe")
    team = state.team_of(sub, assignment_id)
    if team is None:
        return assignment, None, (
            403, "tu n'as pas encore d'équipe pour ce devoir — crée-la ou "
                 "rejoins celle de tes coéquipiers avec leur code")
    # UNE ÉQUIPE NON SCELLÉE N'A ACCÈS À RIEN, ET C'EST TOUT LE PROTOCOLE.
    # C'est ce qui fait qu'on ne gagne rien à rejoindre une équipe : tant que
    # les quatre n'ont pas confirmé la composition, il n'y a pas de document,
    # pas d'historique, pas de salle et pas de remise. L'ancienne garantie --
    # « personne ne peut se mettre sur une équipe » -- est remplacée par
    # celle-ci, qui tient sans que l'enseignant ait à connaître un seul `sub`.
    if not team.get("sealed"):
        return assignment, None, (
            403, "votre équipe n'est pas encore confirmée : le devoir s'ouvre "
                 "quand tous ses membres l'ont validée")
    return assignment, team, None


def exercise_in(assignment, exercise_id):
    """True when this exercise belongs to this assignment.

    THE SECOND HALF OF THE GATE, and it is not optional: `workspace()` proves
    the team, this proves the exercise. Without it, a member of one team could
    reach a document keyed on their own team and any exercise id at all --
    including an exercise of another assignment they have no business in.
    """
    return exercise_id in set(assignment_exercises(assignment))


def members_view(roster, sub, profiles, locks=None):
    """The team, as teammates are allowed to see it. NO `sub` COMES OUT.

    Same rule as `forum_identite()`: a display name only appears if its owner
    chose one AND made it visible. Otherwise the position in the roster, which
    is stable, useful for following a cursor, and says nothing about who it
    is.

    `id` IS THE POSITION, NOT THE ACCOUNT. It is what presence and cursor
    frames carry, and it is meaningless outside this team -- there is nothing
    to correlate against another exercise, another assignment or the forum.
    """
    profiles = profiles or {}
    locks = locks or {}
    out = []
    for index, account in enumerate(roster):
        profile = profiles.get(account) or {}
        name = profile.get("display_name")
        chosen = bool(name) and bool(profile.get("display_name_public"))
        out.append({
            "id": "m%d" % (index + 1),
            "name": name if chosen else ANONYMOUS_LABEL % (index + 1),
            "color": COLORS[index % len(COLORS)],
            "you": account == sub,
            # QUI A CONFIRMÉ, pendant la formation. C'est ce qui rend l'attente
            # lisible : « on attend Coéquipier 3 » plutôt qu'un bouton grisé
            # dont personne ne sait ce qu'il attend.
            "locked": bool(locks.get(account)),
        })
    return out


def member_handle(roster, sub):
    """This account's position in its own team, or "" if it is not on it.

    The handle the socket stamps on every frame it relays. It is derived
    server-side from the roster, so a client cannot claim to be someone else's
    caret by writing a different id -- which is the whole reason cursors do
    not carry a name the browser chose.
    """
    try:
        return "m%d" % (roster.index(sub) + 1)
    except ValueError:
        return ""


# --- The hand-in --------------------------------------------------------------
# WHAT GOES IN THE ARCHIVE COMES FROM `handin.files`, AND ONLY FROM THERE. The
# assignment names the file in the archive, the exercise it comes from, and the
# file within that exercise; `content_catalog._handin()` already refused a name
# that is not one of the exercise's declared files, so nothing here has a path
# to build.
#
# NOTHING IS CONCATENATED, REFORMATTED OR ANNOTATED. What the team wrote is
# what is handed in, byte for byte: a build that silently merged two files
# would hand in code the team has never compiled.
#
# AND THERE IS NO README INSIDE. The assignment sheet asks for main.c and
# matrac_lib.c; an extra file in the archive is one more thing for a marker to
# wonder about, and a manifest that repeats what the file names already say
# buys nothing.


def handin_files(state, assignment, team_id, catalog_entry_of):
    """{archive path: contents} for this team's hand-in, and what is missing.

    Returns `(files, missing)`. A file whose exercise has no document yet is
    NOT silently emitted empty: it comes back in `missing`, and the page says
    so before the team hands in something with a hole in it.

    `None` for `files` means the database did not answer -- never an empty
    archive, which is the one failure that would look like a successful
    hand-in.
    """
    handin = assignment.get("handin") or {}
    root = handin.get("root") or assignment["id"]
    files, missing = {}, []
    for item in handin.get("files") or []:
        exercise_id, wanted = item.get("exercise_id"), item.get("file")
        entry = catalog_entry_of(exercise_id)
        sources = state.read_team_document(team_id, exercise_id)
        if sources is None:
            return None, []
        if entry is not None:
            # THE SAME ALLOW-LIST AS EVERY OTHER PATH. What comes out of the
            # database was put there by a student; the catalog decides which
            # names exist, here as at submission time.
            checked, message, _ = validate_files(entry, sources)
            sources = checked if message is None else {}
        text = sources.get(wanted, "")
        if not text.strip():
            missing.append({"name": item["name"], "exercise_id": exercise_id})
            continue
        files[root + "/" + item["name"]] = text
    return files, missing


# The archive's timestamp. FIXED, and that is the point: the same documents
# must produce the same bytes whenever they are zipped, or "the export is
# deterministic" is a sentence with no check behind it. 1980-01-01 is the
# earliest instant the ZIP format can store.
ARCHIVE_EPOCH = (1980, 1, 1, 0, 0, 0)


def build_zip(files):
    """The archive's bytes. DETERMINISTIC: same input, same output, always.

    Entries are sorted, every timestamp is the same constant, and the mode
    bits and creator system are written rather than inherited from whatever
    machine is running -- a ZIP built on the Dell and one built on a laptop
    must not differ, or the test that proves it would only prove where it ran.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ARCHIVE_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0            # never "this OS"
            info.external_attr = 0o644 << 16  # rw-r--r--, not the umask of the day
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


# WHAT MAY APPEAR IN A FILE NAME WE PUT IN A HEADER. The two halves are
# already bounded at their source -- `ARCHIVE_ROOT_RE` in the content
# validator, `TEAM_ID_RE` in `import_teams.py` -- and this is the belt: a
# `Content-Disposition` is a header, and a quote or a newline reaching one is
# header injection. Belt AND braces, because the roster arrives as a
# spreadsheet somebody edited by hand.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def archive_name(assignment, team):
    """The downloaded file's name: the assignment's root and the team."""
    root = (assignment.get("handin") or {}).get("root") or assignment["id"]
    return "%s-%s.zip" % (_SAFE_NAME.sub("-", str(root))[:64],
                          _SAFE_NAME.sub("-", str(team["team_id"]))[:64])


def assignment_view(assignment, now=None):
    """The assignment as the page reads it: title, deadline, order, hand-in.

    A projection of the projection: `catalog.json` already carries only public
    fields, and this only reshapes them so a workspace does not have to walk
    the whole catalog to draw its header.
    """
    return {
        "id": assignment["id"],
        "title": assignment.get("title", ""),
        "description": assignment.get("description", ""),
        "items": assignment_exercises(assignment),
        "team": dict(assignment.get("team") or {}),
        "deadline": assignment.get("deadline"),
        "deadline_passed": deadline_passed(assignment, now),
        # READ FROM THE PUBLISHED ENTRY, NOT RECOMPUTED. `content_catalog`
        # lives at the repo ROOT and is the worker's; this container mounts
        # `app/` only, so importing it here would have crashed the API at
        # startup -- and only in production, where the mount is real.
        # `publish_content` already computed this field when it wrote the
        # release, and `access()` stays the single reader of a release.
        "access": assignment.get("access", "archived"),
        "handin": [dict(item) for item in
                   (assignment.get("handin") or {}).get("files") or []],
    }


def revisions_view(rows, roster):
    """The history, with the `sub`s replaced by team positions.

    THE HISTORY NAMES A POSITION, NOT AN ACCOUNT, for the same reason presence
    does: "Coéquipier 2 wrote this at 14:32" is what a team needs to
    reconstruct an afternoon, and it is all they need. An account that has
    since erased its data no longer appears at all -- `forget()` deletes its
    revisions -- and its rows simply are not there to name.

    THERE IS NO PERCENTAGE ANYWHERE IN HERE, and there must not be one. A
    number counting typed characters becomes a grade the moment it exists,
    and it is wrong about whoever thinks before typing.
    """
    positions = {account: index + 1 for index, account in enumerate(roster)}
    out = []
    for row in rows:
        index = positions.get(row["account"])
        out.append({"id": row["revision_id"],
                    "author": "m%d" % index if index else "",
                    "created_at": row["created_at"], "bytes": row["bytes"]})
    return out[:config.TEAM_REVISIONS_MAX]
