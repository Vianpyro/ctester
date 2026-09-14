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
