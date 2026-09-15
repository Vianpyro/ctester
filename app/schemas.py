"""Request bodies, validated for shape only.

Domain rules live in services/ so refusals can explain themselves to students.
No model carries an account field: the subject always comes from the token.
"""
from pydantic import BaseModel, ConfigDict

_CONFIG = ConfigDict(extra="ignore")


class _WithExercise(BaseModel):
    model_config = _CONFIG

    exercise_id: str = ""


class SubmissionIn(_WithExercise):
    key: str = ""
    files: dict | None = None
    answers: dict | None = None


class DraftIn(_WithExercise):
    files: dict | None = None


class ScratchIn(BaseModel):
    model_config = _CONFIG

    code: str = ""
    header_name: str = ""
    header: str = ""


class PreferencesIn(BaseModel):
    model_config = _CONFIG

    theme: str = ""


class ForumMessageIn(_WithExercise):
    text: str | None = None
    step: str | None = None
    blocked_kind: str | None = None
    visibility: str | None = None
    reply_to: str | None = None


class ForumTargetIn(BaseModel):
    model_config = _CONFIG

    id: str = ""


class ForumVoteIn(BaseModel):
    model_config = _CONFIG

    id: str = ""
    value: int = 1


class ForumReportIn(BaseModel):
    model_config = _CONFIG

    id: str = ""
    kind: str = "message"


class ForumModerationIn(BaseModel):
    model_config = _CONFIG

    id: str = ""
    action: str = ""


class ForumProfileIn(BaseModel):
    model_config = _CONFIG

    display_name: str | None = None
    group_number: int | str | None = None
    display_name_public: bool = False
    group_number_public: bool = False
    plate_frame: str | None = None
    badges_public: bool = False
    leaderboard_opt_in: bool = False


class DiscordBridgeIn(_WithExercise):
    discord_id: str = ""
    display_name: str | None = None
    text: str | None = None


class TeamDocumentIn(_WithExercise):
    assignment_id: str = ""
    files: dict | None = None


class TeamRestoreIn(_WithExercise):
    assignment_id: str = ""
    revision_id: str = ""


class TeamHandinIn(BaseModel):
    model_config = _CONFIG

    assignment_id: str = ""


class TeamJoinIn(BaseModel):
    model_config = _CONFIG

    assignment_id: str = ""
    number: int = 0


class TeamLeaveIn(BaseModel):
    model_config = _CONFIG

    assignment_id: str = ""
