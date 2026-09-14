<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { lockNote, stripLabel, tileState } from "../lib/domain/catalog";
  import { STATUS_MARK, plural } from "../lib/domain/labels";

  interface Props {
    openMenu: (focusSearch?: boolean) => void;
  }

  const { openMenu }: Props = $props();

  const neighbors = $derived(catalog.neighbors);
  const shown = $derived(neighbors.length >= 2);
  const solved = $derived(neighbors.filter((e) => statuses.of(e.id) === "solved").length);
</script>

<nav id="bandelabo" aria-label="Exercices de ce laboratoire, et accès au catalogue" hidden={!shown}>
  {#if shown}
    {#each neighbors as ex (ex.id)}
      {@const note = lockNote(ex)}
      {@const bloque = !!note && !catalog.staff}
      {@const state = tileState(ex, !!note, statuses.byExercise)}
      {@const current = ex.id === catalog.selectedId}
      {@const said =
        (note || state.word) +
        (ex.bonus ? ", bonus facultatif" : "") +
        (current ? ", ouvert dans l'éditeur" : "")}
      <button
        type="button"
        class={"tile " + state.cls + (ex.bonus ? " bonus" : "") + (current ? " courant" : "")}
        title={ex.short + " — " + said}
        aria-disabled={bloque ? "true" : undefined}
        aria-current={current ? "true" : undefined}
        onclick={() => {
          if (!bloque && !current) exercise.open(ex.id);
        }}
      >
        {stripLabel(ex)}
        <span class="horsecran"> — {said}</span>
        {#if statuses.of(ex.id)}
          <i class="marque">{STATUS_MARK[statuses.of(ex.id)!] ?? ""}</i>
        {/if}
        {#if ex.verification}<i class="quoi">vérif</i>{/if}
        {#if ex.bonus}<i class="quoi">bonus</i>{/if}
        {#if note}<span class="cadenas">🔒</span>{/if}
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
