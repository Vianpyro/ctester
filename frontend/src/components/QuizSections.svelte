<script lang="ts">
  import { quiz } from "../lib/state/quiz.svelte";
  import { pageStatus, sectionLabel, type Mark } from "../lib/domain/quizMarks";

  let { marks, strip = $bindable(null) }: { marks: Record<string, Mark>; strip?: HTMLDivElement | null } =
    $props();

  const GLYPH = { right: "✓", wrong: "✗", unknown: "" };
</script>

<!-- One tile per section, in the same language as the exercise strip above it. -->
<div id="quizsections" bind:this={strip} hidden={quiz.sections.length <= 1}>
  {#each quiz.sections as page, n (page.key)}
    {@const status = pageStatus(
      page.questions.map((q) => q.id),
      quiz.answers,
      marks,
    )}
    <button
      type="button"
      class="tab"
      class:on={quiz.shown.includes(n)}
      aria-current={quiz.shown.includes(n) ? "true" : undefined}
      onclick={() => quiz.showSection(n)}
      title={page.title}
    >
      <span class="name">{sectionLabel(page.title)}</span>
      <span class="count {status.state}">
        {status.answered}/{status.total}
        {GLYPH[status.state]}
      </span>
    </button>
  {/each}
</div>
