import { catalog } from "./catalog.svelte";
import { editor } from "./editor.svelte";
import { answered, quiz } from "./quiz.svelte";
import { statuses } from "./statuses.svelte";
import { submission, type Asked } from "./submission.svelte";
import { system } from "./system.svelte";
import { MISSING_KEY_MESSAGE, sessionKey } from "./accesskey";

export async function afterVerdict(): Promise<void> {
  await statuses.load();
  const progress = await import("../../features/progress/projection.svelte").catch(() => null);
  await progress?.projection.refreshIfOpen();
}

// Kept out of ActionBar: the workspace stays mounted (hidden) while other views are open.
export async function runTest(): Promise<void> {
  const here = catalog.selected;
  if (!here) {
    system.say("Choisis un exercice dans le menu pour commencer.");
    return;
  }
  if (!sessionKey()) {
    system.say(MISSING_KEY_MESSAGE);
    return;
  }
  if (here.mode === "quiz") {
    // Only the exercises that were actually filled in: the server refuses an empty one,
    // and a batch is accepted whole or not at all.
    const touched = quiz.shown.filter((loaded) =>
      Object.values(quiz.answersFor(loaded)).some(answered),
    );
    if (!touched.length) {
      system.say("Saisis au moins une réponse avant de tester.");
      return;
    }
    const asked: Asked[] = touched.map((loaded) => ({
      exercise: { id: loaded.exerciseId, mode: "quiz", short: loaded.title },
      body: { answers: quiz.answersFor(loaded) },
      scope: quiz.scopeOf(loaded),
    }));
    // Snapshot what was sent, and only that: a question is marked only while its field
    // still holds the answer that was graded.
    quiz.snapshot(touched);
    await submission.submit(asked, sessionKey(), afterVerdict);
    return;
  }
  const files = { ...editor.sources };
  if (!Object.values(files).some((v) => v.trim())) {
    system.say("Il n'y a encore rien à tester : écris ou colle ton code d'abord.");
    return;
  }
  await submission.submit(
    [{ exercise: here, body: { files }, scope: null }],
    sessionKey(),
    afterVerdict,
  );
}
