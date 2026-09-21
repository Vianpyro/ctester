<script lang="ts">
  import type { Component } from "svelte";
  import { quiz, type QuizQuestion } from "../lib/state/quiz.svelte";
  import { marksFor } from "../lib/domain/quizMarks";
  import { shapeNote } from "../lib/domain/answerShape";
  import { submission } from "../lib/state/submission.svelte";
  import ChoiceQuestion from "./quiz/ChoiceQuestion.svelte";
  import ClozeQuestion from "./quiz/ClozeQuestion.svelte";
  import MatchQuestion from "./quiz/MatchQuestion.svelte";
  import MultiQuestion from "./quiz/MultiQuestion.svelte";
  import OrderQuestion from "./quiz/OrderQuestion.svelte";
  import TextQuestion from "./quiz/TextQuestion.svelte";

  type Widget = Component<{ q: QuizQuestion; onchange: () => void }>;

  // Dispatch on the type, not on whether options happen to be there. The fallback mirrors
  // the judge's own `unwrap_or("int")`, so a page and a verdict never disagree.
  const WIDGETS: Record<string, Widget> = {
    choice: ChoiceQuestion,
    bool: ChoiceQuestion,
    multi: MultiQuestion,
    match: MatchQuestion,
    order: OrderQuestion,
    cloze: ClozeQuestion,
  };
  const widgetFor = (q: QuizQuestion): Widget => WIDGETS[q.type] ?? TextQuestion;

  // The raw verdict, not the one the panel below narrows to its scope: a run started from
  // one page carries the marks of every page.
  const marks = $derived(
    marksFor(
      submission.phase.kind === "done" ? submission.phase.verdict : null,
      quiz.submitted,
      quiz.answers,
    ),
  );

  // Nothing is said while someone is still typing: the notes appear a second after the
  // last keystroke, anywhere on the page, and vanish on the next one.
  let quiet = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    quiet = false;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      quiet = true;
      quiz.save();
    }, 1000);
  }

  const noteFor = (q: QuizQuestion): string => {
    const value = quiz.answers[q.id];
    return quiet && typeof value === "string" ? shapeNote(q.type, value) : "";
  };
</script>

<div id="quizwrap">
  <div id="quiz">
    {#if quiz.loading && !quiz.pages.length}
      <p>Chargement…</p>
    {:else}
      {#each quiz.pages as page, n (page.key)}
        <div hidden={n !== quiz.page}>
          <div class="qgroup">{page.title}</div>
          {#each page.questions as q (q.id)}
            {@const Widget = widgetFor(q)}
            {@const mark = marks[q.id]}
            {@const note = noteFor(q)}
            <div class="qrow">
              <span id={"qlabel-" + q.id}>{q.label}</span>
              <Widget {q} onchange={onInput} />
              {#if mark}
                <span class="qmark {mark}" aria-hidden="true">{mark === "right" ? "✓" : "✗"}</span>
                <span class="offscreen">{mark === "right" ? "juste" : "faux"}</span>
              {/if}
              {#if note}
                <span class="qshape">{note}</span>
              {/if}
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
