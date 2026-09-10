<script lang="ts">
  // THE THREAD ITSELF, FLAT AND ONE LEVEL DEEP. `reply_to` ALWAYS carries the ROOT (the
  // server flattens with `COALESCE(t.reply_to, t.message_id)` in SQL), so there is no
  // recursion here and no depth to bound -- which is exactly why the column can be a
  // narrow dock.
  //
  // RETAINED FIRST, THEN CHRONOLOGICAL. A thread opened for an answer must not scroll
  // past nine messages before the one the course stands behind -- and the rest keeps its
  // order, since a discussion read out of order is no longer a discussion.

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

  /** THE THREAD'S STATE, as three counters the server derived from what THIS caller can
   *  see. Not a filter: with one thread per exercise there is nothing to filter, and
   *  tabs would promise a list that does not exist. */
  const STATE_WORDS: [keyof NonNullable<typeof thread.state>, string, string][] = [
    ["resolved", "résolue", "accent"],
    ["answered", "répondue", "contour"],
    ["unanswered", "sans réponse", ""],
  ];
</script>

<div class="bloc">
  <h3 class="soustitre">{thread.permalink ? "Une conversation" : "Le fil"}</h3>

  {#if thread.permalink}
    <!-- ARRIVED HERE FROM THE SEARCH. The back button is the only way out: without it
         one would read an isolated conversation with no way back to the thread. -->
    <button type="button" class="nav" onclick={() => thread.backToThread()}>
      Revenir au fil
    </button>
  {/if}

  {#if !messages.length}
    <p class="aide">
      {thread.isChat
        ? "Personne n'a encore écrit ici. Une question, même « bête », en débloque souvent plusieurs."
        : "Personne n'a encore écrit sur cet exercice. Une question bien posée en aide souvent plusieurs."}
    </p>
  {:else}
    {#if thread.state}
      <div class="etatfil">
        {#each STATE_WORDS as [field, word, extra]}
          {#if thread.state[field]}
            <span class={"tag " + extra}>{word}</span>
          {/if}
        {/each}
      </div>
    {/if}
    <ul class="fil">
      {#each ordered as root (root.id)}
        <MessageItem message={root} />
        {#each repliesOf[root.id] ?? [] as answer (answer.id)}
          <MessageItem message={answer} reply />
        {/each}
      {/each}
    </ul>
  {/if}
</div>
