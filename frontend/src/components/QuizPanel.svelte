<script lang="ts">
  import { tick, type Component } from "svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import { quiz, type LoadedQuiz, type QuizQuestion } from "../lib/state/quiz.svelte";
  import {
    fillPage,
    marksFor,
    pageStatus,
    slotsOnScreen,
    tableFor,
    type Mark,
  } from "../lib/domain/quizMarks";
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

  /** The least a page may be given before it is allowed to say nothing fits. */
  const MIN_PAGE = 220;

  let wrap: HTMLDivElement | null = $state(null);
  let inner: HTMLDivElement | null = $state(null);

  /**
   * What this page may hold: the open exercise and the quiz exercises that follow it in
   * the collection. A code exercise ends the run -- it would need an editor of its own --
   * and so does a locked one.
   */
  const candidates = $derived.by(() => {
    const here = catalog.selected;
    if (!here || here.mode !== "quiz") return [];
    const band = catalog.neighbors;
    const from = band.findIndex((one) => one.id === here.id);
    if (from < 0) return [here];
    const run = [here];
    for (let i = from + 1; i < band.length; i++) {
      const next = band[i]!;
      if (next.mode !== "quiz") break;
      if (lockNote(next) && !catalog.staff) break;
      run.push(next);
    }
    return run;
  });

  const marksOf = (loaded: LoadedQuiz): Record<string, Mark> => {
    // The server grades a whole quiz, so one run marks every section of it. The panel
    // below narrows a verdict to its scope; these marks must not be narrowed with it.
    const leg = submission.legs.find((one) => one.exercise === loaded.exerciseId);
    const verdict = leg?.phase.kind === "done" ? leg.phase.verdict : null;
    return marksFor(verdict, quiz.submitted, quiz.answers, loaded.exerciseId);
  };

  /** The height a page has: the viewport below the panel, less what sits under it. */
  function room(): number {
    if (!wrap) return 0;
    const reserve = parseFloat(getComputedStyle(wrap).getPropertyValue("--quiz-reserve"));
    const view = window.visualViewport?.height ?? window.innerHeight;
    // Not clientHeight: below the layout breakpoint the panel is a plain block and grows
    // with its content, so it would always report room for everything.
    return Math.max(MIN_PAGE, view - wrap.getBoundingClientRect().top - (reserve || 0));
  }

  /**
   * The content's own height, never the panel's. `#quizwrap` scrolls, and a scroll box
   * reports `scrollHeight` as at least its `clientHeight`: measuring it would compare the
   * panel to itself and conclude nothing ever fits.
   */
  function taken(): number {
    if (!wrap || !inner) return 0;
    const box = getComputedStyle(wrap);
    const pad = (parseFloat(box.paddingTop) || 0) + (parseFloat(box.paddingBottom) || 0);
    return inner.getBoundingClientRect().height + pad;
  }

  const fits = (): boolean => !!wrap && !!inner && taken() <= room();

  const stamp = (): string =>
    wrap
      ? candidates.map((one) => one.id).join(",") +
        "|" +
        Math.round(wrap.getBoundingClientRect().width) +
        "x" +
        Math.round(room())
      : "";

  let filling = false;
  let filledFor = "";

  async function refill(): Promise<void> {
    if (filling || !wrap) return;
    filling = true;
    try {
      const list = candidates;
      if (!list.length) {
        quiz.clear();
        filledFor = "";
        return;
      }
      const loaded: LoadedQuiz[] = [];
      const kept = await fillPage(list.length, async (n) => {
        while (loaded.length < n) {
          const ex = list[loaded.length]!;
          const one = await quiz.fetch(ex.id, ex.short);
          if (!one) return false;
          loaded.push(one);
        }
        quiz.setPage(loaded.slice(0, n));
        await tick();
        return fits();
      });
      quiz.setPage(loaded.slice(0, kept));
      await tick();
      // A leg whose exercise left the page stops being shown, but its job keeps polling:
      // dropping it would cost the student the attempt.
      submission.reset(quiz.shown.map((one) => one.exerciseId));
      void exercise.showStatements(
        quiz.shown.map((one) => ({ id: one.exerciseId, short: one.title })),
      );
      filledFor = stamp();
    } finally {
      filling = false;
    }
    // A resize that landed mid-fill was dropped: the observer will not fire again on its
    // own, so the page would keep a split measured against a size it no longer has.
    if (stamp() !== filledFor) void refill();
  }

  // Opening another exercise changes the run; the rest is size, which is not reactive.
  $effect(() => {
    void candidates;
    void refill();
  });

  $effect(() => {
    if (!wrap) return;
    const again = () => {
      if (!filling && stamp() !== filledFor) void refill();
    };
    const watch = new ResizeObserver(again);
    watch.observe(wrap);
    window.visualViewport?.addEventListener("resize", again);
    return () => {
      watch.disconnect();
      window.visualViewport?.removeEventListener("resize", again);
    };
  });

  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => quiz.save(), 1500);
  }
</script>

<div id="quizwrap" bind:this={wrap}>
  <div id="quiz" bind:this={inner}>
    {#if quiz.loading && !quiz.shown.length}
      <p>Chargement…</p>
    {:else}
      {#each quiz.shown as loaded (loaded.exerciseId)}
        {@const marks = marksOf(loaded)}
        <!-- An exercise with a single unnamed section IS that section: one heading, not
             two saying the same thing. -->
        {@const lone = loaded.sections.length === 1 && !loaded.sections[0]!.title}
        <!-- One width per exercise: a 23-bit mantissa in one must not blow up the
             two-character hex fields of another sharing the page. -->
        <div
          id={"ex-" + loaded.exerciseId}
          class="qexercise"
          style="--slots: {slotsOnScreen(loaded.sections.flatMap((s) => s.questions))}"
        >
          {#if quiz.shown.length > 1 && !lone}
            <h2 class="qtitle">{loaded.title}</h2>
          {/if}
          {#each loaded.sections as section (section.key)}
            {@const status = pageStatus(
              section.questions.map((q) => q.key),
              quiz.answers,
              marks,
            )}
            {@const table = tableFor(section.questions)}
            <div class="qsection">
              <div class={lone ? "qgroup lead" : "qgroup"}>
                <span>{section.title || loaded.title}</span>
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
                              {@const mark = marks[q.key]}
                              <!-- The widgets name themselves from this span, so a cell
                                   reads as its row and column without any of them
                                   knowing. When the table unfolds it becomes the cell's
                                   visible caption, minus the row half, which the heading
                                   above already carries. -->
                              <span id={"qlabel-" + q.key} class="qcell"
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
                  {#each section.questions as q (q.key)}
                    {@const Widget = widgetFor(q)}
                    {@const mark = marks[q.key]}
                    <div class="qq">
                      <div class="qrow">
                        <span id={"qlabel-" + q.key}>{q.label}</span>
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
        </div>
      {/each}
    {/if}
  </div>
</div>
