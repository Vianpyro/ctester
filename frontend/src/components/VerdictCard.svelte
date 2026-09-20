<script lang="ts">
  import { quiz } from "../lib/state/quiz.svelte";
  import { UNITS } from "../lib/domain/labels";
  import {
    CONTRACT,
    OUTCOMES,
    STEPS,
    STEP_STATE,
    caseClass,
    caseInputs,
    caseNumbers,
    estimatedWait,
    firstError,
    restrictToScope,
    showsContract,
    type Scope,
    type StepState,
  } from "../lib/domain/verdict";
  import type { Verdict } from "../lib/api/types";
  import type { Phase } from "../lib/state/submission.svelte";

  interface Props {
    phase: Phase;
    exercise: string;
    /** Shown only when the page holds more than one exercise. */
    title?: string;
  }

  const { phase, exercise, title = "" }: Props = $props();

  const shown = $derived.by((): { r: Verdict; scope: Scope | null } | null => {
    if (phase.kind !== "done") return null;
    const scope = phase.scope;
    const r =
      scope && phase.verdict.kind === "quiz"
        ? restrictToScope(phase.verdict, scope)
        : phase.verdict;
    return { r, scope };
  });

  const failed = $derived(shown ? shown.r.status !== "ok" : false);
  const outcome = $derived(shown && failed ? (OUTCOMES[shown.r.status] ?? OUTCOMES.error!) : null);
  const complete = $derived(!!shown && !failed && shown.r.passed === shown.r.total);

  const passed = $derived(shown?.r.passed ?? 0);
  const total = $derived(shown?.r.total ?? 0);
  const failedNames = $derived(shown?.r.failed ?? []);
  const gcc = $derived(shown?.r.gcc ?? "");

  const headline = $derived.by(() => {
    if (phase.kind === "sending") return "Envoi…";
    if (phase.kind === "running") return "Test en cours…";
    if (phase.kind === "queued") {
      return (
        `En file d'attente — ${phase.position}${phase.position === 1 ? "er" : "e"}` +
        estimatedWait(phase.eta)
      );
    }
    if (!shown) return "";
    if (failed) return outcome!.title;
    return `${passed} / ${total} ${UNITS[shown.r.kind] ?? "réussis"}`;
  });

  const cls = $derived.by(() => {
    if (phase.kind === "sending" || phase.kind === "queued" || phase.kind === "running") {
      return "wait";
    }
    if (phase.kind === "done") return failed || !complete ? "bad" : "ok";
    return "idle";
  });

  const steps = $derived.by((): StepState[] | null => {
    if (phase.kind !== "done") return null;
    if (failed) return outcome!.steps;
    return ["ok", "ok"];
  });
</script>

<div class="verdictcard">
  {#if title}
    <div class="verdicttitle">{title}</div>
  {/if}

  {#if steps}
    <div class="steps">
      {#each steps as state, i}
        {@const [name, gender] = STEPS[i]!}
        <span class={"step " + (state || "empty")}>
          <b>{name}</b><i>{STEP_STATE[gender][state]}</i>
        </span>
      {/each}
    </div>
  {/if}

  <div class={"verdict " + cls + (phase.kind === "done" && !failed ? " count" : "")}>
    {headline}
  </div>

  {#if cls === "wait"}
    <div class="bar"><i></i></div>
  {/if}

  {#if shown && !failed && total > 0}
    <div class="ticks">
      {#each { length: total } as _, n}
        <i class={n < passed ? "on" : ""} style={"--i:" + Math.min(n, 12)}></i>
      {/each}
    </div>
  {/if}

  {#if shown?.r.message && shown.r.message !== headline}
    <p class="explain">{shown.r.message}</p>
  {/if}

  {#if shown && shown.r.status === "compile_error"}
    <div class="gcc">
      {#if firstError(shown.r.gcc)}
        <pre>{firstError(shown.r.gcc)}</pre>
        <details class="case">
          <summary>Voir toute la sortie du compilateur</summary>
          <pre>{gcc}</pre>
        </details>
      {:else}
        <pre>{gcc}</pre>
      {/if}
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "io"}
    <div>
      {#each shown.r.cases ?? [] as c, i}
        {@const kind = caseClass(c.reason)}
        {@const inputs = caseInputs(c.stdin)}
        {@const numbers = caseNumbers(c)}
        <details class="case" open={i === 0}>
          <summary>Cas {c.case} — {kind}</summary>
          <div class="body">
            <div class="case-field">
              <span class="what"
                >{inputs.length === 1
                  ? "Ton programme reçoit :"
                  : "Ton programme reçoit, dans cet ordre :"}</span
              >
              <pre class="value">{inputs.length
                  ? inputs.join("   puis   ")
                  : "rien — ce cas ne lui fournit aucune entrée"}</pre>
            </div>
            <div class="case-field">
              <span class="what">Ce qu'il a affiché :</span>
              <pre class="value">{c.stdout || "(rien)"}</pre>
            </div>
            {#if numbers}
              <div class="case-field">
                <span class="what">Les nombres que le juge y a lus :</span>
                <pre class="value">{numbers.length ? numbers.join(", ") : "aucun"}</pre>
              </div>
            {/if}
            {#if c.stderr}
              <div class="case-field">
                <span class="what">Sa sortie d'erreur :</span>
                <pre class="value">{c.stderr}</pre>
              </div>
            {/if}
            <p class="why">{c.reason}</p>
            {#if showsContract(c)}
              <p class="contract">{CONTRACT}</p>
            {/if}
          </div>
        </details>
      {/each}
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "unity" && failedNames.length}
    <div class="failures">
      <p class="what">
        {failedNames.length === 1
          ? "Cette vérification a échoué. Son nom décrit le cas qu'elle teste :"
          : "Ces vérifications ont échoué. Leur nom décrit le cas qu'elles testent :"}
      </p>
      <ul>
        {#each failedNames as name (name)}<li>{name}</li>{/each}
      </ul>
      <p class="contract">
        Les valeurs attendues ne sont pas montrées : les trouver EST l'exercice.
      </p>
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "quiz"}
    <ul>
      {#each shown.r.wrong ?? [] as w}
        {@const group = quiz.groupOf(exercise, w.id)}
        {@const ex = group.match(/Exercice\s*\d+/i)}
        {@const empty = !(w.given && w.given.trim())}
        <li class={empty ? "nothing" : ""}>
          {(ex ? ex[0] + " — " : "") +
            w.label +
            (empty ? "" : ` (tu as répondu « ${w.given} »)`) +
            (w.hint ? " — " + w.hint : "")}
        </li>
      {/each}
    </ul>
  {/if}

  {#if shown?.r.warnings}
    <div class="warn">
      <div class="title">Avertissements du compilateur</div>
      <div class="what">
        Ce n'est pas une erreur : ton programme compile. Mais gcc a remarqué ceci, et ça
        vaut le coup d'œil.
      </div>
      <pre>{shown.r.warnings}</pre>
    </div>
  {/if}
</div>
