import { UTF8_BOM, build, codeOf, type Built } from "../domain/mainc";
import { t } from "../i18n.svelte";
import { exportableExercises, type Exercise } from "../domain/catalog";
import { fetchDraft } from "../api/account";
import { fetchProfile } from "../api/forum";
import { drafts } from "./drafts.svelte";
import { session } from "../auth/session.svelte";

type Sources = Record<string, Record<string, string> | undefined>;

async function gather(exercises: Exercise[]): Promise<Sources> {
  const found: Sources = {};
  const missing: Exercise[] = [];
  for (const ex of exercises) {
    const local = drafts.get(ex.id);
    if (local && codeOf(ex, local)) found[ex.id] = local;
    else missing.push(ex);
  }
  if (!missing.length || !session.signedIn) return found;
  // One at a time: the API serializes database access behind a single connection.
  for (const ex of missing) {
    const answer = await fetchDraft(ex.id);
    if (answer?.sources) found[ex.id] = answer.sources;
  }
  return found;
}

async function author(): Promise<string> {
  if (!session.signedIn || !session.forumOffered) return "";
  const profile = await fetchProfile();
  if (!profile) return "";
  return String(profile.display_name || profile.suggestion || "").trim();
}

let previousUrl: string | null = null;

function download(file: string, text: string): void {
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  const blob = new Blob([UTF8_BOM + text], { type: "text/plain;charset=utf-8" });
  previousUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = previousUrl;
  link.download = file;
  document.body.append(link);
  link.click();
  link.remove();
}

export async function exportGroup(
  catalog: Exercise[],
  group: string,
  say: (text: string, failed?: boolean) => void,
): Promise<Built | null> {
  const exercises = exportableExercises(catalog, group);
  if (!exercises.length) {
    say(t("export.nothing", { group }), true);
    return null;
  }
  say(t("export.building", { group }));
  const sources = await gather(exercises);
  const built = build(exercises, sources, await author(), group);
  if (built.empty.length === built.total) {
    say(t("export.no_code", { group }), true);
    return built;
  }
  try {
    download("main.c", built.text);
  } catch {
    say(t("export.download_failed"), true);
    return built;
  }
  const written = built.total - built.empty.length;
  say(
    t("export.done", { count: written, total: built.total }) +
      (built.empty.length ? t("export.empty", { names: built.empty.join(", ") }) : ""),
  );
  return built;
}
