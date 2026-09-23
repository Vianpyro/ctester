<script lang="ts">
  import { groupNumber, localTime } from "../../lib/domain/labels";
  import { t } from "../../lib/i18n.svelte";
  import { thread } from "./thread.svelte";
  import Markdown from "./Markdown.svelte";
  import { stepLabel } from "./labels";
  import type { ForumMessage } from "../../lib/api/types";

  interface Props {
    message: ForumMessage;
    reply?: boolean;
  }

  const { message: m, reply = false }: Props = $props();

  const isReply = $derived(!!m.reply_to);

  function authorLabel(message: ForumMessage): string {
    if (message.role === "me") {
      return message.author
        ? t("forum.author.me_as", { alias: message.author })
        : t("forum.author.me");
    }
    if (message.role === "teacher") return t("forum.author.teacher");
    return message.author || t("identity.participant");
  }
</script>

<li
  class={"message" +
    (m.retained ? " retained" : "") +
    (m.visibility === "private" ? " private" : "") +
    (reply ? " answer" : "")}
>
  <p class="who">
    {#if m.retained}<span class="tag accent">{t("message.retained")}</span>{/if}
    <span class="author">{authorLabel(m)}</span>
    {#if m.group}<span class="group">{groupNumber(m.group)}</span>{/if}
    <time class="when" datetime={String(m.created_at).replace(" ", "T")}>
      {localTime(m.created_at)}
    </time>
    {#if m.hidden}<span class="state">{t("message.hidden")}</span>{/if}
    {#if m.visibility === "private"}<span class="tag">{t("moderation.private")}</span>{/if}
    {#if m.visibility === "group"}<span class="tag">{t("message.group")}</span>{/if}
    {#if m.step}<span class="tag">{stepLabel(m.step)}</span>{/if}
  </p>

  <Markdown source={m.text} />

  <div class="row">
    {#if m.mine}
      <button type="button" class="nav" onclick={() => thread.remove(m.id)}>
        {t("message.delete")}
      </button>
      {#if m.visibility === "private"}
        <button type="button" onclick={() => thread.openToGroup(m.id)}>
          {t("message.open_group")}
        </button>
      {/if}
    {:else}
      <button
        type="button"
        class={m.my_vote === 1 ? "" : "nav"}
        onclick={() => thread.vote(m.id, m.my_vote === 1 ? 0 : 1)}
      >
        {(m.my_vote === 1 ? "✓ " : "") +
          (isReply ? t("message.helped") : t("message.me_too")) +
          (m.upvotes ? " (" + m.upvotes + ")" : "")}
      </button>
      {#if isReply}
        <button
          type="button"
          class="nav"
          onclick={() => thread.vote(m.id, m.my_vote === -1 ? 0 : -1)}
        >
          {(m.my_vote === -1 ? "✓ " : "") +
            t("message.misled") +
            (m.downvotes ? " (" + m.downvotes + ")" : "")}
        </button>
      {/if}
      <button type="button" class="nav" onclick={() => thread.report(m.id)}>{t("message.report")}</button>
    {/if}
    <button type="button" class="nav" onclick={() => (thread.replyTo = m.id)}>{t("composer.answer")}</button>
    {#if m.mine && m.upvotes}
      <span class="tag">
        {t(isReply ? "message.useful" : "message.same", { count: m.upvotes })}
      </span>
    {/if}
    {#if m.reportable_name}
      <button type="button" class="nav" onclick={() => thread.reportName(m.id)}>
        {t("message.report_name")}
      </button>
    {/if}
    {#if thread.moderator}
      {#if m.hidden}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "restore")}>
          {t("moderation.restore")}
        </button>
      {:else}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "hide")}>
          {t("moderation.hide")}
        </button>
      {/if}
      {#if m.retained}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "unretain")}>
          {t("message.unretain")}
        </button>
      {:else}
        <button type="button" class="nav" onclick={() => thread.moderate(m.id, "retain")}>
          {t("message.retain")}
        </button>
      {/if}
    {/if}
  </div>
</li>
