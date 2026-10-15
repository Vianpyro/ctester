<script lang="ts">
  import { tick } from "svelte";
  import { still } from "../../lib/motion";
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";
  import { t } from "../../lib/i18n.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  // Buttons rather than drag-and-drop, for the same reason as the matching widget.
  const items = $derived((quiz.answers[q.id] ?? []) as string[]);
  let said = $state("");
  let list: HTMLOListElement | undefined = $state();

  async function move(from: number, by: number) {
    const to = from + by;
    if (to < 0 || to >= items.length) return;
    const moved = items[from]!;
    const next = [...items];
    [next[from], next[to]] = [next[to]!, next[from]!];
    // FLIP by hand: the two items glide past each other. Svelte's animate: would pull its
    // runtime into the eager bundle, which Rolldown shares with this chunk.
    const before = new Map([...(list?.children ?? [])].map((li) => [li, li.getBoundingClientRect().top]));
    quiz.answers[q.id] = next;
    // Read before the swap: `items` is derived, so it already holds the new order here.
    said = t("quiz.moved", { item: moved, n: to + 1, total: next.length });
    onchange();
    if (still()) return;
    await tick();
    for (const [li, top] of before) {
      const shift = top - li.getBoundingClientRect().top;
      if (shift)
        li.animate([{ translate: `0 ${shift}px` }, { translate: "0 0" }], {
          duration: 260,
          easing: "cubic-bezier(.16, 1, .3, 1)",
        });
    }
  }
</script>

<div class="qorder">
  <ol bind:this={list}>
    {#each items as item, i (item)}
      <li>
        <span class="qitem">{item}</span>
        <button
          type="button"
          class="nav"
          disabled={i === 0}
          aria-label={t("quiz.move_up", { item })}
          onclick={() => move(i, -1)}>↑</button
        >
        <button
          type="button"
          class="nav"
          disabled={i === items.length - 1}
          aria-label={t("quiz.move_down", { item })}
          onclick={() => move(i, 1)}>↓</button
        >
      </li>
    {/each}
  </ol>
  <p class="qsaid" aria-live="polite">{said}</p>
</div>
