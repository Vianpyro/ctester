import { fetchScratchDraft, saveScratchDraft } from "../../lib/api/scratch";
import { i18n, t } from "../../lib/i18n.svelte";
import {
  consoleFiles,
  headerNameHint,
  headerTemplate,
  validHeaderName,
} from "../../lib/domain/scratchHeader";
import { system } from "../../lib/state/system.svelte";
import { socketUrl } from "../../lib/config";
import { ensureValid, renew, session, whenSignedOut } from "../../lib/auth/session.svelte";
import type { ScratchFrame } from "../../lib/api/types";

// Close codes and exit reasons are words the judge and the API send; the page words them.
const CLOSED = [4401, 4403, 4429, 4400, 4503];
const closedMessage = (code: number): string =>
  CLOSED.includes(code) ? t(`console.closed.${code}`) : "";

const UNAUTHORIZED = 4401;

// The untouched program, in the language the page is in.
export const template = (): string =>
  '#include <stdio.h>\n\nint main(void)\n{\n    printf("' +
  t("console.hello") +
  '\\n");\n    return 0;\n}\n';

export interface Chunk {
  text: string;
  kind: "" | "gccoutput" | "scratchecho";
}

class Scratch {
  code = $state("");
  headerName = $state("");
  header = $state("");
  active = $state<"main" | "header">("main");
  output = $state<Chunk[]>([]);
  note = $state("");
  noteFailed = $state(false);
  running = $state(false);
  loaded = $state(false);

  #socket: WebSocket | null = null;
  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  #saved: string | null = null;
  #reauth = false;

  say(text: string, failed = false): void {
    this.note = text;
    this.noteFailed = failed;
  }

  write(text: string, kind: Chunk["kind"] = ""): void {
    this.output = [...this.output, { text, kind }];
  }

