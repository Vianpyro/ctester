import type { Issue } from "../domain/syntax";

export interface EditorSession {
  owns(exerciseId: string): boolean;
  onInput?(file: string): void;
  onCaret?(file: string): void;
  onScroll?(file: string): void;
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
  files = $state<EditorFile[]>([]);
  sources = $state<Record<string, string>>({});
  activeFile = $state<string | null>(null);
  readOnly = $state(false);
  exerciseId = $state<string | null>(null);
  // What the checker last found in the open file, for the reminder beside the verdict.
  issues = $state<Issue[]>([]);

  element: HTMLTextAreaElement | null = null;
  session: EditorSession | null = null;

  get text(): string {
    return this.activeFile === null ? "" : (this.sources[this.activeFile] ?? "");
  }

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
    if (name !== null) this.session?.onSwitch?.(name);
  }

  cycle(by: number): void {
    const names = this.files.map((f) => f.name);
    const i = names.indexOf(this.activeFile ?? "");
    if (i < 0 || !names.length) return;
    this.activate(names[(i + by + names.length) % names.length]!);
  }

  typed(text: string): void {
    if (this.activeFile === null) return;
    this.sources[this.activeFile] = text;
    this.session?.onInput?.(this.activeFile);
  }

  read(name: string): string {
    return this.sources[name] ?? "";
  }

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

  attach(session: EditorSession | null): void {
    this.session = session;
  }

  notify(what: "onCaret" | "onScroll"): void {
    if (this.activeFile === null) return;
    try {
      this.session?.[what]?.(this.activeFile);
    } catch {
    }
  }

  sharedFor(exerciseId: string | null): boolean {
    return !!(exerciseId && this.session && this.session.owns(exerciseId));
  }
}

export const editor = new EditorState();
