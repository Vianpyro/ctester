<script lang="ts">
  import { collaborators } from "../lib/state/collaborators.svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { measure, place, rowColumn, selectionBands, type Metrics } from "../lib/collab/carets";

  interface Props {
    scroll: { left: number; top: number };
  }

  const { scroll }: Props = $props();

  let metrics = $state<Metrics | null>(null);

  $effect(() => {
    const zone = editor.element;
    void editor.activeFile;
    metrics = zone && collaborators.active ? measure(zone) : null;
  });

  const usable = $derived(!!metrics && !!metrics.char && !!metrics.line);
  const text = $derived(editor.text);
  const present = $derived(collaborators.inFile(editor.activeFile));
</script>

<div id="carets" aria-hidden="true">
  {#if usable && metrics}
    {#each present as { member, caret } (member.id)}
      {@const at = rowColumn(text, caret.head)}
      <i
        class="caret"
        style={place(metrics, scroll, at.column, at.row) +
          "height:" + metrics.line + "px;background:" + member.color}
      >
        <b class="caretname" style={"background:" + member.color}>{member.name}</b>
      </i>
      {#each selectionBands(text, caret.anchor, caret.head, metrics, scroll) as band}
        <i class="sel" style={band + "background:" + member.color}></i>
      {/each}
    {/each}
  {/if}
</div>
