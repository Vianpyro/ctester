<script lang="ts">
  // THE EDITING SURFACE, AND THERE IS ONLY ONE OF IT. A `<pre>` of coloured HTML
  // (`.hl`) behind a `<textarea>` whose own text is transparent (`.codein`), a
  // gutter beside them, and the syntax checker's underline on its own layer.
  //
  // IT WAS TWO COPIES, AND THE SECOND ONE SILENTLY FELL BEHIND. The Console had
  // the same three elements and the same classes, but neither the Tab key, nor
  // the auto-closing pairs, nor the syntax checker -- each feature was written
  // for the exercise editor and simply never reached the other. That is the cost
  // this file removes: a feature added here appears in both, or in neither.
  //
  // WHAT STAYS OUT OF IT is what is not editing: the file tabs, the draft status,
  // the teammates' carets, the Console's terminal. The first three belong to the
  // exercise, the last to the Console; a surface that knew about any of them
  // would be the same duplication wearing a prop.
  //
  // `#hl` AND `#code` MUST KEEP IDENTICAL METRICS -- font, size, line height,
  // padding, border, tab-size, white-space. Anything that shifts the text by one
  // pixel shifts the colours off it, and `lib/collab/carets.ts` places both
  // teammates' cursors and the checker's underline by arithmetic on those same
  // metrics. The rules live ONCE in `app.css` (`.hl, .codein`); this component
  // must not restate them.

  import type { Snippet } from "svelte";
  import { highlight } from "../lib/domain/highlight";
  import { commandEdit, keyEdit, lineSpan, parseLine, type Edit } from "../lib/domain/keys";
  import { EDITOR_COMMANDS, TEXT_COMMANDS, matchShortcut, type ShortcutId } from "../lib/domain/shortcuts";
  import { system } from "../lib/state/system.svelte";
  import { check, nextIssue, type Issue } from "../lib/domain/syntax";
  import { measure, rowColumn, selectionBands, type Metrics } from "../lib/collab/carets";

  interface Scroll {
    left: number;
    top: number;
  }

  interface Props {
    /** The text. One-way in; every change comes back through `onInput`. */
    value: string;
    /** Called with the new text, whether it was typed or applied by a key. */
    onInput?: (text: string) => void;
    /** The caret may have moved. */
    onCaret?: () => void;
    /** The view scrolled. The overlays are already placed; this is for others. */
    onScrolled?: () => void;
    readOnly?: boolean;
    label: string;
    placeholder: string;
    /**
     * PREFIXES THE IDS, because both editors are in the document at once --
     * `#travail` is hidden, not unmounted. Nothing selects these ids; they are
     * labels, and duplicating them would still be wrong.
     */
    idPrefix?: string;
    /** Extra class on the box, for a caller with its own layout. */
    wrapClass?: string;
    /** `tabpanel` when the caller has file tabs pointing at this box. */
    wrapRole?: string;
    /** The textarea, for a parent that needs to write into it (`editor.write`). */
    element?: HTMLTextAreaElement | null;
    /** An extra layer over the textarea, given the mirrored scroll offsets. */
    overlay?: Snippet<[Scroll]>;
  }

  let {
    value,
    onInput,
    onCaret,
    onScrolled,
    readOnly = false,
    label,
    placeholder,
    idPrefix = "",
    wrapClass = "",
    wrapRole,
    element = $bindable(null),
    overlay,
  }: Props = $props();

  let zone: HTMLTextAreaElement | undefined = $state();
  let painter: HTMLPreElement | undefined = $state();
  let gutter: HTMLPreElement | undefined = $state();

  /** Scroll offsets, mirrored so the overlays can place themselves. */
  let scroll: Scroll = $state({ left: 0, top: 0 });

  const painted = $derived(highlight(value));
  const lines = $derived(value.split("\n").length);

  $effect(() => {
    element = zone ?? null;
    return () => {
      if (element === zone) element = null;
    };
  });

  // THE ELEMENT FOLLOWS THE STATE when the state changed elsewhere -- a tab switch,
  // an imported file, a shared document. Typing does not come through here: it goes
  // state-ward, and writing the value back would fight the caret.
  $effect(() => {
    const text = value;
    if (zone && zone.value !== text) zone.value = text;
  });

  // --- THE SYNTAX CHECK ------------------------------------------------------
  // NOT A `$derived`, AND THE DELAY IS THE FEATURE. Announcing "unclosed
  // parenthesis" on the keystroke that types `(` is a checker that scolds while
  // you write. Each keystroke pushes the deadline back, so it speaks once the
  // typing pauses.

  let issues = $state<Issue[]>([]);

  $effect(() => {
    const source = value;
    const timer = setTimeout(() => {
      issues = check(source);
    }, 600);
    return () => clearTimeout(timer);
  });

  /** The flagged line numbers, 1-based, and the worst level on each. */
  const flagged = $derived.by(() => {
    const rows = new Map<number, string>();
    for (const issue of issues) {
      const row = rowColumn(value, issue.from).row + 1;
      if (issue.level === "error" || !rows.has(row)) rows.set(row, issue.level);
    }
    return rows;
  });

  // NO METRICS MEANS NO UNDERLINE, the same deliberate silence as `RemoteCarets`:
  // one drawn at the wrong place points at innocent code.
  let metrics = $state<Metrics | null>(null);

  $effect(() => {
    metrics = zone && issues.length ? measure(zone) : null;
  });

  const usable = $derived(!!metrics && !!metrics.char && !!metrics.line);

  /**
   * WHAT A COMMAND DOES, once the table has said which one it is.
   *
   * NAVIGATION WORKS ON A LOCKED DOCUMENT, EDITING DOES NOT, and the split is
   * `TEXT_COMMANDS`. A teammate reading a document somebody else holds must
   * still be able to jump to a fault or to a line number; what they must not do
   * is rewrite it. The refusal SAYS so -- a silent no-op on a locked document
   * reads as a broken page, which is the failure `readOnly` already had once.
   */
  function command(id: ShortcutId) {
    if (!zone) return;
    if (id === "nextIssue") {
      const issue = nextIssue(issues, zone.selectionEnd);
      if (issue) goTo(issue);
      return;
    }
    if (id === "gotoLine") {
      going = "";
      return;
    }
    if (readOnly && TEXT_COMMANDS.has(id)) {
      system.flash("Ce document est en lecture seule : c'est un coéquipier qui écrit.");
      return;
    }
    const edit = commandEdit(id, zone.value, zone.selectionStart, zone.selectionEnd);
    if (edit) apply(edit);
  }

  // --- ALLER À LA LIGNE ------------------------------------------------------
  // A FIELD AND NOT `prompt()`, for three measured reasons: `prompt()` blocks the
  // event loop (in a team room the socket keeps buffering while the UI is frozen),
  // its chrome is in the OS language so this French page grows an English box, and
  // Chrome suppresses it inside an iframe -- which is how this page is embedded in
  // Moodle. It is ONE input, not a dialog: there is no focus trap to build.

  /** `null` when closed. Closed means not rendered, so it is not a tab stop. */
  let going = $state<string | null>(null);
  let goField: HTMLInputElement | undefined = $state();

  $effect(() => {
    // Focused from here and never with `autofocus`, which svelte-check refuses.
    if (going !== null) goField?.focus();
  });

  function onGoKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter" && event.key !== "Escape") return;
    // PREVENTED SO THE WINDOW DOES NOT ACT TOO: without it, this Escape would
    // also reach `App.svelte` and close a panel behind the editor.
    event.preventDefault();
    if (event.key === "Enter") {
      const line = parseLine(going ?? "", value.split("\n").length);
      if (line !== null && zone) {
        const span = lineSpan(value, line);
        zone.focus();
        zone.setSelectionRange(span.from, span.to);
        onCaret?.();
      }
    } else {
      zone?.focus();
    }
    going = null;
  }

  /** Put the caret on a fault. The list is a way IN, not just a report. */
  function goTo(issue: Issue) {
    if (!zone) return;
    zone.focus();
    zone.setSelectionRange(issue.from, issue.to);
    onCaret?.();
  }

  function typed() {
    if (zone) onInput?.(zone.value);
  }

  function onScroll() {
    if (!zone) return;
    scroll = { left: zone.scrollLeft, top: zone.scrollTop };
    if (painter) {
      painter.scrollTop = zone.scrollTop;
      painter.scrollLeft = zone.scrollLeft;
    }
    if (gutter) gutter.scrollTop = zone.scrollTop;
    onScrolled?.();
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

    // THE IDE COMMANDS, AND THEY COME BEFORE THE MODIFIER GUARD BELOW -- which is
    // the whole change: that guard used to be the end of the story, so every
    // Ctrl chord fell through to the browser. `matchShortcut` claims only what
    // the table names, and nothing else, so what follows is unchanged.
    //
    // WE PREVENT THE DEFAULT EVEN WHEN NOTHING HAPPENS. `commandEdit` returns
    // `null` for "there is nothing to do" (Alt+Shift+Up on the first line), and
    // letting the browser act on those would extend a selection over the block
    // the student is trying to move. It is also what keeps Ctrl+D from opening
    // Chrome's bookmark dialog on a read-only document.
    const id = zone ? matchShortcut(event) : null;
    if (id && EDITOR_COMMANDS.has(id)) {
      event.preventDefault();
      command(id);
      return;
    }

    // Ctrl, Meta and Alt are the browser's and the student's -- Ctrl+Z above all.
    // Everything the table did not claim still belongs to them.
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!zone || readOnly) return;
    const { value: text, selectionStart, selectionEnd } = zone;
    const edit = keyEdit(event.key, event.shiftKey, text, selectionStart, selectionEnd);
    if (!edit) return;
    event.preventDefault();
    apply(edit);
  }

  /**
   * `execCommand` AND NOT `zone.value = …`, AND THAT IS THE WHOLE REASON THIS
   * FUNCTION EXISTS. Assigning the value **wipes the browser's undo stack**:
   * tolerable for the single Tab key this used to be, unacceptable once every `(`
   * goes through here, since Ctrl+Z would stop working while typing. `insertText`
   * keeps the stack AND fires a real `input` event, so the handler runs exactly as
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
      typed();
    }
    zone.setSelectionRange(edit.caret, edit.caretEnd ?? edit.caret);
  }
</script>

<div id={idPrefix + "edwrap"} class={"edwrap " + wrapClass} role={wrapRole}>
  <!-- A FLAGGED LINE IS A COLOURED NUMBER, not an added glyph: the gutter is
       `text-align: right`, so a `▲` in front would shove that one line's digits
       sideways. Rendered as spans rather than `{@html}` -- the numbers come from a
       counter, but this file has no business growing a second innerHTML. -->
  <pre bind:this={gutter} id={idPrefix + "gutter"} class="gutter" aria-hidden="true">{#each { length: lines } as _, i}<span
        class={flagged.get(i + 1) ?? ""}>{i + 1}</span>{"\n"}{/each}</pre>
  <div id={idPrefix + "pane"} class="pane">
    <!-- ONE OF THE TWO PLACES THIS APPLICATION USES `{@html}`, and it is safe for
         exactly one reason: every branch of `highlight()` runs its slice through
         `escapeHtml()` first. Text in, escaped HTML out. -->
    <pre bind:this={painter} id={idPrefix + "hl"} class="hl" aria-hidden="true"><code
        id={idPrefix + "hlcode"}>{@html painted}</code
      ></pre>
    <textarea
      bind:this={zone}
      id={idPrefix + "code"}
      class="codein"
      spellcheck="false"
      readonly={readOnly}
      aria-label={label}
      {placeholder}
      oninput={typed}
      onscroll={onScroll}
      onkeydown={onKeydown}
      onkeyup={() => onCaret?.()}
      onclick={() => onCaret?.()}
      onselect={() => onCaret?.()}
    ></textarea>
    {@render overlay?.(scroll)}
    <!-- THE UNDERLINE IS A LAYER, NEVER A SPAN INSIDE `#hl`. Wrapping the coloured
         text would put a second thing inside the one element whose metrics must
         match the textarea to the pixel. `selectionBands()` already turns a range
         into one rectangle per line, in the same arithmetic the teammates' carets
         use. A CLASS and not an id: two editors are in the document at once. -->
    <div class="squiggles" aria-hidden="true">
      {#if usable && metrics}
        {#each issues as issue (issue.from + ":" + issue.message)}
          {#each selectionBands(value, issue.from, issue.to, metrics, scroll) as band}
            <i class={"squig " + issue.level} style={band}></i>
          {/each}
        {/each}
      {/if}
    </div>
  </div>
</div>
{#if going !== null}
  <!-- RENDERED ONLY WHEN OPEN, so a closed field is not a tab stop for anybody
       navigating the page with the keyboard. The label is visually hidden and
       carries the `idPrefix`, because the exercise and the Console are both in
       the document at once. -->
  <div class="aller">
    <label class="horsecran" for={idPrefix + "aller"}>Aller à la ligne</label>
    <input
      bind:this={goField}
      bind:value={going}
      id={idPrefix + "aller"}
      type="text"
      inputmode="numeric"
      placeholder="Aller à la ligne…"
      onkeydown={onGoKeydown}
      onblur={() => (going = null)}
    />
    <span class="allerdit">Entrée pour y aller, Échap pour annuler</span>
  </div>
{/if}
<!-- WHAT THE CHECKER FOUND, under the code. Two levels, and the wording already
     says which is which: an "error" is certain, a "hint" is a guess written as
     one. Each row is a button, so the keyboard reaches the fault the same way the
     mouse does. -->
<div class="diags" aria-live="polite" hidden={issues.length === 0}>
  {#each issues as issue (issue.from + ":" + issue.message)}
    <button type="button" class={"diag " + issue.level} onclick={() => goTo(issue)}>
      <span class="diagline">ligne {rowColumn(value, issue.from).row + 1}</span>
      <span class="diagtexte">{issue.message}</span>
    </button>
  {/each}
</div>
