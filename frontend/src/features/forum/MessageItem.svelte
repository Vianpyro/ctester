<script lang="ts">
  // ONE MESSAGE. Four things on it are STATES THE READER CAN ACT ON rather than
  // decorations:
  //
  //   * "réponse retenue" -- the answer a moderator stands behind, derived from the
  //     append-only journal, so PINNING EDITS NOTHING: a message is immutable, which is
  //     what keeps a report readable.
  //   * "Ça m'a aidé" / "Moi aussi" -- a usefulness counter, deduplicated per account by
  //     the database. IT GRANTS NO XP: a message written to be upvoted is a message
  //     written for the counter.
  //   * "privée" / "ouverte à ton groupe" -- who can read a "bloqué ici".
  //   * "Rendre visible à mon groupe" -- THE ONE transition, and only on one's own
  //     private message. The server refuses the reverse; this simply does not offer it.
  //
  // THE AUTHOR IS A WORD, NOT AN ID: "Vous", the masked alias, a chosen name or
  // "Enseignant", all derived by the server. Nothing here lets two messages be tied
  // back to the same student.
  //
  // EVERY STATE IS SPELLED OUT, not only tinted: a state that only reads through colour
  // does not read at all for some people.

  import { groupNumber, localTime } from "../../lib/domain/labels";
  import { thread } from "./thread.svelte";
  import Markdown from "./Markdown.svelte";
  import type { ForumMessage } from "../../lib/api/types";

  interface Props {
    message: ForumMessage;
    /** A reply, drawn under its root. */
    reply?: boolean;
  }

  const { message: m, reply = false }: Props = $props();

  const isReply = $derived(!!m.reply_to);
  const stepLabel = (id: string) => thread.steps.find((s) => s.id === id)?.title ?? id;
</script>

<li
  class={"message" +
    (m.retained ? " retenue" : "") +
    (m.visibility === "private" ? " privee" : "") +
    (reply ? " reponse" : "")}
>
  <p class="qui">
    {#if m.retained}<span class="tag accent">réponse retenue</span>{/if}
    <span class="auteur">{m.author}</span>
    {#if m.group}<span class="groupe">{groupNumber(m.group)}</span>{/if}
    <time class="quand" datetime={String(m.created_at).replace(" ", "T")}>
      {localTime(m.created_at)}
    </time>
    {#if m.hidden}<span class="etat">masqué</span>{/if}
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
      <!-- THE ESCAPE HATCH: a private question nobody answered is one that can be opened
           to the group, in a click and without republishing it. The reverse is neither
           offered nor accepted. -->
      {#if m.visibility === "private"}
        <button type="button" onclick={() => thread.openToGroup(m.id)}>
          Rendre visible à mon groupe
        </button>
      {/if}
    {:else}
      <!-- THE VOTE IS NOT OFFERED ON ONE'S OWN MESSAGE -- the server refuses it in SQL,
           and a button that always fails is a button that lies.
           ON A QUESTION, +1 READS "moi aussi"; ON A REPLY, "ça m'a aidé" and its
           opposite. The -1 is not drawn on a root, but that is NOT what forbids it: the
           `WHERE` of the statement is. A question cannot be buried by a vote, which is
           the promise of a place built for people afraid to ask. -->
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
    <!-- REPLYING IS OFFERED ON EVERY VISIBLE MESSAGE, one's own included: one completes
         one's own question without publishing a second. -->
    <button type="button" class="nav" onclick={() => (thread.replyTo = m.id)}>Répondre</button>
    {#if m.mine && m.upvotes}
      <span class="tag">
        {m.upvotes} personne{m.upvotes > 1 ? "s ont" : " a"}
        {isReply ? " trouvé ça utile" : " la même question"}
      </span>
    {/if}
    <!-- ONLY WHAT IS DISPLAYED CAN BE REPORTED: the button only exists on a name somebody
         chose. "Participant" cannot be reported, there is nothing in it. -->
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
      <!-- RETAINING EDITS NOTHING: the action goes into the append-only journal and the
           latest one wins -- so it is reversible, and it is journalled. -->
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
