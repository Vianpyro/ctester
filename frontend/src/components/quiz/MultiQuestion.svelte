<script lang="ts">
  import { quiz, type QuizQuestion } from "../../lib/state/quiz.svelte";
  import { t } from "../../lib/i18n.svelte";

  const { q, onchange }: { q: QuizQuestion; onchange: () => void } = $props();

  // A fieldset, not role="radiogroup": there is no checkboxgroup role, and a legend is
  // how a native group of checkboxes gets its accessible name.
  const chosen = $derived((quiz.answers[q.id] ?? []) as string[]);

  function toggle(option: string) {
    const next = chosen.includes(option)
      ? chosen.filter((one) => one !== option)
      : [...chosen, option];
    quiz.answers[q.id] = next;
    onchange();
  }
</script>

<fieldset class="qchoices qmulti">
  <legend class="qlegend">{t("quiz.several", { label: q.label })}</legend>
  {#each q.options as option (option)}
    <label class="qchoice">
      <input
        type="checkbox"
        checked={chosen.includes(option)}
        onchange={() => toggle(option)}
      />
      {option}
    </label>
  {/each}
</fieldset>
