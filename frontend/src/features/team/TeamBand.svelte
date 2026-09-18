<script lang="ts">
  import { collaborators } from "../../lib/state/collaborators.svelte";
  import { room } from "../../lib/collab/room.svelte";
  import { fetchArchive, fetchRevisions, handIn, restoreRevision } from "../../lib/api/team";
  import { localTime } from "../../lib/domain/labels";
  import { system } from "../../lib/state/system.svelte";
  import type { TeamRevision } from "../../lib/api/types";

  let history = $state<{ rows: TeamRevision[]; failed: boolean } | null>(null);
  let previousUrl: string | null = null;

  const context = $derived(room.context);
  const assignment = $derived(context?.assignment);
  const status = $derived(room.status);

  const memberName = (id: string) =>
    collaborators.members.find((m) => m.id === id)?.name ?? "un ancien membre";

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
        "Remettre la version de " +
          memberName(row.author) +
          " du " +
          row.created_at +
          " ? Le code actuel de l'équipe sera remplacé — il reste dans l'historique.",
      )
    ) {
      return;
    }
    const answer = await restoreRevision(room.assignmentId, room.exerciseId, row.id);
    if (!answer.ok) {
      say((answer.body as { error?: string } | null)?.error ?? "La restauration n'a pas abouti.", true);
      return;
    }
    if (answer.body?.sources) room.applyRestored(answer.body.sources);
    history = null;
    say("version restaurée");
  }

  async function downloadArchive() {
    say("");
    let answer: Response;
    try {
      answer = await fetchArchive(room.assignmentId);
    } catch {
      say("Le serveur ne répond pas. Réessaie dans un instant.", true);
      return;
    }
    if (!answer.ok) {
      let body: { error?: string } | null = null;
      try {
        body = (await answer.json()) as { error?: string };
      } catch {
        body = null;
      }
      say(body?.error ?? "L'archive n'a pas pu être construite.", true);
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
    say("archive téléchargée");
  }

  async function submit() {
    if (
      typeof confirm === "function" &&
      !confirm(
        "Remettre le devoir au nom de toute l'équipe ? Tes coéquipiers verront la remise, " +
          "et vous pourrez la refaire jusqu'à la date limite.",
      )
    ) {
      return;
    }
    const answer = await handIn(room.assignmentId);
    if (!answer.ok) {
      say((answer.body as { error?: string } | null)?.error ?? "La remise n'a pas abouti.", true);
      return;
    }
    if (room.context) room.context.submission = answer.body?.submission ?? {};
    say("devoir remis pour l'équipe");
  }

  function deadlineWord(): string {
    if (!assignment?.deadline) return "";
    const when = new Date(assignment.deadline);
    if (isNaN(when.getTime())) return "à remettre";
    return (
      (assignment.deadline_passed ? "remise close le " : "à remettre le ") +
      when.toLocaleDateString(undefined, { day: "numeric", month: "long" }) +
      " à " +
      when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    );
  }
</script>

{#if room.refusal}
  <div class="teamhead">
    <b class="teamtitle">Devoir</b>
    <span class="tag failed">pas d'espace d'équipe</span>
  </div>
  <p class="help">{room.refusal}</p>
{:else if context && assignment}
  <div class="teamhead">
    <b class="teamtitle">{assignment.title}</b>
    {#if assignment.deadline}
      <span class={"tag" + (assignment.deadline_passed ? " failed" : "")}>{deadlineWord()}</span>
    {/if}
    <span class="tag">{context.team.label}</span>
    <span class="tag">groupe {String(context.team.group_number).padStart(2, "0")}</span>
  </div>

  <div class="teamwho">
    {#each collaborators.members as member (member.id)}
      {@const online = member.you || collaborators.online.includes(member.id)}
      <span class={"mate" + (online ? " on" : "")} title={online ? "en ligne" : "hors ligne"}>
        <i class="dot" style={"background:" + member.color}></i>
        <span>{member.name}{member.you ? " (toi)" : ""}</span>
      </span>
    {/each}
    <span class="grow"></span>
    <span class={"state" + (status.bad ? " failed" : "")}>{status.text}</span>
  </div>

  <div class="teamactions">
    <button type="button" class="nav" onclick={toggleHistory}>Historique</button>
    {#if assignment.handin.length}
      <button type="button" class="nav" onclick={downloadArchive}>Télécharger le ZIP</button>
      <button
        type="button"
        class="nav"
        disabled={assignment.deadline_passed}
        title={assignment.deadline_passed ? "la date de remise est passée" : undefined}
        onclick={submit}
      >
        {context.submission?.submitted_at ? "Remettre à nouveau" : "Remettre le devoir"}
      </button>
    {/if}
    {#if context.submission?.submitted_at}
      <span class="tag ok">remis le {context.submission.submitted_at.replace("T", " à ")}</span>
    {/if}
    <span class="grow"></span>
    <span class="help">{room.note}</span>
  </div>

  {#if history}
    <div class="teamhistory">
      <h3>Historique partagé</h3>
      {#if history.failed}
        <p class="help">
          L'historique n'est pas disponible pour l'instant. Ton code, lui, continue d'être
          enregistré.
        </p>
      {:else if !history.rows.length}
        <p class="help">
          Rien encore. Une version est gardée à chaque fois que l'un de vous travaille sur
          cet exercice.
        </p>
      {:else}
        {#each history.rows as row (row.id)}
          <div class="revline">
            <span class="who">{memberName(row.author)}</span>
            <time class="when">{localTime(row.created_at)}</time>
            <span class="tag">{Math.round(row.bytes / 100) / 10} Ko</span>
            <span class="grow"></span>
            <button type="button" class="nav" onclick={() => restore(row)}>Restaurer</button>
          </div>
        {/each}
      {/if}
    </div>
  {/if}
{/if}
