<script lang="ts">
  import { readableThread } from "./labels";
  import { t } from "../../lib/i18n.svelte";
  import { thread } from "./thread.svelte";
  import type { SearchResult } from "../../lib/api/types";

  interface Props {
    rows: SearchResult[];
    empty: string;
  }

  const { rows, empty }: Props = $props();

</script>

{#if !rows.length}
  {#if empty}<p class="help">{empty}</p>{/if}
{:else}
  <ul class="thread">
    {#each rows as r (r.id)}
      <li class="message">
        <p class="who">
          <span class="author">{readableThread(r.exercise_id)}</span>
          {#if r.replies}
            <span class="tag accent">{t("moderation.replies", { count: r.replies })}</span>
          {:else}
            <span class="tag">{t("moderation.no_reply")}</span>
          {/if}
          {#if r.upvotes}<span class="tag">{t("search.same_question", { n: r.upvotes })}</span>{/if}
        </p>
        <p class="excerpt">{r.excerpt}</p>
        <button type="button" class="nav" onclick={() => thread.openPermalink(r.id)}>
          {t("search.open")}
        </button>
      </li>
    {/each}
  </ul>
{/if}
