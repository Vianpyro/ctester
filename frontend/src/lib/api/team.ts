// TEAM ASSIGNMENTS. The authorization chain is walked SERVER-SIDE on every
// request and every socket open:
//
//   validated token -> sub -> team_member -> team -> assignment (OPEN) -> exercise
//
// NO ROUTE AND NO FRAME READS A TEAM IDENTIFIER. There is no team to change in a
// URL, a JSON body or a WebSocket message -- that is "no model carries an identity
// field" extended one notch, and `test_api.py` proves it by having a member of
// another team write `{"team_id": "e1"}`: the write lands in their own.
//
// FOUR ROUTES ANSWER BEFORE THE ASSIGNMENT OPENS -- mine, available, join, leave.
// Teams are chosen in September and the assignment opens in October; a screen that
// only existed once the assignment was open would make people choose teams on the
// morning of the hand-in. And none of them opens anything: they return numbers,
// occupancy and teammates as POSITIONS -- no document, no revision, no room, no
// hand-in.

import { authFetch, authGet, authRequest } from "../auth/session.svelte";
import type {
  AvailableTeams,
  MyTeam,
  TeamContext,
  TeamDocument,
  TeamRevision,
} from "./types";

export const fetchContext = (assignmentId: string) =>
  authRequest<TeamContext>("team/context?assignment=" + encodeURIComponent(assignmentId));

export const fetchMyTeams = () => authGet<{ teams: MyTeam[] }>("team/mine");

/** `/team/available` NAMES NOBODY: "3/4" is enough to choose, and publishing the
 * compositions would turn that choice into a social sort on a web page. */
export const fetchAvailable = (assignmentId: string) =>
  authRequest<AvailableTeams>("team/available?assignment=" + encodeURIComponent(assignmentId));

export const joinTeam = (assignmentId: string, number: number) =>
  authRequest<AvailableTeams>("team/join", {
    method: "POST",
    json: { assignment_id: assignmentId, number },
  });

export const leaveTeam = (assignmentId: string) =>
  authRequest<AvailableTeams>("team/leave", {
    method: "POST",
    json: { assignment_id: assignmentId },
  });

/**
 * The team's shared sources for one exercise -- the CRDT's seed. An EMPTY
 * workspace is not a failure and the two are told apart server-side: `{}` is a
 * team that has not started, 503 is a database that did not answer. Confusing them
 * would have the first member into a room seed the document from nothing and
 * quietly overwrite an afternoon.
 */
export const fetchDocument = (assignmentId: string, exerciseId: string) =>
  authGet<TeamDocument>(
    "team/document?assignment=" +
      encodeURIComponent(assignmentId) +
      "&ex=" +
      encodeURIComponent(exerciseId),
  );

export const saveDocument = (
  assignmentId: string,
  exerciseId: string,
  files: Record<string, string>,
) =>
  authRequest<{ ok: boolean }>("team/document", {
    method: "PUT",
    json: { assignment_id: assignmentId, exercise_id: exerciseId, files },
  });

export const fetchRevisions = (assignmentId: string, exerciseId: string) =>
  authGet<{ revisions: TeamRevision[] }>(
    "team/revisions?assignment=" +
      encodeURIComponent(assignmentId) +
      "&ex=" +
      encodeURIComponent(exerciseId),
  );

/**
 * RESTORING MOVES FORWARD, IT DOES NOT REWIND: the restored version is written as
 * the current document, under the account that restored it, and nothing
 * disappears. The server pushes NOTHING into the CRDT -- the page reapplies the
 * text through the ordinary edit path, which is what keeps the relay dumb.
 */
export const restoreRevision = (assignmentId: string, exerciseId: string, revisionId: string) =>
  authRequest<{ ok: boolean; sources?: Record<string, string> }>("team/restore", {
    method: "POST",
    json: { assignment_id: assignmentId, exercise_id: exerciseId, revision_id: revisionId },
  });

/** The ZIP. Raw, so `authFetch` -- an archive is asked for at hand-in time, which
 * is exactly when a tab has been open all evening and the token has quietly died. */
export const fetchArchive = (assignmentId: string) =>
  authFetch("team/handin.zip?assignment=" + encodeURIComponent(assignmentId));

export const handIn = (assignmentId: string) =>
  authRequest<{ ok: boolean; submission?: { submitted_at?: string } }>("team/handin", {
    method: "POST",
    json: { assignment_id: assignmentId },
  });
