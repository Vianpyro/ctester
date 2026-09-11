// WHAT THIS ACCOUNT HAS DONE: the per-exercise status and the practice counters.
//
// IN THE CORE, and read by the menu, the lab strip and "Mes progrès" alike.
// Knowing what one has done should not require switching screens -- it used to
// live only in "Mes exercices", even though the data was already loaded.
//
// A READ FAILURE PRODUCES AN EMPTY MAP, NOT A FALSE STATUS. "À faire" on a solved
// exercise beats the opposite, and the projection screens say plainly when they
// do not know.

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
    // THE EARLIEST THE PAGE CAN LEARN THE ROLE. The catalog is loaded before
    // there is a session at all, so the menu is told afterwards that dates do
    // not close anything for this account.
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
    await this.loadStates();
    await this.loadPractice();
  }

  forget(): void {
    this.byExercise = {};
    this.practice = {};
    catalog.setStaff(false);
  }
}

export const statuses = new Statuses();

// MARKS LEAVE WITH THE SESSION: leaving check marks in the menu and the strip
// would show the progress of somebody who just signed out.
whenSignedOut(() => statuses.forget());
