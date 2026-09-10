// THE CONSOLE'S SESSION: an interactive C terminal, one WebSocket.
//
// THE SOCKET IS THE SESSION. There is no "stop" frame: closing it IS the stop -- the
// server releases its `flock`, the kernel tells the worker, the container dies. One code
// path, and it works when the tab disappears without warning.
//
// IT HAS ITS OWN EDITOR AND NEVER TOUCHES THE EXERCISE ONE. That editor belongs to an
// exercise id, to its draft and, on an assignment, to the team CRDT; writing into it from
// here would put a second owner on the caret and attribute a scratchpad to an exercise.
//
// IT IS CALLED "Console", NEVER "bac à sable". The sandbox is the judge's gVisor
// container. Reusing the word would do what this repository refuses elsewhere -- one word
// per state. In code everything is called `scratch`.

import { fetchScratchDraft, saveScratchDraft } from "../../lib/api/scratch";
import { socketUrl } from "../../lib/config";
import { ensureValid, renew, session, whenSignedOut } from "../../lib/auth/session.svelte";
import type { ScratchFrame } from "../../lib/api/types";

/** What the server says when it closes. A student whose session expired and one who
 *  arrives while somebody else holds the Console must not read the same thing. */
const CLOSED: Record<number, string> = {
  4401: "Ta session a expiré. Reconnecte-toi pour utiliser la Console.",
  4403: "Origine refusée.",
  4429: "Tu as déjà une session ouverte, ou tu en as lancé beaucoup : attends un instant.",
  4400: "La Console n'a pas pu démarrer. Recharge la page.",
  4503: "La Console ne répond pas en ce moment. Réessaie dans une minute.",
};

const UNAUTHORIZED = 4401;

/** Why the program stopped. `exited` is not here: a program that ends normally has
 *  nothing to explain, so its exit code is shown instead. */
const REASONS: Record<string, string> = {
  cpu: "Ton programme a utilisé tout son temps de calcul — boucle infinie ?",
  timeout: "La session a atteint sa durée maximale.",
  idle: "Session fermée : plus rien ne se passait.",
  output: "Ton programme a écrit beaucoup trop de texte — boucle infinie ?",
  compile_error: "La compilation a échoué (voir ci-dessus).",
  compile_timeout: "La compilation a été trop longue.",
  worker: "Le service de compilation s'est interrompu. Réessaie.",
  // NOT "the service was interrupted": nothing was interrupted, a variable is MISSING on
  // the worker's unit. Blaming the service would send the student retrying in a loop over
  // an outage no retry repairs.
  build_missing:
    "La Console n'est pas complètement installée sur le serveur. Préviens ton enseignant" +
    " — réessayer n'y changera rien.",
  api: "Session interrompue.",
};

export const TEMPLATE =
  '#include <stdio.h>\n\nint main(void)\n{\n    printf("Bonjour !\\n");\n    return 0;\n}\n';

export interface Chunk {
  text: string;
  /** "" the program, "gccsortie" the compiler, "scratchecho" the local echo. */
  kind: "" | "gccsortie" | "scratchecho";
}

class Scratch {
  code = $state("");
  output = $state<Chunk[]>([]);
  note = $state("");
  noteFailed = $state(false);
  running = $state(false);
  /** null until the notepad has been read once. */
  loaded = $state(false);

  #socket: WebSocket | null = null;
  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  /** What the server already has, so an unchanged notepad is not rewritten. */
  #saved: string | null = null;
  /** One token renewal per session. */
  #reauth = false;

  say(text: string, failed = false): void {
    this.note = text;
    this.noteFailed = failed;
  }

  write(text: string, kind: Chunk["kind"] = ""): void {
    this.output = [...this.output, { text, kind }];
  }

