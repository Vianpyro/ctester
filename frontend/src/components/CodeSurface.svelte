<script lang="ts">
  import type { Snippet } from "svelte";
  import { t } from "../lib/i18n.svelte";
  import { highlight } from "../lib/domain/highlight";
  import { commandEdit, keyEdit, lineSpan, parseLine, type Edit } from "../lib/domain/keys";
  import { EDITOR_COMMANDS, TEXT_COMMANDS, matchShortcut, type ShortcutId } from "../lib/domain/shortcuts";
  import { system } from "../lib/state/system.svelte";
  import type { Issue } from "../lib/domain/syntax";
  import { measure, place, rowColumn, selectionBands, type Metrics } from "../lib/collab/carets";

  interface Scroll {
    left: number;
    top: number;
  }

  interface Props {
    value: string;
    onInput?: (text: string) => void;
    onCaret?: () => void;
    onScrolled?: () => void;
    onIssues?: (issues: Issue[]) => void;
    readOnly?: boolean;
    label: string;
    placeholder: string;
    idPrefix?: string;
    wrapClass?: string;
    wrapRole?: string;
    element?: HTMLTextAreaElement | null;
    overlay?: Snippet<[Scroll]>;
  }

  let {
    value,
    onInput,
    onCaret,
    onScrolled,
    onIssues,
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

  let scroll: Scroll = $state({ left: 0, top: 0 });

  const painted = $derived(highlight(value));
  const lines = $derived(value.split("\n").length);

  $effect(() => {
    element = zone ?? null;
    return () => {
      if (element === zone) element = null;
    };
  });

  $effect(() => {
    const text = value;
    if (zone && zone.value !== text) zone.value = text;
  });

  let issues = $state<Issue[]>([]);
  // Out of the eager bundle, but fetched with the page rather than at the first pause: a tab
  // left open across a release would ask for a chunk the new release no longer serves.
  const linting = import("../lib/domain/syntax").catch(() => {
    system.say(t("app.load_failed", { what: t("app.load.checker") }), true);
    return null;
  });
  let lint: typeof import("../lib/domain/syntax") | null = null;
  const formatting = import("../lib/domain/reindent").catch(() => {
    system.say(t("app.load_failed", { what: t("app.load.format") }), true);
    return null;
  });

  $effect(() => {
    const source = value;
    const timer = setTimeout(() => {
      void linting.then((mod) => {
        if (!mod) return;
        lint = mod;
        if (source !== value) return;
        issues = mod.check(source);
        onIssues?.(issues);
      });
    }, 600);
    return () => clearTimeout(timer);
  });

  // One issue per row, the surest first: the row is tinted and its message written after it.
  const flagged = $derived.by(() => {
    const rows = new Map<number, Issue>();
    for (const issue of issues) {
      const row = rowColumn(value, issue.from).row + 1;
      if (!rows.has(row) || (issue.level === "error" && rows.get(row)!.level !== "error")) {
        rows.set(row, issue);
      }
    }
    return rows;
  });

  const lineLengths = $derived(value.split("\n").map((line) => line.length));

  let metrics = $state<Metrics | null>(null);

  $effect(() => {
    metrics = zone && issues.length ? measure(zone) : null;
  });

  const usable = $derived(!!metrics && !!metrics.char && !!metrics.line);

  export function command(id: ShortcutId) {
    if (!zone) return;
    if (id === "nextIssue") {
      const issue = lint?.nextIssue(issues, zone.selectionEnd);
      if (issue) goTo(issue);
      return;
    }
    if (id === "gotoLine") {
      going = "";
      return;
    }
    if (readOnly && TEXT_COMMANDS.has(id)) {
      system.flash(t("editor.read_only"));
      return;
    }
    if (id === "format") {
      void formatting.then((mod) => {
        const edit = zone && mod?.formatEdit(zone.value, zone.selectionStart, zone.selectionEnd);
        if (edit) apply(edit);
      });
      return;
    }
    const edit = commandEdit(id, zone.value, zone.selectionStart, zone.selectionEnd);
    if (edit) apply(edit);
  }

  let going = $state<string | null>(null);
  let goField: HTMLInputElement | undefined = $state();

  $effect(() => {
    if (going !== null) goField?.focus();
  });

  function onGoKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter" && event.key !== "Escape") return;
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

  let escaped = false;

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      escaped = true;
      return;
    }
    const leaving = event.key === "Tab" && escaped;
    escaped = false;
    if (leaving) return;

    const id = zone ? matchShortcut(event) : null;
    if (id && EDITOR_COMMANDS.has(id)) {
      event.preventDefault();
      command(id);
      return;
    }

    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!zone || readOnly) return;
    const { value: text, selectionStart, selectionEnd } = zone;
    const edit = keyEdit(event.key, event.shiftKey, text, selectionStart, selectionEnd);
    if (!edit) return;
    event.preventDefault();
    apply(edit);
  }

  function apply(edit: Edit) {
    if (!zone) return;
    if (edit.insert === "" && edit.from === edit.to) {
      zone.setSelectionRange(edit.caret, edit.caretEnd ?? edit.caret);
      return;
    }
    zone.setSelectionRange(edit.from, edit.to);
    // execCommand keeps the browser's undo stack; assigning value would wipe it.
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
  <pre bind:this={gutter} id={idPrefix + "gutter"} class="gutter" aria-hidden="true">{#each { length: lines } as _, i}<span
        class={flagged.get(i + 1)?.level ?? ""}>{i + 1}</span>{"\n"}{/each}</pre>
  <div id={idPrefix + "pane"} class="pane">
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
    <div class="squiggles" aria-hidden="true">
      {#if usable && metrics}
        {#each flagged as [row, issue] (row)}
          <i
            class={"rowflag " + issue.level}
            style={"top:" + (metrics.top + (row - 1) * metrics.line - scroll.top) + "px;height:" + metrics.line + "px;"}
          ></i>
          <span class={"lens " + issue.level} style={place(metrics, scroll, (lineLengths[row - 1] ?? 0) + 2, row - 1)}
            >{issue.message}</span
          >
        {/each}
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
  <div class="goto">
    <label class="offscreen" for={idPrefix + "goto"}>{t("editor.goto")}</label>
    <input
      bind:this={goField}
      bind:value={going}
      id={idPrefix + "goto"}
      type="text"
      inputmode="numeric"
      placeholder={t("editor.goto_placeholder")}
      onkeydown={onGoKeydown}
      onblur={() => (going = null)}
    />
    <span class="gotohint">{t("editor.goto_hint")}</span>
  </div>
{/if}
<div class="diags" aria-live="polite" hidden={issues.length === 0}>
  <p class="diagsum">{t("editor.issues", { count: issues.length })}</p>
  {#each issues as issue (issue.from + ":" + issue.message)}
    <button type="button" class={"diag " + issue.level} onclick={() => goTo(issue)}>
      <span class="diagline">{t("editor.line", { n: rowColumn(value, issue.from).row + 1 })}</span>
      <span class="diagtext">{issue.message}</span>
    </button>
  {/each}
</div>
