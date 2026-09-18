<script lang="ts">
  import { groupNumber, localTime } from "../../lib/domain/labels";
  import { thread } from "./thread.svelte";
  import Markdown from "./Markdown.svelte";
  import type { ForumMessage } from "../../lib/api/types";

  interface Props {
    message: ForumMessage;
    reply?: boolean;
  }

  const { message: m, reply = false }: Props = $props();

  const isReply = $derived(!!m.reply_to);
  const stepLabel = (id: string) => thread.steps.find((s) => s.id === id)?.title ?? id;
</script>

<li
  class={"message" +
    (m.retained ? " retained" : "") +
    (m.visibility === "private" ? " private" : "") +
    (reply ? " answer" : "")}
>
  <p class="who">
    {#if m.retained}<span class="tag accent">réponse retenue</span>{/if}
    <span class="author">{m.author}</span>
    {#if m.group}<span class="group">{groupNumber(m.group)}</span>{/if}
    <time class="when" datetime={String(m.created_at).replace(" ", "T")}>
      {localTime(m.created_at)}
    </time>
    {#if m.hidden}<span class="state">masqué</span>{/if}
    {#if m.visibility === "private"}<span class="tag">privée</span>{/if}
    {#if m.visibility === "group"}<span class="tag">ouverte à ton groupe</span>{/if}
    {#if m.step}<span class="tag">{stepLabel(m.step)}</span>{/if}
  </p>

  <Markdown source={m.text} />

  <div class="row">
    {#if m.mine}
      <button type="button" class="nav" onclick={() => thread.remove(m.id)}>
        Supprimer mon message
      </button>
      {#if m.visibility === "private"}
        <button type="button" onclick={() => thread.openToGroup(m.id)}>
          Rendre visible à mon groupe
        </button>
      {/if}
    {:else}
      <button
        type="button"
        class={m.my_vote === 1 ? "" : "nav"}
        onclick={() => thread.vote(m.id, m.my_vote === 1 ? 0 : 1)}
      >
        {(m.my_vote === 1 ? "✓ " : "") +
          (isReply ? "Ça m'a aidé" : "Moi aussi") +
          (m.upvotes ? " (" + m.upvotes + ")" : "")}
      </button>
      {#if isReply}
        <button
          type="button"
          class="nav"
          onclick={() => thread.vote(m.id, m.my_vote === -1 ? 0 : -1)}
        >
          {(m.my_vote === -1 ? "✓ " : "") +
            "Ça m'a induit en erreur" +
            (m.downvotes ? " (" + m.downvotes + ")" : "")}
        </button>
      {/if}
      <button type="button" class="nav" onclick={() => thread.report(m.id)}>Signaler</button>
    {/if}
    <button type="button" class="nav" onclick={() => (thread.replyTo = m.id)}>Répondre</button>
    {#if m.mine && m.upvotes}
      <span class="tag">
        {m.upvotes} personne{m.upvotes > 1 ? "s ont" : " a"}
        {isReply ? " trouvé ça utile" : " la même question"}
      </span>
    {/if}
    {#if m.reportable_name}
      <button type="button" class="nav" onclick={() => thread.reportName(m.id)}>
        Signaler le nom
      </button>
    {/if}
    {#if thread.moderator}
      {#if m.hidden}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "restore")}>
          Rétablir
        </button>
      {:else}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "hide")}>
          Masquer
        </button>
      {/if}
      {#if m.retained}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "unretain")}>
          Ne plus retenir
        </button>
      {:else}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "retain")}>
          Retenir comme réponse
        </button>
      {/if}
    {/if}
  </div>
</li>
