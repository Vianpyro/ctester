<script lang="ts">
  import { room } from "../../lib/collab/room.svelte";
  import { sendToGitHub, unlinkGitHub } from "../../lib/api/github";
  import { serverMessage } from "../../lib/api/client";
  import { GITHUB_STATE_KEY, RETURN_KEY } from "../../lib/auth/keys";
  import { localTime } from "../../lib/domain/labels";
  import { system } from "../../lib/state/system.svelte";
  import { sessionSet } from "../../lib/storage";
  import { t } from "../../lib/i18n.svelte";

  const github = $derived(room.context?.github);
  let message = $state("");
  let sending = $state(false);

  // No scope is asked: the server only learns who the student is on GitHub.
  function link() {
    if (!github) return;
    const state = crypto.randomUUID();
    sessionSet(GITHUB_STATE_KEY, state);
    sessionSet(RETURN_KEY, location.search);
    const params = new URLSearchParams({ client_id: github.client_id, state });
    location.assign("https://github.com/login/oauth/authorize?" + params.toString());
  }

  async function unlink() {
    if (typeof confirm === "function" && !confirm(t("github.unlink_confirm"))) return;
    const answer = await unlinkGitHub();
    if (!answer.ok) {
      system.say(serverMessage(answer.body) || t("github.send_failed"), true);
      return;
    }
    if (room.context?.github) room.context.github.login = "";
  }

  async function send(event: SubmitEvent) {
    event.preventDefault();
    sending = true;
    const answer = await sendToGitHub(room.assignmentId, message);
    sending = false;
    if (!answer.ok) {
      system.say(serverMessage(answer.body) || t("github.send_failed"), true);
      return;
    }
    if (answer.body?.github && room.context) room.context.github = answer.body.github;
    if (answer.body?.sha) message = "";
    room.note = answer.body?.sha ? t("github.sent") : t("github.nothing_new");
  }
</script>

{#if github}
  <div class="teamgithub">
    {#if github.login}
      <span class="tag">{t("github.linked_as", { login: github.login })}</span>
      {#if github.repo_url}
        <a href={github.repo_url} target="_blank" rel="noopener noreferrer">{t("github.open_repo")}</a>
      {/if}
      <span class="help">
        {github.synced_at
          ? t("github.synced_at", { time: localTime(github.synced_at) })
          : t("github.not_yet", { minutes: github.idle })}
      </span>
      <form class="githubsend" onsubmit={send}>
        <input
          type="text"
          maxlength="72"
          bind:value={message}
          aria-label={t("github.message_label")}
          placeholder={t("github.message_placeholder")}
        />
        <button type="submit" class="nav" disabled={sending}>{t("github.send")}</button>
      </form>
      <button type="button" class="nav" onclick={unlink}>{t("github.unlink")}</button>
    {:else}
      <button type="button" class="nav" onclick={link}>{t("github.link")}</button>
      <span class="help">{t("github.link_help")}</span>
    {/if}
  </div>
{/if}
