import { fetchPractice, fetchStates } from "../api/account";
import { session, whenSignedOut } from "../auth/session.svelte";
import { catalog } from "./catalog.svelte";
import type { ExerciseStatus, PracticeRow } from "../api/types";

class Statuses {
  byExercise = $state<Record<string, ExerciseStatus>>({});
  practice = $state<Record<string, PracticeRow>>({});

  of(exerciseId: string): ExerciseStatus | undefined {
    return this.byExercise[exerciseId];
  }

  async loadStates(): Promise<void> {
    const answer = await fetchStates();
    const map: Record<string, ExerciseStatus> = {};
    for (const row of answer?.states ?? []) {
      if (row && typeof row.exercise_id === "string") map[row.exercise_id] = row.status;
    }
    this.byExercise = map;
    catalog.setStaff(!!answer?.moderator);
  }

  async loadPractice(): Promise<void> {
    const answer = await fetchPractice();
    const map: Record<string, PracticeRow> = {};
    for (const row of answer?.practice ?? []) {
      if (
        row &&
        typeof row.exercise_id === "string" &&
        Number.isInteger(row.attempts) &&
        Number.isInteger(row.successes)
      ) {
        map[row.exercise_id] = row;
      }
    }
    this.practice = map;
  }

  async load(): Promise<void> {
    if (!session.signedIn) return;
    await Promise.all([this.loadStates(), this.loadPractice()]);
  }

  forget(): void {
    this.byExercise = {};
    this.practice = {};
    catalog.setStaff(false);
  }
}

export const statuses = new Statuses();

whenSignedOut(() => statuses.forget());