  /** A MUTE DATABASE IS NOT AN EMPTY NOTEPAD. Overwriting the editor with "" at the first
   *  Postgres hiccup would erase somebody's work; we leave what is on screen and say so. */
  async load(): Promise<void> {
    const answer = await fetchScratchDraft();
    this.loaded = true;
    if (!answer || answer.error) {
      this.say("Ton bloc-notes n'a pas pu être chargé — ce qui est à l'écran reste là.", true);
      return;
    }
    this.#saved = answer.code || "";
    this.code = this.#saved || TEMPLATE;
  }

  /** The Console is a notepad: one types a lot and saves little. */
  scheduleSave(): void {
    if (this.#saveTimer) clearTimeout(this.#saveTimer);
    this.#saveTimer = setTimeout(async () => {
      if (this.code === this.#saved) return;
      this.#saved = this.code;
      await saveScratchDraft(this.code);
    }, 1500);
  }

  /**
   * `resumed` is a relaunch after a token renewal, not a click. That is what bounds the
   * renewal to ONE per session: a click starts from a clean slate, the automatic relaunch
   * inherits the previous attempt.
   */
  async start(resumed = false): Promise<void> {
    if (this.#socket) return;
    if (!resumed) this.#reauth = false;
    const code = this.code;
    if (!code.trim()) {
      this.say("Il n'y a encore rien à exécuter : écris ou colle ton programme.", true);
      return;
    }
    this.output = [];
    this.say("Connexion…");
    this.running = true;

    // THE TOKEN GOES IN THE FIRST FRAME: it must still be good before opening. A session
    // refused on 4401 is a queue slot spent for nothing, and the student reads "ta session
    // a expiré" when it no longer is.
    await ensureValid();
    if (this.#socket) return; // another session opened in between

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
      // IN THE FIRST FRAME, NEVER IN THE URL: a browser cannot set an `Authorization`
      // header on a WebSocket, and a token in a query string is a token in every proxy log
      // on the path.
      socket.send(JSON.stringify({ t: "hello", token: session.token, code }));
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
      } else if (frame.t === "build") {
        // The compiler's diagnostics, told apart from the program's output: that is why the
        // worker cuts the stream on its phase marker.
        this.write(frame.d, "gccsortie");
      } else if (frame.t === "out") {
        this.say("En cours — ton programme tourne.");
        this.write(frame.d);
      } else if (frame.t === "exit") {
        const why = REASONS[frame.reason];
        this.say(why ?? "Terminé (code " + frame.code + ").", !!why && frame.reason !== "exited");
      }
    };

    socket.onclose = (event) => {
      if (this.#socket === socket) this.#socket = null;
      this.running = false;
      // AN EXPIRED TOKEN IS REPAIRED HERE, AND NOTHING HAS RUN YET: the server refuses at
      // the `hello` frame, before the queue and before the container. One renewal, the SAME
      // program relaunched, and `#reauth` stops there -- otherwise a stubborn refusal would
      // relaunch the Console forever.
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
    // THE NEWLINE IS ADDED HERE, and it is what `scanf` waits for. Without it the program
    // would stay blocked on an input the student believes they sent -- the mistake that
    // makes a terminal look broken.
    this.#socket.send(JSON.stringify({ t: "stdin", d: text + "\n" }));
    // THE ECHO IS LOCAL. The program does not redisplay what it is given (there is no
    // terminal to do it), so without this line the student would never see their answer.
    this.write(text + "\n", "scratchecho");
  }

  endInput(): void {
    this.#socket?.send(JSON.stringify({ t: "eof" }));
    this.write("(fin de l'entrée)\n", "scratchecho");
  }

  /** CLOSING THE SOCKET IS THE STOP. One path, the one that also works when the tab
   *  disappears without warning. */
  stop(): void {
    const socket = this.#socket;
    this.#socket = null;
    this.running = false;
    try {
      socket?.close();
    } catch {
      /* already closed */
    }
  }
}

export const scratch = new Scratch();

whenSignedOut(() => scratch.stop());
