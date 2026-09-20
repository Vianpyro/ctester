<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  // The template alternates text runs and gaps: run 0, gap 0, run 1, gap 1, ... The judge
  // never parses it, so this split and the publisher's must agree on `_{3,}`.
  const runs = $derived(q.template.split(/_{3,}/));
  const filled = $derived((quiz.answers[q.key] ?? []) as string[]);

  function fill(i: number, value: string) {
    const next = [...filled];
    while (next.length < q.gaps.length) next.push("");
    next[i] = value;
    quiz.answers[q.key] = next;
    onchange();
  }
</script>

<div class="qcloze">
  {#each runs as run, i (i)}<span class="qrun">{run}</span>{#if i < q.gaps.length}{#if q.gaps[i]!.length}<select
        aria-label={"Trou " + (i + 1) + " sur " + q.gaps.length}
        value={filled[i] ?? ""}
        onchange={(event) => fill(i, event.currentTarget.value)}
      >
        <option value="">—</option>
        {#each q.gaps[i]! as choice (choice)}
          <option value={choice}>{choice}</option>
        {/each}
      </select>{:else}<input
        type="text"
        spellcheck="false"
        autocomplete="off"
        aria-label={"Trou " + (i + 1) + " sur " + q.gaps.length}
        value={filled[i] ?? ""}
        oninput={(event) => fill(i, event.currentTarget.value)}
      />{/if}{/if}{/each}
</div>
