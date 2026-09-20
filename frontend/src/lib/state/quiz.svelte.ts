import { fetchQuiz } from "../api/public";
import { catalog } from "./catalog.svelte";
import { drafts } from "./drafts.svelte";
import type { Scope } from "../domain/verdict";

export interface QuizQuestion {
  id: string;
  label: string;
  group: string;
  options?: string[];
}

export interface QuizPage {
  title: string;
  questions: QuizQuestion[];
}

class QuizState {
  pages = $state<QuizPage[]>([]);
  page = $state(0);
  answers = $state<Record<string, string>>({});
  exerciseId = $state("");
  loading = $state(false);
  groupOf = $state<Record<string, string>>({});

  async load(id: string): Promise<void> {
    this.loading = true;
    this.exerciseId = id;
    this.pages = [];
    this.page = 0;
    const data = await fetchQuiz(id, catalog.staff);
    this.loading = false;
    if (!data || !Array.isArray(data.questions)) return;
    const held = drafts.get(id) ?? {};
    const pages: QuizPage[] = [];
    const groups: Record<string, string> = {};
    const answers: Record<string, string> = {};
    for (const q of data.questions) {
      groups[q.id] = q.group;
      answers[q.id] = held[q.id] ?? "";
      const last = pages[pages.length - 1];
      if (!last || last.title !== q.group) pages.push({ title: q.group, questions: [q] });
      else last.questions.push(q);
    }
    this.groupOf = groups;
    this.answers = answers;
    this.pages = pages;
  }

  showPage(i: number): void {
    if (!this.pages.length) return;
    this.page = Math.min(Math.max(i, 0), this.pages.length - 1);
  }

  save(): void {
    drafts.putLocal(this.exerciseId, this.answers);
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
    this.exerciseId = "";
    this.page = 0;
  }
}

export const quiz = new QuizState();
