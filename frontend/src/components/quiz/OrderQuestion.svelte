<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  // Buttons rather than drag-and-drop, for the same reason as the matching widget.
  const items = $derived((quiz.answers[q.id] ?? []) as string[]);
  let said = $state("");

  function move(from: number, by: number) {
    const to = from + by;
    if (to < 0 || to >= items.length) return;
    const next = [...items];
    [next[from], next[to]] = [next[to]!, next[from]!];
    quiz.answers[q.id] = next;
    said = "« " + items[from] + " » déplacé en position " + (to + 1) + " sur " + items.length;
    onchange();
  }
</script>

<div class="qorder">
  <ol>
    {#each items as item, i (item)}
      <li>
        <span class="qitem">{item}</span>
        <button
          type="button"
          class="nav"
          disabled={i === 0}
          aria-label={"Monter « " + item + " »"}
          onclick={() => move(i, -1)}>↑</button
        >
        <button
          type="button"
          class="nav"
          disabled={i === items.length - 1}
          aria-label={"Descendre « " + item + " »"}
          onclick={() => move(i, 1)}>↓</button
        >
      </li>
    {/each}
  </ol>
  <p class="qsaid" aria-live="polite">{said}</p>
</div>
