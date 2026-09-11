// THE CATALOG AS THE PAGE HOLDS IT: the two lists, what is selected, the menu
// filter, and the statement cache.
//
// `selectedId` IS WHAT THE MENU SHOWS. What the EDITOR actually holds is
// `editor.exerciseId`, set only once the fill-in has come back over the network --
// setting it here would attribute the previous exercise's code, still displayed,
// to the new id at the next save.

import { fetchCatalog, fetchDetail } from "../api/public";
import {
  EMPTY_CATALOG,
  fold,
  normalize,
  stripNeighbors,
  type CatalogModel,
  type Exercise,
} from "../domain/catalog";
import type { ExerciseDetail, PublishedAssignment, PublishedRelease } from "../api/types";
import { system } from "./system.svelte";

class CatalogState {
  model = $state<CatalogModel>(EMPTY_CATALOG);
  /** The id chosen in the menu -- the only source of that truth. */
  selectedId = $state("");
  /** A deep-linked exercise that could not be opened: its collection unfolds
   * anyway, so the lock and the date show instead of nothing. */
  spotlighted = $state("");
  /** What the filter field holds, already folded. */
  filter = $state("");
  /** True once `/catalog.json` has answered, whatever it said. */
  loaded = $state(false);
  /** THE INSTRUCTOR'S VIEW: locked exercises are openable. Said by the SERVER
   * (`moderator` in `/etats`), never guessed -- and it arrives AFTER the
   * catalog, which is loaded before there is a session at all. Hence the raw
   * payload kept below: `setStaff` re-normalizes instead of refetching. */
  staff = $state(false);
  /** What `/catalog.json` answered, kept only so `setStaff` can re-read it. */
  #published: PublishedRelease | null = null;

  get collections() {
    return this.model.collections;
  }

  /** Open exercises only. Right for a counter, wrong for a map. */
  get catalog() {
    return this.model.catalog;
  }

  get assignments(): PublishedAssignment[] {
    return this.model.assignments;
  }

  get selected(): Exercise | null {
    return this.catalog.find((t) => t.id === this.selectedId) ?? null;
  }

  assignmentOf(id: string): PublishedAssignment | null {
    return this.assignments.find((a) => a.id === id) ?? null;
  }

  /** The displayed lab's exercises, open and locked alike. */
  get neighbors(): Exercise[] {
    const here = this.selected;
    return here ? stripNeighbors(this.collections, here.group) : [];
  }

  setFilter(text: string): void {
    this.filter = fold(text);
  }

  /** Switch between the student's catalog and the instructor's. Idempotent, and
   * a no-op before the release has arrived -- `load()` reads `staff` itself. */
  setStaff(value: boolean): void {
    if (value === this.staff) return;
    this.staff = value;
    if (this.#published) this.model = normalize(this.#published, value);
  }

  /** The next OPEN exercise, for the action following a success. */
  nextOpen(): Exercise | null {
    const i = this.catalog.findIndex((t) => t.id === this.selectedId);
    return i >= 0 ? (this.catalog[i + 1] ?? null) : null;
  }

  step(by: number): Exercise | null {
    const i = this.catalog.findIndex((t) => t.id === this.selectedId);
    return this.catalog[i + by] ?? null;
  }

  // --- The statement and the templates, loaded when an exercise is opened -----
  // They would make up three quarters of the catalog for 73 exercises of which one
  // is displayed. Kept in memory, so coming back to a seen exercise asks for
  // nothing again.
  #details = new Map<string, ExerciseDetail>();

  async detail(id: string): Promise<ExerciseDetail> {
    const held = this.#details.get(id);
    if (held) return held;
    const fresh = await fetchDetail(id, this.staff);
    // THE FALLBACK IS NOT CACHED: a network that comes back must be able to retry.
    if (!fresh.offline) this.#details.set(id, fresh);
    return fresh;
  }

  /**
   * Load the release. Returns the id to open, or "" -- the caller decides what to
   * do with a locked deep link, because it is the one that can open the menu.
   */
  async load(deepLink: string): Promise<string> {
    const published = await fetchCatalog();
    this.loaded = true;
    if (!published || !Array.isArray(published.exercises)) {
      system.say(
        "La liste des exercices n'a pas pu être chargée. Recharge la page ; si ça " +
          "recommence, préviens ton enseignant.",
        true,
      );
      return "";
    }
    this.#published = published;
    this.model = normalize(published, this.staff);
    if (!this.collections.length) {
      system.say("Aucun exercice n'est publié pour l'instant.");
      return "";
    }
    // A DEEP LINK TO A LOCKED EXERCISE DOES NOT OPEN THE EXERCISE: it opens the
    // menu on its lock and its date. Sharing it early bypasses nothing, and does
    // not look like a dead link either.
    const openable = this.catalog.some((t) => t.id === deepLink);
    if (
      deepLink &&
      !openable &&
      this.collections.some((c) => c.items.some((e) => e.id === deepLink))
    ) {
      this.spotlighted = deepLink;
    }
    return openable ? deepLink : (this.catalog[0]?.id ?? "");
  }
}

export const catalog = new CatalogState();
