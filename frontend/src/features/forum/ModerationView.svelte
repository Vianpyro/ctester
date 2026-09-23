<script lang="ts">  import { onMount } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { groupNumber, localTime } from "../../lib/domain/labels";
  import { t } from "../../lib/i18n.svelte";
  import { readableThread } from "./labels";
  import { chat } from "./chat.svelte";
  import { thread } from "./thread.svelte";
  import Markdown from "./Markdown.svelte";

  let title: HTMLHeadingElement | undefined = $state();

  onMount(() => {
    title?.focus();
  });

  const stepLabel = (id: string) => t(`forum.step.${id}`);
  const blockedLabel = (id: string) => t(`forum.blocked.${id}`);
  const exerciseLabel = (id: string) => {
    const found = catalog.catalog.find((ex) => ex.id === id);
    return found ? found.label || found.short || id : id;
  };
  const topRows = $derived((thread.top?.rows ?? []).filter((r) => r.upvotes || !r.replies));

  async function openConversation(id: string) {
    await chat.toggleWide();
    await thread.openPermalink(id);
  }
</script>

<h2 bind:this={title} id="moderationtitle" tabindex="-1">{t("moderation.title")}</h2>
<p class="notice" aria-live="polite">{thread.said}</p>

{#if !thread.moderator}
  <p class="failed">{t("moderation.only")}</p>
{:else}
  <div class="block">
    <h3 class="subtitle">{t("moderation.top")}</h3>
    {#if !thread.top}
      <p class="failed">{t("moderation.top_failed")}</p>
    {:else if !topRows.length}
      <p class="help">{t("moderation.top_empty", { hours: thread.top.hours })}</p>
    {:else}
      <ul class="thread">
        {#each topRows.slice(0, 10) as r (r.id)}
          <li class="message">
            <p class="who">
              <span class="author">{readableThread(r.exercise_id)}</span>
              {#if r.upvotes}<span class="tag accent">{t("moderation.me_too", { n: r.upvotes })}</span>{/if}
              <span class="tag">
                {r.replies ? t("moderation.replies", { count: r.replies }) : t("moderation.no_reply")}
              </span>
              {#if r.visibility !== "thread"}<span class="tag">{t("moderation.private")}</span>{/if}
              {#if r.step}<span class="tag">{stepLabel(r.step)}</span>{/if}
            </p>
            <p class="excerpt">{r.text}</p>
            <button type="button" class="nav" onclick={() => openConversation(r.id)}>
              {t("moderation.open")}
            </button>
          </li>
        {/each}
      </ul>
      <p class="help">{t("moderation.top_help", { hours: thread.top.hours })}</p>
    {/if}
  </div>

  <div class="block">
    <h3 class="subtitle">{t("moderation.help")}</h3>
    {#if thread.help === null}
      <p class="failed">{t("moderation.help_failed")}</p>
    {:else}
      <p class="help">{t("moderation.help_intro", { hours: thread.help.hours })}</p>
      {#if !thread.help.rows.length}
        <p class="help">{t("moderation.nobody_stuck")}</p>
      {:else}
        <table class="rank-table">
          <thead>
            <tr>
              <th>{t("moderation.col.exercise")}</th><th>{t("moderation.col.where")}</th>
              <th>{t("moderation.col.people")}</th>
              <th>{t("moderation.col.opened")}</th><th>{t("moderation.col.since")}</th>
            </tr>
          </thead>
          <tbody>
            {#each thread.help.rows as row (row.exercise_id + "#" + row.step + "#" + row.blocked_kind)}
              <tr>
              <td>{exerciseLabel(row.exercise_id)}</td>
              <td>
                {stepLabel(row.step) + (row.blocked_kind ? " — " + blockedLabel(row.blocked_kind) : "")}
              </td>
              <td class="num">{row.people}</td>
                <td class="num">{t("moderation.opened", { opened: row.opened, people: row.people })}</td>
                <td>{localTime(row.since)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="help">{t("moderation.help_note")}</p>
      {/if}
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">{t("moderation.reports")}</h3>
    {#if thread.reports === null}
      <p class="failed">{t("moderation.reports_failed")}</p>
    {:else if !thread.reports.length}
      <p class="help">{t("moderation.no_reports")}</p>
    {:else}
      <ul class="thread">
        {#each thread.reports as s (s.id)}
          <li class="message">
            <p class="who">
              <span class="author">{s.exercise_id}</span>
              <time class="when">{localTime(s.created_at)}</time>
              <span class="state">
                {t("moderation.report_count", { count: s.report_count }) +
                  (s.hidden ? t("moderation.hidden") : "")}
              </span>
            </p>
            <Markdown source={s.text} />
            <div class="row">
              {#if s.hidden}
                <button type="button" class="nav" onclick={() => thread.moderate(s.id, "restore")}>
                  {t("moderation.restore")}
                </button>
              {:else}
                <button type="button" class="nav" onclick={() => thread.moderate(s.id, "hide")}>
                  {t("moderation.hide")}
                </button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">{t("moderation.names")}</h3>
    {#if thread.reportedNames === null}
      <p class="failed">{t("moderation.names_failed")}</p>
    {:else if !thread.reportedNames.length}
      <p class="help">{t("moderation.no_names")}</p>
    {:else}
      <ul class="thread">
        {#each thread.reportedNames as n (n.id)}
          <li class="message">
            <p class="who">
              <span class="author">{n.display_name || t("moderation.name_erased")}</span>
              {#if n.group_number}<span class="group">{groupNumber(n.group_number)}</span>{/if}
              <time class="when">{localTime(n.created_at)}</time>
              <span class="state">{t("moderation.report_count", { count: n.report_count })}</span>
            </p>
            <div class="row">
              <button type="button" class="nav" onclick={() => thread.clearName(n.id)}>
                {t("moderation.clear_name")}
              </button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
