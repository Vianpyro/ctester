<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();
</script>

<div class="qchoices" role="radiogroup" aria-labelledby={"qlabel-" + q.id}>
  {#each q.options as option (option)}
    <label class="qchoice">
      <input
        type="radio"
        name={"q-" + q.id}
        value={option}
        bind:group={quiz.answers[q.id]}
        {onchange}
      />
      {option}
    </label>
  {/each}
</div>
