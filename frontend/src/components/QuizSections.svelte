<script lang="ts">
  import { quiz } from "../lib/state/quiz.svelte";
  import { pageStatus, sectionLabel, type Mark } from "../lib/domain/quizMarks";

  const { marks }: { marks: Record<string, Mark> } = $props();

  const GLYPH = { right: "✓", wrong: "✗", unknown: "" };
</script>

<!-- One tile per section, in the same language as the exercise strip above it. -->
<div id="quizsections" hidden={quiz.pages.length <= 1}>
  {#each quiz.pages as page, n (page.key)}
    {@const status = pageStatus(
      page.questions.map((q) => q.id),
      quiz.answers,
      marks,
    )}
    <button
      type="button"
      class="tab"
      class:on={n === quiz.page}
      aria-current={n === quiz.page ? "true" : undefined}
      onclick={() => quiz.showPage(n)}
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
