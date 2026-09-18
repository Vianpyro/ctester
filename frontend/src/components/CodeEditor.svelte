<script lang="ts">
  import { editor } from "../lib/state/editor.svelte";
  import { drafts } from "../lib/state/drafts.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import CodeSurface from "./CodeSurface.svelte";
  import RemoteCarets from "./RemoteCarets.svelte";

  let zone: HTMLTextAreaElement | null = $state(null);

  $effect(() => {
    editor.element = zone;
    return () => {
      if (editor.element === zone) editor.element = null;
    };
  });

  function onInput(text: string) {
    editor.typed(text);
    exercise.typed();
  }

  function onTabsKeydown(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step) editor.cycle(step);
  }
</script>

<div id="editor">
  <div class="phead">
    <span id="edtitle" hidden={editor.files.length > 1}>{editor.activeFile ?? ""}</span>
    <!-- svelte-ignore a11y_interactive_supports_focus -->
    <div
      id="tabs"
      role="tablist"
      aria-label="Fichiers de la soumission"
      hidden={editor.files.length <= 1}
      onkeydown={onTabsKeydown}
    >
      {#each editor.files as file (file.name)}
        <button
          type="button"
          class={editor.activeFile === file.name ? "tab on" : "tab"}
          role="tab"
          aria-controls="edwrap"
          aria-selected={editor.activeFile === file.name}
          tabindex={editor.activeFile === file.name ? 0 : -1}
          onclick={() => editor.activate(file.name)}>{file.name}</button
        >
      {/each}
    </div>
    <span class="grow"></span>
    <span id="saving" class={drafts.statusFailed ? "failed" : ""} aria-live="polite"
      >{drafts.status}</span
    >
  </div>
  <CodeSurface
    bind:element={zone}
    value={editor.text}
    {onInput}
    onCaret={() => editor.notify("onCaret")}
    onScrolled={() => editor.notify("onScroll")}
    readOnly={editor.readOnly}
    label={"Code de " + (editor.activeFile ?? "")}
    placeholder="// Écris ton code ici"
    wrapRole="tabpanel"
  >
    {#snippet overlay(scroll)}
      <RemoteCarets {scroll} />
    {/snippet}
  </CodeSurface>
</div>
