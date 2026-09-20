<script lang="ts">
  import { readableThread } from "./labels";
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
            <span class="tag accent">{r.replies > 1 ? r.replies + " réponses" : "1 réponse"}</span>
          {:else}
            <span class="tag">sans réponse</span>
          {/if}
          {#if r.upvotes}<span class="tag">{r.upvotes} × même question</span>{/if}
        </p>
        <p class="excerpt">{r.excerpt}</p>
        <button type="button" class="nav" onclick={() => thread.openPermalink(r.id)}>
          Ouvrir
        </button>
      </li>
    {/each}
  </ul>
{/if}
