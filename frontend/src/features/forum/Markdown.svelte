<script lang="ts">
  // A MESSAGE'S BODY, AND THIS IS THE PAGE'S ONLY OTHER `{@html}`.
  //
  // IT RECEIVES THE SANITIZER'S OUTPUT AT THAT VERY INSTANT: no variable lying around,
  // no concatenation, no cache. What gets written is exactly what DOMPurify just
  // produced for this source, and `lib/domain/markdown.ts` holds the two barriers --
  // escape `<` BEFORE parsing, then a closed allow-list after.
  //
  // PLAIN TEXT FIRST, ALWAYS. If a library is missing, if parsing throws, if the
  // sanitizer cannot be used: what stays on screen is TEXT, never unfiltered HTML.
  // `renderMarkdown` returns null for all three, and that is what the fallback below
  // means.
  //
  // SANITIZED AT EVERY DISPLAY, never at write time: a rule tightened later has to
  // apply to messages already in the database.

  import { renderMarkdown } from "../../lib/domain/markdown";

  interface Props {
    source: string;
    /** The wrapper's classes; a preview and a thread message differ only in these. */
    class?: string;
  }

  const { source, class: className = "texte md" }: Props = $props();

  const clean = $derived(renderMarkdown(source));
</script>

{#if clean === null}
  <div class={className}>{source}</div>
{:else}
  <div class={className}>{@html clean}</div>
{/if}
