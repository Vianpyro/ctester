<script lang="ts">
  import type { Component } from "svelte";
  import { quiz, type QuizQuestion } from "../lib/state/quiz.svelte";
  import {
  marksFor,
  packSheets,
  pageStatus,
  slotsOnScreen,
  tableFor,
} from "../lib/domain/quizMarks";
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
  // narrows a scoped run to the sheet on screen; these marks must not be narrowed with it.
  const marks = $derived(
    marksFor(
      submission.phase.kind === "done" ? submission.phase.verdict : null,
      quiz.submitted,
      quiz.answers,
    ),
  );

  let headings: HTMLDivElement[] = $state([]);
  let blocks: HTMLDivElement[] = $state([]);
  let wrap: HTMLDivElement | null = $state(null);
  let strip: HTMLDivElement | null = $state(null);
  let seen = quiz.sheet;

  // Switching sheet swaps the whole panel under the reader: move the focus to the first
  // heading it shows so it is announced and the next Tab lands in its questions.
  $effect(() => {
    const now = quiz.sheet;
    if (now === seen) return;
    seen = now;
    headings[quiz.shown[0] ?? 0]?.focus();
  });

  // Sections are only split when they do not fit together. Measuring needs them all laid
  // out, so `measuring` shows everything for one pass, then the sheets hide the rest.
  let measuring = $state(true);
  let packedFor = "";

  /** The height a sheet has: the panel less the strip, which sits inside it. */
  const room = (): number =>
    wrap ? wrap.clientHeight - (strip?.offsetHeight ?? 0) - 24 : 0;

  // Keyed on the border-box width, not clientWidth: a scrollbar appearing while everything
  // is laid out must not read as a new size, or measuring would feed itself for ever.
  const stamp = (): string =>
    wrap
      ? `${quiz.exerciseId}|${quiz.sections.length}|${Math.round(
          wrap.getBoundingClientRect().width,
        )}x${wrap.clientHeight}`
      : "";

  $effect(() => {
    if (!measuring || !quiz.sections.length || !wrap) return;
    const heights = quiz.sections.map((_, i) => blocks[i]?.offsetHeight ?? 0);
    if (heights.some((height) => height === 0)) return;
    const here = quiz.shown[0] ?? 0;
    quiz.sheets = packSheets(heights, room());
    quiz.showSection(here);
    seen = quiz.sheet;
    packedFor = stamp();
    measuring = false;
  });

  // A new quiz, or a panel that changed size, has to be measured again; nothing else does.
  $effect(() => {
    const now = stamp();
    if (!measuring && now && now !== packedFor) measuring = true;
  });

  $effect(() => {
    if (!wrap) return;
    const watch = new ResizeObserver(() => {
      if (!measuring && stamp() !== packedFor) measuring = true;
    });
    watch.observe(wrap);
    return () => watch.disconnect();
  });

  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => quiz.save(), 1500);
  }
</script>

<div id="quizwrap" bind:this={wrap}>
  <div id="quiz">
    {#if quiz.loading && !quiz.sections.length}
      <p>Chargement…</p>
    {:else}
      {#each quiz.sections as page, n (page.key)}
        {@const status = pageStatus(
          page.questions.map((q) => q.id),
          quiz.answers,
          marks,
        )}
        {@const table = tableFor(page.questions)}
        <!-- One width per section, not per sheet: a 23-bit mantissa in one section must
             not blow up the two-character hex fields of another. -->
        <div
          class="qsection"
          style="--slots: {slotsOnScreen(page.questions)}"
          bind:this={blocks[n]}
          hidden={!measuring && !quiz.shown.includes(n)}
        >
          <div class="qgroup" tabindex="-1" bind:this={headings[n]}>
            <span>{page.title}</span>
            <span class="qcount">{status.answered}/{status.total} répondues</span>
          </div>
          {#if table}
            <table class="qtable">
              <thead>
                <tr>
                  <td></td>
                  {#each table.cols as col (col)}<th scope="col">{col}</th>{/each}
                </tr>
              </thead>
              <tbody>
                {#each table.rows as row (row.label)}
                  <tr>
                    <th scope="row">{row.label}</th>
                    {#each row.cells as q, c (table.cols[c])}
                      <td>
                        {#if q}
                          {@const Widget = widgetFor(q)}
                          {@const mark = marks[q.id]}
                          <!-- The widgets name themselves from this span, so a cell reads
                               as its row and column without any of them knowing. When the
                               table unfolds it becomes the cell's visible caption, minus
                               the row half, which the heading above already carries. -->
                          <span id={"qlabel-" + q.id} class="qcell"
                            ><span class="qcell-row">{row.label} —</span>{" "}{table.cols[
                              c
                            ]}</span
                          >
                          <Widget {q} onchange={onInput} />
                          {#if mark}
                            <p class="qmark {mark.state}">
                              {mark.state === "right"
                                ? "✓"
                                : "✗ " + (mark.hint ?? "réponse incorrecte")}
                            </p>
                          {/if}
                        {/if}
                      </td>
                    {/each}
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <div class="qlist">
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
                      {mark.state === "right"
                        ? "✓ juste"
                        : "✗ " + (mark.hint ?? "réponse incorrecte")}
                    </p>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
  <QuizSections {marks} bind:strip />
</div>
