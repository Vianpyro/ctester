<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { quiz } from "../lib/state/quiz.svelte";
  import { lockNote, stripLabel, tileState } from "../lib/domain/catalog";
  import { STATUS_MARK, plural } from "../lib/domain/labels";

  interface Props {
    openMenu: (focusSearch?: boolean) => void;
  }

  const { openMenu }: Props = $props();

  const neighbors = $derived(catalog.neighbors);
  const shown = $derived(neighbors.length >= 2);
  const solved = $derived(neighbors.filter((e) => statuses.of(e.id) === "solved").length);
  // A page can hold several exercises, so the strip marks all of them, not just the one
  // the header names.
  const onPage = $derived(new Set(quiz.shown.map((one) => one.exerciseId)));
</script>

<nav id="labband" aria-label="Exercices de ce laboratoire, et accès au catalogue" hidden={!shown}>
  {#if shown}
    {#each neighbors as ex (ex.id)}
      {@const note = lockNote(ex)}
      {@const locked = !!note && !catalog.staff}
      {@const state = tileState(ex, !!note, statuses.byExercise)}
      {@const current = ex.id === catalog.selectedId}
      {@const here = current || onPage.has(ex.id)}
      {@const said =
        (note || state.word) +
        (ex.bonus ? ", bonus facultatif" : "") +
        (here ? ", affiché sur cette page" : "")}
      <button
        type="button"
        class={"tile " + state.cls + (ex.bonus ? " bonus" : "") + (here ? " current" : "")}
        title={ex.short + " — " + said}
        aria-disabled={locked ? "true" : undefined}
        aria-current={here ? "true" : undefined}
        onclick={() => {
          if (!locked && !current) exercise.open(ex.id);
        }}
      >
        {stripLabel(ex)}
        <span class="offscreen"> — {said}</span>
        {#if statuses.of(ex.id)}
          <i class="mark">{STATUS_MARK[statuses.of(ex.id)!] ?? ""}</i>
        {/if}
        {#if ex.verification}<i class="what">vérif</i>{/if}
        {#if ex.bonus}<i class="what">bonus</i>{/if}
        {#if note}<span class="padlock">🔒</span>{/if}
      </button>
    {/each}

    <span class="grow"></span>
    <span class="tag">{plural(neighbors.length, "exercice")}</span>
    <span class={"tag" + (solved ? " accent" : "")}>
      {solved} réussi{solved > 1 ? "s" : ""}
    </span>
    <button type="button" class="nav" onclick={() => openMenu(true)}>
      Tous les exercices<span class="shortcut">Ctrl+K</span>
    </button>
  {/if}
</nav>
