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

// Passed as a thunk, not as a Storage: reading `localStorage` itself throws when a browser
// blocks site data, so the access has to happen inside the guard.
const read = (store: () => Storage, name: string): string => {
  try {
    return store().getItem(name) || "";
  } catch {
    return "";
  }
};

const write = (store: () => Storage, name: string, value: string): boolean => {
  try {
    store().setItem(name, value);
    return true;
  } catch {
    return false;
  }
};

const drop = (store: () => Storage, name: string): void => {
  try {
    store().removeItem(name);
  } catch {
  }
};

const session = () => sessionStorage;
const local = () => localStorage;

export const sessionGet = (name: string): string => read(session, name);

export const sessionSet = (name: string, value: string): void => {
  write(session, name, value);
};

export const sessionDrop = (name: string): void => drop(session, name);

export const localGet = (name: string): string => read(local, name);

export const localSet = (name: string, value: string): boolean =>
  write(local, name, value);

export const localDrop = (name: string): void => drop(local, name);

export function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return String(Math.random()).slice(2) + Date.now();
}
