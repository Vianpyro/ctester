// THE CONSOLE'S NOTEPAD, kept ON THE ACCOUNT so it follows from the lab to a
// laptop. The session itself is a WebSocket and lives in
// `state/scratch.svelte.ts` -- there is no "stop" frame: closing the socket IS the
// stop, the server releases its lock and the worker destroys the container. One
// code path, and it works when the tab dies without warning.

import { authGet, authRequest } from "../auth/session.svelte";
import type { ScratchDraft } from "./types";

export const fetchScratchDraft = () => authGet<ScratchDraft>("scratch/draft");

export const saveScratchDraft = (code: string) =>
  authRequest<{ ok: boolean }>("scratch/draft", { method: "PUT", json: { code } });
