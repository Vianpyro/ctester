// THE CATALOG, READ TWICE, AND THAT IS INTENTIONAL.
//
//   `collections` carries the MENU TREE: every exercise, open or not, with its
//     lock and its date. Showing is not giving -- making anything not yet open
//     disappear looked like an outage the night before class.
//   `catalog` carries only OPEN exercises, flat, in the shape "Mes progrès", the
//     export and the counters read. A locked exercise has no business in a
//     progression count nor in a submission `main.c`, and keeping the two lists
//     apart is what avoids adding the same filter in three screens where it
//     would be forgotten in one.
//
// EVERYTHING HERE IS PURE. No DOM, no fetch, no reactive state: this is the
// translation from the published release to what the page reads, and it is
// tested by calling it.

import type {
  Access,
  ExerciseMode,
  ExerciseStatus,
  PublishedAssignment,
  PublishedExercise,
  PublishedRelease,
} from "../api/types";

/** An exercise, in the shape every screen reads. */
export interface Exercise {
  id: string;
  mode: ExerciseMode;
  /** Bare: "ex.1". Ambiguous on its own -- ten labs have one. */
  short: string;
  /** The collection this entry was reached through. */
  group: string;
  /** Qualified: "TP2 : ex.1". What "Mes progrès" and the export show. */
  label: string;
  verification: boolean;
  /** Which assignment this exercise belongs to, or "". */
  assignment: string;
  files: { name: string }[];
  learning: { skills?: string[]; context?: string; difficulty?: string };
  access: Access;
  available_from: string;
}

export interface Collection {
  titre: string;
  access: Access;
  available_from: string;
  items: Exercise[];
}

export interface CatalogModel {
  /** The menu tree: everything, open or not. */
  collections: Collection[];
  /** Open exercises only (a moderator also gets the locked ones), deduplicated,
   * in collection order. */
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
    // `label` QUALIFIED, `short` BARE. "ex.1" alone names an exercise in each of
    // the ten labs, and "Mes progrès" has no collection column to disambiguate.
    label: group ? group.replace(/\s+/g, "") + " : " + title : title,
    verification: !!ex.verification,
    assignment: ex.assignment ?? "",
    // NAMES ONLY. The server path never crosses the publication.
    files: (ex.files ?? []).map((f) => ({ name: f.name })),
    learning,
    access: ex.access ?? "available",
    available_from: ex.release?.available_from ?? "",
  };
}

/**
 * The published release, turned into the two lists above.
 *
 * `staff` IS THE INSTRUCTOR'S VIEW, AND THE DEFAULT IS THE STUDENT'S. Dates are
 * for students: a moderator must be able to open a locked exercise to check
 * that it renders and grades as intended. It changes exactly one thing -- the
 * flat list keeps what is not open yet -- so everything downstream (`selected`,
 * the lab strip, the editor, the submission) works with no branch of its own.
 * `lockNote()` is untouched: the lock and the date stay on screen, because that
 * is precisely the information the instructor came for.
 */
export function normalize(release: PublishedRelease, staff = false): CatalogModel {
  // ASSIGNMENTS ARE NOT COLLECTIONS, and they are kept in their own list for
  // that reason. A collection is the menu's path through the catalog; an
  // assignment is assessed work with a deadline, a team and a hand-in. Folding
  // one into the other would make "which lab is this in" and "what am I handing
  // in" the same field.
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
    const titre = String(col.title ?? col.id ?? "");
    for (const id of items) classified.add(id);
    collections.push({
      titre,
      access: col.access ?? "available",
      available_from: col.release?.available_from ?? "",
      items: items.map((id) => catalogEntry(byId.get(id)!, titre)),
    });
  }
  // AN EXERCISE MAY BE IN NO COLLECTION AT ALL. Publishing it must be enough to
  // make it reachable, or one forgotten collection line would make it disappear
  // with nothing to flag it.
  const orphans = [...byId.keys()].filter((id) => !classified.has(id));
  if (orphans.length) {
    collections.push({
      titre: "Autres",
      access: "available",
      available_from: "",
      items: orphans.map((id) => catalogEntry(byId.get(id)!, "Autres")),
    });
  }
  // UNIQUE, AND IN COLLECTION ORDER. An exercise shared by two collections shows
  // twice in the menu -- that is the point of a cross-cutting path -- but counts
  // once in a progression and exports once into a main.c.
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

/**
 * WHAT A LOCK SAYS, and it must say a date: "not open yet" without "opens
 * September 18" sends the student off to write an email.
 */
export function lockNote(entry: { access?: Access; available_from?: string } | null): string {
  if (!entry || entry.access === "available") return "";
  if (entry.access === "archived") return "archivé";
  const when = new Date(entry.available_from ?? "");
  return isNaN(when.getTime())
    ? "à venir"
    : // "fr-CA" ET PAS `undefined`. La locale du navigateur rendait « September 25 »
      // au milieu de « ouvre le … » : la moitié de la phrase est écrite en dur en
      // français, donc laisser l'autre moitié suivre le poste donne un mélange,
      // jamais une traduction. Toute la page est en français, la date aussi.
      "ouvre le " + when.toLocaleDateString("fr-CA", { day: "numeric", month: "long" });
}

