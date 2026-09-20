<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { submission, type Phase } from "../lib/state/submission.svelte";
  import { system } from "../lib/state/system.svelte";
  import { AFTER_FAILURE, OUTCOMES } from "../lib/domain/verdict";
  import { legLine } from "../lib/domain/summary";
  import type { Component } from "svelte";

  let box: HTMLDivElement | undefined = $state();

  // A student who has not submitted anything never needs the card's markup, and the
  // anonymous bundle is budgeted. Fetched right after the first paint, well before any
  // verdict can land.
  type Card = Component<{ phase: Phase; exercise: string; title?: string }>;
  let VerdictCard = $state<Card | null>(null);
  $effect(() => {
    const soon = setTimeout(() => {
      void import("./VerdictCard.svelte").then((m) => (VerdictCard = m.default as Card));
    }, 0);
    return () => clearTimeout(soon);
  });

  const legs = $derived(submission.legs);
  /** Several exercises share a page, so each card says which one it speaks for. */
  const named = $derived(legs.length > 1);

  const waiting = $derived(
    legs.some((one) => ["sending", "queued", "running"].includes(one.phase.kind)),
  );
  const resting = $derived(
    !legs.length || legs.every((one) => ["idle", "lost", "cooldown"].includes(one.phase.kind)),
  );
  const done = $derived(legs.filter((one) => one.phase.kind === "done"));
  const allDone = $derived(!!legs.length && done.length === legs.length);

  const bad = $derived(
    done.some((one) => {
      if (one.phase.kind !== "done") return false;
      const r = one.phase.verdict;
      return r.status !== "ok" || r.passed !== r.total;
    }),
  );

  // The box carries the worst outcome on the page: one exercise still wrong is not a win.
  const cls = $derived(waiting ? "wait" : resting ? "idle" : bad ? "bad" : "ok");

  const nextAction = $derived.by(() => {
    if (!allDone) return null;
    const first = done.find((one) => one.phase.kind === "done" && one.phase.verdict.status !== "ok");
    if (first && first.phase.kind === "done") {
      return { text: (OUTCOMES[first.phase.verdict.status] ?? OUTCOMES.error!).suite, next: null };
    }
    if (bad) {
      const kind = done[0]?.phase.kind === "done" ? done[0].phase.verdict.kind : "quiz";
      return { text: AFTER_FAILURE[kind] ?? "", next: null };
    }
    const next = catalog.nextOpen();
    return next
      ? { text: "Tu peux passer à la suite.", next }
      : { text: "C'est le dernier exercice ouvert pour l'instant.", next: null };
  });

  const offersHelp = $derived(cls === "bad" && session.signedIn && session.forumOffered);

  async function openDiscussions() {
    const { chat } = await import("../features/forum/chat.svelte");
    await chat.toggleWide();
  }

  // One aria-live region for the page: the cards must not talk over each other.
  const announcement = $derived.by(() => {
    if (waiting) return "Test en cours…";
    if (!done.length) return "";
    return done
      .map((one) =>
        one.phase.kind === "done"
          ? legLine(named ? one.title : "", one.phase.verdict, one.phase.scope)
          : "",
      )
      .filter(Boolean)
      .join(" · ");
  });

  let lastSeen = $state<unknown>(null);
  $effect(() => {
    if (!allDone || legs === lastSeen) return;
    lastSeen = legs;
    // 700px, matching app.css: from there up the verdict is pinned in view already, so
    // only the stacked phone layout needs scrolling to it.
    const narrow =
      typeof matchMedia === "function" && matchMedia("(max-width: 700px)").matches;
    if (!narrow || !box) return;
    box.scrollIntoView?.({ block: "start", behavior: "smooth" });
    box.focus?.();
  });

  $effect(() => {
    if (announcement) system.announce(announcement);
  });

  const idleHelp =
    "Écris ton code, puis clique sur « Tester ». Les résultats ne sont pas une " +
    "note : ces tests t'aident à trouver tes erreurs, ils ne remplacent pas la " +
    "correction.";
</script>

<div bind:this={box} id="out" class={cls} tabindex="-1">
  {#if !legs.length}
    <div class="verdict idle">
      {catalog.catalog.length
        ? "En attente d'une soumission."
        : "Aucun exercice n'est encore ouvert."}
    </div>
    <p class="explain">
      <!-- Also the text shown before /catalog.json answers: swapping it afterwards
           reflows the panel and pushes the editor up. -->
      {!catalog.loaded || catalog.catalog.length
        ? idleHelp
        : "Le menu « Exercices » donne la date d'ouverture de chacun."}
    </p>
  {:else}
    {#each legs as leg (leg.exercise)}
      {#if VerdictCard}
        <VerdictCard phase={leg.phase} exercise={leg.exercise} title={named ? leg.title : ""} />
      {/if}
    {/each}
    {#if legs.some((one) => one.phase.kind === "cooldown")}
      <p class="explain">{idleHelp}</p>
    {/if}
  {/if}

  {#if nextAction}
    <div class="suite">
      <span>{nextAction.text}</span>
      {#if nextAction.next}
        <button type="button" class="nav" onclick={() => exercise.open(nextAction.next!.id)}>
          Ouvrir « {nextAction.next.short} »
        </button>
      {/if}
      {#if offersHelp}
        <button type="button" class="nav help" onclick={openDiscussions}>
          En parler dans les discussions
        </button>
      {/if}
    </div>
  {/if}
</div>
