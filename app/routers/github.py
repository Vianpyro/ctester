import headers
import state
from deps import Sub, throttle_write
from fastapi import APIRouter, Request
from schemas import GitHubCommitIn, GitHubLinkIn
from services import github
from services import teams as team_service

router = APIRouter(tags=["github"])


def _off():
    return None if github.enabled() else headers.error(503, "github_disabled")


@router.post("/github/link")
def link(sub: Sub, body: GitHubLinkIn, request: Request):
    refused = _off()
    if refused is not None:
        return refused
    if not 0 < len(body.code) <= 256:
        return headers.error(400, "github_link_failed")
    throttle_write(request)
    try:
        who = github.exchange(body.code)
    except github.Unavailable:
        return headers.error(502, "github_unavailable")
    if who is None:
        return headers.error(400, "github_link_failed")
    if not state.write_github_link(sub, who["github_id"], who["login"]):
        return headers.error(503, "db_down")
    return {"ok": True, "login": who["login"]}


@router.delete("/github/link")
def unlink(sub: Sub, request: Request):
    refused = _off()
    if refused is not None:
        return refused
    throttle_write(request)
    if not state.drop_github_link(sub):
        return headers.error(503, "db_down")
    return {"ok": True}


@router.post("/github/commit")
def commit(sub: Sub, body: GitHubCommitIn, request: Request):
    refused = _off()
    if refused is not None:
        return refused
    assignment, team, refusal = team_service.workspace(state, sub, body.assignment_id)
    if refusal:
        return headers.error(*refusal)
    link_row = state.github_link_of(sub)
    if link_row is None:
        return headers.error(503, "db_down")
    if not link_row:
        return headers.error(409, "github_not_linked")
    throttle_write(request)
    try:
        sha = github.sync(assignment, team["team_id"], note=body.message, sender=sub)
    except github.Unavailable:
        return headers.error(502, "github_unavailable")
    return {"ok": True, "sha": sha,
            "github": github.view(assignment, team["team_id"], sub)}