  async load(): Promise<void> {
    const answer = await fetchScratchDraft();
    this.loaded = true;
    if (!answer || answer.error) {
      this.say(t("console.load_failed"), true);
      return;
    }
    const name = answer.header_name ?? "";
    const valid = validHeaderName(name);
    this.code = answer.code || template();
    this.headerName = valid ? name : "";
    this.header = valid ? (answer.header ?? "") : "";
    this.active = "main";
    this.#saved = JSON.stringify({
      code: answer.code || "",
      header_name: this.headerName,
      header: this.header,
    });
  }

  get activeName(): string {
    return this.active === "header" && this.headerName ? this.headerName : "main.c";
  }

  get activeText(): string {
    return this.active === "header" && this.headerName ? this.header : this.code;
  }

  typed(text: string): void {
    if (this.active === "header" && this.headerName) this.header = text;
    else this.code = text;
    this.scheduleSave();
  }

  addHeader(name: string): string {
    if (!validHeaderName(name)) return headerNameHint();
    this.headerName = name;
    this.header = headerTemplate(name);
    this.active = "header";
    this.scheduleSave();
    return "";
  }

  renameHeader(name: string): string {
    if (!validHeaderName(name)) return headerNameHint();
    this.headerName = name;
    this.scheduleSave();
    return "";
  }

  removeHeader(): void {
    this.headerName = "";
    this.header = "";
    this.active = "main";
    this.scheduleSave();
  }

  // Loads first: the Console only loads its draft when nothing is loaded yet, so a later load
  // would overwrite the copied code.
  async adopt(files: { name: string }[], sources: Record<string, string>): Promise<boolean> {
    const moved = consoleFiles(files, sources);
    if (typeof moved === "string") {
      system.say(moved, true);
      return false;
    }
    if (!this.loaded) await this.load();
    const held = (this.code.trim() && this.code !== template()) || this.header.trim();
    const same =
      this.code === moved.code &&
      this.headerName === moved.headerName &&
      this.header === moved.header;
    if (
      held &&
      !same &&
      typeof confirm === "function" &&
      !confirm(t("console.replace_confirm"))
    ) {
      return false;
    }
    this.stop();
    this.code = moved.code;
    this.headerName = moved.headerName;
    this.header = moved.header;
    this.active = "main";
    this.output = [];
    this.say(t("console.copied"));
    this.scheduleSave();
    return true;
  }

  #draft(): { code: string; header_name: string; header: string } {
    return { code: this.code, header_name: this.headerName, header: this.header };
  }

  scheduleSave(): void {
    if (this.#saveTimer) clearTimeout(this.#saveTimer);
    this.#saveTimer = setTimeout(async () => {
      const draft = this.#draft();
      const serialized = JSON.stringify(draft);
      if (serialized === this.#saved) return;
      this.#saved = serialized;
      await saveScratchDraft(draft);
    }, 1500);
  }

  async start(resumed = false): Promise<void> {
    if (this.#socket) return;
    if (!resumed) this.#reauth = false;
    const { code, header_name, header } = this.#draft();
    if (!code.trim()) {
      this.say(t("console.nothing_to_run"), true);
      return;
    }
    this.output = [];
    this.say(t("console.connecting"));
    this.running = true;

    await ensureValid();
    if (this.#socket) return;

    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/scratch/live"));
    } catch {
      this.say(t("console.open_failed"), true);
      this.running = false;
      return;
    }
    this.#socket = socket;

    socket.onopen = () => {
      const hello = header_name
        ? { t: "hello", token: session.token, code, header_name, header }
        : { t: "hello", token: session.token, code };
      socket.send(JSON.stringify(hello));
    };

    socket.onmessage = (event) => {
      let frame: ScratchFrame | null = null;
      try {
        frame = JSON.parse(String(event.data)) as ScratchFrame;
      } catch {
        return;
      }
      if (!frame || typeof frame !== "object") return;
      if (frame.t === "queued") {
        this.say(
          frame.position
            ? t("console.queued", { position: frame.position }) +
                (frame.eta
                  ? t("console.queued_eta", { minutes: Math.ceil((frame.eta / 60) * 10) / 10 })
                  : "")
            : t("console.waiting"),
        );
      } else if (frame.t === "ready") {
        this.say(t("console.compiling"));
      } else if (frame.t === "running") {
        this.say(t("console.running"));
      } else if (frame.t === "build") {
        this.write(frame.d, "gccoutput");
      } else if (frame.t === "out") {
        this.say(t("console.running"));
        this.write(frame.d);
      } else if (frame.t === "exit") {
        const reason = `console.reason.${frame.reason}`;
        const why = i18n.has(reason) ? t(reason) : null;
        this.say(why ?? t("console.finished", { code: frame.code }), !!why);
      }
    };

    socket.onclose = (event) => {
      if (this.#socket === socket) this.#socket = null;
      this.running = false;
      if (event.code === UNAUTHORIZED && !this.#reauth) {
        this.#reauth = true;
        this.say(t("console.reconnecting"));
        void renew().then((ok) => {
          if (ok) return this.start(true);
          this.say(closedMessage(UNAUTHORIZED), true);
        });
        return;
      }
      const said = closedMessage(event.code);
      if (said) this.say(said, true);
    };

    socket.onerror = () => {
      this.say(t("console.lost"), true);
    };
  }

  send(text: string): void {
    if (!this.#socket) return;
    this.#socket.send(JSON.stringify({ t: "stdin", d: text + "\n" }));
    this.write(text + "\n", "scratchecho");
  }

  endInput(): void {
    this.#socket?.send(JSON.stringify({ t: "eof" }));
    this.write(t("console.eof_echo") + "\n", "scratchecho");
  }

  stop(): void {
    const socket = this.#socket;
    this.#socket = null;
    this.running = false;
    try {
      socket?.close();
    } catch {
    }
  }
}

export const scratch = new Scratch();

whenSignedOut(() => scratch.stop());
