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

export type Delta = { retain?: number; insert?: unknown; delete?: number }[];

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

// Carets are placed from one measured character width, which assumes a monospace font.
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
