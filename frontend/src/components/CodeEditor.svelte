<script lang="ts">
  // THE EDITOR: a `<pre>` of coloured HTML behind a `<textarea>` whose own text is
  // transparent, plus a gutter beside them.
  //
  // `#hl` AND `#code` MUST KEEP IDENTICAL METRICS -- font, size, line height,
  // padding, border, tab-size, white-space. Anything that shifts the text by one
  // pixel shifts the colours off it, and `lib/collab/carets.ts` places teammates'
  // cursors by arithmetic on those same metrics. The rules live ONCE in `app.css`
  // (`.hl, .codein`); this component must not restate them.
  //
  // IT WAS NOT REPLACED BY A LIBRARY, and that is a decision: CodeMirror or Monaco
  // would bring their own line box, their own selection model and their own DOM, and
  // the caret overlay would have to be rewritten against it -- for a page whose
  // editor needs C colouring, a tab key and a gutter.
  //
  // WHAT A KEY DOES LIVES IN `domain/keys.ts`, not here: this component only applies
  // the edit to the element. That is what makes the behaviour testable by calling a
  // function instead of driving a fake DOM.

  import { editor } from "../lib/state/editor.svelte";
  import { drafts } from "../lib/state/drafts.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { gutterText, highlight } from "../lib/domain/highlight";
  import { keyEdit, type Edit } from "../lib/domain/keys";
  import RemoteCarets from "./RemoteCarets.svelte";

  let zone: HTMLTextAreaElement | undefined = $state();
  let overlay: HTMLPreElement | undefined = $state();
  let gutter: HTMLPreElement | undefined = $state();

  /** Scroll offsets, mirrored so the caret overlay can place itself. */
  let scroll = $state({ left: 0, top: 0 });

  const painted = $derived(highlight(editor.text));
  const lines = $derived(gutterText(editor.text.split("\n").length));

  // The element is registered here and nowhere else: `editor.write()` is the one
  // place a caret can be lost, and it needs the element to preserve it.
  $effect(() => {
    editor.element = zone ?? null;
    return () => {
      if (editor.element === zone) editor.element = null;
    };
  });

  // THE ELEMENT FOLLOWS THE STATE when the state changed elsewhere -- a tab switch,
  // an imported file, a shared document. Typing does not come through here: it goes
  // state-ward, and writing the value back would fight the caret.
  $effect(() => {
    const value = editor.text;
    if (zone && zone.value !== value) zone.value = value;
  });

  function onInput() {
    if (!zone) return;
    editor.typed(zone.value);
    exercise.typed();
  }

  function onScroll() {
    if (!zone) return;
    scroll = { left: zone.scrollLeft, top: zone.scrollTop };
    if (overlay) {
      overlay.scrollTop = zone.scrollTop;
      overlay.scrollLeft = zone.scrollLeft;
    }
    if (gutter) gutter.scrollTop = zone.scrollTop;
    editor.notify("onScroll");
  }

  /**
   * ESCAPE-THEN-TAB ESCAPES THE TRAP: without the escape hatch a keyboard user
   * could never leave the field, since Tab indents. That is the standard
   * accessible behaviour for a code area, and it is why this is not simply
   * `preventDefault`.
   */
  let escaped = false;

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      escaped = true;
      return;
    }
    const leaving = event.key === "Tab" && escaped;
    escaped = false;
    if (leaving) return;
    // Ctrl, Meta and Alt are the browser's and the student's -- Ctrl+Z above all.
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!zone || editor.readOnly) return;
    const { value, selectionStart, selectionEnd } = zone;
    const edit = keyEdit(event.key, event.shiftKey, value, selectionStart, selectionEnd);
    if (!edit) return;
    event.preventDefault();
    apply(edit);
  }

  /**
   * `execCommand` AND NOT `zone.value = …`, AND THAT IS THE WHOLE REASON THIS
   * FUNCTION EXISTS. Assigning the value **wipes the browser's undo stack**:
   * tolerable for the single Tab key this used to be, unacceptable once every `(`
   * goes through here, since Ctrl+Z would stop working while typing. `insertText`
   * keeps the stack AND fires a real `input` event, so `onInput()` runs exactly as
   * it does for a keystroke -- meaning the CRDT diff of `lib/collab/room.svelte.ts`
   * sees a shared edit without one extra `if`.
   *
   * ponytail: `execCommand` is deprecated and has no replacement for this; the
   * fallback below is the pre-existing behaviour, undo stack and all.
   */
  function apply(edit: Edit) {
    if (!zone) return;
    // Stepping over a closing character moves the caret and changes no text.
    if (edit.insert === "" && edit.from === edit.to) {
      zone.setSelectionRange(edit.caret, edit.caretEnd ?? edit.caret);
      return;
    }
    zone.setSelectionRange(edit.from, edit.to);
    let done = false;
    try {
      done = edit.insert
        ? document.execCommand("insertText", false, edit.insert)
        : document.execCommand("delete");
    } catch {
      done = false;
    }
    if (!done) {
      zone.value = zone.value.slice(0, edit.from) + edit.insert + zone.value.slice(edit.to);
      editor.typed(zone.value);
      exercise.typed();
    }
    zone.setSelectionRange(edit.caret, edit.caretEnd ?? edit.caret);
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
  <!-- THE PANEL THE TABS GOVERN. `role="tab"` used to be set with neither
       `aria-controls` nor a `tabpanel`: a screen reader announced a tab whose panel
       it could not find, and partial ARIA is worse than none. -->
  <div id="edwrap" class="edwrap" role="tabpanel">
    <pre bind:this={gutter} id="gutter" class="gutter" aria-hidden="true">{lines}</pre>
    <div id="pane" class="pane">
      <!-- ONE OF THE TWO PLACES THIS APPLICATION USES `{@html}`, and it is safe for
           exactly one reason: every branch of `highlight()` runs its slice through
           `escapeHtml()` first. Text in, escaped HTML out. -->
      <pre bind:this={overlay} id="hl" class="hl" aria-hidden="true"><code id="hlcode"
          >{@html painted}</code
        ></pre>
      <textarea
        bind:this={zone}
        id="code"
        class="codein"
        spellcheck="false"
        readonly={editor.readOnly}
        aria-label={"Code de " + (editor.activeFile ?? "")}
        placeholder="// Colle ici le contenu de ton fichier"
        oninput={onInput}
        onscroll={onScroll}
        onkeydown={onKeydown}
        onkeyup={() => editor.notify("onCaret")}
        onclick={() => editor.notify("onCaret")}
        onselect={() => editor.notify("onCaret")}
      ></textarea>
      <!-- TEAMMATES' CARETS, on their own layer and AFTER the textarea so they draw
           on top of it. `pointer-events: none` in the stylesheet: this layer must
           never intercept a click meant for the editor. Empty outside a team room. -->
      <RemoteCarets {scroll} />
    </div>
  </div>
</div>
