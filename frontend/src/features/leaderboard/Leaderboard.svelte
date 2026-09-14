<script lang="ts">  import { onMount } from "svelte";
  import { fetchLeaderboard } from "../../lib/api/leaderboard";
  import { redrawAlias } from "../../lib/api/forum";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import { plural } from "../../lib/domain/labels";
  import type { LeaderboardPayload } from "../../lib/api/types";

  let title: HTMLHeadingElement | undefined = $state();
  let payload = $state<LeaderboardPayload | null>(null);
  let error = $state("");
  let said = $state("");
  let scope = $state<"group" | "course">("group");
  let targetGroup = $state<number | null>(null);

  async function load() {
    const answer = await fetchLeaderboard(scope, targetGroup);
    if (!answer || typeof answer.participating !== "boolean") {
      payload = null;
      error =
        "Le classement n'est pas disponible pour l'instant. L'exercice et le bouton " +
        "« Tester », eux, fonctionnent normalement.";
      return;
    }
    payload = answer;
    error = "";
  }

  onMount(() => {
    void load();
    title?.focus();
  });

  whenSignedOut(() => {
    payload = null;
    error = "";
    said = "";
  });

  async function openIdentity() {
    const { identity } = await import("../forum/identity.svelte");
    await identity.toggle();
  }

  async function newAlias() {
    const answer = await redrawAlias();
    said = answer.ok ? "Nouveau pseudonyme." : "Le pseudonyme n'a pas pu être changé.";
    await load();
  }

  async function pick(next: "group" | "course", group: number | null) {
    scope = next;
    targetGroup = group;
    await load();
  }
</script>

<h2 bind:this={title} id="leaderboardtitle" tabindex="-1">Classement</h2>
<p class="aide">
  Facultatif. Tu y participes parce que tu l'as coché, et tu peux te retirer à tout moment
  : ta pratique et tes progrès ne changent pas.
</p>

{#if said}<p class="annonce" aria-live="polite">{said}</p>{/if}

{#if !payload}
  <p class="rate">{error}</p>
{:else if !payload.participating && !payload.moderator}
  <div class="bloc plan">
    <div class="kicker">Tu n'y participes pas</div>
    <p>
      Le classement est facultatif, et tu n'y es pas. Rien de ce que tu fais n'y apparaît
      tant que tu ne l'as pas coché.
    </p>
    <p class="aide">
      Tu y apparaîtrais sous un pseudonyme tiré au hasard, jamais sous ton nom, et tu
      pourrais te retirer à tout moment sans que ta pratique ni tes progrès changent.
    </p>
    <button type="button" onclick={openIdentity}>Ouvrir « Mon identité »</button>
  </div>
{:else}
  {#if payload.moderator && (payload.groups ?? []).length}
    <div class="tabs">
      <button
        type="button"
        class={"nav" + (targetGroup === null ? " on" : "")}
        aria-pressed={targetGroup === null}
        onclick={() => pick("course", null)}>Tous les groupes</button
      >
      {#each payload.groups ?? [] as g}
        <button
          type="button"
          class={"nav" + (targetGroup === g ? " on" : "")}
          aria-pressed={targetGroup === g}
          onclick={() => pick("group", g)}>Groupe {String(g).padStart(2, "0")}</button
        >
      {/each}
    </div>
  {:else}
    <div class="tabs">
      {#each [["group", "Mon groupe"], ["course", "Cours entier"]] as const as [id, label]}
        <button
          type="button"
          class={"nav" + (scope === id ? " on" : "")}
          aria-pressed={scope === id}
          onclick={() => pick(id, targetGroup)}>{label}</button
        >
      {/each}
    </div>
  {/if}

  <div class="bloc">
    {#if payload.moderator}
      <p>
        Tu n'apparais pas au classement : il ne compte que les comptes étudiants qui s'y
        sont inscrits.
      </p>
    {:else}
      <p class="aliasrow">
        <span>Tu apparais sous</span>
        <b class="alias-value">{payload.alias || "—"}</b>
        <button type="button" class="nav" onclick={newAlias}>Un autre nom</button>
      </p>
      <p class="aide">
        Tiré au hasard, jamais ton vrai nom, et rechangeable autant de fois que tu veux.
      </p>
    {/if}
  </div>

  {#if payload.me}
    <div class="bloc plan rang">
      <span class="chiffre">{payload.me.rank}</span>
      <div>
        <p>
          sur {plural(payload.cohort, "compte")}{payload.scope === "course"
            ? " du cours"
            : " de ton groupe"}, ces {payload.window_days} derniers jours
        </p>
        {#if payload.gap}
          <p class="aide">
            {payload.gap.solved > 0
              ? plural(payload.gap.solved, "exercice") +
                " de plus et tu passes " +
                payload.gap.rank +
                (payload.gap.rank === 1 ? "er" : "e") +
                "."
              : "Tu es à égalité avec la place au-dessus."}
          </p>
        {:else}
          <p class="aide">Personne devant toi cette semaine.</p>
        {/if}
      </div>
    </div>
  {/if}

  {#if payload.rows.length}
    <div class="bloc">
      <table class="rank-table">
        <thead>
          <tr>
            <th>#</th><th>Compte</th><th>Exercices réussis pour la première fois</th>
          </tr>
        </thead>
        <tbody>
          {#each payload.rows as row (row.rank)}
            <tr class={row.mine ? "mine" : ""}>
              <td class="num">{row.rank}</td>
              <td>{row.mine ? "Toi — " + row.alias : row.alias}</td>
              <td class="num">{row.solved}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="aide">
        Refaire un exercice déjà réussi ne compte pas : la colonne ne bouge qu'à la
        première réussite. Les rangs suivants ne sont pas affichés — chaque personne voit
        sa propre ligne.
      </p>
    </div>
  {:else}
    <div class="bloc">
      <p>
        Vous êtes {plural(payload.cohort, "compte")} à participer ici. Il en faut au moins
        {payload.minimum} pour afficher un tableau.
      </p>
      <p class="aide">
        En dessous, un classement nomme tout le monde — y compris la dernière personne. Tu
        vois donc ta ligne, et rien d'autre.
      </p>
    </div>
  {/if}

  {#if (payload.divisions ?? []).length}
    <div class="bloc">
      <h3 class="soustitre">Divisions du cours</h3>
      <div class="divisions">
        {#each payload.divisions ?? [] as d (d.id)}
          <div class={"division" + (d.id === payload.division?.id ? " on" : "")}>
            <span class="name">{d.title}</span>
            <span class="quoi">
              {d.id === payload.division?.id
                ? "tu es ici — " + plural(d.accounts, "compte")
                : plural(d.accounts, "compte")}
            </span>
          </div>
        {/each}
      </div>
      <p class="aide">
        Les divisions montent, jamais ne descendent en cours de session : un mauvais mois
        ne fait rien perdre.
      </p>
    </div>
  {/if}
{/if}
