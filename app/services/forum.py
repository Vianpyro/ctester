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


# --- LE CHAT ------------------------------------------------------------------
# LE CHAT EST PUBLIC, LE FORUM GARDE LE PRIVÉ, ET LE PRÉFIXE EST TOUTE LA
# DISTINCTION. Un fil de chat est une valeur de plus dans `exercise_id` :
# `@chat:<exercice>` ou `@chat:general`. Pas de table (elle dupliquerait la
# borne de texte, le quota, le signalement, la modération, le masquage et
# `forget()` -- six règles dont celle qui dérive est celle qui cesse de
# border), pas de colonne `kind` (elle ajouterait un `WHERE` à chaque requête
# du forum, et celui qu'on oublierait serait celui qui mélange les deux
# espaces).
#
# `@` NE PEUT APPARAÎTRE DANS AUCUN IDENTIFIANT DU CATALOGUE, donc une clé de
# chat ne résout par `find_exercise()` chez personne -- et ne devient jamais un
# chemin : le forum n'ouvre aucun fichier.
CHAT_PREFIX = "@chat:"
CHAT_GENERAL = CHAT_PREFIX + "general"


def est_chat(fil):
    """True si cette clé de fil est un chat. Le seul prédicat que la distinction coûte.

    Il sert à TROIS endroits, pas un de plus : forcer la visibilité à
    l'écriture (`forum_visibility`), choisir le rendu de l'auteur
    (`forum_identite`), et étiqueter l'écran.
    """
    return str(fil or "").startswith(CHAT_PREFIX)


def chat_de(exercice):
    """La clé du fil de chat d'un exercice. Une concaténation, nommée une fois."""
    return CHAT_PREFIX + str(exercice)


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


# --- "Je suis bloqué ici" (design 1g) ----------------------------------------
# TWO CLOSED LISTS AND A VISIBILITY, and they are closed for one reason: they
# are what the instructor's aggregate groups by (design 1h). Free text there
# would make that aggregate useless on the morning it matters -- six ways of
# writing "compilation" read as six different problems.
#
# The labels are French because they are shown as-is; the ids are the stored
# values. Adding a step is one line here and nothing else.

STEPS = {
    "statement": "l'énoncé",
    "compilation": "la compilation",
    "execution": "l'exécution",
    "result": "le résultat",
}

BLOCKED_KINDS = {
    "statement-unclear": "Je ne comprends pas l'énoncé",
    "wrong-result": "Ça compile mais le résultat est faux",
    "unclear-error": "Je ne comprends pas le message d'erreur",
}

# PRIVATE IS THE DEFAULT, and `thread` is what an ordinary question has always
# been. `group` is reachable only from `private`, and only by the author.
VISIBILITIES = ("private", "group", "thread")


def forum_step(raw):
    """(step id|None, error). None means "an ordinary question", not a refusal."""
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in STEPS:
        return None, "étape inconnue"
    return value, None


def forum_blocked_kind(raw):
    """(blocked-kind id|None, error). Same rule as the step."""
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in BLOCKED_KINDS:
        return None, "type de blocage inconnu"
    return value, None


def forum_visibility(raw, with_step, fil=None):
    """(visibility, error) -- private by default for a "stuck" post.

    A POST WITH A STEP DEFAULTS TO PRIVATE, an ordinary one to `thread`. That
    asymmetry is the design: asking for help should not require deciding, in
    the same breath, to say so publicly. `thread` is refused on a stuck post --
    the two paths stay distinguishable, which is what lets the aggregate count
    "opened to the group" as a separate number.

    DANS UN CHAT, TOUT EST PUBLIC, et c'est ici que ça se décide -- une ligne,
    au seul endroit qui décidait déjà de la visibilité. `can_see()` ne change
    donc pas d'un caractère : un message `thread` est visible de tous, c'est
    déjà son premier cas. C'est ce qui fait qu'il n'y a AUCUNE règle de
    confidentialité neuve à écrire pour le chat.
    """
    if est_chat(fil):
        if raw not in (None, "", "thread"):
            return None, "dans le chat, tous les messages sont publics"
        return "thread", None
    if raw is None or raw == "":
        return ("private" if with_step else "thread"), None
    value = str(raw)
    if value not in VISIBILITIES:
        return None, "visibilité inconnue"
    if with_step and value == "thread":
        return None, "une demande d'aide est privée ou ouverte à ton groupe"
    if not with_step and value != "thread":
        return None, "une question ordinaire est visible du fil"
    return value, None


