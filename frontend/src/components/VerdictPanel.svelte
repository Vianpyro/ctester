<script lang="ts">
  // THE VERDICT CHANNEL. It talks about the STUDENT'S CODE and about nothing else --
  // the service speaks through `SystemBanner`. See `lib/domain/verdict.ts` for why
  // the two must never merge again.
  //
  // `textContent` EVERYWHERE, which in Svelte means ordinary interpolation: what
  // arrives here is a compiler's output and a student program's output, that is to
  // say arbitrary strings. There is no `{@html}` in this file.
  //
  // IT DECIDES NOTHING. Which stage broke, what to say, what to do next: all of it
  // comes from `lib/domain/verdict.ts`, and the submission's phase decides which of
  // the shapes below is on screen.

  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { system } from "../lib/state/system.svelte";
  import { quiz } from "../lib/state/quiz.svelte";
  import { UNITS } from "../lib/domain/labels";
  import {
    AFTER_FAILURE,
    CONTRACT,
    OUTCOMES,
    STEPS,
    STEP_STATE,
    caseClass,
    caseInputs,
    estimatedWait,
    firstError,
    restrictToScope,
    showsContract,
    type Scope,
    type StepState,
  } from "../lib/domain/verdict";
  import type { Verdict } from "../lib/api/types";

  let box: HTMLDivElement | undefined = $state();

  const phase = $derived(submission.phase);

  /** The verdict being displayed, already restricted to the quiz page if any. */
  const shown = $derived.by((): { r: Verdict; scope: Scope | null } | null => {
    if (phase.kind !== "done") return null;
    const scope = phase.scope;
    const r = scope && phase.verdict.kind === "quiz"
      ? restrictToScope(phase.verdict, scope)
      : phase.verdict;
    return { r, scope };
  });

  const failed = $derived(shown ? shown.r.status !== "ok" : false);
  const outcome = $derived(
    shown && failed ? (OUTCOMES[shown.r.status] ?? OUTCOMES.error!) : null,
  );
  const complete = $derived(!!shown && !failed && shown.r.passed === shown.r.total);

  /** The heading, and the count keeps the large type -- a state's title does not. */
  const headline = $derived.by(() => {
    if (phase.kind === "sending") return "Envoi…";
    if (phase.kind === "running") return "Test en cours…";
    if (phase.kind === "queued") {
      // "COMPILATION EN COURS" WAS WRONG HALF THE TIME: `running` covers
      // compilation, execution AND tests -- the worker reports no sub-state, and
      // announcing a stage we do not know shapes the wrong mental model in the
      // person who has the least of one.
      return (
        `En file d'attente — ${phase.position}${phase.position === 1 ? "er" : "e"}` +
        estimatedWait(phase.eta)
      );
    }
    if (phase.kind === "idle" || phase.kind === "lost" || phase.kind === "cooldown") {
      return catalog.catalog.length
        ? "En attente d'une soumission."
        : "Aucun exercice n'est encore ouvert.";
    }
    if (!shown) return "";
    if (failed) return outcome!.titre;
    const frame = shown.scope && shown.r.kind === "quiz" ? " — " + shown.scope.titre : "";
    return `${shown.r.passed ?? 0} / ${shown.r.total ?? 0} ${UNITS[shown.r.kind] ?? "réussis"}${frame}`;
  });

  const cls = $derived.by(() => {
    if (phase.kind === "sending" || phase.kind === "queued" || phase.kind === "running") {
      return "wait";
    }
    if (phase.kind === "done") return failed || !complete ? "bad" : "ok";
    return "idle";
  });

  /** Two steps when the judge graded: the count below IS the tests' result, and a
   *  third box would only repeat it. Three when it did not, so "not reached" shows. */
  const steps = $derived.by((): StepState[] | null => {
    if (phase.kind !== "done") return null;
    if (failed) return outcome!.etapes;
    return ["ok", "ok"];
  });

  const nextAction = $derived.by(() => {
    if (phase.kind !== "done") return null;
    if (failed) return { text: outcome!.suite, next: null };
    if (!complete) return { text: AFTER_FAILURE[shown!.r.kind] ?? "", next: null };
    // WHAT IS OFFERED AFTER A COMPLETE SUCCESS. A button, not a sentence: it is the
    // only moment in the loop where the student has nothing left to fix, and the
    // page used to offer them nothing.
    const next = catalog.nextOpen();
    return next
      ? { text: "Tu peux passer à la suite.", next }
      : { text: "C'est le dernier exercice ouvert pour l'instant.", next: null };
  });

  /** HELP IS OFFERED WHERE THE NEED IS BORN: in front of a failing verdict, not in a
   *  button on the global bar. Both conditions come from the server. */
  const offersHelp = $derived(cls === "bad" && session.signedIn && session.forumOffered);

  async function openDiscussions() {
    const { chat } = await import("../features/forum/chat.svelte");
    await chat.toggleWide();
  }

  /**
   * ON A SMALL SCREEN THE RESULT SITS BELOW THE EDITOR AND OFF-SCREEN: clicking
   * "Tester" visibly produced NOTHING there. On a large screen it is already in the
   * grid next to the editor, and stealing focus mid-correction would be worse than
   * the problem.
   */
  let lastSeen = $state<unknown>(null);
  $effect(() => {
    if (phase.kind !== "done" || phase === lastSeen) return;
    lastSeen = phase;
    const narrow =
      typeof matchMedia === "function" && matchMedia("(max-width: 900px)").matches;
    if (!narrow || !box) return;
    box.scrollIntoView?.({ block: "start", behavior: "smooth" });
    box.focus?.();
  });

  // The heading is what gets announced, and nothing more: the compiler's whole
  // output read aloud would be worse than silence.
  $effect(() => {
    if (headline) system.announce(headline);
  });

  /** Which exercise a wrong quiz answer belongs to, so it can be named. */
  const quizGroup = (id: string): string => quiz.groupOf[id] ?? "";

  const idleHelp =
    "Écris ton code, puis clique sur « Tester ». Les résultats ne sont pas une " +
    "note : ces tests t'aident à trouver tes erreurs, ils ne remplacent pas la " +
    "correction.";
