// Keys that used to be French. Each old value moves once, when this module loads and
// before anything reads a key, so nobody loses a login, the lab key or a setting.
const RENAMED_LOCAL: [string, string][] = [
  ["ctester.chat.ouvert", "ctester.chat.open"],
  ["ctester.chat.vu", "ctester.chat.seen"],
  ["ctester.expire", "ctester.expiry"],
  ["ctester.exercice", "ctester.exercise"],
  ["ctester.charte", "ctester.charter"],
  ["ctester.poste", "ctester.station"],
];
const RENAMED_SESSION: [string, string][] = [
  ["ctester.cle", "ctester.key"],
  ["ctester.retour", "ctester.return"],
];

export function moveRenamedKeys(store: Storage, renamed: [string, string][]): void {
  for (const [old, name] of renamed) {
    const value = store.getItem(old);
    if (value === null) continue;
    if (store.getItem(name) === null) store.setItem(name, value);
    store.removeItem(old);
  }
}

try {
  moveRenamedKeys(localStorage, RENAMED_LOCAL);
  moveRenamedKeys(sessionStorage, RENAMED_SESSION);
} catch {
}

export function sessionGet(name: string): string {
  try {
    return sessionStorage.getItem(name) || "";
  } catch {
    return "";
  }
}

export function sessionSet(name: string, value: string): void {
  try {
    sessionStorage.setItem(name, value);
  } catch {
  }
}

export function sessionDrop(name: string): void {
  try {
    sessionStorage.removeItem(name);
  } catch {
  }
}

export function localGet(name: string): string {
  try {
    return localStorage.getItem(name) || "";
  } catch {
    return "";
  }
}

export function localSet(name: string, value: string): boolean {
  try {
    localStorage.setItem(name, value);
    return true;
  } catch {
    return false;
  }
}

export function localDrop(name: string): void {
  try {
    localStorage.removeItem(name);
  } catch {
  }
}

export function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return String(Math.random()).slice(2) + Date.now();
}
