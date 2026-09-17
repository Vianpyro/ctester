import { fetchScratchDraft, saveScratchDraft } from "../../lib/api/scratch";
import { HEADER_NAME_HINT, headerTemplate, validHeaderName } from "../../lib/domain/scratchHeader";
import { socketUrl } from "../../lib/config";
import { ensureValid, renew, session, whenSignedOut } from "../../lib/auth/session.svelte";
import type { ScratchFrame } from "../../lib/api/types";

const CLOSED: Record<number, string> = {
  4401: "Ta session a expiré. Reconnecte-toi pour utiliser la Console.",
  4403: "Origine refusée.",
  4429: "Tu as déjà une session ouverte, ou tu en as lancé beaucoup : attends un instant.",
  4400: "La Console n'a pas pu démarrer. Recharge la page.",
  4503: "La Console ne répond pas en ce moment. Réessaie dans une minute.",
};

const UNAUTHORIZED = 4401;

const REASONS: Record<string, string> = {
  cpu: "Ton programme a utilisé tout son temps de calcul — boucle infinie ?",
  timeout: "La session a atteint sa durée maximale.",
  idle: "Session fermée : plus rien ne se passait.",
  output: "Ton programme a écrit beaucoup trop de texte — boucle infinie ?",
  compile_error: "La compilation a échoué (voir ci-dessus).",
  compile_timeout: "La compilation a été trop longue.",
  worker: "Le service de compilation s'est interrompu. Réessaie.",
  build_missing:
    "La Console n'est pas complètement installée sur le serveur. Préviens ton enseignant" +
    " — réessayer n'y changera rien.",
  api: "Session interrompue.",
};

export const TEMPLATE =
  '#include <stdio.h>\n\nint main(void)\n{\n    printf("Bonjour !\\n");\n    return 0;\n}\n';

export interface Chunk {
  text: string;
  kind: "" | "gccsortie" | "scratchecho";
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
      this.say("Ton bloc-notes n'a pas pu être chargé — ce qui est à l'écran reste là.", true);
      return;
    }
    const name = answer.header_name ?? "";
    const valid = validHeaderName(name);
    this.code = answer.code || TEMPLATE;
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
    if (!validHeaderName(name)) return HEADER_NAME_HINT;
    this.headerName = name;
    this.header = headerTemplate(name);
    this.active = "header";
    this.scheduleSave();
    return "";
  }

  renameHeader(name: string): string {
    if (!validHeaderName(name)) return HEADER_NAME_HINT;
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
      this.say("Il n'y a encore rien à exécuter : écris ou colle ton programme.", true);
      return;
    }
    this.output = [];
    this.say("Connexion…");
    this.running = true;

    await ensureValid();
    if (this.#socket) return;

    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/scratch/live"));
    } catch {
      this.say("La Console n'a pas pu s'ouvrir.", true);
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
            ? "Dans la file : " +
                frame.position +
                (frame.eta ? " — environ " + Math.ceil((frame.eta / 60) * 10) / 10 + " min" : "")
            : "En attente…",
        );
      } else if (frame.t === "ready") {
        this.say("Compilation…");
      } else if (frame.t === "running") {
        this.say("En cours — tu peux répondre à ton programme.");
      } else if (frame.t === "build") {
        this.write(frame.d, "gccsortie");
      } else if (frame.t === "out") {
        this.say("En cours — tu peux répondre à ton programme.");
        this.write(frame.d);
      } else if (frame.t === "exit") {
        const why = REASONS[frame.reason];
        this.say(why ?? "Terminé (code " + frame.code + ").", !!why && frame.reason !== "exited");
      }
    };

    socket.onclose = (event) => {
      if (this.#socket === socket) this.#socket = null;
      this.running = false;
      if (event.code === UNAUTHORIZED && !this.#reauth) {
        this.#reauth = true;
        this.say("Reconnexion…");
        void renew().then((ok) => {
          if (ok) return this.start(true);
          this.say(CLOSED[UNAUTHORIZED]!, true);
        });
        return;
      }
      const said = CLOSED[event.code];
      if (said) this.say(said, true);
    };

    socket.onerror = () => {
      this.say("La connexion à la Console a été perdue.", true);
    };
  }

  send(text: string): void {
    if (!this.#socket) return;
    this.#socket.send(JSON.stringify({ t: "stdin", d: text + "\n" }));
    this.write(text + "\n", "scratchecho");
  }

  endInput(): void {
    this.#socket?.send(JSON.stringify({ t: "eof" }));
    this.write("(fin de l'entrée)\n", "scratchecho");
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
