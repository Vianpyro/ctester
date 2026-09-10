<script lang="ts">
  // THE WIDE VIEW: what the dock has no room for -- the search, the permalinks, the
  // charter to reread, and a moderator's door.
  //
  // TWO COLUMNS ON A LARGE SCREEN, one on a small one, and the CSS grid decides: what one
  // writes on the left, what one reads on the right. Stacked, the thread used to start
  // below three panels and left two thirds of the screen empty.
  //
  // THE FIELD IS UNDER THE THREAD, not at the bottom of the other column. That is the
  // defect this repairs: everywhere else -- Discord, Teams, Instagram -- one writes
  // exactly where one has just read.

  import { onMount } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { submission } from "../../lib/state/submission.svelte";
  import { chat } from "./chat.svelte";
  import { identity } from "./identity.svelte";
  import { thread } from "./thread.svelte";
  import { CHARTER } from "./Guidelines.svelte";
  import Channels from "./Channels.svelte";
  import Composer from "./Composer.svelte";
  import SearchResults from "./SearchResults.svelte";
  import ThreadList from "./ThreadList.svelte";

  let title: HTMLHeadingElement | undefined = $state();
  let terms = $state("");

  onMount(() => {
    // Focus follows the view: without this, tabbing would restart from the top of the
    // page and a screen reader would not announce the screen change.
    title?.focus();
    return thread.watch();
  });

  const masked = $derived(identity.profile?.alias || "un nom masqué");
  /** THE CONTEXT WE JUST LOST. Opening discussions clears the workbench: we arrive here
   *  to talk about a verdict that is no longer visible. Recalling it avoids a round trip
   *  to copy it back -- and it is the first thing we will be asked in the thread. */
  const recalled = $derived(
    submission.lastVerdict && submission.lastVerdict.exercise === thread.key
      ? submission.lastVerdict
      : null,
  );

  const reportsWaiting = $derived(
    (thread.reports ?? []).length + (thread.reportedNames ?? []).length,
  );
  const stuckPeople = $derived((thread.help?.rows ?? []).reduce((n, r) => n + r.people, 0));

  async function runSearch() {
    await thread.runSearch(terms);
  }
</script>

<h2 bind:this={title} id="forumtitre" tabindex="-1">Chat du cours</h2>
<!-- WHAT THE STUDENT MUST KNOW BEFORE WRITING: that it is public, and under which name
     they appear. The second point is the whole reason this exists, so it is said here and
     not only in a panel one does not open. -->
<p class="aide">
  Visible par les autres comptes connectés du cours. Ce n'est pas une note, et ça n'a
  aucun effet sur tes progrès. Tu y apparais sous « {masked} » — ton vrai nom n'apparaît
  que si tu l'affiches dans Compte → Mon identité.
</p>

{#if recalled}
  <p class="rappel">
    <span class="quoi">Ton dernier test sur cet exercice : </span><b>{recalled.title}</b>
  </p>
{/if}

<p class="annonce" aria-live="polite">{thread.said}</p>

<div class="colonne">
  <div class="bloc">
    <h3 class="soustitre">Canaux</h3>
    <Channels />
    <!-- WHAT ONE HAS TO KNOW BEFORE WRITING, and not after. It is the contract the chat
         makes with somebody afraid of looking silly. -->
    <p class="aide">
      {thread.isChat
        ? "Ici tout est public : ton message est lisible par tous les comptes du cours, sous ton nom masqué."
        : "Ce que tu as envoyé en privé. Seul l'enseignant le lit."}
    </p>
  </div>

  {#if catalog.catalog.length && thread.mode !== "chat-general"}
    <div class="bloc">
      <label for="forumex">Exercice</label>
      <!-- THE MENU CARRIES THE EXERCISE, `thread.key` CARRIES THE THREAD KEY. The two
           stopped being the same string when the chat appeared: `threadKey()` translates,
           and it is the only place that does. -->
      <select
        id="forumex"
        value={thread.currentExercise}
        onchange={(e) =>
          thread.openChannel(
            thread.mode === "chat-general" ? "chat-ex" : thread.mode,
            (e.currentTarget as HTMLSelectElement).value,
          )}
      >
        {#each catalog.catalog as tp (tp.id)}
          <option value={tp.id}>{tp.group} — {tp.short || tp.label}</option>
        {/each}
      </select>
    </div>
  {/if}

  <!-- THE CHARTER FOLDS. It used to take the whole column on every visit, and it is what
       pushed the field eight hundred pixels below the last message. The moment it COUNTS
       is the session's first post, and the panel puts it full-screen then. -->
  <details class="bloc second">
    <summary class="soustitre">Ce qui se publie ici</summary>
    <ul class="regles">
      {#each CHARTER as rule}<li>{rule}</li>{/each}
    </ul>
    <p class="aide">
      Modération humaine : rien n'est vérifié automatiquement. Signale plutôt que de
      répondre à une fuite.
    </p>
  </details>
</div>

<div class="colonne large">
  {#if thread.messages === null}
    <p class="rate">{thread.error}</p>
  {:else}
    <div class="bloc">
      <h3 class="soustitre">Chercher</h3>
      <input
        type="search"
        id="forumrecherche"
        placeholder="un mot de la question…"
        bind:value={terms}
        onkeydown={(e) => {
          if (e.key === "Enter") void runSearch();
        }}
      />
      <button type="button" class="nav" onclick={runSearch}>Chercher</button>
      {#if thread.results !== null}
        <SearchResults rows={thread.results} empty="Aucun message ne correspond." />
      {/if}
    </div>

    <ThreadList />
    <Composer />

    <!-- MODERATION IS NO LONGER RENDERED HERE. What remains is a door to it, visible only
         to a moderator. -->
    {#if thread.moderator}
      <div class="bloc second">
        <h3 class="soustitre">Modération</h3>
        <p>
          {reportsWaiting
            ? reportsWaiting +
              (reportsWaiting > 1 ? " éléments signalés" : " élément signalé") +
              " à examiner."
            : "Rien de signalé pour l'instant."}
        </p>
        {#if stuckPeople}
          <p>
            {stuckPeople > 1
              ? stuckPeople + " personnes ont signalé être bloquées."
              : "1 personne a signalé être bloquée."}
          </p>
        {/if}
        <button type="button" onclick={() => chat.openModeration()}>Ouvrir la modération</button>
      </div>
    {/if}
  {/if}
</div>
