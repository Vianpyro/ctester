<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
  import { t } from "../../lib/i18n.svelte";
  import { session } from "../../lib/auth/session.svelte";
  import { unread } from "../../lib/state/unread.svelte";
  import { CHAT_GENERAL, CHAT_PREFIX } from "../../lib/api/forum";
  import { thread } from "./thread.svelte";

  const here = $derived(catalog.catalog.find((ex) => ex.id === thread.currentExercise));
  const entries = $derived([
    ["chat-general", t("forum.general"), t("channels.general_about"), CHAT_GENERAL] as const,
    ...(here
      ? [
          [
            "chat-ex",
            t("forum.channel", { name: here.short || here.id }),
            t("channels.exercise_about"),
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
            aria-label={t("topbar.unread")}
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
    {isPrivate ? t("channels.back") : t("channels.mine")}
    {#if !isPrivate && unread.has(thread.currentExercise)}
      <span class="pill" aria-label={t("topbar.unread")}></span>
    {/if}
  </button>
{/if}

{#if session.discordUrl}
  <a class="nav discordlink" href={session.discordUrl} target="_blank" rel="noopener noreferrer">
    {t("channels.discord")}
  </a>
{/if}
