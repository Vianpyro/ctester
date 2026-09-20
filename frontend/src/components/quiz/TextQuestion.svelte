<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  const NUMERIC = new Set(["int", "bin", "bin8", "hex8"]);
  const mode = (t: string): "decimal" | "numeric" | undefined =>
    t === "number" ? "decimal" : NUMERIC.has(t) ? "numeric" : undefined;

  // One dot per character the answer needs, so a half-filled field is visible at a glance.
  // The wording stays in the question's own label, which is what a screen reader announces.
  // Only the dots vary: every field on screen shares one width, set on the panel.
  const slots = $derived(q.width > 0 ? "·".repeat(q.width) : undefined);
</script>

<!-- Never type="number": it rejects "12,625" under a French locale and edits on scroll. -->
<!-- The width says how long the answer is; it is never a maxlength, because the judge
     normalises first: "1011 1010" and "0b10111010" are legitimate 8-bit answers.
     ponytail: one plain input, not a segmented bit field, which breaks paste and select-all. -->
<input
  type="text"
  inputmode={mode(q.type)}
  spellcheck="false"
  autocomplete="off"
  placeholder={slots}
  data-qid={q.id}
  data-qtype={q.type}
  aria-labelledby={"qlabel-" + q.key}
  bind:value={quiz.answers[q.key]}
  oninput={onchange}
/>
