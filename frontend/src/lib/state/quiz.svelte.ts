import { fetchQuiz } from "../api/public";
import { catalog } from "./catalog.svelte";
import { drafts } from "./drafts.svelte";
import type { Scope } from "../domain/verdict";
import { type Answer, answered, packAll } from "../domain/answer";

export { answered, packAll, type Answer };

export interface QuizQuestion {
  id: string;
  label: string;
  group: string;
  type: string;
  options: string[];
  prompts: string[];
  template: string;
  gaps: string[][];
}

export interface QuizPage {
  /** Unique even when two runs of questions carry the same group, which `{#each}` keys on. */
  key: string;
  title: string;
  questions: QuizQuestion[];
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
  pages = $state<QuizPage[]>([]);
  page = $state(0);
  answers = $state<Record<string, Answer>>({});
  exerciseId = $state("");
  loading = $state(false);
  groupOf = $state<Record<string, string>>({});
  /** The answers as they were last sent, so a mark is dropped the moment a field is retyped. */
  submitted = $state<Record<string, string>>({});

  async load(id: string): Promise<void> {
    // Reloading the same quiz (boot does, once the token arrives) keeps the questions on
    // screen until the new ones land, so the panel never collapses to nothing.
    const same = this.exerciseId === id && this.pages.length > 0;
    this.loading = true;
    this.exerciseId = id;
    if (!same) {
      this.pages = [];
      this.page = 0;
      this.submitted = {};
    }
    const data = await fetchQuiz(id, catalog.staff);
    this.loading = false;
    if (!data || !Array.isArray(data.questions)) return;
    const held = drafts.get(id) ?? {};
    const pages: QuizPage[] = [];
    const groups: Record<string, string> = {};
    const answers: Record<string, Answer> = {};
    for (const wire of data.questions) {
      const q: QuizQuestion = {
        id: wire.id,
        label: wire.label,
        group: wire.group,
        type: wire.type ?? "int",
        options: wire.options ?? [],
        prompts: wire.prompts ?? [],
        template: wire.template ?? "",
        gaps: wire.gaps ?? [],
      };
      groups[q.id] = q.group;
      answers[q.id] = unpack(held[q.id], blankFor(q));
      const last = pages[pages.length - 1];
      if (!last || last.title !== q.group) {
        pages.push({ key: q.group + "\u0000" + pages.length, title: q.group, questions: [q] });
      } else last.questions.push(q);
    }
    this.groupOf = groups;
    this.answers = answers;
    this.pages = pages;
    if (this.page >= pages.length) this.page = 0;
  }

  showPage(i: number): void {
    if (!this.pages.length) return;
    this.page = Math.min(Math.max(i, 0), this.pages.length - 1);
  }

  save(): void {
    drafts.putLocal(this.exerciseId, packAll(this.answers));
  }

  currentScope(): Scope | null {
    const here = this.pages[this.page];
    if (!here) return null;
    return { title: here.title, ids: here.questions.map((q) => q.id) };
  }

  clear(): void {
    this.pages = [];
    this.answers = {};
    this.groupOf = {};
    this.submitted = {};
    this.exerciseId = "";
    this.page = 0;
  }
}

export const quiz = new QuizState();
