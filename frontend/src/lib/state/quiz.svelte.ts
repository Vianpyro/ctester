// THE QUIZ: questions grouped into pages, and the answers typed into them.
//
// IT IS IN THE MAIN BUNDLE, and that is a deliberate change from the old split.
// The lazy modules exist to keep the ANONYMOUS path from downloading anything
// account-related; a quiz is not account-related -- an anonymous student takes one
// -- so deferring it would only add a loading state in front of something they
// need immediately. It is four kilobytes.
//
// SAME DRAFT CONTRACT AS THE EDITOR: what was typed is there on return, in the
// same store, so "Effacer mes brouillons" erases the answers too.

import { fetchQuiz } from "../api/public";
import { drafts } from "./drafts.svelte";
import type { Scope } from "../domain/verdict";

export interface QuizQuestion {
  id: string;
  label: string;
  group: string;
}

export interface QuizPage {
  titre: string;
  questions: QuizQuestion[];
}

class QuizState {
  pages = $state<QuizPage[]>([]);
  page = $state(0);
  /** question id -> what was typed. */
  answers = $state<Record<string, string>>({});
  exerciseId = $state("");
  loading = $state(false);
  /** question id -> its group, so a wrong answer can be named by exercise. */
  groupOf = $state<Record<string, string>>({});

  async load(id: string): Promise<void> {
    this.loading = true;
    this.exerciseId = id;
    this.pages = [];
    this.page = 0;
    const data = await fetchQuiz(id);
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
      if (!last || last.titre !== q.group) pages.push({ titre: q.group, questions: [q] });
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

  /**
   * THE CURRENT PAGE IS THE CURRENT EXERCISE: pages are already split by group, so
   * "Tester l'exercice" has nothing to re-split. It restricts the READING only --
   * see `restrictToScope`.
   */
  currentScope(): Scope | null {
    const here = this.pages[this.page];
    if (!here) return null;
    return { titre: here.titre, ids: here.questions.map((q) => q.id) };
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
