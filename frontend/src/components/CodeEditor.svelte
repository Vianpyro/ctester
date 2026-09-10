<script lang="ts">
  // THE EXERCISE EDITOR: the shared `CodeSurface` plus what only an exercise has
  // -- the file tabs, the draft status, and the teammates' carets.
  //
  // THE EDITING ITSELF IS NOT HERE ANY MORE, and that is the point. Colouring, the
  // gutter, the Tab key, the auto-closing pairs and the syntax checker live in
  // `CodeSurface.svelte`, which the Console mounts too. They were written here
  // once and the Console never got them; a second copy of a surface is a second
  // place for a feature to be missing from.
  //
  // IT WAS NOT REPLACED BY A LIBRARY, and that is a decision: CodeMirror or Monaco
  // would bring their own line box, their own selection model and their own DOM, and
  // the caret overlay would have to be rewritten against it -- for a page whose
  // editor needs C colouring, a tab key and a gutter.

  import { editor } from "../lib/state/editor.svelte";
  import { drafts } from "../lib/state/drafts.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import CodeSurface from "./CodeSurface.svelte";
  import RemoteCarets from "./RemoteCarets.svelte";

  // REGISTERED HERE AND NOWHERE ELSE: `editor.write()` is the one place a caret can
  // be lost, and it needs the element to preserve it. The Console binds nothing, so
  // it cannot take this over while both editors sit in the document.
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

  /** Arrow keys move between tabs, as a tablist is expected to behave. */
  function onTabsKeydown(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step) editor.cycle(step);
  }
</script>

<div id="editor">
  <div class="phead">
    <span id="edtitle" hidden={editor.files.length > 1}>{editor.activeFile ?? ""}</span>
    <!-- svelte-ignore a11y_interactive_supports_focus -->
    <!-- THE ROVING TABINDEX IS ON THE TABS, which is the pattern this needs: the list
         itself must not be focusable, or a keyboard user would stop on an empty container
         before reaching the tab. The handler is here because the event bubbles from
         whichever tab has focus. -->
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
    <!-- THE SAVE STATUS LIVES HERE, above the code, and NOT in the action bar: the
         question "am I going to lose this?" comes up while looking at one's code, not
         while looking at the buttons. It is permanent -- it used to stay empty until
         the first keystroke. -->
    <span id="sauvegarde" class={drafts.statusFailed ? "rate" : ""} aria-live="polite"
      >{drafts.status}</span
    >
  </div>
  <!-- `wrapRole` IS THE PANEL THE TABS GOVERN. `role="tab"` used to be set with
       neither `aria-controls` nor a `tabpanel`: a screen reader announced a tab
       whose panel it could not find, and partial ARIA is worse than none. -->
  <CodeSurface
    bind:element={zone}
    value={editor.text}
    {onInput}
    onCaret={() => editor.notify("onCaret")}
    onScrolled={() => editor.notify("onScroll")}
    readOnly={editor.readOnly}
    label={"Code de " + (editor.activeFile ?? "")}
    placeholder="// Colle ici le contenu de ton fichier"
    wrapRole="tabpanel"
  >
    <!-- TEAMMATES' CARETS, on their own layer and AFTER the textarea so they draw
         on top of it. `pointer-events: none` in the stylesheet: this layer must
         never intercept a click meant for the editor. Empty outside a team room.
         Only the exercise has them -- the Console is one person's scratchpad. -->
    {#snippet overlay(scroll)}
      <RemoteCarets {scroll} />
    {/snippet}
  </CodeSurface>
</div>
