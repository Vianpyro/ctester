// THE EXPORT'S SIDE EFFECTS: gathering the drafts, asking for a name, and handing a
// file to the browser. The FILE ITSELF is built by `lib/domain/mainc.ts`, which is
// pure and tested by calling it -- this module is only the parts that touch the world.
//
// NO ROUTE WAS ADDED FOR THIS. It works with NO ACCOUNT: the drafts on this device
// are enough, and the export then emits no request at all.

import { UTF8_BOM, build, codeOf, type Built } from "../domain/mainc";
import { exportableExercises, type Exercise } from "../domain/catalog";
import { fetchDraft } from "../api/account";
import { fetchProfile } from "../api/forum";
import { drafts } from "./drafts.svelte";
import { session } from "../auth/session.svelte";

type Sources = Record<string, Record<string, string> | undefined>;

/**
 * THE LOCAL DRAFT FIRST, THE ACCOUNT NEXT. `localStorage` has everything this device
 * has seen, which covers the vast majority of cases; exercises worked on elsewhere
 * only live on the account.
 *
 * ONE AT A TIME, NOT IN PARALLEL: `/brouillon` goes through `state.py`'s single
 * Postgres connection, behind its global lock. Ten requests at once would not go any
 * faster and would take the queue away from everyone while another student submits.
 * Worst case, it costs one second on a download button.
 */
async function gather(exercises: Exercise[]): Promise<Sources> {
  const found: Sources = {};
  const missing: Exercise[] = [];
  for (const ex of exercises) {
    const local = drafts.get(ex.id);
    if (local && codeOf(ex, local)) found[ex.id] = local;
    else missing.push(ex);
  }
  if (!missing.length || !session.signedIn) return found;
  for (const ex of missing) {
    const answer = await fetchDraft(ex.id);
    if (answer?.sources) found[ex.id] = answer.sources;
  }
  return found;
}

/**
 * THE NAME PRE-FILLS, IT DOES NOT IMPOSE ITSELF. CTester only ever knows a student by
 * an opaque `sub`: the only name it has is the one typed into "Mon identité", or the
 * suggestion Rauthy reports. Same treatment as the identity form -- a field the
 * student rereads, in a file that goes onto THEIR OWN disk and nowhere else. Nothing
 * is published, and it stays empty when unknown.
 */
async function author(): Promise<string> {
  if (!session.signedIn || !session.forumOffered) return "";
  const profile = await fetchProfile();
  if (!profile) return "";
  return String(profile.display_name || profile.suggestion || "").trim();
}

/** ONE LIVE URL AT A TIME. Revoking right after the click chases the download the
 *  browser just started; a timer would be left lying around. We revoke the PREVIOUS
 *  one at the start of the next export: never a race, never more than one live blob. */
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

/**
 * `say(text, failed)`: THE CALLER SAYS WHERE IT DISPLAYS. The action bar's button
 * writes on the draft's line, "Mes progrès"'s button next to itself -- and that line
 * is not even on screen from the list view. A module choosing its own spot would
 * write into the void half the time.
 */
export async function exportGroup(
  catalog: Exercise[],
  group: string,
  say: (text: string, failed?: boolean) => void,
): Promise<Built | null> {
  const exercises = exportableExercises(catalog, group);
  if (!exercises.length) {
    say("rien à exporter pour " + group, true);
    return null;
  }
  say("assemblage de " + group + "…");
  const sources = await gather(exercises);
  const built = build(exercises, sources, await author(), group);
  if (built.vides.length === built.total) {
    say("aucun code enregistré pour " + group + " : rien à exporter", true);
    return built;
  }
  try {
    download("main.c", built.texte);
  } catch {
    say("le téléchargement a échoué — copie ton code à la main", true);
    return built;
  }
  const written = built.total - built.vides.length;
  say(
    "main.c exporté — " +
      written +
      " exercice" +
      (written > 1 ? "s" : "") +
      " sur " +
      built.total +
      (built.vides.length ? " (rien pour : " + built.vides.join(", ") + ")" : ""),
  );
  return built;
}
