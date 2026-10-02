<script lang="ts">
  import { layout, type Cell, type MetroLine, type MetroNode } from "../../lib/domain/metro";
  import { t } from "../../lib/i18n.svelte";
  import type { Achievement } from "../../lib/api/types";

  const { lines, achievements }: { lines: MetroLine[]; achievements: Achievement[] } = $props();

  // One cell in CSS pixels; the column count follows the width, so a phone never scrolls sideways.
  const CELL = 72;
  let width = $state(0);
  let wrap: HTMLDivElement | undefined = $state();
  // Not bind:clientWidth: its runtime helper would land in the eager chunk every page loads.
  $effect(() => {
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(([entry]) => (width = entry!.contentRect.width));
    watch.observe(wrap);
    return () => watch.disconnect();
  });
  const columns = $derived(Math.min(10, Math.max(5, Math.floor(width / CELL) || 5)));
  const map = $derived(layout(lines, achievements, columns));

  const byId = $derived(new Map(achievements.map((a) => [a.id, a])));
  const names = $derived(new Map(lines.map((l) => [l.on, l.name])));

  let chosen = $state("");
  const selected = $derived(
    map.nodes.find((n) => n.id === chosen) ??
      map.nodes.find((n) => n.state === "next") ??
      map.nodes[0],
  );

  const centre = (cell: Cell) => [(cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL];

  function label(n: MetroNode): string {
    if (n.kind === "start") return names.get(n.line) ?? "";
    return (byId.get(n.id)?.name ?? "") + " — " + t(`collection.state.${n.state}`);
  }

  function lineCount(on: string) {
    const stops = achievements.filter((a) => a.on === on);
    return { count: stops.filter((a) => a.unlocked_at).length, total: stops.length };
  }
</script>

<p class="help">{t("collection.map_hint")}</p>
<div class="metrowrap" bind:this={wrap}>
  <div class="metro" style={`width:${map.columns * CELL}px;height:${map.rows * CELL}px`}>
    <svg width={map.columns * CELL} height={map.rows * CELL} aria-hidden="true">
      {#each map.links as link, i (i)}
        {@const [x1, y1] = centre(link.from)}
        {@const [x2, y2] = centre(link.to)}
        <line class="link" {x1} {y1} {x2} {y2} />
      {/each}
      {#each map.segments as s, i (i)}
        {@const [x1, y1] = centre(s.from)}
        {@const [x2, y2] = centre(s.to)}
        <line class={"track" + (s.lit ? " lit" : "")} style={`--c:var(--metro-${s.color})`} {x1} {y1} {x2} {y2} />
      {/each}
    </svg>
    {#each map.nodes as n (n.id)}
      {@const [x, y] = centre(n.at)}
      <button
        type="button"
        class={`stop ${n.kind} ${n.state}`}
        style={`left:${x}px;top:${y}px;--c:var(--metro-${n.color})`}
        aria-label={label(n)}
        aria-pressed={selected?.id === n.id}
        onclick={() => (chosen = n.id)}
      >
        {#if n.kind === "start"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" /></svg>
        {:else if n.state === "next"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path class="fill" d="M5.5 3.5v9l7-4.5z" /></svg>
        {:else if n.kind === "flag"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 13.5v-10h7l-1.5 2.5 1.5 2.5h-7" /></svg>
        {/if}
      </button>
      {#if n.kind === "start"}
        <span class="linename" style={`left:${x}px;top:${y + CELL * 0.42}px`}>{names.get(n.line)}</span>
      {/if}
    {/each}
  </div>
</div>

<div class="metrodetail" aria-live="polite">
  {#if selected?.kind === "start"}
    {@const tally = lineCount(selected.line)}
    <span class="title">{names.get(selected.line)}</span>
    <span class="what">{t("progress.achievements_earned", tally)}</span>
  {:else if selected}
    {@const a = byId.get(selected.id)}
    {#if a}
      <span class="title">{a.name}</span>
      <span class="what">{a.description}</span>
      {#if a.unlocked_at}
        <time class="when" datetime={a.unlocked_at}>{t("progress.unlocked_on", { date: a.unlocked_at })}</time>
      {:else}
        <span class="when">{t("progress.achievement_count", { count: a.count, threshold: a.threshold })}</span>
        <span class="meter" aria-hidden="true">
          <i style={"width:" + Math.round((a.count / a.threshold) * 100) + "%"}></i>
        </span>
      {/if}
    {/if}
  {/if}
</div>
