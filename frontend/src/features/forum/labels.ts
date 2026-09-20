import { CHAT_GENERAL, CHAT_PREFIX, bareExercise } from "../../lib/api/forum";
import { catalog } from "../../lib/state/catalog.svelte";

export function readableThread(key: string): string {
  if (key === CHAT_GENERAL) return "# général";
  const bare = bareExercise(key);
  const found = catalog.catalog.find((t) => t.id === bare);
  const name = found ? found.short || found.label : bare;
  return key.startsWith(CHAT_PREFIX) ? "# " + name : "Mes questions — " + name;
}
