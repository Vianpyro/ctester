<script lang="ts">
  import { tick } from "svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { explainGcc } from "../lib/domain/gcc";
  import { lineSpan } from "../lib/domain/keys";
  import { t, tOr } from "../lib/i18n.svelte";

  let { output }: { output: string } = $props();

  const error = $derived(explainGcc(output));
  const hint = $derived(error?.hint ? tOr(`verdict.gcc.${error.hint}`, "") : "");
  // The judge may compile under another name; a single file is still unambiguous.
  const file = $derived.by(() => {
    if (!error) return null;
    const names = Object.keys(editor.sources);
    if (names.includes(error.file)) return error.file;
    return names.length === 1 ? names[0]! : null;
  });

  async function goToError() {
    if (!error || !file) return;
    if (file !== editor.activeFile) editor.activate(file);
    await tick();
    const zone = document.getElementById("code") as HTMLTextAreaElement | null;
    if (!zone) return;
    const span = lineSpan(zone.value, error.line);
    zone.focus();
    zone.setSelectionRange(span.from, span.to);
  }
</script>

{#if hint}<p class="explain">{hint}</p>{/if}
{#if error && file}
  <button type="button" class="nav" onclick={goToError}>
    {t("verdict.goto_line", { n: error.line, file })}
  </button>
{/if}
