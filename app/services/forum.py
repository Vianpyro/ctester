"""The peer help forum: bounds, chosen identity, and a `sub`-free view.

NO `sub` EVER CROSSES THE HTTP BOUNDARY. `forum_vue()` translates the author
into "Vous" / "Enseignant" / the name the student CHOSE to display, else
"Participant". This is this module's most important property, and a test
exercises it by searching for `sub` in the JSON payload -- including in the
most detailed view, a moderator's.

THE SERVER RENDERS NOTHING AND SANITIZES NOTHING, IT BOUNDS. Messages are
stored in their SOURCE form; it is `forum.js` that escapes `<` before Markdown
parsing then runs the output through DOMPurify. Sanitizing here would freeze
the rule at write time, whereas a rule tightened later must apply to messages
already in the database.
"""

import config
from security import is_moderator, oidc_enabled


# ONE chronological thread per PUBLISHED exercise, private to signed-in
# accounts. Nothing here produces game value: no XP, no achievement, no
# counter, and phase 1's progression is neither read nor written from these
# routes.
#
# MODERATION IS HUMAN, AND WE DO NOT PRETEND OTHERWISE. There is no solution
# detector: the only automatic rules are bounds (length, quota) and refusing
# links, which is a charter rule -- not a judgment on content. Everything else
# goes through a report and someone reading it.


def forum_enabled():
    """True when the forum can be offered. FALSE by default.

    It requires sign-in (so the issuer, the client and the database) AND at
    least one configured moderator. The second condition is not cosmetic: a
    report must reach someone, or we would be offering a public channel with
    no recourse.
    """
    return oidc_enabled() and bool(config.FORUM_MODERATORS)


def forum_texte(brut):
    """(text, error message) -- restricted, short Markdown, and nothing else.

    WHAT IS STORED IS THE SOURCE, NOT HTML. The server renders nothing and
    sanitizes nothing: it bounds. Rendering -- Markdown then a sanitizer --
    happens at DISPLAY time, on every display, in `forum.js`. Sanitizing only
    at write time would be the wrong half of the work: a rule tightened later
    would not apply to messages already in the database.

    Control characters are stripped anyway: they serve no purpose in
    Markdown, they complicate a human proofread, and they have no reason to
    wait for the browser to disappear.
    """
    if not isinstance(brut, str):
        return None, "message manquant"
    texte = brut.replace("\r\n", "\n")
    texte = "".join(c for c in texte if c in "\n\t" or c >= " ").strip()
    if not texte:
        return None, "un message vide n'aide personne"
    if len(texte) > config.FORUM_MAX_CHARS:
        return None, f"message trop long (maximum {config.FORUM_MAX_CHARS} caractères)"
    return texte, None


# A display name: short, one line, and not impersonating an interface label.
_PSEUDOS_RESERVES = frozenset({"vous", "participant", "equipe du cours",
                               "équipe du cours", "moderateur", "modérateur",
                               "anonyme", "enseignant"})


def forum_pseudo(brut):
    """(name|None, error) -- the name one gives oneself, or nothing.

    NOTHING COMES FROM AN OIDC CLAIM: this field is typed in, so it is bounded
    like a message. Empty or absent means "no name", not an error -- it is
    the default state and it remains on offer.

    Interface labels are reserved: an "Enseignant" chosen by a student would
    make their message look like a reply from the course, and no color fixes
    that. The old label "Équipe du cours" stays reserved too -- nothing
    should be able to reclaim it.
    """
    if brut is None:
        return None, None
    if not isinstance(brut, str):
        return None, "nom invalide"
    # CONTROL CHARACTERS BECOME SPACES, they do not disappear: removing them
    # would glue a name written on two lines into a single word, i.e. into a
    # different name than the one typed.
    nom = " ".join("".join(c if c >= " " else " " for c in brut).split())
    if not nom:
        return None, None
    if len(nom) > config.FORUM_PSEUDO_MAX:
        return None, f"nom trop long (maximum {config.FORUM_PSEUDO_MAX} caractères)"
    if nom.casefold() in _PSEUDOS_RESERVES:
        return None, "ce nom est réservé à l'interface, choisis-en un autre"
    return nom, None


def forum_groupe(brut):
    """(number|None, error) -- the group number, or nothing.

    If `CTESTER_FORUM_GROUPES` lists specific groups, only those pass;
    otherwise a two-digit number (1..99), which is what a course outline
    hands out.
    """
    if brut is None or brut == "":
        return None, None
    if isinstance(brut, bool):
        return None, "numéro de groupe invalide"
    try:
        numero = int(brut)
    except (TypeError, ValueError):
        return None, "numéro de groupe invalide"
    if config.FORUM_GROUPES:
        if numero not in config.FORUM_GROUPES:
            return None, "groupe inconnu pour cette session"
    elif not 1 <= numero <= 99:
        return None, "le numéro de groupe va de 1 à 99"
    return numero, None


def forum_identite(profil, sub, auteur, moderateur_lecteur):
    """(displayed author, displayed group number, is the name chosen).

    THE ONLY PLACE A PROFILE BECOMES PUBLIC. A name only comes out if its
    owner made it visible; the group number also comes out for the
    instructor, at all times, because that is what lets a problem be traced
    to a group without asking anyone for a name.
    """
    profil = profil or {}
    pseudo = profil.get("pseudo")
    choisi = bool(pseudo) and bool(profil.get("pseudo_public"))
    if auteur == sub:
        nom = "Vous"
    elif is_moderator(auteur):
        nom = "Enseignant"
    else:
        nom = pseudo if choisi else "Participant"
    groupe = profil.get("groupe")
    if groupe is not None and not (profil.get("groupe_public")
                                  or moderateur_lecteur or auteur == sub):
        groupe = None
    return nom, groupe, choisi and auteur != sub


def forum_vue(messages, sub, moderateur, profils=None):
    """What a thread becomes for THIS caller. NO `sub` ever crosses this line.

    "Vous" for its own author, "Enseignant" for a moderator, and for
    everyone else the name they CHOSE TO DISPLAY, else "Participant". The
    name and group number are typed in by the student and only appear if they
    made them visible -- anonymity stays the default, and two messages only
    get tied together if their author wanted that. The `sub` itself still
    never crosses.

    Hidden messages only ever go out to a moderator: they are the one who
    must be able to restore them.
    """
    profils = profils or {}
    vus = []
    for m in messages:
        if not (moderateur or not m["masque"]):
            continue
        nom, groupe, signalable = forum_identite(
            profils.get(m["utilisateur"]), sub, m["utilisateur"], moderateur)
        vus.append({"id": m["id"], "texte": m["texte"], "cree_le": m["cree_le"],
                    "auteur": nom, "groupe": groupe,
                    "nom_signalable": signalable,
                    "mien": m["utilisateur"] == sub,
                    "masque": m["masque"]})
    return vus
