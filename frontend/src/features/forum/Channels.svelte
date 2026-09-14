<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
  import { session } from "../../lib/auth/session.svelte";
  import { thread } from "./thread.svelte";

  const here = $derived(catalog.catalog.find((t) => t.id === thread.currentExercise));
  const entries = $derived([
    ["chat-general", "# général", "Tout le cours, tous sujets."] as const,
    ...(here
      ? [
          [
            "chat-ex",
            "# " + (here.short || here.id),
            "Le chat de l'exercice ouvert.",
          ] as const,
        ]
      : []),
  ]);
  const isPrivate = $derived(thread.mode === "forum");
</script>

<ul class="canaux">
  {#each entries as [mode, label, about]}
    <li>
      <button
        type="button"
        class={thread.mode === mode ? "" : "nav"}
        title={about}
        aria-current={thread.mode === mode}
        onclick={() => thread.openChannel(mode)}>{label}</button
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
  </button>
{/if}

{#if session.discordUrl}
  <a class="nav discordlien" href={session.discordUrl} target="_blank" rel="noopener noreferrer">
    Discord du cours ↗
  </a>
{/if}
