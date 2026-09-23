<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { lockNote, matchesFilter } from "../lib/domain/catalog";
  import { STATUS_CLASS, STATUS_MARK, statusWord } from "../lib/domain/labels";
  import { t } from "../lib/i18n.svelte";

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
    <span class="what">{t("menu.exercise")}</span>
    <span class="title">{catalog.selected?.short ?? t("menu.to_pick")}</span>
  </summary>
  <div class="menupanel">
    <label class="offscreen" for="search">{t("menu.filter_label")}</label>
    <input
      bind:this={field}
      bind:value={typed}
      type="search"
      id="search"
      autocomplete="off"
      placeholder={t("menu.filter_placeholder")}
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
                {#if ex.verification}<span class="verification">{t("catalog.verification")}</span>{/if}
                {#if done}
                  <span class={"state " + (STATUS_CLASS[done] ?? done)}>
                    {(STATUS_MARK[done] ?? "") + " " + statusWord(done)}
                  </span>
                {/if}
                {#if note}<span class="padlock">🔒 {note}</span>{/if}
              </button>
            {/each}
          </details>
        {/if}
      {/each}
      {#if catalog.filter && !shown}
        <p class="help">{t("menu.no_match", { text: typed })}</p>
      {/if}
    </div>
  </div>
</details>
