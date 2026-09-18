<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
  import { session } from "../../lib/auth/session.svelte";
  import { unread } from "../../lib/state/unread.svelte";
  import { CHAT_GENERAL, CHAT_PREFIX } from "../../lib/api/forum";
  import { thread } from "./thread.svelte";

  const here = $derived(catalog.catalog.find((t) => t.id === thread.currentExercise));
  const entries = $derived([
    ["chat-general", "# général", "Tout le cours, tous sujets.", CHAT_GENERAL] as const,
    ...(here
      ? [
          [
            "chat-ex",
            "# " + (here.short || here.id),
            "Le chat de l'exercice ouvert.",
            CHAT_PREFIX + here.id,
          ] as const,
        ]
      : []),
  ]);
  const isPrivate = $derived(thread.mode === "forum");
</script>

<ul class="channels">
  {#each entries as [mode, label, about, key]}
    <li>
      <button
        type="button"
        class={thread.mode === mode ? "" : "nav"}
        title={about}
        aria-current={thread.mode === mode}
        onclick={() => thread.openChannel(mode)}
        >{label}{#if unread.has(key)}<span
            class="pill"
            aria-label="Des messages non lus"
          ></span>{/if}</button
      >
    </li>
  {/each}
</ul>

{#if thread.currentExercise}
  <button
    type="button"
    class="nav"
    onclick={() => thread.openChannel(isPrivate ? "chat-ex" : "forum")}
  >
    {isPrivate ? "← Revenir au chat" : "Mes questions à l'enseignant"}
    {#if !isPrivate && unread.has(thread.currentExercise)}
      <span class="pill" aria-label="Des messages non lus"></span>
    {/if}
  </button>
{/if}

{#if session.discordUrl}
  <a class="nav discordlink" href={session.discordUrl} target="_blank" rel="noopener noreferrer">
    Discord du cours ↗
  </a>
{/if}