/**
 * A TILE'S STATE -- PROGRESS, NOT LOCATION, and the two are deliberately
 * separate axes. "Open in the editor" is where one IS; "réussi" is what one has
 * DONE, and an exercise can be both. Folding them into one value made a solved
 * exercise stop reading as solved the moment it was opened, which is exactly
 * when a student looks at it.
 *
 * ORDER MATTERS: locked beats everything, since there is nothing to report about
 * an exercise one cannot open yet.
 */
export function tileState(
  ex: Exercise,
  locked: boolean,
  statuses: Record<string, ExerciseStatus | undefined>,
): { cls: string; word: string } {
  if (locked) return { cls: "afaire", word: "pas encore ouvert" };
  const status = statuses[ex.id] ?? "";
  if (status === "solved") return { cls: "reussi", word: "réussi" };
  if (ex.verification) return { cls: "verif", word: "vérification" };
  if (status === "attempted") return { cls: "afaire", word: "essayé" };
  return { cls: "afaire", word: "à faire" };
}

/**
 * A BONUS IS RECOGNIZED BY ITS LABEL, not by a catalog field: the content names
 * them "bonus" and there is no flag for it. If one appears, the counters and the
 * export keep treating it as an ordinary exercise -- only the border changes,
 * which is the honest amount of meaning a naming convention deserves.
 */
export const isBonus = (ex: Exercise): boolean => /bonus/i.test(ex.short || "");

/**
 * A SHORT LABEL, BECAUSE THERE ARE ELEVEN OF THEM. The content itself writes
 * "TP5 : ex.1 celcius_to_fahrenheit"; eleven thirty-character pills fill three
 * lines and steal from the statement the room it needs, when the full name is
 * already shown right above.
 */
export function stripLabel(ex: Exercise): string {
  const bare = (ex.short || "").replace(/^[^:]*:\s*/, "");
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return "ex." + number[1];
  // THE ELLIPSIS IS LOAD-BEARING: "convertir_en_radia" cut off flat reads like a
  // display bug, not like a shortcut.
  return bare.length > 20 ? bare.slice(0, 19) + "…" : bare;
}

/** "ex.3" on a grid tile, "vérif" on a verification. Shorter than the strip's. */
export function gridLabel(ex: Exercise): string {
  if (ex.verification) return "vérif";
  const bare = (ex.short || "").replace(/^[^:]*:\s*/, "");
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return number[1]!;
  return bare.length > 8 ? bare.slice(0, 7) + "…" : bare;
}

/**
 * ACCENT-INSENSITIVE, and that is not cosmetic: somebody typing "vitesse" must
 * find "vitesse limite" without knowing where it lives, and "reussi" must match
 * "réussi" or they conclude the search is broken.
 */
export const fold = (text: string): string =>
  String(text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

export const matchesFilter = (ex: Exercise, group: string, filter: string): boolean =>
  !filter || fold(ex.short + " " + ex.id + " " + group).includes(filter);

/**
 * The lab's exercises IN CATALOG ORDER, open and locked alike. Read from
 * `collections` because `catalog` drops what is not open, and deduplicated
 * because an exercise may belong to two collections.
 */
export function stripNeighbors(collections: Collection[], group: string): Exercise[] {
  const seen = new Set<string>();
  const rows: Exercise[] = [];
  for (const col of collections) {
    if (col.titre !== group) continue;
    for (const ex of col.items) {
      if (seen.has(ex.id)) continue;
      seen.add(ex.id);
      rows.push(ex);
    }
  }
  return rows;
}

// --- What the one-piece main.c can bundle -------------------------------------
// The submission format relies on `#define exercice N` to choose WHICH `main()`
// gets compiled: that only makes sense for "io" exercises, which are complete
// programs. A "unity" exercise is a module with NO `main()`, a quiz has no code
// at all, and offering the button there would promise a file that does not
// compile.
//
// VERIFICATIONS ARE NOT THERE: they are not part of the submission, and an io
// verification would sneak in with its own `#if exercice == N`. NEITHER ARE A
// TEAM ASSIGNMENT'S EXERCISES: the assignment has its own hand-in, and folding
// six shared modules into somebody's personal main.c would hand in the wrong
// artifact under the wrong name.
//
// TWO EXERCISES AT LEAST, because a file that bundles one bundles nothing: the
// student already has that code in front of them in the editor.

const EXPORT_MINIMUM = 2;

export const exportableExercises = (catalog: Exercise[], group: string): Exercise[] =>
  catalog.filter((t) => t.group === group && t.mode === "io" && !t.verification && !t.assignment);

export const isGroupExportable = (catalog: Exercise[], group: string): boolean =>
  exportableExercises(catalog, group).length >= EXPORT_MINIMUM;
