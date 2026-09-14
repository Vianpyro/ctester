<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
  import { CHAT_GENERAL, CHAT_PREFIX, bareExercise } from "../../lib/api/forum";
  import { thread } from "./thread.svelte";
  import type { SearchResult } from "../../lib/api/types";

  interface Props {
    rows: SearchResult[];
    empty: string;
  }

  const { rows, empty }: Props = $props();

  function readableThread(key: string): string {
    if (key === CHAT_GENERAL) return "# général";
    const bare = bareExercise(key);
    const found = catalog.catalog.find((t) => t.id === bare);
    const name = found ? found.short || found.label : bare;
    return key.startsWith(CHAT_PREFIX) ? "# " + name : "Mes questions — " + name;
  }
</script>

{#if !rows.length}
  {#if empty}<p class="aide">{empty}</p>{/if}
{:else}
  <ul class="fil">
    {#each rows as r (r.id)}
      <li class="message">
        <p class="qui">
          <span class="auteur">{readableThread(r.exercise_id)}</span>
          {#if r.replies}
            <span class="tag accent">{r.replies > 1 ? r.replies + " réponses" : "1 réponse"}</span>
          {:else}
            <span class="tag">sans réponse</span>
          {/if}
          {#if r.upvotes}<span class="tag">{r.upvotes} × même question</span>{/if}
        </p>
        <p class="extrait">{r.extrait}</p>
        <button type="button" class="nav" onclick={() => thread.openPermalink(r.id)}>
          Ouvrir
        </button>
      </li>
    {/each}
  </ul>
{/if}
