<script lang="ts">  import { onMount } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { localTime } from "../../lib/domain/labels";
  import { CHAT_GENERAL, CHAT_PREFIX, bareExercise } from "../../lib/api/forum";
  import { chat } from "./chat.svelte";
  import { thread } from "./thread.svelte";
  import Markdown from "./Markdown.svelte";

  let title: HTMLHeadingElement | undefined = $state();

  onMount(() => {
    title?.focus();
  });

  const stepLabel = (id: string) => thread.steps.find((s) => s.id === id)?.title ?? id;
  const blockedLabel = (id: string) => thread.blockedKinds.find((b) => b.id === id)?.title ?? id;
  const exerciseLabel = (id: string) => {
    const found = catalog.catalog.find((t) => t.id === id);
    return found ? found.label || found.short || id : id;
  };
  function readableThread(key: string): string {
    if (key === CHAT_GENERAL) return "# général";
    const bare = bareExercise(key);
    const found = catalog.catalog.find((t) => t.id === bare);
    const name = found ? found.short || found.label : bare;
    return key.startsWith(CHAT_PREFIX) ? "# " + name : "Mes questions — " + name;
  }

  const topRows = $derived((thread.top?.rows ?? []).filter((r) => r.upvotes || !r.replies));

  async function openConversation(id: string) {
    await chat.toggleWide();
    await thread.openPermalink(id);
  }
</script>

<h2 bind:this={title} id="moderationtitle" tabindex="-1">Modération</h2>
<p class="notice" aria-live="polite">{thread.said}</p>

{#if !thread.moderator}
  <p class="failed">Cette page est réservée à la modération.</p>
{:else}
  <div class="block">
    <h3 class="subtitle">Questions du moment</h3>
    {#if !thread.top}
      <p class="failed">Le classement des questions n'a pas pu être lu.</p>
    {:else if !topRows.length}
      <p class="help">Rien qui ressorte sur les dernières {thread.top.hours} heures.</p>
    {:else}
      <ul class="thread">
        {#each topRows.slice(0, 10) as r (r.id)}
          <li class="message">
            <p class="who">
              <span class="author">{readableThread(r.exercise_id)}</span>
              {#if r.upvotes}<span class="tag accent">{r.upvotes} × « moi aussi »</span>{/if}
              <span class="tag">
                {r.replies ? (r.replies > 1 ? r.replies + " réponses" : "1 réponse") : "sans réponse"}
              </span>
              {#if r.visibility !== "thread"}<span class="tag">privée</span>{/if}
              {#if r.step}<span class="tag">{stepLabel(r.step)}</span>{/if}
            </p>
            <p class="excerpt">{r.text}</p>
            <button type="button" class="nav" onclick={() => openConversation(r.id)}>
              Ouvrir la conversation
            </button>
          </li>
        {/each}
      </ul>
      <p class="help">
        Sur les dernières {thread.top.hours} heures. Aucun nom, aucun compte : un nombre par
        question.
      </p>
    {/if}
  </div>

  <div class="block">
    <h3 class="subtitle">Qui a besoin d'aide</h3>
    {#if thread.help === null}
      <p class="failed">Le tableau d'aide n'a pas pu être lu.</p>
    {:else}
      <p class="help">
        Agrégé par exercice et par étape sur les {thread.help.hours} dernières heures. Aucun
        code, aucun nom : un compte de personnes suffit pour savoir où aller dans le local.
      </p>
      {#if !thread.help.rows.length}
        <p class="help">Personne n'a signalé être bloqué pour l'instant.</p>
      {:else}
        <table class="rank-table">
          <thead>
            <tr>
              <th>Exercice</th><th>Où ça coince</th><th>Personnes</th>
              <th>Ouvertes au groupe</th><th>Depuis</th>
            </tr>
          </thead>
          <tbody>
            {#each thread.help.rows as row}
              <tr>
              <td>{exerciseLabel(row.exercise_id)}</td>
              <td>
                {stepLabel(row.step) + (row.blocked_kind ? " — " + blockedLabel(row.blocked_kind) : "")}
              </td>
              <td class="num">{row.people}</td>
                <td class="num">{row.opened} sur {row.people}</td>
                <td>{localTime(row.since)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="help">
          Une question privée reste privée : seul son auteur peut l'ouvrir à son groupe. Ce
          tableau les compte toutes, parce que c'est le compte qui dit où aller.
        </p>
      {/if}
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">Signalements</h3>
    {#if thread.reports === null}
      <p class="failed">La file de signalements n'a pas pu être lue.</p>
    {:else if !thread.reports.length}
      <p class="help">Aucun signalement en attente.</p>
    {:else}
      <ul class="thread">
        {#each thread.reports as s (s.id)}
          <li class="message">
            <p class="who">
              <span class="author">{s.exercise_id}</span>
              <time class="when">{localTime(s.created_at)}</time>
              <span class="state">
                {s.report_count} signalement{s.report_count > 1 ? "s" : ""}{s.hidden
                  ? " — masqué"
                  : ""}
              </span>
            </p>
            <Markdown source={s.text} />
            <div class="row">
              {#if s.hidden}
                <button type="button" class="nav" onclick={() => thread.moderate(s.id, "restore")}>
                  Rétablir
                </button>
              {:else}
                <button type="button" class="nav" onclick={() => thread.moderate(s.id, "hide")}>
                  Masquer
                </button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">Noms signalés</h3>
    {#if thread.reportedNames === null}
      <p class="failed">La file des noms n'a pas pu être lue.</p>
    {:else if !thread.reportedNames.length}
      <p class="help">Aucun nom signalé.</p>
    {:else}
      <ul class="thread">
        {#each thread.reportedNames as n (n.id)}
          <li class="message">
            <p class="who">
              <span class="author">{n.display_name || "(nom déjà effacé)"}</span>
              {#if n.group_number}<span class="group">groupe {n.group_number}</span>{/if}
              <time class="when">{localTime(n.created_at)}</time>
              <span class="state">{n.report_count} signalement{n.report_count > 1 ? "s" : ""}</span>
            </p>
            <div class="row">
              <button type="button" class="nav" onclick={() => thread.clearName(n.id)}>
                Effacer le nom
              </button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
