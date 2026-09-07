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


# --- Rejoindre une équipe -------------------------------------------------------
# LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE DE COURS, et un étudiant prend
# une place libre dans celle qu'il veut. C'est le geste qu'il fait déjà sur
# Moodle, et il DOIT correspondre : « Équipe 7 » ici est « Équipe 7 » là-bas,
# sinon l'enseignant corrige deux listes qui divergent.
#
# DEUX AUTRES DESSINS ONT ÉTÉ ESSAYÉS ET RETIRÉS, et le savoir évite de les
# refaire : un listage écrit par l'enseignant (impossible -- CTester ne lui
# montre jamais un `sub`), puis un code d'invitation avec confirmation unanime
# (correct, mais sans rapport avec ce que les étudiants font déjà, et pas
# nécessaire).
#
# CE QUI FERME LES ÉQUIPES EST UNE DATE QUE LE CONTENU PORTE DÉJÀ : on rejoint
# et on quitte TANT QUE LE DEVOIR EST FERMÉ. Les deux conditions lisent la même
# valeur -- `access` de l'entrée publiée -- donc elles sont mutuellement
# exclusives PAR CONSTRUCTION : il n'existe aucun instant où l'on peut à la
# fois rejoindre une équipe et lire son document.

# Ce qu'une équipe s'appelle. Le numéro est celui de Moodle, et le mot est
# celui de l'énoncé -- rien ici n'est saisi par un étudiant.
TEAM_NAME = "Équipe %d"


def team_size(assignment):
    """(min, max, count) pour ce devoir, depuis son contenu.

    `count` EST COMBIEN D'ÉQUIPES CHAQUE GROUPE A, et c'est ce qui rend la
    correspondance avec Moodle possible : la liste montre exactement ces
    équipes-là, ni plus ni moins.
    """
    team = assignment.get("team") or {}
    low = team.get("min") if isinstance(team.get("min"), int) else 1
    high = team.get("max") if isinstance(team.get("max"), int) else low
    count = team.get("count") if isinstance(team.get("count"), int) else 0
    return low, high, count


def team_handle(group_number, number):
    """`g04-e07` -- la poignée d'une équipe. CONSTRUITE, jamais saisie.

    Elle clé le document partagé, nomme la salle de collaboration et finit
    dans le nom de l'archive. Elle porte le GROUPE parce que les équipes sont
    numérotées par groupe : « Équipe 7 » du groupe 04 et « Équipe 7 » du
    groupe 06 sont deux équipes, et une poignée qui ne porterait que le numéro
    en ferait une seule -- avec un seul document.
    """
    return "g%02d-e%02d" % (int(group_number), int(number))


def joinable(assignment):
    """True tant que le devoir n'est pas ouvert. LA SEULE FERMETURE.

    Pas de scellement, pas de date à part : la date d'ouverture du devoir
    ferme les équipes toute seule. Tant qu'il est fermé, il n'y a rien à voler
    dans une équipe qu'on rejoindrait ; une fois ouvert, plus personne ne
    bouge.

    ELLE LIT `access`, LA MÊME VALEUR QUE `find_assignment()`, et c'est ce qui
    rend les deux mutuellement exclusives : il n'existe aucun instant où l'on
    peut à la fois rejoindre une équipe et ouvrir son document. Deux sources --
    une date ici, une release là -- auraient fini par se croiser.
    """
    return bool(assignment) and assignment.get("access") != "available"


def available_teams(assignment, group_number, existantes):
    """La liste que l'étudiant parcourt : les `count` équipes de SON groupe.

    LE CONTENU DIT COMBIEN, LA BASE DIT QUI EST DEDANS. Une équipe que
    personne n'a rejointe n'a pas de ligne -- la peupler à la publication
    ferait douze lignes par groupe que personne ne lit -- donc elle apparaît
    ici avec zéro membre et sera créée le jour où quelqu'un y entre.

    `full` EST CALCULÉ ICI, PAS PAR LA PAGE : une page qui déciderait qu'une
    équipe a de la place serait une page où l'on s'en déclare une depuis la
    console. Le `WHERE` de l'INSERT le revérifie de toute façon.
    """
    _low, high, count = team_size(assignment)
    par_numero = {ligne["number"]: ligne for ligne in existantes}
    liste = []
    for number in range(1, count + 1):
        ligne = par_numero.get(number) or {}
        membres = int(ligne.get("members") or 0)
        liste.append({
            "number": number,
            "name": TEAM_NAME % number,
            "members": membres,
            "max": high,
            "full": membres >= high,
        })
    return liste
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
        # LE DEVOIR EST OUVERT (`find_assignment` l'exige) ET CE COMPTE N'A PAS
        # D'ÉQUIPE : les équipes se choisissaient AVANT l'ouverture, donc il
        # est trop tard pour en prendre une seul. C'est le seul cas qui demande
        # l'enseignant, et le message le dit plutôt que de renvoyer vers une
        # liste qui ne s'ouvrira plus.
        return assignment, None, (
            403, "tu n'es dans aucune équipe pour ce devoir, et les équipes "
                 "sont figées depuis son ouverture — vois avec ton enseignant")
    return assignment, team, None


def exercise_in(assignment, exercise_id):
    """True when this exercise belongs to this assignment.

    THE SECOND HALF OF THE GATE, and it is not optional: `workspace()` proves
    the team, this proves the exercise. Without it, a member of one team could
    reach a document keyed on their own team and any exercise id at all --
    including an exercise of another assignment they have no business in.
    """
    return exercise_id in set(assignment_exercises(assignment))


def members_view(roster, sub, profiles):
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
