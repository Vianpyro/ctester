import { authRequest } from "../auth/session.svelte";
import type { GitHubView } from "./types";

export const linkGitHub = (code: string) =>
  authRequest<{ ok: boolean; login?: string }>("github/link", {
    method: "POST",
    json: { code },
  });

export const unlinkGitHub = () =>
  authRequest<{ ok: boolean }>("github/link", { method: "DELETE" });

export const sendToGitHub = (assignmentId: string, message: string) =>
  authRequest<{ ok: boolean; sha?: string; github?: GitHubView | null }>("github/commit", {
    method: "POST",
    json: { assignment_id: assignmentId, message },
  });
