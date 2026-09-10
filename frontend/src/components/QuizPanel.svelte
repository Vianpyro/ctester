<script lang="ts">
  // THE QUIZ: one page per group of questions, and the browser's own pagination.
  //
  // SAME DRAFT CONTRACT AS THE EDITOR: what was typed is there on return, in the same
  // store, so "Effacer mes brouillons" erases the answers too.

  import { quiz } from "../lib/state/quiz.svelte";

  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => quiz.save(), 1500);
  }
</script>

<div id="quizwrap">
  <div id="quiz">
    {#if quiz.loading}
      <p>Chargement…</p>
    {:else}
      {#each quiz.pages as page, n (page.titre)}
        <div hidden={n !== quiz.page}>
          <div class="qgroup">{page.titre}</div>
          {#each page.questions as q (q.id)}
            <div class="qrow">
              <span id={"qlabel-" + q.id}>{q.label}</span>
              <input
                type="text"
                spellcheck="false"
                autocomplete="off"
                data-qid={q.id}
                aria-labelledby={"qlabel-" + q.id}
                bind:value={quiz.answers[q.id]}
                oninput={onInput}
              />
            </div>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
  <div id="quiznav" hidden={quiz.pages.length <= 1}>
    {#if quiz.pages.length > 1}
      <button
        type="button"
        class="nav"
        id="qprev"
        disabled={quiz.page === 0}
        onclick={() => quiz.showPage(quiz.page - 1)}>‹ Précédent</button
      >
      <span class="pos" id="qpos">page {quiz.page + 1} sur {quiz.pages.length}</span>
      <button
        type="button"
        class="nav"
        id="qnext"
        disabled={quiz.page === quiz.pages.length - 1}
        onclick={() => quiz.showPage(quiz.page + 1)}>Suivant ›</button
      >
    {/if}
  </div>
</div>
