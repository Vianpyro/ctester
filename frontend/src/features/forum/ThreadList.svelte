<script lang="ts">
  import { thread } from "./thread.svelte";
  import { t } from "../../lib/i18n.svelte";
  import MessageItem from "./MessageItem.svelte";

  const messages = $derived(thread.messages ?? []);
  const roots = $derived(messages.filter((m) => !m.reply_to));
  const ordered = $derived([
    ...roots.filter((m) => m.retained),
    ...roots.filter((m) => !m.retained),
  ]);
  const repliesOf = $derived.by(() => {
    const byRoot: Record<string, typeof messages> = {};
    for (const m of messages) {
      if (!m.reply_to) continue;
      (byRoot[m.reply_to] ??= []).push(m);
    }
    return byRoot;
  });

  const STATE_WORDS: [keyof NonNullable<typeof thread.state>, string, string][] = [
    ["resolved", "thread.resolved", "accent"],
    ["answered", "thread.answered", "outline"],
    ["unanswered", "moderation.no_reply", ""],
  ];
</script>

<div class="block">
  <h3 class="subtitle">{thread.permalink ? t("thread.conversation") : t("thread.thread")}</h3>

  {#if thread.permalink}
    <button type="button" class="nav" onclick={() => thread.backToThread()}>
      {t("thread.back")}
    </button>
  {/if}

  {#if !messages.length}
    <p class="help">
      {thread.isChat ? t("thread.empty_chat") : t("thread.empty_forum")}
    </p>
  {:else}
    {#if thread.state}
      <div class="threadstate">
        {#each STATE_WORDS as [field, word, extra]}
          {#if thread.state[field]}
            <span class={"tag " + extra}>{t(word)}</span>
          {/if}
        {/each}
      </div>
    {/if}
    <ul class="thread">
      {#each ordered as root (root.id)}
        <MessageItem message={root} />
        {#each repliesOf[root.id] ?? [] as answer (answer.id)}
          <MessageItem message={answer} reply />
        {/each}
      {/each}
    </ul>
  {/if}
</div>
