<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { lockNote, matchesFilter } from "../lib/domain/catalog";
  import { STATUS_CLASS, STATUS_MARK, STATUS_WORD } from "../lib/domain/labels";

  interface Props {
    open: boolean;
    focusSearch: boolean;
    onOpenChange: (open: boolean) => void;
  }

  let { open, focusSearch, onOpenChange }: Props = $props();

  let field: HTMLInputElement | undefined = $state();
  let typed = $state("");

  $effect(() => {
    if (open && focusSearch) field?.focus();
  });

  const rows = $derived(
    catalog.collections.map((col) => ({
      col,
      items: col.items.filter((ex) => matchesFilter(ex, col.title, catalog.filter)),
    })),
  );
  const shown = $derived(rows.reduce((n, r) => n + r.items.length, 0));
</script>

<details class="menu" id="menuex" {open} ontoggle={(e) => onOpenChange((e.currentTarget as HTMLDetailsElement).open)}>
  <summary class="nav" id="excurrent">
    <span class="what">Exercice</span>
    <span class="title">{catalog.selected?.short ?? "à choisir"}</span>
  </summary>
  <div class="menupanel">
    <label class="offscreen" for="search">Filtrer les exercices</label>
    <input
      bind:this={field}
      bind:value={typed}
      type="search"
      id="search"
      autocomplete="off"
      placeholder="Filtrer… (Ctrl+K)"
      oninput={() => catalog.setFilter(typed)}
    />
    <div id="exlist">
      {#each rows as { col, items } (col.title)}
        {#if items.length}
          <details
            class="col"
            open={!!catalog.filter ||
              col.items.some(
                (ex) => ex.id === catalog.selectedId || ex.id === catalog.spotlighted,
              )}
          >
            <summary>
              <span>{col.title}</span>
              {#if lockNote(col)}<span class="padlock">🔒 {lockNote(col)}</span>{/if}
            </summary>
            {#each items as ex (ex.id)}
              {@const note = lockNote(ex)}
              {@const locked = !!note && !catalog.staff}
              {@const done = statuses.of(ex.id)}
              <button
                type="button"
                class={"exline" + (ex.id === catalog.selectedId ? " on" : "") + (locked ? " locked" : "")}
                data-id={ex.id}
                aria-disabled={locked ? "true" : undefined}
                onclick={() => {
                  if (locked) return;
                  onOpenChange(false);
                  exercise.open(ex.id);
                }}
              >
                <span class="title">{ex.short}</span>
                {#if ex.verification}<span class="verification">vérification</span>{/if}
                {#if done}
                  <span class={"state " + (STATUS_CLASS[done] ?? done)}>
                    {(STATUS_MARK[done] ?? "") + " " + (STATUS_WORD[done] ?? done)}
                  </span>
                {/if}
                {#if note}<span class="padlock">🔒 {note}</span>{/if}
              </button>
            {/each}
          </details>
        {/if}
      {/each}
      {#if catalog.filter && !shown}
        <p class="help">Aucun exercice ne correspond à « {typed} ».</p>
      {/if}
    </div>
  </div>
</details>
