<script lang="ts">
  import { onDestroy } from "svelte";
  import { fetchCollection } from "../../lib/api/account";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import { tier } from "../../lib/domain/rarity";
  import { t } from "../../lib/i18n.svelte";
  import { drops } from "../../lib/state/drops.svelte";
  import { system } from "../../lib/state/system.svelte";
  import { view } from "../../lib/state/view.svelte";
  import CardArt from "../collection/CardArt.svelte";
  import type { Card } from "../../lib/api/types";

  const { openView }: { openView: (name: "collection") => void } = $props();

  const CARD = "card:";

  const dismiss = () => (drops.ids = []);
  onDestroy(whenSignedOut(dismiss));

  // A card's name, drawing and rarity come from the content, so they are fetched on arrival.
  let cards = $state<Record<string, Card>>({});
  // Plain on purpose: a card missing from the answer must not trigger another fetch.
  const asked = new Set<string>();

  $effect(() => {
    const wanted = drops.ids.filter((id) => id.startsWith(CARD) && !asked.has(id));
    if (!wanted.length) return;
    for (const id of wanted) asked.add(id);
    void fetchCollection().then((answer) => {
      const known: Record<string, Card> = {};
      for (const c of answer?.cards ?? []) known[CARD + c.id] = c;
      cards = known;
    });
  });

  type Item = { id: string; card: Card | null; name: string; what: string; tier: string };

  const items = $derived(
    drops.ids.flatMap((id): Item[] => {
      if (!id.startsWith(CARD)) {
        return [{
          id,
          card: null,
          name: t(`achievement.${id}.title`),
          what: t(`achievement.${id}.description`),
          tier: "ok",
        }];
      }
      const card = cards[id];
      return card ? [{ id, card, name: card.name, what: card.condition, tier: String(tier(card.rarity)) }] : [];
    }),
  );

  $effect(() => {
    if (items.length) system.announce(t("drops.announce", { names: items.map((i) => i.name).join(", ") }));
  });
</script>

{#if items.length}
  <aside class="drops" aria-labelledby="dropstitle">
    <h2 id="dropstitle">{t("drops.title")}</h2>
    <ul>
      {#each items as item, i (item.id)}
        <li class="drop" data-tier={item.tier} style={"--i:" + i}>
          {#if item.card}<div class="drawing"><CardArt art={item.card.art} /></div>{/if}
          <div class="text">
            <span class="kind">{item.card ? t("drops.card") : t("drops.achievement")}</span>
            <span class="name">{item.name}</span>
            <span class="what">{item.what}</span>
          </div>
        </li>
      {/each}
    </ul>
    <div class="actions">
      {#if items.some((i) => i.card)}
        <button
          type="button"
          onclick={() => {
            if (view.current !== "collection") openView("collection");
            dismiss();
          }}>{t("drops.see_collection")}</button
        >
      {/if}
      <button type="button" class="nav" onclick={dismiss}>{t("drops.close")}</button>
    </div>
  </aside>
{/if}
