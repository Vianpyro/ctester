<script lang="ts">
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
    title?.focus();
    return thread.watch();
  });

  const masked = $derived(identity.profile?.alias || "un nom masqué");
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

<h2 bind:this={title} id="forumtitle" tabindex="-1">Chat du cours</h2>
<p class="help">
  Visible par les autres comptes connectés du cours. Ce n'est pas une note, et ça n'a
  aucun effet sur tes progrès. Tu y apparais sous « {masked} » — ton vrai nom n'apparaît
  que si tu l'affiches dans Compte → Mon identité.
</p>

{#if recalled}
  <p class="reminder">
    <span class="what">Ton dernier test sur cet exercice : </span><b>{recalled.title}</b>
  </p>
{/if}

<p class="notice" aria-live="polite">{thread.said}</p>

<div class="column">
  <div class="block">
    <h3 class="subtitle">Canaux</h3>
    <Channels />
    <p class="help">
      {thread.isChat
        ? "Ici tout est public : ton message est lisible par tous les comptes du cours, sous ton nom masqué."
        : "Ce que tu as envoyé en privé. Seul l'enseignant le lit."}
    </p>
  </div>

  {#if catalog.catalog.length && thread.mode !== "chat-general"}
    <div class="block">
      <label for="forumex">Exercice</label>
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

  <details class="block second">
    <summary class="subtitle">Ce qui se publie ici</summary>
    <ul class="rules">
      {#each CHARTER as rule}<li>{rule}</li>{/each}
    </ul>
    <p class="help">
      Modération humaine : rien n'est vérifié automatiquement. Signale plutôt que de
      répondre à une fuite.
    </p>
  </details>
</div>

<div class="column large">
  {#if thread.messages === null}
    <p class="failed">{thread.error}</p>
  {:else}
    <div class="block">
      <h3 class="subtitle">Chercher</h3>
      <input
        type="search"
        id="forumsearch"
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

    {#if thread.moderator}
      <div class="block second">
        <h3 class="subtitle">Modération</h3>
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
