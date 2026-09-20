<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  // A native <select> per prompt, not drag-and-drop: complete at the keyboard and correct
  // to a screen reader for free, where dragging would need a keyboard fallback anyway.
  const pairs = $derived((quiz.answers[q.key] ?? {}) as Record<string, string>);

  function pick(prompt: string, chosen: string) {
    quiz.answers[q.key] = { ...pairs, [prompt]: chosen };
    onchange();
  }
</script>

<div class="qmatch">
  {#each q.prompts as prompt, i (prompt)}
    <div class="qpair">
      <label for={"m-" + q.key + "-" + i}>{prompt}</label>
      <select
        id={"m-" + q.key + "-" + i}
        value={pairs[prompt] ?? ""}
        onchange={(event) => pick(prompt, event.currentTarget.value)}
      >
        <option value="">—</option>
        {#each q.options as option (option)}
          <option value={option}>{option}</option>
        {/each}
      </select>
    </div>
  {/each}
</div>
