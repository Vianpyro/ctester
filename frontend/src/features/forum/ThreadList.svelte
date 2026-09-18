<script lang="ts">
  import { thread } from "./thread.svelte";
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
    ["resolved", "résolue", "accent"],
    ["answered", "répondue", "outline"],
    ["unanswered", "sans réponse", ""],
  ];
</script>

<div class="block">
  <h3 class="subtitle">{thread.permalink ? "Une conversation" : "Le fil"}</h3>

  {#if thread.permalink}
    <button type="button" class="nav" onclick={() => thread.backToThread()}>
      Revenir au fil
    </button>
  {/if}

  {#if !messages.length}
    <p class="help">
      {thread.isChat
        ? "Personne n'a encore écrit ici. Une question, même « bête », en débloque souvent plusieurs."
        : "Personne n'a encore écrit sur cet exercice. Une question bien posée en aide souvent plusieurs."}
    </p>
  {:else}
    {#if thread.state}
      <div class="threadstate">
        {#each STATE_WORDS as [field, word, extra]}
          {#if thread.state[field]}
            <span class={"tag " + extra}>{word}</span>
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
