<script lang="ts">
  import { onMount } from "svelte";
  import { chat } from "./chat.svelte";
  import { thread } from "./thread.svelte";
  import { readableThread } from "./labels";
  import { session } from "../../lib/auth/session.svelte";
  import Channels from "./Channels.svelte";
  import Composer from "./Composer.svelte";
  import ThreadList from "./ThreadList.svelte";

  onMount(() => thread.watch());

</script>

<div class="chathead">
  <span class="chattitre">{readableThread(thread.key)}</span>
  <span class="grow"></span>
  <button
    type="button"
    class="nav"
    title="Ouvrir en grand (recherche, historique)"
    aria-label="Ouvrir le chat en grand"
    onclick={() => chat.toggleWide()}>⤢</button
  >
  <button
    type="button"
    class="nav"
    title="Fermer le chat"
    aria-label="Fermer le chat"
    onclick={() => chat.toggleDock()}>✕</button
  >
</div>

<Channels />

<div class="chatflux">
  {#if thread.messages === null}
    <p class="failed">{thread.error}</p>
  {:else}
    {#if thread.said}
      <p class="notice" aria-live="polite">{thread.said}</p>
    {/if}
    <ThreadList />
  {/if}
</div>

{#if thread.messages !== null && session.signedIn}
  <Composer compact />
{/if}
