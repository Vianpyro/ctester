// THE DOCUMENT HALF OF A ROOM: one `Y.Text` per file of the exercise, named after
// the file. The names come from the catalog, which is the same allow-list
// `validate_files` checks server-side -- a shared document can hold nothing the
// exercise does not declare.
//
// SEPARATE FROM THE TRANSPORT ON PURPOSE. Nothing here knows there is a socket, so
// the diff below -- the one piece of this feature that is easy to get subtly wrong
// -- is tested by calling it with a `Y.Doc` and no network at all.

import * as Y from "yjs";

/** The transaction origin that means "I typed this". */
export const LOCAL = "local";
/** The origin that means "this arrived from the room". */
export const REMOTE = "remote";

export const textOf = (doc: Y.Doc, name: string): Y.Text => doc.getText("f:" + name);

/**
 * THE DIFF THAT TURNS A TEXTAREA INTO CRDT OPERATIONS. A keystroke, a paste and a
 * replaced selection are all ONE contiguous change, which is what the common prefix
 * and suffix find. Replacing the whole text instead -- delete everything, insert
 * everything -- would technically converge and would destroy every teammate's caret
 * on every keystroke.
 *
 * Returns false when there was nothing to do.
 */
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

/**
 * SEED FROM THE SERVER'S PLAIN TEXT. Only ever called for the first client into an
 * EMPTY room: two clients cannot both see an empty room, because join order is
 * decided in one process, under one event loop, before either `ready` is written.
 * The `length === 0` guard is the belt on top.
 */
export function seed(doc: Y.Doc, files: string[], server: Record<string, string>): void {
  doc.transact(() => {
    for (const name of files) {
      const ytext = textOf(doc, name);
      const text = server[name] ?? "";
      if (ytext.length === 0 && text) ytext.insert(0, text);
    }
  }, LOCAL);
}

/** The whole shared document as plain text -- what gets saved, tested and handed in. */
export function snapshot(doc: Y.Doc, files: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of files) out[name] = textOf(doc, name).toString();
  return out;
}