def can_see(message, sub, moderateur, my_group, groups):
    """Can THIS reader see this message? The only visibility rule.

    FOUR CASES, AND THE ORDER MATTERS:
      * one's own message, always -- including one's own private ones;
      * a moderator, always: a private question is addressed to them, that is
        what "seulement le chargé de lab" means on the form;
      * `thread`, the ordinary public post everyone sees;
      * `group`, only for someone whose group number matches the author's.

    A `group` MESSAGE FROM AN AUTHOR WITH NO GROUP is visible to nobody but
    them and a moderator: without a group there is no group to open it to, and
    guessing one would publish it wider than asked.
    """
    if message["account"] == sub or moderateur:
        return True
    # ABSENT READS AS `thread`, the same default the column carries: a row
    # written before this column existed is an ordinary public post, and
    # treating it as private would make old threads vanish.
    visibility = message.get("visibility") or "thread"
    if visibility == "thread":
        return True
    if visibility != "group":
        return False
    their_group = groups.get(message["account"])
    return their_group is not None and my_group is not None and their_group == my_group


def forum_frame(raw, unlocked):
    """(frame id|None, error) -- a plate frame among those this account unlocked.

    THE LIST OF UNLOCKED FRAMES IS RECOMPUTED SERVER-SIDE from the level, and
    never taken from the request: a frame is decoration, but "which ones do I
    have" is still a fact about an account, and a fact about an account is not
    something the browser gets to assert.

    Empty is not an error -- it is the default, and it stays on offer.
    """
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in {c["id"] for c in unlocked}:
        return None, "ce cadre n'est pas débloqué"
    return value, None


