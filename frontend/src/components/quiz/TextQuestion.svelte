<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();
</script>

<!-- Never type="number": it rejects "12,625" under a French locale and edits on scroll. -->
<input
  type="text"
  inputmode={q.type === "number" ? "decimal" : undefined}
  spellcheck="false"
  autocomplete="off"
  data-qid={q.id}
  aria-labelledby={"qlabel-" + q.id}
  bind:value={quiz.answers[q.id]}
  oninput={onchange}
/>
