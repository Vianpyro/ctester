import { fetchQuiz } from "../api/public";
import { catalog } from "./catalog.svelte";
import { drafts } from "./drafts.svelte";
import type { Scope } from "../domain/verdict";
import { type Answer, answered, keyOf, pack, splitKey } from "../domain/answer";

export { answered, keyOf, type Answer };

export interface QuizQuestion {
  /** Unique within its quiz, and what the judge reads back in `wrong[].id`. */
  id: string;
  /** Unique across the page: question ids only have to be unique inside one quiz. */
  key: string;
  exercise: string;
  label: string;
  group: string;
  row: string;
  col: string;
  type: string;
  width: number;
  options: string[];
  prompts: string[];
  template: string;
  gaps: string[][];
}

/** One `group` of a quiz: a heading and a counter, nothing more. */
export interface QuizSection {
  /** Unique even when two runs of questions carry the same group, which `{#each}` keys on. */
  key: string;
  title: string;
  questions: QuizQuestion[];
}

/** One exercise on the page. A page holds as many as it can show without scrolling. */
export interface LoadedQuiz {
  exerciseId: string;
  title: string;
  sections: QuizSection[];
}

/** An untouched answer of the shape its question expects. */
function blankFor(q: QuizQuestion): Answer {
  if (q.type === "multi") return [];
  // An ordering starts from the order the page shows, so the student rearranges it.
  if (q.type === "order") return [...q.options];
  if (q.type === "cloze") return q.gaps.map(() => "");
  if (q.type === "match") return {};
  return "";
}

// A draft is stored as text. A structured answer travels as JSON and is only restored when
// it still has the shape its question expects: a question whose type changed must not
// poison a widget with a value it cannot render.
function unpack(raw: string | undefined, blank: Answer): Answer {
  if (raw === undefined) return blank;
  if (typeof blank === "string") return raw;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return blank;
    return Array.isArray(parsed) === Array.isArray(blank) ? (parsed as Answer) : blank;
  } catch {
    return blank;
  }
}

class QuizState {
  /** The exercises the page shows, in the collection's order. */
  shown = $state<LoadedQuiz[]>([]);
  /** Every answer on the page, keyed across exercises. */
  answers = $state<Record<string, Answer>>({});
  /** The answers as they were last sent, so a mark is dropped the moment a field is retyped. */
  submitted = $state<Record<string, string>>({});
  loading = $state(false);

  #groups = new Map<string, string>();

  /** The group a question belongs to, for the verdict to name where an answer went wrong. */
  groupOf(exercise: string, question: string): string {
    return this.#groups.get(keyOf(exercise, question)) ?? "";
  }

  /**
   * One exercise's questions, with its drafts restored. Loading does not put it on the
   * page: the panel decides that once it has measured what fits.
   */
  async fetch(exerciseId: string, title: string): Promise<LoadedQuiz | null> {
    this.loading = true;
    const data = await fetchQuiz(exerciseId, catalog.staff);
    this.loading = false;
    if (!data || !Array.isArray(data.questions)) return null;
    const held = drafts.get(exerciseId) ?? {};
    const sections: QuizSection[] = [];
    const answers = { ...this.answers };
    for (const wire of data.questions) {
      const q: QuizQuestion = {
        id: wire.id,
        key: keyOf(exerciseId, wire.id),
        exercise: exerciseId,
        label: wire.label,
        group: wire.group,
        row: wire.row ?? "",
        col: wire.col ?? "",
        type: wire.type ?? "int",
        width: wire.width ?? 0,
        options: wire.options ?? [],
        prompts: wire.prompts ?? [],
        template: wire.template ?? "",
        gaps: wire.gaps ?? [],
      };
      this.#groups.set(q.key, q.group);
      answers[q.key] = unpack(held[q.id], blankFor(q));
      const last = sections[sections.length - 1];
      if (!last || last.title !== q.group) {
        sections.push({
          key: exerciseId + "\u0000" + sections.length,
          title: q.group,
          questions: [q],
        });
      } else last.questions.push(q);
    }
    this.answers = answers;
    return { exerciseId, title, sections };
  }

  setPage(loaded: LoadedQuiz[]): void {
    this.shown = loaded;
  }

  /** What one exercise sends: its own answers, under the ids the judge reads. */
  answersFor(loaded: LoadedQuiz): Record<string, Answer> {
    const found: Record<string, Answer> = {};
    for (const section of loaded.sections) {
      for (const q of section.questions) found[q.id] = this.answers[q.key] ?? "";
    }
    return found;
  }

  scopeOf(loaded: LoadedQuiz): Scope {
    return {
      title: loaded.title,
      ids: loaded.sections.flatMap((s) => s.questions.map((q) => q.id)),
    };
  }

  /**
   * Remember the answers of the exercises being sent, and only those: an exercise left out
   * of a run must not wear marks from an older verdict.
   */
  snapshot(loaded: LoadedQuiz[]): void {
    const sent: Record<string, string> = {};
    for (const one of loaded) {
      for (const section of one.sections) {
        for (const q of section.questions) sent[q.key] = pack(this.answers[q.key]);
      }
    }
    this.submitted = sent;
  }

  /** Drafts stay per exercise: that is the key the server and the export both use. */
  save(): void {
    const byExercise = new Map<string, Record<string, string>>();
    for (const [key, value] of Object.entries(this.answers)) {
      const [exercise, question] = splitKey(key);
      if (!byExercise.has(exercise)) byExercise.set(exercise, {});
      byExercise.get(exercise)![question] = pack(value);
    }
    for (const loaded of this.shown) {
      const flat = byExercise.get(loaded.exerciseId);
      if (flat) drafts.putLocal(loaded.exerciseId, flat);
    }
  }

  clear(): void {
    this.shown = [];
    this.answers = {};
    this.submitted = {};
    this.#groups.clear();
  }
}

export const quiz = new QuizState();
