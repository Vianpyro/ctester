// WHAT THE EDITOR HOLDS, AND THE WHOLE CONTRACT A COLLABORATIVE SESSION GETS.
//
// This module owns the open exercise's files, their contents, which tab is
// active, and whether typing is allowed. The COMPONENT owns the `<textarea>`
// element and registers it here; the collaboration session owns a shared document
// and never touches the element itself.
//
// THE CARET IS THE POINT. A remote change arriving while somebody is typing used
// to be what made shared editors unusable: the text jumps and the cursor goes to
// the end. `write()` takes the selection the session computed from the CRDT delta
// -- the only place that knows how many characters landed before it -- and there is
// exactly ONE place in this application where a caret can be lost.

/** What the core tells a collaborative session, and when. */
export interface EditorSession {
  /** True while this session owns the exercise's saving (the TEAM's document). */
  owns(exerciseId: string): boolean;
  /** Every keystroke: a CRDT update has to leave immediately, not on a timer. */
  onInput?(file: string): void;
  /** The caret moved without the text changing: arrows, a click, a selection. */
  onCaret?(file: string): void;
  onScroll?(file: string): void;
  /** A caret in `matrac_lib.c` is not a caret in `main.c`. */
  onSwitch?(file: string): void;
}

export interface EditorFile {
  name: string;
  template: string;
}

export interface Selection {
  start: number;
  end: number;
}

class EditorState {
  /** The declared files. NAMES are authoritative and come from the catalog. */
  files = $state<EditorFile[]>([]);
  /** file name -> its text. The active file's text is mirrored from the element. */
  sources = $state<Record<string, string>>({});
  activeFile = $state<string | null>(null);
  /**
   * READ-ONLY IS A REAL STATE, not a disabled button: a workspace whose library
   * did not load, or whose socket died on a document nobody has seeded, must stop
   * accepting typing rather than accept it and lose it.
   */
  readOnly = $state(false);
  /**
   * The exercise the editor ACTUALLY holds -- not what the menu shows. Set only
   * once the fill-in has arrived. See `state/catalog.svelte.ts`.
   */
  exerciseId = $state<string | null>(null);

  /** The element, registered by the component that renders it. */
  element: HTMLTextAreaElement | null = null;
  session: EditorSession | null = null;

  get text(): string {
    return this.activeFile === null ? "" : (this.sources[this.activeFile] ?? "");
  }

  /** Open an exercise's files. `held` is the draft, or null for the templates. */
  open(exerciseId: string | null, files: EditorFile[], held: Record<string, string> | null): void {
    this.files = files;
    if (held) {
      this.sources = { ...held };
    } else {
      const fresh: Record<string, string> = {};
      for (const f of files) fresh[f.name] = f.template || "";
      this.sources = fresh;
    }
    this.exerciseId = exerciseId;
    this.activate(files[0]?.name ?? null);
  }

  activate(name: string | null): void {
    this.activeFile = name;
    if (name !== null && this.sources[name] === undefined) this.sources[name] = "";
    // The element's value follows the state; the component's effect does that.
    if (name !== null) this.session?.onSwitch?.(name);
  }

  /** Cycle tabs with the arrow keys, the way a tablist is expected to behave. */
  cycle(by: number): void {
    const names = this.files.map((f) => f.name);
    const i = names.indexOf(this.activeFile ?? "");
    if (i < 0 || !names.length) return;
    this.activate(names[(i + by + names.length) % names.length]!);
  }

  /** What the student typed, mirrored out of the element. */
  typed(text: string): void {
    if (this.activeFile === null) return;
    this.sources[this.activeFile] = text;
    this.session?.onInput?.(this.activeFile);
  }

  read(name: string): string {
    return this.sources[name] ?? "";
  }

  /**
   * A file's new text, from anywhere but the keyboard: a shared document, a
   * restored revision, an imported file. `selection` is where the caller wants the
   * caret left.
   */
  write(name: string, text: string, selection?: Selection | null): void {
    this.sources[name] = text;
    if (name !== this.activeFile) return;
    const zone = this.element;
    if (!zone) return;
    if (zone.value === text && !selection) return;
    zone.value = text;
    if (selection) {
      zone.selectionStart = Math.min(selection.start, text.length);
      zone.selectionEnd = Math.min(selection.end, text.length);
    }
  }

  lock(locked: boolean): void {
    this.readOnly = !!locked;
  }

  /** The session registers itself; the direction stays one-way. */
  attach(session: EditorSession | null): void {
    this.session = session;
  }

  notify(what: "onCaret" | "onScroll"): void {
    if (this.activeFile === null) return;
    try {
      this.session?.[what]?.(this.activeFile);
    } catch {
      // A collaboration hook must NEVER break typing.
    }
  }

  /** True while a collaborative session is doing the saving for this exercise. */
  sharedFor(exerciseId: string | null): boolean {
    return !!(exerciseId && this.session && this.session.owns(exerciseId));
  }
}

export const editor = new EditorState();
