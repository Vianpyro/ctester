<script lang="ts">
  // THE MODERATION SCREEN, KEPT APART. It has no business in a student's path, and the
  // instructor opening it does not need to go through a thread to get there.
  //
  // THE AGGREGATE COMES FIRST: during a lab it is the actionable half, and the report
  // queue is the one that can wait ten minutes.
  //
  // "QUI A BESOIN D'AIDE": COUNTS AND STEPS, NEVER PEOPLE. No name, no text, no code -- a
  // number is what says where to walk in the room, and six people on the same conversion
  // is one explanation at the board rather than six replies. PRIVATE QUESTIONS ARE
  // COUNTED, NOT SHOWN: their author is the only one who can open them, which is exactly
  // what the student's form promised.

  import { onMount } from "svelte";
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

  /** Only what stands out: voted, or unanswered. */
  const topRows = $derived((thread.top?.rows ?? []).filter((r) => r.upvotes || !r.replies));

  async function openConversation(id: string) {
    await chat.toggleWide();
    await thread.openPermalink(id);
  }
</script>

<h2 bind:this={title} id="moderationtitre" tabindex="-1">Modération</h2>
<p class="annonce" aria-live="polite">{thread.said}</p>

{#if !thread.moderator}
  <p class="rate">Cette page est réservée à la modération.</p>
{:else}
  <!-- THE MOST-VOTED QUESTIONS, AND ONLY FOR THE INSTRUCTOR. Students see NO ranking: a
       public counter on what each of them asked is the opposite of what the chat is for.
       "Moi aussi" is what answers "what is blocking the class?" without counting anybody
       -- it is a number per question, not a number per student. -->
  <div class="bloc">
    <h3 class="soustitre">Questions du moment</h3>
    {#if !thread.top}
      <p class="rate">Le classement des questions n'a pas pu être lu.</p>
    {:else if !topRows.length}
      <p class="aide">Rien qui ressorte sur les dernières {thread.top.hours} heures.</p>
    {:else}
      <ul class="fil">
        {#each topRows.slice(0, 10) as r (r.id)}
          <li class="message">
            <p class="qui">
              <span class="auteur">{readableThread(r.exercise_id)}</span>
              {#if r.upvotes}<span class="tag accent">{r.upvotes} × « moi aussi »</span>{/if}
              <span class="tag">
                {r.replies ? (r.replies > 1 ? r.replies + " réponses" : "1 réponse") : "sans réponse"}
              </span>
              {#if r.visibility !== "thread"}<span class="tag">privée</span>{/if}
              {#if r.step}<span class="tag">{stepLabel(r.step)}</span>{/if}
            </p>
            <!-- Text: this comes from a student and does not go through the sanitizer, so
                 it must never become HTML. -->
            <p class="extrait">{r.text}</p>
            <button type="button" class="nav" onclick={() => openConversation(r.id)}>
              Ouvrir la conversation
            </button>
          </li>
        {/each}
      </ul>
      <p class="aide">
        Sur les dernières {thread.top.hours} heures. Aucun nom, aucun compte : un nombre par
        question.
      </p>
    {/if}
  </div>

  <div class="bloc">
    <h3 class="soustitre">Qui a besoin d'aide</h3>
    {#if thread.help === null}
      <!-- NOT "personne n'est bloqué": during an outage those are opposite claims, and
           the wrong one sends an instructor home. -->
      <p class="rate">Le tableau d'aide n'a pas pu être lu.</p>
    {:else}
      <p class="aide">
        Agrégé par exercice et par étape sur les {thread.help.hours} dernières heures. Aucun
        code, aucun nom : un compte de personnes suffit pour savoir où aller dans le local.
      </p>
      {#if !thread.help.rows.length}
        <p class="aide">Personne n'a signalé être bloqué pour l'instant.</p>
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
              <!-- "0 ouvertes" IS INFORMATION, not an empty cell: it says every one of
                   them is private, so nobody in the room can answer them but the
                   instructor. -->
                <td class="num">{row.opened} sur {row.people}</td>
                <td>{localTime(row.since)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="aide">
          Une question privée reste privée : seul son auteur peut l'ouvrir à son groupe. Ce
          tableau les compte toutes, parce que c'est le compte qui dit où aller.
        </p>
      {/if}
    {/if}
  </div>

  <div class="bloc second">
    <h3 class="soustitre">Signalements</h3>
    {#if thread.reports === null}
      <p class="rate">La file de signalements n'a pas pu être lue.</p>
    {:else if !thread.reports.length}
      <p class="aide">Aucun signalement en attente.</p>
    {:else}
      <ul class="fil">
        {#each thread.reports as s (s.id)}
          <li class="message">
            <p class="qui">
              <span class="auteur">{s.exercise_id}</span>
              <time class="quand">{localTime(s.created_at)}</time>
              <span class="etat">
                {s.report_count} signalement{s.report_count > 1 ? "s" : ""}{s.hidden
                  ? " — masqué"
                  : ""}
              </span>
            </p>
            <!-- SAME PIPELINE AS EVERYWHERE ELSE. A moderator reads exactly what a student
                 reads, sanitized the same way: a moderation view that rendered raw HTML
                 "to see what's inside" would be the site's easiest page to attack, and the
                 one where an attack would pay off most. -->
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

  <!-- REPORTED NAMES, next to reported messages but not inside them: it is not the
       message that is the problem, it is the name, and the action is not the same. -->
  <div class="bloc second">
    <h3 class="soustitre">Noms signalés</h3>
    {#if thread.reportedNames === null}
      <p class="rate">La file des noms n'a pas pu être lue.</p>
    {:else if !thread.reportedNames.length}
      <p class="aide">Aucun nom signalé.</p>
    {:else}
      <ul class="fil">
        {#each thread.reportedNames as n (n.id)}
          <li class="message">
            <p class="qui">
              <span class="auteur">{n.display_name || "(nom déjà effacé)"}</span>
              {#if n.group_number}<span class="groupe">groupe {n.group_number}</span>{/if}
              <time class="quand">{localTime(n.created_at)}</time>
              <span class="etat">{n.report_count} signalement{n.report_count > 1 ? "s" : ""}</span>
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
