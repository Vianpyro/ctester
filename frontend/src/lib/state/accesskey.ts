import { sessionGet, sessionSet } from "../storage";

const KEY_STORAGE = "ctester.key";

let cached: string | null = null;

export function captureAccessKey(search: string): string {
  const fromLink = new URLSearchParams(search).get("k") || "";
  if (fromLink) sessionSet(KEY_STORAGE, fromLink);
  cached = fromLink || sessionGet(KEY_STORAGE);
  return cached;
}

export function sessionKey(): string {
  if (cached === null) cached = sessionGet(KEY_STORAGE);
  return cached;
}
