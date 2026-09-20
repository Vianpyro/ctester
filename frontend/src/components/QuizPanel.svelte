<script lang="ts">
  import type { Component } from "svelte";
  import { quiz, type QuizQuestion } from "../lib/state/quiz.svelte";
  import { marksFor, pageStatus } from "../lib/domain/quizMarks";
  import { submission } from "../lib/state/submission.svelte";
  import QuizSections from "./QuizSections.svelte";
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

  // The server grades the whole quiz, so one run marks every section. The panel below
  // narrows a scoped run to its own page; these marks must not be narrowed with it.
  const marks = $derived(
    marksFor(
      submission.phase.kind === "done" ? submission.phase.verdict : null,
      quiz.submitted,
      quiz.answers,
    ),
  );

  let headings: HTMLDivElement[] = $state([]);
  let seen = quiz.page;

  // Switching section swaps the whole panel under the reader: move the focus to the new
  // heading so it is announced and the next Tab lands in its questions.
  $effect(() => {
    const now = quiz.page;
    if (now === seen) return;
    seen = now;
    headings[now]?.focus();
  });

  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => quiz.save(), 1500);
  }
</script>

<div id="quizwrap">
  <div id="quiz">
    {#if quiz.loading && !quiz.pages.length}
      <p>Chargement…</p>
    {:else}
      {#each quiz.pages as page, n (page.key)}
        {@const status = pageStatus(
          page.questions.map((q) => q.id),
          quiz.answers,
          marks,
        )}
        <div hidden={n !== quiz.page}>
          <div class="qgroup" tabindex="-1" bind:this={headings[n]}>
            <span>{page.title}</span>
            <span class="qcount">{status.answered}/{status.total} répondues</span>
          </div>
          {#each page.questions as q (q.id)}
            {@const Widget = widgetFor(q)}
            {@const mark = marks[q.id]}
            <div class="qq">
              <div class="qrow">
                <span id={"qlabel-" + q.id}>{q.label}</span>
                <Widget {q} onchange={onInput} />
              </div>
              {#if mark}
                <p class="qmark {mark.state}">
                  {mark.state === "right" ? "✓ juste" : "✗ " + (mark.hint ?? "réponse incorrecte")}
                </p>
              {/if}
            </div>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
  <QuizSections {marks} />
</div>
