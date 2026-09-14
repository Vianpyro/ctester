import config
from security import is_moderator, oidc_enabled

# `@` never appears in a catalog id, so a chat key can't resolve to an exercise.
CHAT_PREFIX = "@chat:"
CHAT_GENERAL = CHAT_PREFIX + "general"


def is_chat(thread):
    return str(thread or "").startswith(CHAT_PREFIX)


def chat_key(exercise):
    return CHAT_PREFIX + str(exercise)


def forum_enabled():
    return oidc_enabled() and bool(config.FORUM_MODERATORS)


def forum_text(raw):
    if not isinstance(raw, str):
        return None, "message manquant"
    text = raw.replace("\r\n", "\n")
    text = "".join(c for c in text if c in "\n\t" or c >= " ").strip()
    if not text:
        return None, "un message vide n'aide personne"
    if len(text) > config.FORUM_MAX_CHARS:
        return None, f"message trop long (maximum {config.FORUM_MAX_CHARS} caractères)"
    return text, None


_RESERVED_NAMES = frozenset({"vous", "participant", "equipe du cours",
                             "équipe du cours", "moderateur", "modérateur",
                             "anonyme", "enseignant"})


def forum_display_name(raw):
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, "nom invalide"
    name = " ".join("".join(c if c >= " " else " " for c in raw).split())
    if not name:
        return None, None
    if len(name) > config.FORUM_PSEUDO_MAX:
        return None, f"nom trop long (maximum {config.FORUM_PSEUDO_MAX} caractères)"
    if name.casefold() in _RESERVED_NAMES:
        return None, "ce nom est réservé à l'interface, choisis-en un autre"
    return name, None


def forum_group(raw):
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, bool):
        return None, "numéro de groupe invalide"
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None, "numéro de groupe invalide"
    if config.FORUM_GROUPS:
        if number not in config.FORUM_GROUPS:
            return None, "groupe inconnu pour cette session"
    elif not 1 <= number <= 99:
        return None, "le numéro de groupe va de 1 à 99"
    return number, None


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

VISIBILITIES = ("private", "group", "thread")


def forum_step(raw):
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in STEPS:
        return None, "étape inconnue"
    return value, None


def forum_blocked_kind(raw):
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in BLOCKED_KINDS:
        return None, "type de blocage inconnu"
    return value, None


def forum_visibility(raw, with_step, thread=None):
    if is_chat(thread):
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


def can_see(message, sub, moderator, my_group, groups):
    if message["account"] == sub or moderator:
        return True
    visibility = message.get("visibility") or "thread"
    if visibility == "thread":
        return True
    if visibility != "group":
        return False
    their_group = groups.get(message["account"])
    return their_group is not None and my_group is not None and their_group == my_group


def forum_frame(raw, unlocked):
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in {c["id"] for c in unlocked}:
        return None, "ce cadre n'est pas débloqué"
    return value, None


def forum_identity(profile, sub, author, reader_is_moderator):
    """Display name, group and reportability. Never an account id, even for moderators."""
    profile = profile or {}
    display_name = profile.get("display_name")
    alias = profile.get("alias")
    chosen = bool(display_name) and bool(profile.get("display_name_public"))
    if author == sub:
        name = "Vous (%s)" % alias if alias else "Vous"
    elif is_moderator(author):
        name = "Enseignant"
    elif chosen:
        name = display_name
    else:
        name = alias or "Participant"
    group = profile.get("group_number")
    if group is not None and not (profile.get("group_number_public")
                                 or reader_is_moderator or author == sub):
        group = None
    return name, group, chosen and author != sub


def forum_view(messages, sub, moderator, profiles=None):
    profiles = profiles or {}
    groups = {account: (p or {}).get("group_number")
             for account, p in profiles.items()}
    my_group = (profiles.get(sub) or {}).get("group_number")
    seen = []
    for m in messages:
        if not (moderator or not m["hidden"]):
            continue
        if not can_see(m, sub, moderator, my_group, groups):
            continue
        name, group, reportable = forum_identity(
            profiles.get(m["account"]), sub, m["account"], moderator)
        seen.append({"id": m["id"], "text": m["text"], "created_at": m["created_at"],
                     "author": name, "group": group,
                     "reportable_name": reportable,
                     "mine": m["account"] == sub,
                     "hidden": m["hidden"],
                     "step": m.get("step"),
                     "blocked_kind": m.get("blocked_kind"),
                     "visibility": m.get("visibility") or "thread",
                     "retained": bool(m.get("retained")),
                     "reply_to": m.get("reply_to"),
                     "upvotes": int(m.get("upvotes") or 0),
                     "downvotes": int(m.get("downvotes") or 0),
                     "my_vote": int(m.get("my_vote") or 0)})
    return seen


def thread_state(views):
    if not views:
        return {"unanswered": 0, "answered": 0, "resolved": 0}
    if any(v["retained"] for v in views):
        return {"unanswered": 0, "answered": 0, "resolved": 1}
    if len(views) > 1 and len({v["author"] for v in views}) > 1:
        return {"unanswered": 0, "answered": 1, "resolved": 0}
    return {"unanswered": 1, "answered": 0, "resolved": 0}
