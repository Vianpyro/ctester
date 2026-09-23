<script lang="ts">
  import { collaborators } from "../../lib/state/collaborators.svelte";
  import { room } from "../../lib/collab/room.svelte";
  import { fetchArchive, fetchRevisions, handIn, restoreRevision } from "../../lib/api/team";
  import { groupNumber, localTime, memberName, teamLabel } from "../../lib/domain/labels";
  import { system } from "../../lib/state/system.svelte";
  import { serverMessage } from "../../lib/api/client";
  import { i18n, t } from "../../lib/i18n.svelte";
  import type { TeamRevision } from "../../lib/api/types";

  let history = $state<{ rows: TeamRevision[]; failed: boolean } | null>(null);
  let previousUrl: string | null = null;

  const context = $derived(room.context);
  const assignment = $derived(context?.assignment);
  const status = $derived(room.status);

  const authorName = (id: string) => {
    const member = collaborators.members.find((m) => m.id === id);
    return member ? memberName(member) : t("team.former_member");
  };

  function say(text: string, bad = false) {
    room.note = text;
    if (bad) system.say(text, true);
  }

  async function toggleHistory() {
    if (history) {
      history = null;
      return;
    }
    const answer = await fetchRevisions(room.assignmentId, room.exerciseId);
    history =
      answer && Array.isArray(answer.revisions)
        ? { rows: answer.revisions, failed: false }
        : { rows: [], failed: true };
  }

  async function restore(row: TeamRevision) {
    if (
      typeof confirm === "function" &&
      !confirm(
        t("team.restore_confirm", { who: authorName(row.author), date: localTime(row.created_at) }),
      )
    ) {
      return;
    }
    const answer = await restoreRevision(room.assignmentId, room.exerciseId, row.id);
    if (!answer.ok) {
      say(serverMessage(answer.body) || t("team.restore_failed"), true);
      return;
    }
    if (answer.body?.sources) room.applyRestored(answer.body.sources);
    history = null;
    say(t("team.restored"));
  }

  async function downloadArchive() {
    say("");
    let answer: Response;
    try {
      answer = await fetchArchive(room.assignmentId);
    } catch {
      say(t("submit.no_answer"), true);
      return;
    }
    if (!answer.ok) {
      let body: unknown = null;
      try {
        body = await answer.json();
      } catch {
        body = null;
      }
      say(serverMessage(body) || t("team.archive_failed"), true);
      return;
    }
    const blob = await answer.blob();
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    previousUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = previousUrl;
    link.download = room.assignmentId + ".zip";
    document.body.append(link);
    link.click();
    link.remove();
    say(t("team.archive_done"));
  }

  async function submit() {
    if (
      typeof confirm === "function" &&
      !confirm(t("team.handin_confirm"))
    ) {
      return;
    }
    const answer = await handIn(room.assignmentId);
    if (!answer.ok) {
      say(serverMessage(answer.body) || t("team.handin_failed"), true);
      return;
    }
    if (room.context) room.context.submission = answer.body?.submission ?? {};
    say(t("team.handed_in"));
  }

  function deadlineWord(): string {
    if (!assignment?.deadline) return "";
    const when = new Date(assignment.deadline);
    if (isNaN(when.getTime())) return t("team.due");
    return t(assignment.deadline_passed ? "team.closed_on" : "team.due_on", {
      date: when.toLocaleDateString(i18n.lang, { day: "numeric", month: "long" }),
      time: when.toLocaleTimeString(i18n.lang, { hour: "2-digit", minute: "2-digit" }),
    });
  }
</script>

{#if room.refusal}
  <div class="teamhead">
    <b class="teamtitle">{t("team.assignment")}</b>
    <span class="tag failed">{t("team.no_space")}</span>
  </div>
  <p class="help">{room.refusal}</p>
{:else if context && assignment}
  <div class="teamhead">
    <b class="teamtitle">{assignment.title}</b>
    {#if assignment.deadline}
      <span class={"tag" + (assignment.deadline_passed ? " failed" : "")}>{deadlineWord()}</span>
    {/if}
    <span class="tag">{teamLabel(context.team.number)}</span>
    <span class="tag">{groupNumber(context.team.group_number)}</span>
  </div>

  <div class="teamwho">
    {#each collaborators.members as member (member.id)}
      {@const online = member.you || collaborators.online.includes(member.id)}
      <span class={"mate" + (online ? " on" : "")} title={online ? t("team.online") : t("team.offline_short")}>
        <i class="dot" style={"background:" + member.color}></i>
        <span>{memberName(member)}{member.you ? t("team.you") : ""}</span>
      </span>
    {/each}
    <span class="grow"></span>
    <span class={"state" + (status.bad ? " failed" : "")}>{status.text}</span>
  </div>

  <div class="teamactions">
    <button type="button" class="nav" onclick={toggleHistory}>{t("team.history")}</button>
    {#if assignment.handin.length}
      <button type="button" class="nav" onclick={downloadArchive}>{t("team.download")}</button>
      <button
        type="button"
        class="nav"
        disabled={assignment.deadline_passed}
        title={assignment.deadline_passed ? t("team.deadline_passed") : undefined}
        onclick={submit}
      >
        {context.submission?.submitted_at ? t("team.hand_in_again") : t("team.hand_in")}
      </button>
    {/if}
    {#if context.submission?.submitted_at}
      <span class="tag ok"
        >{t("team.handed_in_on", {
          date: context.submission.submitted_at.split("T")[0] ?? "",
          time: context.submission.submitted_at.split("T")[1] ?? "",
        })}</span
      >
    {/if}
    <span class="grow"></span>
    <span class="help">{room.note}</span>
  </div>

  {#if history}
    <div class="teamhistory">
      <h3>{t("team.shared_history")}</h3>
      {#if history.failed}
        <p class="help">{t("team.history_unavailable")}</p>
      {:else if !history.rows.length}
        <p class="help">{t("team.history_empty")}</p>
      {:else}
        {#each history.rows as row (row.id)}
          <div class="revline">
            <span class="who">{authorName(row.author)}</span>
            <time class="when">{localTime(row.created_at)}</time>
            <span class="tag">{t("team.kb", { n: Math.round(row.bytes / 100) / 10 })}</span>
            <span class="grow"></span>
            <button type="button" class="nav" onclick={() => restore(row)}>{t("team.restore")}</button>
          </div>
        {/each}
      {/if}
    </div>
  {/if}
{/if}
