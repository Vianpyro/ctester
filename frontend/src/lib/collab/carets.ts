// CARET GEOMETRY, AND IT IS ARITHMETIC RATHER THAN A SECOND COPY OF THE DOCUMENT.
//
// The overlay is already there: the highlight layer and the textarea share their
// metrics to the pixel (see the note in `app.css`), so a caret is a character
// width measured once plus a row and a column. Four remote carets over a 64 KB
// file would otherwise cost a second DOM tree on every keystroke.
//
// ponytail: this holds because the editor is monospaced. The day it accepts a
// proportional font, this is the function to rewrite.
//
// EVERYTHING HERE IS PURE, so the transform a remote edit applies to a caret is
// tested by calling it -- which matters, because getting it wrong is what makes a
// shared editor unusable.

export interface Metrics {
  char: number;
  line: number;
  top: number;
  left: number;
}

export interface RowColumn {
  row: number;
  column: number;
}

/** A Yjs delta, as `Y.Text.observe` reports it. */
export type Delta = { retain?: number; insert?: unknown; delete?: number }[];

/**
 * WHERE THE CARET LANDS AFTER SOMEBODY ELSE'S CHANGE. The delta says what happened
 * before it; this is the standard transform, and it is the whole reason a remote
 * edit does not throw the typist to the end of the file.
 */
export function shift(delta: Delta, position: number): number {
  let index = 0;
  let moved = position;
  for (const op of delta) {
    if (op.retain) {
      index += op.retain;
    } else if (typeof op.insert === "string") {
      if (index < moved) moved += op.insert.length;
      index += op.insert.length;
    } else if (op.delete) {
      if (index < moved) moved -= Math.min(op.delete, moved - index);
    }
    if (index > moved) break;
  }
  return Math.max(0, moved);
}

export function rowColumn(text: string, offset: number): RowColumn {
  const before = text.slice(0, Math.max(0, offset));
  const rows = before.split("\n");
  return { row: rows.length - 1, column: rows[rows.length - 1]!.length };
}

/**
 * WHERE A (COLUMN, ROW) LANDS IN THE OVERLAY. One function, so a caret and the
 * selection band under it can never disagree about the same position.
 *
 * `setAttribute("style", …)`-shaped output, like every computed style on this page:
 * one way of writing it, and the one the CSP's `style-src 'unsafe-inline'` already
 * covers.
 */
export function place(
  box: Metrics,
  scroll: { left: number; top: number },
  column: number,
  row: number,
): string {
  return (
    "left:" + (box.left + column * box.char - scroll.left) + "px;" +
    "top:" + (box.top + row * box.line - scroll.top) + "px;"
  );
}

/**
 * Measure the editor's metrics once. `getBoundingClientRect` returns zeros in a
 * headless DOM, which is exactly where this must not throw -- and a zero width is
 * what tells the caller to draw NO caret at all: one drawn at the wrong place is
 * worse than none, because it points at a line its owner is not on.
 */
export function measure(zone: HTMLTextAreaElement): Metrics {
  const style = typeof window.getComputedStyle === "function" ? window.getComputedStyle(zone) : null;
  const probe = document.createElement("span");
  probe.textContent = "0".repeat(50);
  probe.setAttribute(
    "style",
    "position:absolute;visibility:hidden;white-space:pre" + (style ? ";font:" + style.font : ""),
  );
  (zone.parentNode ?? document.body).appendChild(probe);
  const box = probe.getBoundingClientRect ? probe.getBoundingClientRect() : null;
  probe.remove();
  return {
    char: box && box.width ? box.width / 50 : 0,
    line: style ? parseFloat(style.lineHeight) || 0 : 0,
    top: style ? parseFloat(style.paddingTop) || 0 : 0,
    left: style ? parseFloat(style.paddingLeft) || 0 : 0,
  };
}

/**
 * The selection bands for one caret: one rectangle per line, and only when there
 * IS a selection. Drawn as rectangles rather than text ranges because the overlay
 * is `white-space: pre`, so a line's width in characters is all it takes.
 */
export function selectionBands(
  text: string,
  anchor: number,
  head: number,
  box: Metrics,
  scroll: { left: number; top: number },
): string[] {
  if (anchor === head) return [];
  const from = rowColumn(text, Math.min(anchor, head));
  const to = rowColumn(text, Math.max(anchor, head));
  const lines = text.split("\n");
  const bands: string[] = [];
  for (let row = from.row; row <= to.row && row < lines.length; row++) {
    const startColumn = row === from.row ? from.column : 0;
    const endColumn = row === to.row ? to.column : lines[row]!.length;
    if (endColumn <= startColumn) continue;
    bands.push(
      place(box, scroll, startColumn, row) +
        "width:" + (endColumn - startColumn) * box.char + "px;" +
        "height:" + box.line + "px;",
    );
  }
  return bands;
}

// --- Bytes on the wire ---------------------------------------------------------
// Yjs speaks Uint8Array, the socket carries JSON. base64 rather than a binary
// frame, for one reason: the frames the server relays also carry a `from` it
// stamps itself, and a JSON envelope is what lets it do that without parsing -- or
// even understanding -- the payload inside.

export const toBase64 = (bytes: Uint8Array): string => {
  let out = "";
  for (const byte of bytes) out += String.fromCharCode(byte);
  return btoa(out);
};

export const fromBase64 = (text: string): Uint8Array => {
  const raw = atob(text);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
};
