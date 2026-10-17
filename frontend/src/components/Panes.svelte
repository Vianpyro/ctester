<script lang="ts">
  import { onMount } from "svelte";
  import { t } from "../lib/i18n.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { view } from "../lib/state/view.svelte";
  import { showPane } from "../lib/panes";

  // The pane on screen, read from #work's own scroll: a swipe and a tap agree.
  let at = $state(0);
  onMount(() => {
    const work = document.getElementById("work")!;
    const follow = () => (at = Math.round(work.scrollLeft / (work.clientWidth || 1)));
    work.addEventListener("scroll", follow, { passive: true });
    return () => work.removeEventListener("scroll", follow);
  });

  // A test sets off: its result is where the student looks next.
  $effect(() => {
    if (submission.phase.kind === "sending") showPane(2);
  });

  // Another exercise opens on its statement.
  $effect(() => {
    void catalog.selectedId;
    showPane(0);
  });
</script>

<nav id="panes" aria-label={t("panes.label")} hidden={view.current !== ""}>
  {#each ["statement", "code", "result"] as pane, i (pane)}
    <button type="button" id={"to" + pane} aria-current={at === i || undefined} onclick={() => showPane(i)}
      >{[t("statement.title"), t("panes.code"), t("panes.result")][i]}</button
    >
  {/each}
</nav>
