import { authGet, authRequest } from "../auth/session.svelte";
import type { ScratchDraft } from "./types";

export const fetchScratchDraft = () => authGet<ScratchDraft>("scratch/draft");

export const saveScratchDraft = (draft: { code: string; header_name: string; header: string }) =>
  authRequest<{ ok: boolean }>("scratch/draft", { method: "PUT", json: draft });