</script>

<!-- FOCUSABLE WITHOUT BEING IN THE TAB ORDER: the effect above puts focus here on
     small screens, where the verdict lands off-screen. -->
<div bind:this={box} id="out" class={cls} tabindex="-1">
  {#if steps}
    <div class="etapes">
      {#each steps as state, i}
        {@const [name, gender] = STEPS[i]!}
        <span class={"pas " + (state || "vide")}>
          <!-- THE WORD, NOT ONLY THE COLOUR nor only a check mark: a state visible
               through a tint alone disappears in black and white as under colour
               blindness, and does not read aloud. -->
          <b>{name}</b><i>{STEP_STATE[gender][state]}</i>
        </span>
      {/each}
    </div>
  {/if}

  <div class={"verdict " + cls + (phase.kind === "done" && !failed ? " compte" : "")}>
    {headline}
  </div>

  {#if cls === "wait"}
    <div class="barre"><i></i></div>
  {/if}

  {#if shown && !failed && (shown.r.total ?? 0) > 0}
    <div class="ticks">
      {#each { length: shown.r.total ?? 0 } as _, n}
        <i class={n < (shown.r.passed ?? 0) ? "on" : ""} style={"--i:" + Math.min(n, 12)}></i>
      {/each}
    </div>
  {/if}

  <!-- AS BODY TEXT, NEVER AT 2.1REM. `link_error` and `memory_error` messages run
       two hundred characters: in title typography they crushed the result area. And
       when the title IS the server's message, it is not repeated. -->
  {#if phase.kind === "idle" || phase.kind === "lost" || phase.kind === "cooldown"}
    <p class="explique">
      {catalog.catalog.length
        ? idleHelp
        : "Le menu « Exercices » donne la date d'ouverture de chacun."}
    </p>
  {:else if shown?.r.message && shown.r.message !== headline}
    <p class="explique">{shown.r.message}</p>
  {/if}

  {#if shown && shown.r.status === "compile_error"}
    <div class="gcc">
      {#if firstError(shown.r.gcc)}
        <!-- THE FIRST ERROR, NOT THE LAST. In C, errors cascade: one missing `;`
             produces six, five of which do not really exist -- and the raw output
             scrolls, so what a beginner reads is the most derived one. -->
        <pre>{firstError(shown.r.gcc)}</pre>
        <!-- EVERYTHING IS ALWAYS THERE, just folded: hiding the rest would raise
             doubt about what is not shown, and some errors only make sense read as
             a chain. -->
        <details class="case">
          <summary>Voir toute la sortie du compilateur</summary>
          <pre>{shown.r.gcc ?? ""}</pre>
        </details>
      {:else}
        <pre>{shown.r.gcc ?? ""}</pre>
      {/if}
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "io"}
    <div>
      {#each shown.r.cases ?? [] as c, i}
        {@const kind = caseClass(c.reason)}
        {@const inputs = caseInputs(c.stdin)}
        <details class="case" open={i === 0}>
          <summary>Cas {c.case} — {kind}</summary>
          <div class="corps">
            <div class="champ">
              <span class="quoi"
                >{inputs.length === 1
                  ? "Ton programme reçoit :"
                  : "Ton programme reçoit, dans cet ordre :"}</span
              >
              <pre class="valeur">{inputs.length
                  ? inputs.join("   puis   ")
                  : "rien — ce cas ne lui fournit aucune entrée"}</pre>
            </div>
            <div class="champ">
              <span class="quoi">Ce qu'il a affiché :</span>
              <pre class="valeur">{c.stdout || "(rien)"}</pre>
            </div>
            <!-- THE NUMBERS THE JUDGE READ, at the same rank as the output. This is
                 the block's single most actionable piece of information -- it takes
                 apart the matching black box -- and it used to live in 12px grey
                 under everything else. -->
            {#if c.nombres}
              <div class="champ">
                <span class="quoi">Les nombres que le juge y a lus :</span>
                <pre class="valeur">{c.nombres.length ? c.nombres.join(", ") : "aucun"}</pre>
              </div>
            {/if}
            {#if c.stderr}
              <div class="champ">
                <span class="quoi">Sa sortie d'erreur :</span>
                <pre class="valeur">{c.stderr}</pre>
              </div>
            {/if}
            <p class="pourquoi">{c.reason}</p>
            {#if showsContract(c)}
              <p class="contrat">{CONTRACT}</p>
            {/if}
          </div>
        </details>
      {/each}
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "unity" && (shown.r.failed ?? []).length}
    <div class="rates">
      <!-- TEST NAMES ARE WRITTEN FOR THE STUDENT -- one still has to say so. A list
           of bare ids does not announce itself as French. -->
      <p class="quoi">
        {(shown.r.failed ?? []).length === 1
          ? "Cette vérification a échoué. Son nom décrit le cas qu'elle teste :"
          : "Ces vérifications ont échoué. Leur nom décrit le cas qu'elles testent :"}
      </p>
      <ul>
        {#each shown.r.failed ?? [] as name}<li>{name}</li>{/each}
      </ul>
      <p class="contrat">
        Les valeurs attendues ne sont pas montrées : les trouver EST l'exercice.
      </p>
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "quiz"}
    <ul>
      {#each shown.r.wrong ?? [] as w}
        {@const group = quizGroup(w.id)}
        {@const ex = group.match(/Exercice\s*\d+/i)}
        {@const empty = !(w.given && w.given.trim())}
        <!-- Not answered is not wrong: red is reserved for actual errors. -->
        <li class={empty ? "rien" : ""}>
          {(ex ? ex[0] + " — " : "") +
            w.label +
            (empty ? "" : ` (tu as répondu « ${w.given} »)`) +
            (w.hint ? " — " + w.hint : "")}
        </li>
      {/each}
    </ul>
  {/if}

  {#if nextAction}
    <!-- THE NEXT ACTION, AND ONE IS NEEDED EVERYWHERE -- success included. The
         moment the student is most receptive used to be exactly the one where the
         page offered nothing. -->
    <div class="suite">
      <span>{nextAction.text}</span>
      {#if nextAction.next}
        <button type="button" class="nav" onclick={() => exercise.open(nextAction.next!.id)}>
          Ouvrir « {nextAction.next.short} »
        </button>
      {/if}
      {#if offersHelp}
        <button type="button" class="nav aide" onclick={openDiscussions}>
          En parler dans les discussions
        </button>
      {/if}
    </div>
  {/if}

  {#if shown?.r.warnings}
    <div class="avert">
      <div class="titre">Avertissements du compilateur</div>
      <div class="quoi">
        Ce n'est pas une erreur : ton programme compile. Mais gcc a remarqué ceci, et
        ça vaut le coup d'œil.
      </div>
      <pre>{shown.r.warnings}</pre>
    </div>
  {/if}
</div>
