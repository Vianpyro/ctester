<script lang="ts">
  // THE COLLECTION: the cards a signed-in account has earned, and the ones it has not.
  // Loaded ON CLICK, never before.
  //
  // A CARD IS A TRACE, NOT AN ADVANTAGE. Nothing here is drawn at random, nothing is
  // bought, nothing expires, and holding a card grants no XP, no access and no standing.
  // What it says is "you did this".
  //
  // A LOCKED CARD IS SHOWN, WITH ITS CONDITION, and that is the whole difference from a
  // loot box: one can read what to do to get it, decide it is not worth it, and lose
  // nothing.
  //
  // NOTHING IS COMPUTED HERE. Which cards are held and how rare each one is arrive
  // decided. Rarity is an OBSERVED RATE -- the share of practising accounts that hold it --
  // and the server withholds it entirely under a minimum cohort, because a percentage over
  // four people describes those four people.

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
  <!-- WE DO NOT INVENT AN EMPTY COLLECTION. A grid of eight locked cards during an outage
       tells somebody they have earned nothing, and that would be false. -->
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
          <!-- A RARITY OF `null` IS NOT A ZERO. It means "too few accounts to say", and
               printing "0 %" there would be a made-up number about real people. -->
          <span class="code">{c.rarity === null || c.rarity === undefined ? "—" : c.rarity + " %"}</span>
        </div>
        <div class="dessin"><CardArt id={c.id} /></div>
        <div class="name">{c.name}</div>
        <!-- THE CONDITION IS ALWAYS PRINTED, held or not: on a held card it says what it
             was earned for, which is the whole point of a trace. -->
        <div class="quoi">{c.held ? c.condition : "verrouillée · " + c.condition}</div>
        <!-- The state in words, for a reader: the frame and the tint say it to everyone
             else, and neither reads aloud. -->
        <span class="horsecran"> — {c.held ? "obtenue" : "pas encore obtenue"}</span>
      </div>
    {/each}
  </div>
  <p class="aide">
    Une carte grise est encore verrouillée et dit à quelle condition elle tombe — rien de
    caché derrière un tirage au sort, rien qui s'achète, rien qui expire. Une carte ne
    donne aucun avantage : c'est une trace de ce que tu as fait.
  </p>
  <!-- The rarity's denominator, said out loud: "34 %" means nothing without "of whom", and
       a number one cannot situate is decoration. -->
  <p class="aide">
    {payload.cohort
      ? "Le pourcentage est la part des comptes ayant pratiqué qui possèdent la carte, mesurée — jamais une rareté décrétée."
      : "Les pourcentages apparaîtront quand assez de comptes auront pratiqué."}
  </p>
{/if}
