<script lang="ts">
  // THE DOCK: the chat NEXT TO the code, not instead of it.
  //
  // It lives inside the workbench grid, so it disappears on its own when another
  // destination takes the screen and comes back unchanged on return. No fifth view, no
  // entry in the view arbitration: it is not a destination, it is a column.
  //
  // `#chatdock[hidden] { display: none }` IS OBLIGATORY in the stylesheet: `display:
  // flex` beats `[hidden]`. Same trap as the team band.

  import { onMount } from "svelte";
  import { chat } from "./chat.svelte";
  import { thread } from "./thread.svelte";
  import { CHAT_GENERAL, CHAT_PREFIX, bareExercise } from "../../lib/api/forum";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { session } from "../../lib/auth/session.svelte";
  import Channels from "./Channels.svelte";
  import Composer from "./Composer.svelte";
  import ThreadList from "./ThreadList.svelte";

  // ONE WATCHER WHILE ON SCREEN: the bell reconnects only while somebody is watching,
  // and the release cannot be forgotten because it is the teardown.
  onMount(() => thread.watch());

  function readableThread(key: string): string {
    if (key === CHAT_GENERAL) return "# général";
    const bare = bareExercise(key);
    const found = catalog.catalog.find((t) => t.id === bare);
    const name = found ? found.short || found.label : bare;
    return key.startsWith(CHAT_PREFIX) ? "# " + name : "Mes questions — " + name;
  }
</script>

<div class="chathead">
  <span class="chattitre">{readableThread(thread.key)}</span>
  <span class="grow"></span>
  <!-- "EN GRAND" IS THE ONLY DOOR TO THE WIDE VIEW, and that is why the top bar has one
       button: two entries for two sizes of the same thing were two words to learn for
       one idea. -->
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
    <!-- WE DO NOT INVENT AN EMPTY THREAD: "no messages" during an outage tells somebody
         nobody answered them. -->
    <p class="rate">{thread.error}</p>
  {:else}
    {#if thread.said}
      <p class="annonce" aria-live="polite">{thread.said}</p>
    {/if}
    <ThreadList />
  {/if}
</div>

{#if thread.messages !== null && session.signedIn}
  <Composer compact />
{/if}
