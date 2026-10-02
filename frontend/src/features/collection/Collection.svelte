<script lang="ts">
  import { onMount } from "svelte";
  import { fetchCollection } from "../../lib/api/account";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import AchievementMap from "./AchievementMap.svelte";
  import CardArt from "./CardArt.svelte";
  import { tier } from "../../lib/domain/rarity";
  import { drops } from "../../lib/state/drops.svelte";
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
      if (answer.unlocked?.length) drops.ids = answer.unlocked;
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
      <div class={"card " + (c.held ? "held" : "locked")} data-tier={c.held ? tier(c.rarity) : undefined}>
        <div class="header">
          <span class="code">{c.id}</span>
          <span class="code">{c.rarity === null || c.rarity === undefined ? "—" : c.rarity + " %"}</span>
        </div>
        <div class="drawing"><CardArt art={c.art} /></div>
        <div class="name">{c.name}</div>
        <div class="what">{c.held ? c.condition : t("collection.locked", { condition: c.condition })}</div>
        {#if !c.held && c.needed}
          <div class="progress">{t("collection.progress", { count: c.progress, total: c.needed })}</div>
          <span class="gauge" aria-hidden="true">
            <i style={"width:" + Math.round((c.progress / c.needed) * 100) + "%"}></i>
          </span>
        {/if}
        <span class="offscreen"> — {c.held ? t("collection.earned") : t("collection.not_earned")}</span>
      </div>
    {/each}
  </div>
  <p class="help">{t("collection.help")}</p>
  <p class="help">
    {payload.cohort ? t("collection.rarity") : t("collection.rarity_pending")}
  </p>
  {#if payload.achievements?.length}
    <h3 class="subtitle achievementstitle">{t("progress.achievements")}</h3>
    <p>
      {t("progress.achievements_earned", {
        count: payload.achievements.filter((a) => a.unlocked_at).length,
        total: payload.achievements.length,
      })}
    </p>
    {#if payload.lines?.length}
      <AchievementMap lines={payload.lines} achievements={payload.achievements} />
    {:else}
      <ul class="achievements">
        {#each payload.achievements as a (a.id)}
          <!-- Only the collection measures rarity: elsewhere an earned tile keeps the plain bar. -->
          <li
            class={a.unlocked_at ? "earned" : "locked"}
            data-tier={a.unlocked_at && a.rarity !== undefined ? tier(a.rarity) : undefined}
          >
            <span class="title">{a.name}</span>
            <span class="what">{a.description}</span>
            {#if a.unlocked_at}
              <time class="when" datetime={a.unlocked_at}>{t("progress.unlocked_on", { date: a.unlocked_at })}</time>
            {:else}
              <span class="when">
                {t("progress.achievement_count", { count: a.count, threshold: a.threshold })}
              </span>
              <span class="meter" aria-hidden="true">
                <i style={"width:" + Math.round((a.count / a.threshold) * 100) + "%"}></i>
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
{/if}
