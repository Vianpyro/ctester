<script lang="ts">
  import "./quiz/quiz.css";
  import type { Component } from "svelte";
  import { t } from "../lib/i18n.svelte";
  import { answered, quiz, type QuizQuestion } from "../lib/state/quiz.svelte";
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

  // Each page's state for the step list: to fix beats answered, which beats still to do.
  const pageState = (n: number): "fix" | "done" | "todo" => {
    const questions = quiz.pages[n]?.questions ?? [];
    if (questions.some((q) => marks[q.id] === "wrong")) return "fix";
    return questions.every((q) => answered(quiz.answers[q.id] ?? ""))
      ? "done"
      : "todo";
  };

  const noteFor = (q: QuizQuestion): string => {
    const value = quiz.answers[q.id];
    return quiet && typeof value === "string" ? shapeNote(q.type, value) : "";
  };
</script>

<div id="quizwrap">
  <div id="quiz">
    {#if quiz.loading && !quiz.pages.length}
      <p class="qloading">{t("statement.loading")}</p>
    {:else if quiz.failed}
      <div class="qfailed">
        <p>{t("quiz.load_failed")}</p>
        <button type="button" class="nav" onclick={() => quiz.load(quiz.exerciseId)}>
          {t("statement.retry")}
        </button>
      </div>
    {:else}
      {#each quiz.pages as page, n (page.key)}
        <div hidden={n !== quiz.page}>
          <div class="qgroup">{page.title}</div>
          {#each page.questions as q (q.id)}
            {@const Widget = widgetFor(q)}
            {@const mark = marks[q.id]}
            {@const note = noteFor(q)}
            <div class={mark ? "qrow " + mark : "qrow"}>
              <span id={"qlabel-" + q.id}>{q.label}</span>
              <Widget {q} onchange={onInput} />
              <!-- Always rendered, so the field does not jump aside when a verdict lands. -->
              <span class={mark ? "qmark " + mark : "qmark"} aria-hidden="true"
                >{mark ? (mark === "right" ? "✓" : "✗") : ""}</span
              >
              {#if mark}
                <span class="offscreen">{mark === "right" ? t("quiz.right") : t("quiz.wrong")}</span>
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
  <div id="quiznav" hidden={!quiz.pages.length}>
    {#if quiz.pages.length > 1}
      <button
        type="button"
        class="nav"
        id="qprev"
        disabled={quiz.page === 0}
        onclick={() => quiz.showPage(quiz.page - 1)}>{t("quiz.previous")}</button
      >
      <ol class="qpages" aria-label={t("quiz.pages")}>
        {#each quiz.pages as page, n (page.key)}
          {@const state = pageState(n)}
          <li>
            <button
              type="button"
              class={"qstep " + state}
              aria-current={n === quiz.page ? "step" : undefined}
              aria-label={state === "fix"
                ? t("quiz.page_fix", { n: n + 1 })
                : state === "done"
                  ? t("quiz.page_done", { n: n + 1 })
                  : t("quiz.page_todo", { n: n + 1 })}
              title={page.title}
              onclick={() => quiz.showPage(n)}>{n + 1}</button
            >
          </li>
        {/each}
      </ol>
      <span class="pos offscreen" id="qpos">{t("quiz.page", { n: quiz.page + 1, total: quiz.pages.length })}</span>
      <button
        type="button"
        class="nav"
        id="qnext"
        disabled={quiz.page === quiz.pages.length - 1}
        onclick={() => quiz.showPage(quiz.page + 1)}>{t("quiz.next")}</button
      >
    {/if}
    <span class="saved">{t("quiz.saved_here")}</span>
  </div>
</div>
