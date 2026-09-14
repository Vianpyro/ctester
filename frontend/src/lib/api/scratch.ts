import { authGet, authRequest } from "../auth/session.svelte";
import type { ScratchDraft } from "./types";

export const fetchScratchDraft = () => authGet<ScratchDraft>("scratch/draft");

export const saveScratchDraft = (code: string) =>
  authRequest<{ ok: boolean }>("scratch/draft", { method: "PUT", json: { code } });
