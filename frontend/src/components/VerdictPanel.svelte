<script lang="ts">
  import type { Component } from "svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { system } from "../lib/state/system.svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { runTest } from "../lib/state/run";
  import { t } from "../lib/i18n.svelte";
  import {
    OUTCOMES,
    afterFailure,
    estimatedWait,
    firstError,
    outcomeNext,
    outcomeTitle,
    restrictToScope,
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
  const note = $derived(submission.note);

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
  const waiting = $derived(
    phase.kind === "sending" || phase.kind === "queued" || phase.kind === "running",
  );

  // Six states, each with its own colour and its own shape: a fault is the service failing,
  // never a judgment on the code, and a partial pass is progress, not a red screen.
  const cls = $derived.by(() => {
    if (waiting) return "wait";
    if (phase.kind === "done") return failed ? "bad" : complete ? "ok" : "partial";
    if (phase.kind === "lost" || phase.kind === "cooldown" || note?.kind === "fault") return "fault";
    return "idle";
  });

  const passed = $derived(shown?.r.passed ?? 0);
  const total = $derived(shown?.r.total ?? 0);

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
    if (cls === "fault") return note?.text ?? t("verdict.idle");
    if (cls === "idle") return catalog.catalog.length ? t("verdict.idle") : t("verdict.nothing_open");
    if (!shown) return "";
    if (failed) return outcomeTitle(shown.r.status);
    const frame = shown.scope && shown.r.kind === "quiz" ? " — " + shown.scope.title : "";
    return verdictCount(passed, total, shown.r.kind) + frame;
  });

  const explanation = $derived(shown ? verdictExplain(shown.r) : "");
  const gcc = $derived(shown?.r.gcc ?? "");

  // A quiz is neither compiled nor run: the judge's line belongs to code exercises.
  const quizMode = $derived(catalog.selected?.mode === "quiz");

  // While the judge works, the line is drawn empty and an ink pulse runs along it.
  const steps = $derived.by((): StepState[] | null => {
    if (quizMode) return null;
    if (waiting) return ["", "", ""];
    if (phase.kind !== "done") return null;
    if (failed) return outcome!.steps;
    return complete ? ["ok", "ok", "ok"] : ["ok", "ok", "ko"];
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

  const offersHelp = $derived(
    (cls === "bad" || cls === "partial") && session.signedIn && session.forumOffered,
  );

  async function openDiscussions() {
    const { chat } = await import("../features/forum/chat.svelte");
    await chat.toggleWide();
  }

  let lastSeen = $state<unknown>(null);
  $effect(() => {
    if (phase.kind !== "done" || phase === lastSeen) return;
    lastSeen = phase;
    // A recalled verdict comes with the exercise; the page stays where the student put it.
    if (phase.recalled) return;
    // 700px, matching app.css: from there up the verdict is pinned in view already, so
    // only the stacked phone layout needs scrolling to it.
    const narrow =
      typeof matchMedia === "function" && matchMedia("(max-width: 700px)").matches;
    if (!narrow || !box) return;
    box.scrollIntoView?.({ block: "start", behavior: "smooth" });
    box.focus?.();
  });

  // One string, so a verdict and the note that comes with it are never cut off by each other.
  $effect(() => {
    const extra = note && cls !== "fault" ? " " + note.text : "";
    if (headline) system.announce(headline + extra);
  });

  // Never a gate: gcc stays the judge, and a heuristic can be wrong.
  const lintFirst = $derived(
    (cls === "wait" || cls === "bad" || cls === "partial") && editor.issues.length
      ? editor.issues[0]!
      : null,
  );

  function showLint() {
    const zone = editor.element;
    if (!zone || !lintFirst) return;
    zone.focus();
    zone.setSelectionRange(lintFirst.from, lintFirst.to);
  }

  // Only a failed compile needs gcc's help, so it stays out of the eager bundle.
  let GccHelp = $state<Component<{ output: string }> | null>(null);
  $effect(() => {
    if (shown?.r.status !== "compile_error" || GccHelp) return;
    // A failed load leaves the raw gcc error, which is still enough to fix it.
    import("./GccHelp.svelte").then((mod) => (GccHelp = mod.default), () => {});
  });

  // The cases, checks and wrong answers wait in their own chunk, fetched as soon as a test
  // leaves: it is there before the verdict is, and the anonymous page never pays for it.
  let Details = $state<Component<{ r: Verdict; complete: boolean }> | null>(null);
  $effect(() => {
    if (phase.kind === "idle" || Details) return;
    import("./VerdictDetails.svelte").then((mod) => (Details = mod.default), () => {});
  });
</script>

<div bind:this={box} id="out" class={cls} tabindex="-1">
  {#if lintFirst}
    <p class="lintnote">
      <span>{t("verdict.lint_before", { count: editor.issues.length })}</span>
      <button type="button" class="nav" onclick={showLint}>
        {t("verdict.lint_show", { n: editor.text.slice(0, lintFirst.from).split("\n").length })}
      </button>
    </p>
  {/if}

  {#if cls === "idle" && !quizMode}
    <ol class="howto" aria-label={t("verdict.howto")}>
      {#each [0, 1, 2] as i (i)}<li style={"--i:" + i}>{stepLabel(i)}</li>{/each}
    </ol>
  {:else if steps}
    <ol class="steps" aria-hidden={cls === "wait" ? "true" : undefined}>
      {#each steps as state, i (i)}
        <li class={"step " + (state || "empty")} style={"--i:" + i}>
          <b>{stepLabel(i)}</b>
          {#if cls !== "wait"}<i>{stepState(i, state)}</i>{/if}
        </li>
      {/each}
    </ol>
  {/if}

  <div class={"verdict " + cls + (phase.kind === "done" && !failed ? " count" : "")}>
    {headline}
  </div>

  {#if cls === "wait"}
    <div class="bar"><i></i></div>
  {/if}

  {#if note && cls !== "fault"}
    <p class="note">{note.text}</p>
  {/if}

  {#if shown && !failed && total > 0}
    <div class="ticks">
      {#each { length: total } as _, n}
        <i class={n < passed ? "on" : "off"} style={"--i:" + Math.min(n, 12)}></i>
      {/each}
    </div>
  {/if}

  {#if cls === "idle"}
    <p class="explain">
      <!-- Also the text shown before /catalog.json answers: swapping it afterwards
           reflows the panel and pushes the editor up. -->
      {!catalog.loaded || catalog.catalog.length
        ? t("verdict.idle_help")
        : t("verdict.opening_dates")}
    </p>
  {:else if cls === "fault" && phase.kind !== "cooldown"}
    <div class="suite">
      <button type="button" class="nav retry" onclick={() => runTest(catalog.selected?.mode === "quiz")}>
        {t("verdict.retry")}
      </button>
    </div>
  {:else if explanation && explanation !== headline}
    <p class="explain">{explanation}</p>
  {/if}

  {#if shown && shown.r.status === "compile_error"}
    <div class="gcc">
      {#if firstError(shown.r.gcc)}
        <pre>{firstError(shown.r.gcc)}</pre>
        {#if GccHelp}<GccHelp output={gcc} />{/if}
        <details class="case">
          <summary>{t("verdict.full_compiler_output")}</summary>
          <pre>{gcc}</pre>
        </details>
      {:else}
        <pre>{gcc}</pre>
      {/if}
    </div>
  {/if}

  {#if shown && Details}
    <Details r={shown.r} {complete} />
  {/if}

  {#if nextAction}
    <div class="suite">
      <span>{nextAction.text}</span>
      {#if nextAction.next}
        <button type="button" class="nav next" onclick={() => exercise.open(nextAction.next!.id)}>
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
</div>
