<script lang="ts">
  // THE LEADERBOARD: a signed-in account's OPTIONAL view. Loaded ON CLICK -- the
  // anonymous visitor downloads none of it, and neither does a signed-in student who
  // never opens it, which matters more here than anywhere else since taking part is
  // optional and most accounts never opt in.
  //
  // NOTHING IS COMPUTED HERE. Ranks, the gap to the row above, the cohort threshold and
  // the divisions all arrive decided. A page that ranked itself would be a page where one
  // ranks oneself from the console -- and this is the one screen where that would be worth
  // doing.
  //
  // NOBODY IS NAMED LAST, and that is the server's doing too: only the top of the table
  // plus one's OWN row ever come down. There is nothing here to truncate, because nothing
  // more ever arrives.
  //
  // THE OPT-IN IS NOT ON THIS SCREEN, deliberately: joining a ranking is an identity
  // setting, next to "show my name" and "show my group". Two places to consent would be
  // two places that can disagree about whether one did.

  import { onMount } from "svelte";
  import { fetchLeaderboard } from "../../lib/api/leaderboard";
  import { redrawAlias } from "../../lib/api/forum";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import { plural } from "../../lib/domain/labels";
  import type { LeaderboardPayload } from "../../lib/api/types";

  let title: HTMLHeadingElement | undefined = $state();
  let payload = $state<LeaderboardPayload | null>(null);
  let error = $state("");
  let said = $state("");
  /** The scope is a REQUEST PARAMETER, not a filter over a full table: the full table
   *  never comes down. */
  let scope = $state<"group" | "course">("group");
  /** The group an instructor is looking at. `null` = their own, so for staff with no
   *  group on their profile, the whole course. */
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
  <!-- WE DO NOT INVENT AN EMPTY RANKING. "Personne" during an outage says nobody is
       working, and that would be false. -->
  <p class="rate">{error}</p>
{:else if !payload.participating}
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
  <!-- THE GROUP SELECTOR ONLY EXISTS FOR A MODERATOR, and it is the SERVER that says so
       (`moderator` in the response): the page does not guess a role. -->
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
        <!-- `aria-pressed` RATHER THAN A CLASS: "on" says nothing to a screen reader, and
             which scope one is looking at is the whole context of the numbers below. -->
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
      <!-- WE DO NOT TELL SOMEBODY THE `WHERE` EXCLUDES "you appear as X". The instructor
           reads the leaderboard and never figures in it -- their XP is test XP, and a
           table carrying it would be unfair to everyone who is in it. The rule is in SQL;
           what is here is not lying about it. -->
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

  <!-- ONE'S OWN STANDING, AND THE STEP UP. "Deux de plus et tu passes 3e" is something to
       do; "quelqu'un te rattrape" is pressure with nothing to do about it, and it is not
       sent. -->
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
    <!-- UNDER THE MINIMUM COHORT THERE IS NO TABLE, and the reason is written on screen: a
         ranking of four people names those four people, including the last one. The server
         already refuses to send it; this says why, so an empty screen does not read as a
         failure. THE THRESHOLD APPLIES TO THE INSTRUCTOR TOO, deliberately. -->
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
