import { CHAT_GENERAL, CHAT_PREFIX, bareExercise } from "../../lib/api/forum";
import { t } from "../../lib/i18n.svelte";
import { catalog } from "../../lib/state/catalog.svelte";

export function readableThread(key: string): string {
  if (key === CHAT_GENERAL) return t("forum.general");
  const bare = bareExercise(key);
  const found = catalog.catalog.find((ex) => ex.id === bare);
  const name = found ? found.short || found.label : bare;
  return key.startsWith(CHAT_PREFIX)
    ? t("forum.channel", { name })
    : t("forum.my_questions", { name });
}
