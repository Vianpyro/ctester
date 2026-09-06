"""Request bodies, declared instead of validated by hand.

THESE MODELS VALIDATE ONLY SHAPE -- presence and type. Domain rules (a
message's length, allowed file names, a session's group, a known theme) stay
in `services/` and in `state.py`, for two reasons:

  * they produce messages written FOR THE STUDENT ("message trop long
    (maximum 1200 caractères)"), which Pydantic would replace with a generic
    400 -- and a student blocked without knowing why gives up;
  * they are exercised by direct call in `test_ctester.py`, with no server to
    stand up. Moving them here would make them reachable only through an HTTP
    request.

NO MODEL CARRIES AN IDENTITY FIELD, and none should ever be added: `account`,
`sub`, `owner`, `moderateur` come from the validated token and nowhere else.
One more field here would be a door into writing someone else's state.
"""

from pydantic import BaseModel, ConfigDict

# `extra="ignore"`: a newer client sending one extra field is not rejected.
# `forbid` would turn a page deployed ahead of the API into a total outage,
# on a day when only the page was redeployed.
_CONFIG = ConfigDict(extra="ignore")


class _AvecExercice(BaseModel):
    """The targeted exercise, under the name that already lives in every table.

    `exercise_id` is the only accepted spelling; `extra="ignore"` (above)
    means an old cached page targets the empty exercise, which
    `find_exercise` refuses with a 404.
    """

    model_config = _CONFIG

    exercise_id: str = ""


class SoumissionIn(_AvecExercice):
    """POST /submit -- a code submission, or a quiz.

    `key` IS THE SESSION KEY, compared in constant time and BEFORE any other
    work: nothing must be measurable from the outside without it.

    `files` and `answers` are left as raw `dict`: it is the catalog that says
    which file names exist for THIS exercise (`validate_files`), and a schema
    cannot know that ahead of time.
    """

    model_config = _CONFIG

    key: str = ""
    files: dict | None = None
    answers: dict | None = None


class BrouillonIn(_AvecExercice):
    """PUT /brouillon -- the code in progress."""

    model_config = _CONFIG

    files: dict | None = None


class PreferencesIn(BaseModel):
    """PUT /preferences -- the theme, which follows the ACCOUNT and not the device."""

    model_config = _CONFIG

    theme: str = ""


class ForumMessageIn(_AvecExercice):
    """POST /forum -- post into a published exercise's thread."""

    model_config = _CONFIG

    text: str | None = None


class ForumSignalementIn(BaseModel):
    """POST /forum/signalement -- report a message, or a displayed name.

    TWO TARGETS, ONE ROUTE. Reporting a name is the same gesture and the same
    queue: the message serves as the handle because the browser has no
    account id, and never will.
    """

    model_config = _CONFIG

    id: str = ""
    kind: str = "message"


class ForumModerationIn(BaseModel):
    """POST /forum/moderation -- hide, restore, or clear a name.

    Editing a message is not among these: a message is immutable, and a
    moderator who could correct it could also make someone say something
    else.
    """

    model_config = _CONFIG

    id: str = ""
    action: str = ""


class ForumProfilIn(BaseModel):
    """POST /forum/profil -- a name, a group, and what is displayed.

    TWO INDEPENDENT CHECKBOXES, and nothing appears unless its owner checked
    it. `group_number` accepts an integer or a string: the form sends one or
    the other depending on whether it is a dropdown or a free-text field, and
    `forum_groupe()` settles it.
    """

    model_config = _CONFIG

    display_name: str | None = None
    group_number: int | str | None = None
    display_name_public: bool = False
    group_number_public: bool = False
