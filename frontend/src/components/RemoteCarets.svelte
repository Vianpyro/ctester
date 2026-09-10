<script lang="ts">
  // TEAMMATES' CARETS AND SELECTIONS, drawn on a layer over the editor.
  //
  // IT READS `collaborators`, NOT THE ROOM. That is deliberate and it is what keeps
  // Yjs out of the main bundle: this component ships with the editor, which every
  // student sees, while the room and its 92 KB of CRDT ship only with an assignment.
  //
  // NO METRICS MEANS NO CARETS, and that is a deliberate silence: one drawn at the
  // wrong place is worse than none at all, because it points at a line its owner is
  // not on. `getBoundingClientRect` returns zeros in a headless DOM, which is exactly
  // where this must not throw.

  import { collaborators } from "../lib/state/collaborators.svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { measure, place, rowColumn, selectionBands, type Metrics } from "../lib/collab/carets";

  interface Props {
    scroll: { left: number; top: number };
  }

  const { scroll }: Props = $props();

  let metrics = $state<Metrics | null>(null);

  // Measured once per editor element, and again when the tab changes -- a different
  // file can mean a different scroll box.
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
        <!-- THE NAME RIDES ON THE CARET, in the same colour: two carets a line apart
             are otherwise two identical slivers. Text, like everything else that
             comes from another account. -->
        <b class="caretname" style={"background:" + member.color}>{member.name}</b>
      </i>
      {#each selectionBands(text, caret.anchor, caret.head, metrics, scroll) as band}
        <i class="sel" style={band + "background:" + member.color}></i>
      {/each}
    {/each}
  {/if}
</div>
