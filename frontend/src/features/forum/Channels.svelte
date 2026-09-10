<script lang="ts">
  // TWO CHANNELS, AND THAT IS ALL ONE CHOOSES.
  //
  // There used to be a three-button "Où écrire" panel -- "Chat de l'exercice", "Chat
  // général", "Forum de l'exercice" -- so three doors, TWO OF WHICH CARRIED THE SAME
  // WORD, to be settled BEFORE writing a line. A first-session student arrives from
  // Discord, Teams and Instagram: they know a LIST OF CHANNELS, and nowhere a separate
  // place for "the same question, but private". So the private case became a checkbox
  // under the field -- a choice made while writing, when one finally knows what one is
  // writing.
  //
  // "MES QUESTIONS À L'ENSEIGNANT" IS NOT A CHANNEL, and it must not look like one: it
  // is where one REREADS what was sent privately, and the answer.

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
      <!-- THE ACTIVE STATE IS SAID TO THE MACHINE TOO. The three old tabs carried no ARIA
           attribute: a screen reader announced three identical buttons, only one of which
           counted. -->
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

<!-- THE COURSE DISCORD EXISTS, AND SAYING NOTHING ABOUT IT DOES NOT MAKE IT GO AWAY. The
     button is where one looks for "where do we talk", that is to say in the channel
     list. Absent if the deployment declares none. -->
{#if session.discordUrl}
  <a class="nav discordlien" href={session.discordUrl} target="_blank" rel="noopener noreferrer">
    Discord du cours ↗
  </a>
{/if}
