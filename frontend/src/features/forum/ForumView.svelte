<script lang="ts">
  import { onMount } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { submission } from "../../lib/state/submission.svelte";
  import { chat } from "./chat.svelte";
  import { identity } from "./identity.svelte";
  import { thread } from "./thread.svelte";
  import { CHARTER } from "./Guidelines.svelte";
  import { t } from "../../lib/i18n.svelte";
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

  const masked = $derived(identity.profile?.alias || t("forum.masked"));
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

<h2 bind:this={title} id="forumtitle" tabindex="-1">{t("forum.title")}</h2>
<p class="help">{t("forum.intro", { masked })}</p>

{#if recalled}
  <p class="reminder">
    <span class="what">{t("forum.last_test")}</span><b>{recalled.title}</b>
  </p>
{/if}

<p class="notice" aria-live="polite">{thread.said}</p>

<div class="column">
  <div class="block">
    <h3 class="subtitle">{t("forum.channels")}</h3>
    <Channels />
    <p class="help">
      {thread.isChat ? t("forum.public") : t("forum.private_help")}
    </p>
  </div>

  {#if catalog.catalog.length && thread.mode !== "chat-general"}
    <div class="block">
      <label for="forumex">{t("forum.exercise")}</label>
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
    <summary class="subtitle">{t("forum.rules")}</summary>
    <ul class="rules">
      {#each CHARTER as rule}<li>{t(rule)}</li>{/each}
    </ul>
    <p class="help">{t("forum.rules_help")}</p>
  </details>
</div>

<div class="column large">
  {#if thread.messages === null}
    <p class="failed">{thread.error}</p>
  {:else}
    <div class="block">
      <h3 class="subtitle">{t("forum.search")}</h3>
      <input
        type="search"
        id="forumsearch"
        placeholder={t("forum.search_placeholder")}
        bind:value={terms}
        onkeydown={(e) => {
          if (e.key === "Enter") void runSearch();
        }}
      />
      <button type="button" class="nav" onclick={runSearch}>{t("forum.search")}</button>
      {#if thread.results !== null}
        <SearchResults rows={thread.results} empty={t("forum.no_match")} />
      {/if}
    </div>

    <ThreadList />
    <Composer />

    {#if thread.moderator}
      <div class="block second">
        <h3 class="subtitle">{t("moderation.title")}</h3>
        <p>
          {reportsWaiting
            ? t("forum.reports", { count: reportsWaiting })
            : t("forum.no_reports")}
        </p>
        {#if stuckPeople}
          <p>
            {t("forum.stuck", { count: stuckPeople })}
          </p>
        {/if}
        <button type="button" onclick={() => chat.openModeration()}>{t("forum.open_moderation")}</button>
      </div>
    {/if}
  {/if}
</div>
