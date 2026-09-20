<script lang="ts">
  import { exercise } from "../lib/state/exercise.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import StatementBody from "./StatementBody.svelte";

  const shown = $derived(exercise.statements);
  const closed = $derived(lockNote(catalog.selected));
</script>

<details id="statement" open>
  <summary class="phead">Consigne</summary>
  {#if closed}
    <p class="preview">🔒 Invisible pour les étudiants — {closed}.</p>
  {/if}
  {#each shown as one (one.id + "|" + one.title)}
    {#if one.title}
      <h3 class="stitle">{one.title}</h3>
    {/if}
    <StatementBody current={one.state} />
  {/each}
</details>

<style>
  .preview {
    margin: 0.6rem 0.6rem 0;
    padding: 0.35rem 0.6rem;
    border: 1px solid var(--wait);
    border-radius: var(--coin);
    color: var(--wait);
    font-size: 0.9em;
  }
</style>
