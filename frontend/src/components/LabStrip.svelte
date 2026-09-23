<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { lockNote, stripLabel, tileState } from "../lib/domain/catalog";
  import { STATUS_MARK } from "../lib/domain/labels";
  import { t } from "../lib/i18n.svelte";

  interface Props {
    openMenu: (focusSearch?: boolean) => void;
  }

  const { openMenu }: Props = $props();

  const neighbors = $derived(catalog.neighbors);
  const shown = $derived(neighbors.length >= 2);
  const solved = $derived(neighbors.filter((e) => statuses.of(e.id) === "solved").length);
</script>

<nav id="labband" aria-label={t("lab.label")} hidden={!shown}>
  {#if shown}
    {#each neighbors as ex (ex.id)}
      {@const note = lockNote(ex)}
      {@const locked = !!note && !catalog.staff}
      {@const state = tileState(ex, !!note, statuses.byExercise)}
      {@const current = ex.id === catalog.selectedId}
      {@const said =
        (note || state.word) +
        (ex.bonus ? t("lab.bonus") : "") +
        (current ? t("lab.current") : "")}
      <button
        type="button"
        class={"tile " + state.cls + (ex.bonus ? " bonus" : "") + (current ? " current" : "")}
        title={ex.short + " — " + said}
        aria-disabled={locked ? "true" : undefined}
        aria-current={current ? "true" : undefined}
        onclick={() => {
          if (!locked && !current) exercise.open(ex.id);
        }}
      >
        {stripLabel(ex)}
        <span class="offscreen"> — {said}</span>
        {#if statuses.of(ex.id)}
          <i class="mark">{STATUS_MARK[statuses.of(ex.id)!] ?? ""}</i>
        {/if}
        {#if ex.verification}<i class="what">{t("catalog.verification_short")}</i>{/if}
        {#if ex.bonus}<i class="what">{t("lab.bonus_tag")}</i>{/if}
        {#if note}<span class="padlock">🔒</span>{/if}
      </button>
    {/each}

    <span class="grow"></span>
    <span class="tag">{t("lab.exercises", { count: neighbors.length })}</span>
    <span class={"tag" + (solved ? " accent" : "")}>
      {t("lab.solved", { count: solved })}
    </span>
    <button type="button" class="nav" onclick={() => openMenu(true)}>
      {t("lab.all")}<span class="shortcut">Ctrl+K</span>
    </button>
  {/if}
</nav>
