import * as Y from "yjs";

export const LOCAL = "local";
export const REMOTE = "remote";

export const textOf = (doc: Y.Doc, name: string): Y.Text => doc.getText("f:" + name);

export function applyLocal(doc: Y.Doc, ytext: Y.Text, next: string): boolean {
  const previous = ytext.toString();
  if (previous === next) return false;
  const shortest = Math.min(previous.length, next.length);
  let start = 0;
  while (start < shortest && previous[start] === next[start]) start++;
  let tail = 0;
  while (
    tail < shortest - start &&
    previous[previous.length - 1 - tail] === next[next.length - 1 - tail]
  ) {
    tail++;
  }
  const removed = previous.length - start - tail;
  const inserted = next.slice(start, next.length - tail);
  doc.transact(() => {
    if (removed) ytext.delete(start, removed);
    if (inserted) ytext.insert(start, inserted);
  }, LOCAL);
  return true;
}

export function seed(doc: Y.Doc, files: string[], server: Record<string, string>): void {
  doc.transact(() => {
    for (const name of files) {
      const ytext = textOf(doc, name);
      const text = server[name] ?? "";
      if (ytext.length === 0 && text) ytext.insert(0, text);
    }
  }, LOCAL);
}

export function snapshot(doc: Y.Doc, files: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of files) out[name] = textOf(doc, name).toString();
  return out;
}
