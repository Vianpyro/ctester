import type {
  Access,
  ExerciseMode,
  ExerciseStatus,
  PublishedAssignment,
  PublishedExercise,
  PublishedRelease,
} from "../api/types";

export interface Exercise {
  id: string;
  mode: ExerciseMode;
  short: string;
  group: string;
  label: string;
  verification: boolean;
  bonus: boolean;
  assignment: string;
  files: { name: string }[];
  learning: { skills?: string[]; context?: string; difficulty?: string };
  access: Access;
  available_from: string;
}

export interface Collection {
  title: string;
  access: Access;
  available_from: string;
  items: Exercise[];
}

export interface CatalogModel {
  collections: Collection[];
  catalog: Exercise[];
  assignments: PublishedAssignment[];
}

export const EMPTY_CATALOG: CatalogModel = { collections: [], catalog: [], assignments: [] };

function catalogEntry(ex: PublishedExercise, group: string): Exercise {
  const learning: Exercise["learning"] = {};
  if (Array.isArray(ex.skills) && ex.skills.length) learning.skills = ex.skills;
  if (Array.isArray(ex.contexts) && ex.contexts.length) learning.context = ex.contexts[0];
  if (ex.difficulty) learning.difficulty = ex.difficulty;
  const title = ex.title ?? ex.id;
  return {
    id: ex.id,
    mode: ex.mode,
    short: title,
    group,
    label: group ? group.replace(/\s+/g, "") + " : " + title : title,
    verification: !!ex.verification,
    bonus: !!ex.bonus,
    assignment: ex.assignment ?? "",
    files: (ex.files ?? []).map((f) => ({ name: f.name })),
    learning,
    access: ex.access ?? "available",
    available_from: ex.release?.available_from ?? "",
  };
}

export function normalize(release: PublishedRelease, staff = false): CatalogModel {
  const assignments = (release.assignments ?? []).filter(
    (a): a is PublishedAssignment => !!a && typeof a.id === "string",
  );
  const byId = new Map<string, PublishedExercise>();
  for (const ex of release.exercises ?? []) {
    if (ex && typeof ex.id === "string") byId.set(ex.id, ex);
  }
  const collections: Collection[] = [];
  const classified = new Set<string>();
  for (const col of release.collections ?? []) {
    const items = (col.items ?? []).filter((id) => byId.has(id));
    if (!items.length) continue;
    const title = String(col.title ?? col.id ?? "");
    for (const id of items) classified.add(id);
    collections.push({
      title,
      access: col.access ?? "available",
      available_from: col.release?.available_from ?? "",
      items: items.map((id) => catalogEntry(byId.get(id)!, title)),
    });
  }
  const orphans = [...byId.keys()].filter((id) => !classified.has(id));
  if (orphans.length) {
    collections.push({
      title: "Autres",
      access: "available",
      available_from: "",
      items: orphans.map((id) => catalogEntry(byId.get(id)!, "Autres")),
    });
  }
  const seen = new Set<string>();
  const catalog: Exercise[] = [];
  for (const col of collections) {
    for (const ex of col.items) {
      if ((!staff && ex.access !== "available") || seen.has(ex.id)) continue;
      seen.add(ex.id);
      catalog.push(ex);
    }
  }
  return { collections, catalog, assignments };
}

export function lockNote(entry: { access?: Access; available_from?: string } | null): string {
  if (!entry || entry.access === "available") return "";
  if (entry.access === "archived") return "archivé";
  const when = new Date(entry.available_from ?? "");
  return isNaN(when.getTime())
    ? "à venir"
    :
      "ouvre le " + when.toLocaleDateString("fr-CA", { day: "numeric", month: "long" });
}

export function tileState(
  ex: Exercise,
  locked: boolean,
  statuses: Record<string, ExerciseStatus | undefined>,
): { cls: string; word: string } {
  if (locked) return { cls: "todo", word: "pas encore ouvert" };
  const status = statuses[ex.id] ?? "";
  if (status === "solved") return { cls: "solved", word: "réussi" };
  if (ex.verification) return { cls: "verification", word: "vérification" };
  if (status === "attempted") return { cls: "todo", word: "essayé" };
  return { cls: "todo", word: "à faire" };
}

// The collection prefix ("TP 3: ") is noise once the exercise is shown inside its collection.
const bareLabel = (ex: Exercise): string => ex.short.replace(/^[^:]*:\s*/, "");

export function stripLabel(ex: Exercise): string {
  const bare = bareLabel(ex);
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return "ex." + number[1];
  return bare.length > 20 ? bare.slice(0, 19) + "…" : bare;
}

export function gridLabel(ex: Exercise): string {
  if (ex.verification) return "vérif";
  const bare = bareLabel(ex);
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return number[1]!;
  return bare.length > 8 ? bare.slice(0, 7) + "…" : bare;
}

export const fold = (text: string): string =>
  String(text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

export const matchesFilter = (ex: Exercise, group: string, filter: string): boolean =>
  !filter || fold(ex.short + " " + ex.id + " " + group).includes(filter);

export function stripNeighbors(collections: Collection[], group: string): Exercise[] {
  const seen = new Set<string>();
  const rows: Exercise[] = [];
  for (const col of collections) {
    if (col.title !== group) continue;
    for (const ex of col.items) {
      if (seen.has(ex.id)) continue;
      seen.add(ex.id);
      rows.push(ex);
    }
  }
  return rows;
}

const EXPORT_MINIMUM = 2;

export const exportableExercises = (catalog: Exercise[], group: string): Exercise[] =>
  catalog.filter(
    (t) =>
      t.group === group && t.mode === "io" && !t.verification && !t.bonus && !t.assignment,
  );

export const isGroupExportable = (catalog: Exercise[], group: string): boolean =>
  exportableExercises(catalog, group).length >= EXPORT_MINIMUM;