def forum_identite(profil, sub, auteur, moderateur_lecteur):
    """(displayed author, displayed group number, is the name chosen).

    THE ONLY PLACE A PROFILE BECOMES PUBLIC. A name only comes out if its
    owner made it visible; the group number also comes out for the
    instructor, at all times, because that is what lets a problem be traced
    to a group without asking anyone for a name.

    L'ANONYME EST MASQUÉ, PAS INDISTINCT. « Participant » pour tout le monde
    rendait une conversation illisible : on ne sait pas qui répond à qui. Le
    repli est donc l'ALIAS -- tiré d'un vocabulaire fermé
    (`policy.possible_aliases()`), donc rien de ce qu'un étudiant tape ne peut
    l'atteindre, DONC IL N'Y A AUCUN PSEUDONYME À MODÉRER. C'est la même
    valeur qu'au classement, exprès : une seule identité masquée par compte,
    et « Un autre nom » la change partout, historique compris.

    ON MODIFIE CETTE FONCTION, ON NE LA DUPLIQUE PAS. Une seconde fonction
    d'identité serait le second endroit où la visibilité d'un nom peut diverger
    de ce que la base dit. Conséquence assumée : le forum en profite aussi,
    deux « Participant » y devenant distinguables.

    « Participant » RESTE le dernier repli, pour un compte qui n'a pas encore
    d'alias -- un nom manquant ne doit jamais empêcher d'afficher un message.

    L'ALIAS N'EST PAS SIGNALABLE : le troisième retour ne parle que du nom
    TAPÉ. Signaler un mot d'un vocabulaire fermé n'aurait rien à corriger.
    """
    profil = profil or {}
    pseudo = profil.get("display_name")
    alias = profil.get("alias")
    choisi = bool(pseudo) and bool(profil.get("display_name_public"))
    if auteur == sub:
        # SOUS QUEL NOM JE PARLE. Quelqu'un qui écrit masqué doit pouvoir lire
        # sa propre poignée : sans ça, il ne peut pas se reconnaître dans le
        # fil, ni savoir ce que les autres voient de lui.
        nom = "Vous (%s)" % alias if alias else "Vous"
    elif is_moderator(auteur):
        nom = "Enseignant"
    elif choisi:
        nom = pseudo
    else:
        nom = alias or "Participant"
    groupe = profil.get("group_number")
    if groupe is not None and not (profil.get("group_number_public")
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
    must be able to restore them. PRIVATE messages go out to their author and
    to a moderator, group ones to the author's group -- `can_see()` is the
    single rule, applied here and nowhere else.

    A MESSAGE'S OWN GROUP NUMBER IS NOT WHAT DECIDES: `groupes` is built from
    the profiles already read for this thread, so the visibility rule reads
    the same source as the displayed group. Two sources would drift, and the
    one that drifted would be the one that shows too much.
    """
    profils = profils or {}
    groups = {account: (p or {}).get("group_number")
             for account, p in profils.items()}
    my_group = (profils.get(sub) or {}).get("group_number")
    vus = []
    for m in messages:
        if not (moderateur or not m["hidden"]):
            continue
        if not can_see(m, sub, moderateur, my_group, groups):
            continue
        nom, groupe, signalable = forum_identite(
            profils.get(m["account"]), sub, m["account"], moderateur)
        vus.append({"id": m["id"], "text": m["text"], "created_at": m["created_at"],
                    "author": nom, "group": groupe,
                    "reportable_name": signalable,
                    "mine": m["account"] == sub,
                    "hidden": m["hidden"],
                    # "Bloqué ici": the step and the kind travel as ids, and
                    # the page owns the labels -- the same split as skills.
                    "step": m.get("step"),
                    "blocked_kind": m.get("blocked_kind"),
                    "visibility": m.get("visibility") or "thread",
                    # The retained answer and the usefulness counter, both
                    # derived server-side (see `state.forum_fil`). `helped_me`
                    # is what turns the button off for someone who already
                    # clicked it, without a second round trip.
                    "retained": bool(m.get("retained")),
                    # LE LIEN VERS LA RACINE, un handle opaque déjà public.
                    # C'est de la navigation : la visibilité d'une réponse ne
                    # se dérive pas de lui, elle est la sienne.
                    "reply_to": m.get("reply_to"),
                    # LE VOTE, EN DEUX COMPTEURS ET UN SIGNE. `downvotes` ne
                    # peut être non nul que sur une réponse -- le `WHERE` de
                    # `forum_voter` l'y enferme -- donc aucune question
                    # n'affiche jamais de négatif, sans qu'une règle
                    # d'affichage ait à le tenir.
                    "upvotes": int(m.get("upvotes") or 0),
                    "downvotes": int(m.get("downvotes") or 0),
                    "my_vote": int(m.get("my_vote") or 0)})
    return vus


# --- The thread's state (design 1f) -------------------------------------------
# A QUESTION HAS A STATE, and the state is DERIVED, never stored: a thread
# where the answer that worked is findable is the whole ask. Storing it would
# be one more column to keep true; deriving it means a moderator retaining an
# answer changes the state with no second write.


def thread_state(views):
    """{"unanswered": n, "answered": n, "resolved": n} for this rendered thread.

    Read on what the CALLER can see, so the counts match the messages under
    them: a private question nobody else can read must not inflate anyone
    else's "sans réponse".

    ONE THREAD PER EXERCISE is still the model (there is no question id): the
    thread is "resolved" once a moderator has retained an answer in it,
    "answered" once someone other than the first author has written, and
    "unanswered" otherwise. That is a state one can act on without inventing
    a question/answer schema the forum does not have.
    """
    if not views:
        return {"unanswered": 0, "answered": 0, "resolved": 0}
    if any(v["retained"] for v in views):
        return {"unanswered": 0, "answered": 0, "resolved": 1}
    if len(views) > 1 and len({v["author"] for v in views}) > 1:
        return {"unanswered": 0, "answered": 1, "resolved": 0}
    return {"unanswered": 1, "answered": 0, "resolved": 0}
