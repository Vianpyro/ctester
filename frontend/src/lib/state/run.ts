// SOUMETTRE, ET CE N'EST PAS UNE DÉCISION DE COMPOSANT.
//
// Ces quarante lignes ont vécu dans `ActionBar.svelte`, où elles étaient
// seulement HÉBERGÉES : quiz ou fichiers, vide ou non, clé de session présente
// ou absente, c'est de l'arbitrage, et « la logique n'est pas dans les
// composants » vaut ici comme ailleurs.
//
// CE QUI A FORCÉ LE DÉMÉNAGEMENT, c'est `Ctrl+Entrée`. La barre d'actions est
// à l'intérieur de `#travail`, qui est `hidden` et NON DÉMONTÉ quand une autre
// vue est ouverte : un `<svelte:window>` posé là serait vivant pendant que
// « Mes progrès » est à l'écran, et le raccourci soumettrait depuis un écran
// sans éditeur. C'est `App.svelte` qui garde la portée, parce que c'est
// `view.svelte.ts` qui sait quelle vue est ouverte.
//
// AUCUNE RUNE ICI : c'est un module d'action, comme `export.ts` et
// `accesskey.ts`. L'état de la soumission vit dans `submission.svelte.ts`.

import { catalog } from "./catalog.svelte";
import { editor } from "./editor.svelte";
import { quiz } from "./quiz.svelte";
import { statuses } from "./statuses.svelte";
import { submission } from "./submission.svelte";
import { system } from "./system.svelte";
import { MISSING_KEY_MESSAGE, sessionKey } from "./accesskey";

/** Ce qu'il faut relire une fois un verdict arrivé. La page n'en calcule rien. */
export async function afterVerdict(): Promise<void> {
  await statuses.load();
  const progress = await import("../../features/progres/projection.svelte").catch(() => null);
  await progress?.projection.refreshIfOpen();
}

/**
 * Soumettre l'exercice ouvert. `scoped` restreint la LECTURE d'un verdict de
 * quiz à la page affichée -- jamais ce qui est envoyé au juge.
 */
export async function runTest(scoped: boolean): Promise<void> {
  const here = catalog.selected;
  if (!here) {
    system.say("Choisis un exercice dans le menu pour commencer.");
    return;
  }
  // WE DO NOT SEND A SUBMISSION WE KNOW WILL BE REFUSED: the server's 403 says
  // "clé de session invalide ou expirée", which helps nobody.
  if (!sessionKey()) {
    system.say(MISSING_KEY_MESSAGE);
    return;
  }
  if (here.mode === "quiz") {
    const answers = { ...quiz.answers };
    // NOTHING TO TEST IS NOT A FAILURE. In red, at 2.1rem, where the verdict goes,
    // it used to scold somebody who had just opened the exercise and clicked to
    // see what the button does.
    if (!Object.values(answers).some((v) => v.trim())) {
      system.say("Saisis au moins une réponse avant de tester.");
      return;
    }
    await submission.submit(here, sessionKey(), { answers }, scoped ? quiz.currentScope() : null, afterVerdict);
    return;
  }
  const files = { ...editor.sources };
  if (!Object.values(files).some((v) => v.trim())) {
    system.say("Il n'y a encore rien à tester : écris ou colle ton code d'abord.");
    return;
  }
  await submission.submit(here, sessionKey(), { files }, null, afterVerdict);
}
