import config
from security import is_moderator, moderators, oidc_enabled

# `@` never appears in a catalog id, so a chat key can't resolve to an exercise.
CHAT_PREFIX = "@chat:"
CHAT_GENERAL = CHAT_PREFIX + "general"


def is_chat(thread):
    return str(thread or "").startswith(CHAT_PREFIX)


def chat_key(exercise):
    return CHAT_PREFIX + str(exercise)


def forum_enabled():
    return oidc_enabled() and bool(moderators())


def forum_text(raw):
    if not isinstance(raw, str):
        return None, "message_missing"
    text = raw.replace("\r\n", "\n")
    text = "".join(c for c in text if c in "\n\t" or c >= " ").strip()
    if not text:
        return None, "message_empty"
    if len(text) > config.FORUM_MAX_CHARS:
        return None, ("message_too_long", {"max": config.FORUM_MAX_CHARS})
    return text, None


_RESERVED_NAMES = frozenset({"vous", "participant", "equipe du cours",
                             "équipe du cours", "moderateur", "modérateur",
                             "anonyme", "enseignant"})


def forum_display_name(raw):
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, "invalid_name"
    name = " ".join("".join(c if c >= " " else " " for c in raw).split())
    if not name:
        return None, None
    if len(name) > config.FORUM_PSEUDO_MAX:
        return None, ("name_too_long", {"max": config.FORUM_PSEUDO_MAX})
    if name.casefold() in _RESERVED_NAMES:
        return None, "reserved_name"
    return name, None


def forum_group(raw):
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, bool):
        return None, "invalid_group"
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None, "invalid_group"
    if config.FORUM_GROUPS:
        if number not in config.FORUM_GROUPS:
            return None, "unknown_group"
    elif not 1 <= number <= 99:
        return None, "group_range"
    return number, None


# The page words them (forum.step.<id>, forum.blocked.<id>); stored ids never change.
STEPS = ("statement", "compilation", "execution", "result")

BLOCKED_KINDS = ("statement-unclear", "wrong-result", "unclear-error")

VISIBILITIES = ("private", "group", "thread")


def forum_step(raw):
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in STEPS:
        return None, "unknown_step"
    return value, None


def forum_blocked_kind(raw):
    if raw is None or raw == "":
        return None, None
    value = str(raw)
    if value not in BLOCKED_KINDS:
        return None, "unknown_blocked_kind"
    return value, None


def forum_visibility(raw, with_step, thread=None):
    if is_chat(thread):
        if raw not in (None, "", "thread"):
            return None, "chat_is_public"
        return "thread", None
    if raw is None or raw == "":
        return ("private" if with_step else "thread"), None
    value = str(raw)
    if value not in VISIBILITIES:
        return None, "unknown_visibility"
    if with_step and value == "thread":
        return None, "help_private_or_group"
    if not with_step and value != "thread":
        return None, "question_is_public"
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
        return None, "frame_locked"
    return value, None


def forum_identity(profile, sub, author, reader_is_moderator):
    """Display name, group, reportability and role. Never an account id, even for moderators.

    The role ("me", "teacher" or "") is worded by the page; the name is only ever one the
    student chose or was drawn, and empty when there is none.
    """
    profile = profile or {}
    display_name = profile.get("display_name")
    alias = profile.get("alias")
    chosen = bool(display_name) and bool(profile.get("display_name_public"))
    role = ""
    if author == sub:
        name, role = alias or "", "me"
    elif is_moderator(author):
        name, role = "", "teacher"
    elif chosen:
        name = display_name
    else:
        name = alias or ""
    group = profile.get("group_number")
    if group is not None and not (profile.get("group_number_public")
                                 or reader_is_moderator or author == sub):
        group = None
    return name, group, chosen and author != sub, role


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
        name, group, reportable, role = forum_identity(
            profiles.get(m["account"]), sub, m["account"], moderator)
        seen.append({"id": m["id"], "text": m["text"], "created_at": m["created_at"],
                     "author": name, "role": role, "group": group,
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
    if len(views) > 1 and len({(v["role"], v["author"]) for v in views}) > 1:
        return {"unanswered": 0, "answered": 1, "resolved": 0}
    return {"unanswered": 1, "answered": 0, "resolved": 0}
