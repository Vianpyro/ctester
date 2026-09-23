import { fetchCatalog, fetchDetail } from "../api/public";
import { t } from "../i18n.svelte";
import { setSkillLabels } from "../domain/labels";
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
  selectedId = $state("");
  spotlighted = $state("");
  filter = $state("");
  loaded = $state(false);
  staff = $state(false);
  #published: PublishedRelease | null = null;

  get collections() {
    return this.model.collections;
  }

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

  get neighbors(): Exercise[] {
    const here = this.selected;
    return here ? stripNeighbors(this.collections, here.group) : [];
  }

  setFilter(text: string): void {
    this.filter = fold(text);
  }

  setStaff(value: boolean): void {
    if (value === this.staff) return;
    this.staff = value;
    if (this.#published) this.model = normalize(this.#published, value);
  }

  nextOpen(): Exercise | null {
    const i = this.catalog.findIndex((t) => t.id === this.selectedId);
    return i >= 0 ? (this.catalog[i + 1] ?? null) : null;
  }

  step(by: number): Exercise | null {
    const i = this.catalog.findIndex((t) => t.id === this.selectedId);
    return this.catalog[i + by] ?? null;
  }

  #details = new Map<string, ExerciseDetail>();

  async detail(id: string): Promise<ExerciseDetail> {
    const held = this.#details.get(id);
    if (held) return held;
    const fresh = await fetchDetail(id, this.staff);
    if (!fresh.offline) this.#details.set(id, fresh);
    return fresh;
  }

  async load(deepLink: string, remembered = ""): Promise<string> {
    const published = await fetchCatalog();
    this.loaded = true;
    if (!published || !Array.isArray(published.exercises)) {
      system.say(t("catalog.load_failed"), true);
      return "";
    }
    this.#published = published;
    setSkillLabels(published.skill_labels ?? {});
    this.model = normalize(published, this.staff);
    if (!this.collections.length) {
      system.say(t("progress.none_published"));
      return "";
    }
    const openable = this.catalog.some((t) => t.id === deepLink);
    if (
      deepLink &&
      !openable &&
      this.collections.some((c) => c.items.some((e) => e.id === deepLink))
    ) {
      this.spotlighted = deepLink;
    }
    if (openable) return deepLink;
    if (remembered && this.catalog.some((t) => t.id === remembered)) return remembered;
    return this.catalog[0]?.id ?? "";
  }
}

export const catalog = new CatalogState();
