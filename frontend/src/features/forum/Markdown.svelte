<script lang="ts">
  import { renderMarkdown } from "../../lib/domain/markdown";

  interface Props {
    source: string;
    class?: string;
  }

  const { source, class: className = "text md" }: Props = $props();

  const clean = $derived(renderMarkdown(source));
</script>

{#if clean === null}
  <div class={className}>{source}</div>
{:else}
  <div class={className}>{@html clean}</div>
{/if}
