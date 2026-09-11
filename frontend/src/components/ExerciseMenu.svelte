<script lang="ts">
  // THE CATALOG MENU: one `<details>` per collection inside the bar's `<details>`.
  // The browser knows how to collapse, so there is no accordion in script and no
  // open/closed state to track elsewhere.
  //
  // THE MENU CARRIES EVERY EXERCISE, open or not; `catalog.catalog` carries only the
  // open ones. A locked exercise is in the menu, announced as unavailable, with its
  // padlock and its date -- making it disappear looked like an outage the night
  // before class. But it must not count in a progression nor in a hand-in main.c, and
  // keeping the two lists apart is what avoids adding the same filter in three
  // screens.
  //
  // COLLAPSED EXCEPT THE ONE BEING WORKED ON: with eleven collections and
  // seventy-three exercises, unfolding all of them is the same as not organizing
  // anything. FILTERING OPENS EVERYTHING IT KEPT -- a match hidden inside a collapsed
  // collection is a search that answers "nothing found" having found something.

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
      items: col.items.filter((ex) => matchesFilter(ex, col.titre, catalog.filter)),
    })),
  );
  const shown = $derived(rows.reduce((n, r) => n + r.items.length, 0));
</script>

<details class="menu" id="menuex" {open} ontoggle={(e) => onOpenChange((e.currentTarget as HTMLDetailsElement).open)}>
  <summary class="nav" id="excourant">{catalog.selected?.short ?? "Exercices"}</summary>
  <div class="menupanneau">
    <!-- THE SEARCH FIELD IS PART OF THE MENU, not a separate palette. The menu is
         already the list of everything; a palette would be a second list of the same
         thing, with its own overlay to dismiss. Ctrl/⌘+K opens this one and lands
         here. -->
    <label class="horsecran" for="search">Filtrer les exercices</label>
    <input
      bind:this={field}
      bind:value={typed}
      type="search"
      id="search"
      autocomplete="off"
      placeholder="Filtrer… (Ctrl+K)"
      oninput={() => catalog.setFilter(typed)}
    />
    <div id="exliste">
      {#each rows as { col, items } (col.titre)}
        <!-- A COLLECTION WITH NO MATCH DISAPPEARS while filtering and comes back when
             the field is emptied: an empty `<details>` one can open onto nothing is
             worse than no row at all. -->
        {#if items.length}
          <details
            class="col"
            open={!!catalog.filter ||
              col.items.some(
                (ex) => ex.id === catalog.selectedId || ex.id === catalog.spotlighted,
              )}
          >
            <summary>
              <span>{col.titre}</span>
              {#if lockNote(col)}<span class="cadenas">🔒 {lockNote(col)}</span>{/if}
            </summary>
            {#each items as ex (ex.id)}
              {@const note = lockNote(ex)}
              <!-- THE LOCK IS SHOWN TO EVERYONE, IT ONLY BLOCKS STUDENTS. Dates are
                   for students: a moderator opens the row to check that the exercise
                   renders and grades as intended, and still reads the date telling
                   them the class cannot. `catalog.staff` is said by the server. -->
              {@const bloque = !!note && !catalog.staff}
              {@const done = statuses.of(ex.id)}
              <!-- `aria-disabled` AND NOT `disabled`. A `disabled` button drops out of
                   the tab order: opening dates used to exist for the mouse only, when
                   they are the whole reason to keep the exercise displayed. -->
              <button
                type="button"
                class={"exline" + (ex.id === catalog.selectedId ? " on" : "") + (bloque ? " verrouille" : "")}
                data-id={ex.id}
                aria-disabled={bloque ? "true" : undefined}
                onclick={() => {
                  if (bloque) return;
                  onOpenChange(false);
                  exercise.open(ex.id);
                }}
              >
                <span class="titre">{ex.short}</span>
                <!-- MARKED, AND SPELLED OUT. A verification must be recognizable
                     BEFORE it is opened -- that is what tells it apart from a practice
                     exercise -- and colour alone would not say so. -->
                {#if ex.verification}<span class="verif">vérification</span>{/if}
                {#if done}
                  <span class={"etat " + (STATUS_CLASS[done] ?? done)}>
                    {(STATUS_MARK[done] ?? "") + " " + (STATUS_WORD[done] ?? done)}
                  </span>
                {/if}
                {#if note}<span class="cadenas">🔒 {note}</span>{/if}
              </button>
            {/each}
          </details>
        {/if}
      {/each}
      <!-- "NOTHING MATCHES" IS SAID, not left as an empty panel: an empty menu reads
           as a catalog that failed to load, which is a different problem with a
           different fix. -->
      {#if catalog.filter && !shown}
        <p class="aide">Aucun exercice ne correspond à « {typed} ».</p>
      {/if}
    </div>
  </div>
</details>
