<script lang="ts">  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { system } from "../lib/state/system.svelte";
  import { quiz } from "../lib/state/quiz.svelte";
  import { t } from "../lib/i18n.svelte";
  import {
    OUTCOMES,
    afterFailure,
    caseClass,
    caseInputs,
    caseNumbers,
    caseReason,
    estimatedWait,
    firstError,
    outcomeNext,
    outcomeTitle,
    quizHint,
    restrictToScope,
    showsContract,
    stepLabel,
    stepState,
    verdictCount,
    verdictExplain,
    type Scope,
    type StepState,
  } from "../lib/domain/verdict";
  import type { Verdict } from "../lib/api/types";

  let box: HTMLDivElement | undefined = $state();

  const phase = $derived(submission.phase);

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

  const headline = $derived.by(() => {
    if (phase.kind === "sending") return t("verdict.sending");
    if (phase.kind === "running") return t("verdict.running");
    if (phase.kind === "queued") {
      return (
        (phase.position === 1
          ? t("verdict.queued_first")
          : t("verdict.queued", { position: phase.position })) + estimatedWait(phase.eta)
      );
    }
    if (phase.kind === "idle" || phase.kind === "lost" || phase.kind === "cooldown") {
      return catalog.catalog.length ? t("verdict.idle") : t("verdict.nothing_open");
    }
    if (!shown) return "";
    if (failed) return outcomeTitle(shown.r.status);
    const frame = shown.scope && shown.r.kind === "quiz" ? " — " + shown.scope.title : "";
    return verdictCount(passed, total, shown.r.kind) + frame;
  });

  const explanation = $derived(shown ? verdictExplain(shown.r) : "");
  const passed = $derived(shown?.r.passed ?? 0);
  const total = $derived(shown?.r.total ?? 0);
  const failedNames = $derived(shown?.r.failed ?? []);
  const gcc = $derived(shown?.r.gcc ?? "");

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

  const nextAction = $derived.by(() => {
    if (phase.kind !== "done") return null;
    if (failed) return { text: outcomeNext(shown!.r.status), next: null };
    if (!complete) return { text: afterFailure(shown!.r.kind), next: null };
    const next = catalog.nextOpen();
    return next
      ? { text: t("verdict.move_on"), next }
      : { text: t("verdict.last_open"), next: null };
  });

  const offersHelp = $derived(cls === "bad" && session.signedIn && session.forumOffered);

  async function openDiscussions() {
    const { chat } = await import("../features/forum/chat.svelte");
    await chat.toggleWide();
  }

  let lastSeen = $state<unknown>(null);
  $effect(() => {
    if (phase.kind !== "done" || phase === lastSeen) return;
    lastSeen = phase;
    // 700px, matching app.css: from there up the verdict is pinned in view already, so
    // only the stacked phone layout needs scrolling to it.
    const narrow =
      typeof matchMedia === "function" && matchMedia("(max-width: 700px)").matches;
    if (!narrow || !box) return;
    box.scrollIntoView?.({ block: "start", behavior: "smooth" });
    box.focus?.();
  });

  $effect(() => {
    if (headline) system.announce(headline);
  });

  const quizGroup = (id: string): string => quiz.groupOf[id] ?? "";

</script>

<div bind:this={box} id="out" class={cls} tabindex="-1">
  {#if steps}
    <div class="steps">
      {#each steps as state, i}
        <span class={"step " + (state || "empty")}>
          <b>{stepLabel(i)}</b><i>{stepState(i, state)}</i>
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

  {#if phase.kind === "idle" || phase.kind === "lost" || phase.kind === "cooldown"}
    <p class="explain">
      <!-- Also the text shown before /catalog.json answers: swapping it afterwards
           reflows the panel and pushes the editor up. -->
      {!catalog.loaded || catalog.catalog.length
        ? t("verdict.idle_help")
        : t("verdict.opening_dates")}
    </p>
  {:else if explanation && explanation !== headline}
    <p class="explain">{explanation}</p>
  {/if}

  {#if shown && shown.r.status === "compile_error"}
    <div class="gcc">
      {#if firstError(shown.r.gcc)}
        <pre>{firstError(shown.r.gcc)}</pre>
        <details class="case">
          <summary>{t("verdict.full_compiler_output")}</summary>
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
          <summary>{t("verdict.case", { n: c.case, kind: t(`verdict.case.${kind}`) })}</summary>
          <div class="body">
            <div class="case-field">
              <span class="what"
                >{t("verdict.receives", { count: inputs.length })}</span
              >
              <pre class="value">{inputs.length
                  ? inputs.join(t("verdict.then"))
                  : t("verdict.no_input")}</pre>
            </div>
            <div class="case-field">
              <span class="what">{t("verdict.printed")}</span>
              <pre class="value">{c.stdout || t("verdict.nothing")}</pre>
            </div>
            {#if numbers}
              <div class="case-field">
                <span class="what">{t("verdict.numbers_read")}</span>
                <pre class="value">{numbers.length ? numbers.join(", ") : t("verdict.no_numbers")}</pre>
              </div>
            {/if}
            {#if c.stderr}
              <div class="case-field">
                <span class="what">{t("verdict.stderr")}</span>
                <pre class="value">{c.stderr}</pre>
              </div>
            {/if}
            <p class="why">{caseReason(c)}</p>
            {#if showsContract(c)}
              <p class="contract">{t("verdict.contract")}</p>
            {/if}
          </div>
        </details>
      {/each}
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "unity" && failedNames.length}
    <div class="failures">
      <p class="what">
        {t("verdict.failed_checks", { count: failedNames.length })}
      </p>
      <ul>
        {#each failedNames as name (name)}<li>{name}</li>{/each}
      </ul>
      <p class="contract">{t("verdict.hidden_values")}</p>
    </div>
  {/if}

  {#if shown && !failed && !complete && shown.r.kind === "quiz"}
    <ul>
      {#each shown.r.wrong ?? [] as w}
        {@const group = quizGroup(w.id)}
        {@const ex = group.match(/Exercice\s*\d+/i)}
        {@const empty = !(w.given && w.given.trim())}
        <li class={empty ? "nothing" : ""}>
          {(ex ? ex[0] + " — " : "") +
            w.label +
            (empty ? "" : t("verdict.you_answered", { given: w.given ?? "" })) +
            (w.hint ? " — " + quizHint(w.hint) : "")}
        </li>
      {/each}
    </ul>
  {/if}

  {#if nextAction}
    <div class="suite">
      <span>{nextAction.text}</span>
      {#if nextAction.next}
        <button type="button" class="nav" onclick={() => exercise.open(nextAction.next!.id)}>
          {t("verdict.open_next", { name: nextAction.next.short })}
        </button>
      {/if}
      {#if offersHelp}
        <button type="button" class="nav help" onclick={openDiscussions}>
          {t("verdict.discuss")}
        </button>
      {/if}
    </div>
  {/if}

  {#if shown?.r.warnings || shown?.r.long_source}
    <div class="warn">
      <div class="title">{t("verdict.warnings")}</div>
      <div class="what">{t("verdict.warnings_explain")}</div>
      <pre
        >{[
          shown.r.warnings ?? "",
          shown.r.long_source ? t("verdict.long_source", shown.r.long_source) : "",
        ]
          .filter(Boolean)
          .join("\n")}</pre
      >
    </div>
  {/if}
</div>
