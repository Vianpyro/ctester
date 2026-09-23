import { catalog } from "./catalog.svelte";
import { editor } from "./editor.svelte";
import { answered, quiz } from "./quiz.svelte";
import { statuses } from "./statuses.svelte";
import { submission } from "./submission.svelte";
import { system } from "./system.svelte";
import { sessionKey } from "./accesskey";
import { t } from "../i18n.svelte";

async function afterVerdict(): Promise<void> {
  await statuses.load();
  const progress = await import("../../features/progress/projection.svelte").catch(() => null);
  await progress?.projection.refreshIfOpen();
}

// Kept out of ActionBar: the workspace stays mounted (hidden) while other views are open.
export async function runTest(scoped: boolean): Promise<void> {
  const here = catalog.selected;
  if (!here) {
    system.say(t("run.pick_exercise"));
    return;
  }
  if (!sessionKey()) {
    system.say(t("access.missing_key"));
    return;
  }
  if (here.mode === "quiz") {
    const answers = { ...quiz.answers };
    if (!Object.values(answers).some(answered)) {
      system.say(t("run.no_answer"));
      return;
    }
    quiz.snapshot();
    await submission.submit(here, sessionKey(), { answers }, scoped ? quiz.currentScope() : null, afterVerdict);
    return;
  }
  const files = { ...editor.sources };
  if (!Object.values(files).some((v) => v.trim())) {
    system.say(t("run.empty"));
    return;
  }
  await submission.submit(here, sessionKey(), { files }, null, afterVerdict);
}
