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
  import { highlight } from "../lib/domain/highlight";
  import { keyEdit, type Edit } from "../lib/domain/keys";
  import { check, type Issue } from "../lib/domain/syntax";
  import { measure, rowColumn, selectionBands, type Metrics } from "../lib/collab/carets";
  import RemoteCarets from "./RemoteCarets.svelte";

  let zone: HTMLTextAreaElement | undefined = $state();
  let overlay: HTMLPreElement | undefined = $state();
  let gutter: HTMLPreElement | undefined = $state();

  /** Scroll offsets, mirrored so the caret overlay can place itself. */
  let scroll = $state({ left: 0, top: 0 });

  const painted = $derived(highlight(editor.text));
  const lines = $derived(editor.text.split("\n").length);

  // --- THE SYNTAX CHECK ----------------------------------------------------
  // NOT A `$derived`, AND THE DELAY IS THE FEATURE. Announcing "unclosed
  // parenthesis" on the keystroke that types `(` is a checker that scolds while
  // you write. Each keystroke pushes the deadline back, so it speaks once the
  // typing pauses.

  let issues = $state<Issue[]>([]);

  $effect(() => {
    const source = editor.text;
    const timer = setTimeout(() => {
      issues = check(source);
    }, 600);
    return () => clearTimeout(timer);
  });

  /** The flagged line numbers, 1-based, and the worst level on each. */
  const flagged = $derived.by(() => {
    const rows = new Map<number, string>();
    for (const issue of issues) {
      const row = rowColumn(editor.text, issue.from).row + 1;
      if (issue.level === "error" || !rows.has(row)) rows.set(row, issue.level);
    }
    return rows;
  });

  // Measured like `RemoteCarets` does, and for the same reason: no metrics means
  // NO underline. One drawn at the wrong place points at innocent code.
  let metrics = $state<Metrics | null>(null);

  $effect(() => {
    const element = editor.element;
    void editor.activeFile;
    metrics = element && issues.length ? measure(element) : null;
  });

  const usable = $derived(!!metrics && !!metrics.char && !!metrics.line);

  /** Put the caret on a fault. The list is a way IN, not just a report. */
  function goTo(issue: Issue) {
    if (!zone) return;
    zone.focus();
    zone.setSelectionRange(issue.from, issue.to);
    editor.notify("onCaret");
  }

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
    <!-- A FLAGGED LINE IS A COLOURED NUMBER, not an added glyph: the gutter is
         `text-align: right`, so a `▲` in front would shove that one line's digits
         sideways. Rendered as spans rather than `{@html}` -- the numbers come from
         a counter, but this file has no business growing a second innerHTML. -->
    <pre bind:this={gutter} id="gutter" class="gutter" aria-hidden="true">{#each { length: lines } as _, i}<span
          class={flagged.get(i + 1) ?? ""}>{i + 1}</span>{"\n"}{/each}</pre>
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
      <!-- THE UNDERLINE IS A LAYER, NEVER A SPAN INSIDE `#hl`. Wrapping the
           coloured text would put a second thing inside the one element whose
           metrics must match `#code` to the pixel. `selectionBands()` already
           turns a range into one rectangle per line, in the same arithmetic the
           teammates' carets use. -->
      <div id="squiggles" aria-hidden="true">
        {#if usable && metrics}
          {#each issues as issue (issue.from + ":" + issue.message)}
            {#each selectionBands(editor.text, issue.from, issue.to, metrics, scroll) as band}
              <i class={"squig " + issue.level} style={band}></i>
            {/each}
          {/each}
        {/if}
      </div>
    </div>
  </div>
  <!-- WHAT THE CHECKER FOUND, under the code and above the buttons. Two levels,
       and the wording already says which is which: an "error" is certain, a
       "hint" is a guess written as one. Each row is a button, so the keyboard
       reaches the fault the same way the mouse does. -->
  <div id="diags" aria-live="polite" hidden={issues.length === 0}>
    {#each issues as issue (issue.from + ":" + issue.message)}
      <button type="button" class={"diag " + issue.level} onclick={() => goTo(issue)}>
        <span class="diagline">ligne {rowColumn(editor.text, issue.from).row + 1}</span>
        <span class="diagtexte">{issue.message}</span>
      </button>
    {/each}
  </div>
</div>
