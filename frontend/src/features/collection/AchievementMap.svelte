<script lang="ts">
  import { layout, type Cell, type MetroLine, type MetroNode, type MetroStation } from "../../lib/domain/metro";
  import { t } from "../../lib/i18n.svelte";
  import CardArt from "./CardArt.svelte";
  import type { Achievement, Card } from "../../lib/api/types";

  type Line = MetroLine & { description?: string };
  const {
    lines,
    achievements,
    cards,
  }: { lines: Line[]; achievements: Achievement[]; cards: Card[] } = $props();

  // One cell in CSS pixels; the column count follows the width, so a phone never scrolls sideways.
  const CELL = 72;
  const TIP = 320;
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

  // On the map the cards are the stations of their line; the achievements that count them
  // stay in "My progress". A content base with cards but no such line still gets one.
  const CARD = "card:";
  const drawn = $derived<Line[]>(
    cards.length && !lines.some((l) => l.on === "cards")
      ? [...lines, { on: "cards", name: t("collection.cards_line") }]
      : lines,
  );
  const stations = $derived<MetroStation[]>([
    ...achievements.filter((a) => !(cards.length && a.on === "cards")),
    ...cards.map((c) => ({
      id: CARD + c.id,
      on: "cards",
      unlocked_at: c.held ? "held" : null,
      kind: "card" as const,
    })),
  ]);
  const map = $derived(layout(drawn, stations, columns));

  const byId = $derived(new Map(achievements.map((a) => [a.id, a])));
  const cardOf = $derived(new Map(cards.map((c) => [CARD + c.id, c])));
  const lineOf = $derived(new Map(drawn.map((l) => [l.on, l])));

  // Hover and focus show the tooltip; a click or a tap pins it until Escape or a click away.
  let open = $state<string | null>(null);
  let pinned = $state(false);
  const shown = $derived(map.nodes.find((n) => n.id === open));

  function show(id: string) {
    if (!pinned) open = id;
  }

  function hide() {
    if (!pinned) open = null;
  }

  function toggle(id: string) {
    const same = pinned && open === id;
    pinned = !same;
    open = same ? null : id;
  }

  function close() {
    pinned = false;
    open = null;
  }

  const centre = (cell: Cell) => [(cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL];

  function label(n: MetroNode): string {
    if (n.kind === "start") return lineOf.get(n.line)?.name ?? "";
    const name = cardOf.get(n.id)?.name ?? byId.get(n.id)?.name ?? "";
    return name + " — " + t(`collection.state.${n.state}`);
  }

  function tally(on: string) {
    const stops = stations.filter((s) => s.on === on);
    return { count: stops.filter((s) => s.unlocked_at).length, total: stops.length };
  }

  // In the map's own coordinates: above a station in the lower half, below otherwise, and
  // never past either side, so it stays on a phone's screen.
  function place(n: MetroNode): string {
    const [x, y] = centre(n.at);
    const room = map.columns * CELL;
    const tip = Math.min(TIP, room - 16);
    const left = Math.max(8, Math.min(x - tip / 2, room - tip - 8));
    const above = n.at[1] >= map.rows / 2;
    const top = above ? y - CELL * 0.45 : y + CELL * 0.45;
    return `left:${left}px;top:${top}px;width:${tip}px;--c:var(--metro-${n.color})` +
      (above ? ";transform:translateY(-100%)" : "");
  }

  const pct = (count: number, total: number) => (total ? Math.round((count / total) * 100) : 0);
</script>

<svelte:window
  onkeydown={(e) => {
    if (e.key === "Escape" && open) close();
  }}
  onclick={(e) => {
    if (pinned && !(e.target as Element | null)?.closest?.(".metro .stop, .metrotip")) close();
  }}
/>

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
        aria-describedby={open === n.id ? "metrotip" : undefined}
        aria-expanded={open === n.id}
        onpointerenter={() => show(n.id)}
        onpointerleave={hide}
        onfocus={() => show(n.id)}
        onblur={hide}
        onclick={() => toggle(n.id)}
      >
        {#if n.kind === "card"}
          <CardArt art={cardOf.get(n.id)?.art ?? ""} />
        {:else if n.kind === "start"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" /></svg>
        {:else if n.state === "next"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path class="fill" d="M5.5 3.5v9l7-4.5z" /></svg>
        {:else if n.kind === "flag"}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 13.5v-10h7l-1.5 2.5 1.5 2.5h-7" /></svg>
        {/if}
      </button>
      {#if n.kind === "start"}
        <span class="linename" style={`left:${x}px;top:${y + CELL * 0.42}px`}>{lineOf.get(n.line)?.name}</span>
      {/if}
    {/each}

    {#if shown}
      {@const line = lineOf.get(shown.line)}
      <div id="metrotip" class="metrotip" role="tooltip" style={place(shown)}>
        <span class="linetitle">{line?.name}</span>
        {#if line?.description}<span class="about">{line.description}</span>{/if}
        <hr />
        {#if shown.kind === "start"}
          {@const n = tally(shown.line)}
          <div class="goal">
            <span>{t("progress.achievements_earned", n)}</span>
          </div>
          <span class="meter" aria-hidden="true"><i style={`width:${pct(n.count, n.total)}%`}></i></span>
        {:else if shown.kind === "card"}
          {@const c = cardOf.get(shown.id)}
          {#if c}
            <div class="cardrow">
              <span class="drawing"><CardArt art={c.art} /></span>
              <span class="named">
                <span class="title">{c.name}</span>
                <span class="what">{c.condition}</span>
              </span>
            </div>
            {#if c.held}
              <span class="when">{t("collection.earned")}</span>
            {:else}
              <div class="goal">
                <span>{t(`collection.state.${shown.state}`)}</span>
                <span class="count">{c.progress} / {c.needed}</span>
              </div>
              <span class="meter" aria-hidden="true"><i style={`width:${pct(c.progress, c.needed)}%`}></i></span>
            {/if}
            {#if c.rarity !== null && c.rarity !== undefined}
              <span class="when">{t("collection.rarity_short", { rarity: c.rarity })}</span>
            {/if}
          {/if}
        {:else}
          {@const a = byId.get(shown.id)}
          {#if a}
            <span class="title">{a.name}</span>
            <span class="what">{a.description}</span>
            {#if a.unlocked_at}
              <time class="when" datetime={a.unlocked_at}>{t("progress.unlocked_on", { date: a.unlocked_at })}</time>
            {:else}
              <div class="goal">
                <span>{t(`collection.state.${shown.state}`)}</span>
                <span class="count">{a.count} / {a.threshold}</span>
              </div>
              <span class="meter" aria-hidden="true"><i style={`width:${pct(a.count, a.threshold)}%`}></i></span>
            {/if}
          {/if}
        {/if}
      </div>
    {/if}
  </div>
</div>
