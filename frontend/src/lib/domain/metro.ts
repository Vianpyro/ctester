// Lays the achievements out as a metro map: one line per fact, a station per achievement,
// one cell apart. The content only names the lines; where they run is computed here, from a
// seed taken from the content itself, so a student sees the same map on every visit.

export const PALETTE = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"];

export interface MetroLine {
  on: string;
  name: string;
  color?: string | null;
}

export interface MetroStation {
  id: string;
  on: string;
  unlocked_at: string | null;
}

export type Cell = [number, number];

export interface MetroNode {
  id: string;
  line: string;
  at: Cell;
  kind: "start" | "station" | "flag";
  state: "earned" | "next" | "locked";
  color: string;
}

export interface MetroMap {
  nodes: MetroNode[];
  /** Between adjacent cells only, so two lines can never cross. */
  segments: { line: string; from: Cell; to: Cell; lit: boolean; color: string }[];
  /** Dotted, from a line's start to the nearest node of an earlier line. */
  links: { from: Cell; to: Cell }[];
  columns: number;
  rows: number;
}

function seeded(seed: number): () => number {
  // mulberry32: small, fast and the same in every browser.
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

const RIGHT: Cell = [1, 0];
const LEFT: Cell = [-1, 0];
const DOWN: Cell = [0, 1];

// Never up: the map reads from top to bottom, like the course.
function directions(random: () => number, previous: Cell | null): Cell[] {
  const pool: { d: Cell; w: number }[] = [RIGHT, LEFT, DOWN].map((d) => ({
    d,
    w: (d === DOWN ? 1.6 : 1) * (d === previous ? 1.8 : 1),
  }));
  const order: Cell[] = [];
  while (pool.length) {
    let pick = random() * pool.reduce((n, p) => n + p.w, 0);
    let i = 0;
    while (i < pool.length - 1 && (pick -= pool[i]!.w) > 0) i++;
    order.push(pool.splice(i, 1)[0]!.d);
  }
  return order;
}

export function layout(lines: MetroLine[], stations: MetroStation[], columns: number): MetroMap {
  const drawn = lines
    .map((line) => ({ line, stops: stations.filter((s) => s.on === line.on) }))
    .filter((l) => l.stops.length);
  const random = seeded(hash(drawn.map((l) => l.line.on + ":" + l.stops.map((s) => s.id)).join("|")));
  // Which line holds each cell. A cell touching another line is refused too, so every line
  // keeps a gutter around it and reads on its own, as on CodinGame.
  const taken = new Map<string, string>();
  const key = ([c, r]: Cell) => c + "," + r;
  let current = "";
  const free = ([c, r]: Cell) =>
    c >= 0 &&
    c < columns &&
    r >= 0 &&
    !taken.has(key([c, r])) &&
    [[c + 1, r], [c - 1, r], [c, r + 1], [c, r - 1]].every(
      (n) => (taken.get(key(n as Cell)) ?? current) === current,
    );

  const map: MetroMap = { nodes: [], segments: [], links: [], columns, rows: 0 };

  drawn.forEach(({ line, stops }, index) => {
    const color = line.color && PALETTE.includes(line.color) ? line.color : PALETTE[index % PALETTE.length]!;
    let path: Cell[] = [];
    current = line.on;

    // Depth-first, at most three ways per step: a line of seven stations costs a few
    // thousand steps in the worst case, and a start below everything always succeeds.
    const walk = (previous: Cell | null): boolean => {
      if (path.length === stops.length + 1) return true;
      const here = path[path.length - 1]!;
      // The first step leaves sideways, so the line's name has the cell below its start.
      const ways = directions(random, previous).filter((d) => path.length > 1 || d !== DOWN);
      for (const d of ways) {
        const next: Cell = [here[0] + d[0], here[1] + d[1]];
        if (!free(next) || path.some((p) => key(p) === key(next))) continue;
        path.push(next);
        if (walk(d)) return true;
        path.pop();
      }
      return false;
    };

    // A start two rows below everything always succeeds: the row between is the gutter.
    const lowest = Math.max(-1, ...[...taken.keys()].map((k) => Number(k.split(",")[1])));
    search: for (let r = 0; r <= lowest + 3; r++) {
      for (let c = 0; c < columns; c++) {
        const start: Cell = [c, r];
        if (!free(start) || !free([c, r + 1])) continue;
        // The cell below the start holds the line's name: the walk must not come back to it.
        taken.set(key([c, r + 1]), line.on);
        path = [start];
        if (walk(null)) break search;
        taken.delete(key([c, r + 1]));
      }
    }

    for (const cell of path) taken.set(key(cell), line.on);

    const firstMissing = stops.findIndex((s) => !s.unlocked_at);
    const earlier = map.nodes.slice();
    map.nodes.push({ id: "line:" + line.on, line: line.on, at: path[0]!, kind: "start", state: "earned", color });
    stops.forEach((stop, i) => {
      const state = stop.unlocked_at ? "earned" : i === firstMissing ? "next" : "locked";
      map.nodes.push({
        id: stop.id,
        line: line.on,
        at: path[i + 1]!,
        kind: i === stops.length - 1 ? "flag" : "station",
        state,
        color,
      });
      map.segments.push({ line: line.on, from: path[i]!, to: path[i + 1]!, lit: !!stop.unlocked_at, color });
    });

    if (earlier.length) {
      const [c, r] = path[0]!;
      const near = earlier.reduce((best, n) =>
        Math.abs(n.at[0] - c) + Math.abs(n.at[1] - r) < Math.abs(best.at[0] - c) + Math.abs(best.at[1] - r)
          ? n
          : best,
      );
      map.links.push({ from: near.at, to: path[0]! });
    }
  });

  map.rows = Math.max(0, ...[...taken.keys()].map((k) => Number(k.split(",")[1]) + 1));
  return map;
}
