<script lang="ts">
  import { onMount } from "svelte";
  import { fetchCollection } from "../../lib/api/account";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import CardArt from "./CardArt.svelte";
  import type { CollectionPayload } from "../../lib/api/types";

  let title: HTMLHeadingElement | undefined = $state();
  let payload = $state<CollectionPayload | null>(null);
  let error = $state("");

  onMount(() => {
    void (async () => {
      const answer = await fetchCollection();
      if (!answer || !Array.isArray(answer.cards)) {
        payload = null;
        error =
          "Ta collection n'est pas disponible pour l'instant. L'exercice et le bouton " +
          "« Tester », eux, fonctionnent normalement.";
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

<h2 bind:this={title} id="collectiontitle" tabindex="-1">Ma collection</h2>

{#if !payload}
  <p class="rate">{error}</p>
{:else}
  <p class="aide">
    {held} pièce{held > 1 ? "s" : ""} sur {payload.cards.length} · privée par défaut
  </p>
  <div class="cards">
    {#each payload.cards as c (c.id)}
      <div class={"card " + (c.held ? "held" : "locked")}>
        <div class="entete">
          <span class="code">{c.id}</span>
          <span class="code">{c.rarity === null || c.rarity === undefined ? "—" : c.rarity + " %"}</span>
        </div>
        <div class="dessin"><CardArt id={c.id} /></div>
        <div class="name">{c.name}</div>
        <div class="quoi">{c.held ? c.condition : "verrouillée · " + c.condition}</div>
        <span class="horsecran"> — {c.held ? "obtenue" : "pas encore obtenue"}</span>
      </div>
    {/each}
  </div>
  <p class="aide">
    Une carte grise est encore verrouillée et dit à quelle condition elle tombe — rien de
    caché derrière un tirage au sort, rien qui s'achète, rien qui expire. Une carte ne
    donne aucun avantage : c'est une trace de ce que tu as fait.
  </p>
  <p class="aide">
    {payload.cohort
      ? "Le pourcentage est la part des comptes ayant pratiqué qui possèdent la carte, mesurée — jamais une rareté décrétée."
      : "Les pourcentages apparaîtront quand assez de comptes auront pratiqué."}
  </p>
{/if}
