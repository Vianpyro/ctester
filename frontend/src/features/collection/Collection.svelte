<script lang="ts">
  import { onMount } from "svelte";
  import { fetchCollection } from "../../lib/api/account";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import CardArt from "./CardArt.svelte";
  import { t } from "../../lib/i18n.svelte";
  import type { CollectionPayload } from "../../lib/api/types";

  let title: HTMLHeadingElement | undefined = $state();
  let payload = $state<CollectionPayload | null>(null);
  let error = $state("");

  onMount(() => {
    void (async () => {
      const answer = await fetchCollection();
      if (!answer || !Array.isArray(answer.cards)) {
        payload = null;
        error = t("collection.unavailable");
        return;
      }
      payload = answer;
      error = "";
    })();
    title?.focus();
  });

  whenSignedOut(() => {
    payload = null;
    error = "";
  });

  const held = $derived((payload?.cards ?? []).filter((c) => c.held).length);
</script>

<h2 bind:this={title} id="collectiontitle" tabindex="-1">{t("progress.my_collection")}</h2>

{#if !payload}
  <p class="failed">{error}</p>
{:else}
  <p class="help">
    {t("collection.held", { count: held, total: payload.cards.length })}
  </p>
  <div class="cards">
    {#each payload.cards as c (c.id)}
      <div class={"card " + (c.held ? "held" : "locked")}>
        <div class="header">
          <span class="code">{c.id}</span>
          <span class="code">{c.rarity === null || c.rarity === undefined ? "—" : c.rarity + " %"}</span>
        </div>
        <div class="drawing"><CardArt art={c.art} /></div>
        <div class="name">{c.name}</div>
        <div class="what">{c.held ? c.condition : t("collection.locked", { condition: c.condition })}</div>
        <span class="offscreen"> — {c.held ? t("collection.earned") : t("collection.not_earned")}</span>
      </div>
    {/each}
  </div>
  <p class="help">{t("collection.help")}</p>
  <p class="help">
    {payload.cohort ? t("collection.rarity") : t("collection.rarity_pending")}
  </p>
{/if}
