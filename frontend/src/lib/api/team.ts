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

export const restoreRevision = (assignmentId: string, exerciseId: string, revisionId: string) =>
  authRequest<{ ok: boolean; sources?: Record<string, string> }>("team/restore", {
    method: "POST",
    json: { assignment_id: assignmentId, exercise_id: exerciseId, revision_id: revisionId },
  });

export const fetchArchive = (assignmentId: string) =>
  authFetch("team/handin.zip?assignment=" + encodeURIComponent(assignmentId));

export const handIn = (assignmentId: string) =>
  authRequest<{ ok: boolean; submission?: { submitted_at?: string } }>("team/handin", {
    method: "POST",
    json: { assignment_id: assignmentId },
  });
