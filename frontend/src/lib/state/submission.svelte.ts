// SUBMITTING, AND THE STATES IT REALLY HAS. They are named rather than inferred
// from a pair of booleans, because the page says something different in each one:
//
//   idle       nothing has run yet -- and NOT a strip of three "not reached",
//              which before the first submission would announce a failure
//   sending    the request is in flight
//   queued     position and ETA, both from the server
//   running    compilation, execution AND tests: the worker reports no sub-state,
//              and announcing a stage we do not know shapes the wrong mental model
//              in the person who has the least of one
//   done       a verdict, and the only state that carries one
//   cooldown   the quota, counted down; NOT a refusal of the code
//   lost       the verdict was swept or never existed: a SERVICE failure
//
// THE PAGE DECLARES NO VALUE. `passed`, `solved`, XP: the API derives all of it
// from its own reading of the verdict. This module reads a verdict to DISPLAY it,
// and asks the projections to be re-read afterwards.

import { poll as pollJob, submit as postSubmission } from "../api/submission";
import { verdictHeadline, type Scope } from "../domain/verdict";
import { canonicalizeFiles } from "../domain/source";
import type { PollResult, SubmissionBody, Verdict } from "../api/types";
import { session, ensureValid } from "../auth/session.svelte";
import { system } from "./system.svelte";
import { localGet, localSet, randomId } from "../storage";

export type Phase =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "queued"; position: number; eta?: number }
  | { kind: "running" }
  | { kind: "done"; verdict: Verdict; scope: Scope | null }
  | { kind: "cooldown"; seconds: number }
  | { kind: "lost" };

/** Every two seconds, 150 times: five minutes of queue before we give up. */
const POLL_EVERY = 2000;
const POLL_TRIES = 150;

/**
 * THE STATION ID, so the anonymous quota is not the whole room's. In the first
 * labs eighty stations leave through one NATed IP. `localStorage` and NOT
 * `sessionStorage` like the presence id: two tabs are two windows but one student.
 * It proves nothing and only ever travels to `/submit`.
 */
function stationId(): string {
  const held = localGet("ctester.poste");
  if (held) return held;
  const fresh = randomId();
  localSet("ctester.poste", fresh);
  return fresh;
}

class SubmissionState {
  phase = $state<Phase>({ kind: "idle" });

  /**
   * THE LAST RENDERED VERDICT, to recall it at the top of a discussion thread:
   * opening one clears the workbench, and what one came to talk about with it.
   * Only real verdicts count -- neither the wait nor the idle state.
   */
  lastVerdict = $state<{ exercise: string; title: string } | null>(null);

  /**
   * NOT `disabled`, AND THAT IS DELIBERATE. Disabling the focused button drops
   * focus onto `<body>`: with a keyboard one had to tab through the whole page
   * again after EVERY submission. And a greyed-out button with no word reads as
   * "broken" rather than "in progress". It stays focusable and SAYS what it is
   * doing -- and it stays clickable, because a poll that never completes used to
   * leave the student in front of a dead button with no way out.
   */
  get busy(): boolean {
    const k = this.phase.kind;
    return k === "sending" || k === "queued" || k === "running" || k === "cooldown";
  }

  // --- Do not ask again for what was just asked -------------------------------
  // Resending identical code costs a queue slot, a cooldown and a wait, for a
  // verdict already on screen. So the page does not send it: it redisplays.
  //
  // IT ASSERTS NOTHING TO THE SERVER, and that is the only reason this shortcut is
  // allowed here. A hash sent IN the request would CHOOSE which stored verdict
  // comes back -- broken code plus the hash of a successful submission would yield
  // `passed == total`, which the API turns into "solved" and into XP. Deciding not
  // to bother the server needs no trust; dictating its answer would need all of it.
  //
  // IN MEMORY ONLY: a page reload re-judges, which is the right default. It is a
  // session shortcut, not a cache.
  #known = new Map<string, { key: string; verdict: Verdict }>();
  #forcedResend: string | null = null;
  #inFlight: { token: number; exercise: string; key: string } | null = null;
  /** A stale poll stays silent: an abandoned test's verdict arrives LAST. */
  #token = 0;
  #cooldownTimer: ReturnType<typeof setTimeout> | null = null;

  idle(): void {
    this.phase = { kind: "idle" };
  }

  /** Called when the open exercise changes: the buttons must not stay busy. */
  reset(): void {
    this.#token++;
    if (this.#cooldownTimer) clearTimeout(this.#cooldownTimer);
    this.#cooldownTimer = null;
    this.idle();
  }

  #record(verdict: Verdict, scope: Scope | null, exercise: string): void {
    this.phase = { kind: "done", verdict, scope };
    this.lastVerdict = { exercise, title: verdictHeadline(verdict, scope) };
  }

  /**
   * Submit. `scope` is the displayed quiz page's ids, or null for the whole lab.
   * `after` is what re-reads the projections once a verdict has landed -- the page
   * computes none of them.
   */
  async submit(
    exercise: { id: string; mode: string },
    key: string,
    body: Omit<SubmissionBody, "key" | "exercise_id">,
    scope: Scope | null,
    after: () => Promise<void>,
  ): Promise<void> {
    // CANONISÉ AVANT LA CLÉ *ET* AVANT L'ENVOI, dans cet ordre-là : la page
    // compare exactement ce qu'elle enverra. Un espace de fin ajouté puis
    // retiré cesse ainsi de coûter une place dans la file, pour un verdict
    // qu'elle tient déjà. Les réponses d'un quiz ne sont pas du code et ne
    // passent pas par là.
    const sent = body.files ? { ...body, files: canonicalizeFiles(body.files) } : body;
    const payload: SubmissionBody = { key, exercise_id: exercise.id, ...sent };
    // THE SAME CODE AS LAST TIME HAS NOTHING TO ASK AGAIN. No request goes out at
    // all, so neither cooldown, nor queue slot, nor wait.
    const submissionKey = JSON.stringify(payload.answers ?? payload.files);
    const held = this.#known.get(exercise.id);
    if (held && held.key === submissionKey && this.#forcedResend !== submissionKey) {
      // THE SECOND CLICK RESENDS, and this escape hatch is not optional: a test
      // case fixed by the five-minute tick makes the kept verdict wrong, and the
      // page has no way to learn that. Without it, the button would look broken.
      this.#forcedResend = submissionKey;
      this.#record(held.verdict, scope, exercise.id);
      system.say(
        "Même code que ta dernière soumission — voici son verdict, sans reprendre " +
          "de place dans la file. Clique encore pour le renvoyer au juge.",
      );
      return;
    }
    this.#forcedResend = null;
    const token = ++this.#token;
    this.#inFlight = { token, exercise: exercise.id, key: submissionKey };
    system.clear();
    this.phase = { kind: "sending" };
    // RENEWED BEFORE THE SUBMISSION, AND THIS IS THE SILENT ONE. `/submit` accepts
    // an anonymous job: an expired token is not REFUSED here, it is IGNORED -- the
    // job is recorded with no owner, so the status, the attempt and the XP simply
    // never happen, and nothing on screen says a word about it. A 401 would at
    // least have been visible.
    if (session.token) await ensureValid();
    const answer = await postSubmission(payload, stationId());
    if (token !== this.#token) return;
    // THE QUOTA HAS ITS OWN PATH: `retry_after` was always sent by the API and
    // always discarded by the page.
    if (answer.status === 429 && answer.body?.retry_after) {
      this.startCooldown(answer.body.retry_after);
      return;
    }
    if (answer.status === 0) {
      system.say(
        "Le serveur ne répond pas. Ton code est enregistré sur cet appareil ; " +
          "réessaie dans un instant.",
        true,
      );
      this.idle();
      return;
    }
    if (!answer.ok || !answer.body?.id) {
      system.say(
        answer.body?.error ||
          `Le serveur a répondu ${answer.status} et n'a pas pris ta soumission. ` +
            `Ton code est enregistré — réessaie dans un instant.`,
        true,
      );
      this.idle();
      return;
    }
    await this.#poll(answer.body.id, POLL_TRIES, scope, token, exercise.id, after);
  }

  async #poll(
    jobId: string,
    tries: number,
    scope: Scope | null,
    token: number,
    exercise: string,
    after: () => Promise<void>,
  ): Promise<void> {
    if (token !== this.#token) return;
    const answer = await pollJob(jobId);
    if (token !== this.#token) return;
    const body: PollResult = answer.body ?? { state: "error" };
    if (body.state === "done") {
      const verdict = body as Verdict;
      // A VERDICT CLEARS THE SYSTEM BANNER: leaving "the server is unreachable"
      // above a result that just arrived would say two contradictory things.
      system.clear();
      if (isJudgeOutage(verdict)) {
        system.say((verdict.message ?? "") + " Ton code est enregistré.", true);
        // AND WE GO BACK TO IDLE: without this the verdict stayed frozen on
        // "Envoi…" while the banner announced a failure -- two screens saying two
        // different things at once.
        this.idle();
        return;
      }
      this.#record(verdict, scope, exercise);
      // WE ONLY KEEP WHAT THE SERVER AGREES TO KEEP ITSELF. `rejouer` comes from
      // the worker: it sets it on any verdict it refuses to cache -- a timeout, a
      // judge failure, and exercises whose PROGRAM is randomized, which the page
      // has no way to recognize on its own.
      const flight = this.#inFlight;
      if (flight && flight.token === token && !verdict.rejouer && verdict.status !== "error") {
        this.#known.set(flight.exercise, { key: flight.key, verdict });
      }
      // THE VERDICT IS ALREADY ON SCREEN, and nothing that follows must be able to
      // spoil it. The API has just derived this verdict's status; we RE-READ the
      // projections, the page declares none of them.
      try {
        await after();
      } catch {
        // A projection that failed must not take a correct verdict down with it.
      }
      return;
    }
    if (answer.status === 404 || tries <= 0) {
      // LOSING A VERDICT IS A SERVICE FAILURE, not a judgment on the code.
      system.say(
        "Le résultat de ce test s'est perdu. Ton code est enregistré — relance " +
          "simplement le test.",
        true,
      );
      this.phase = { kind: "lost" };
      return;
    }
    this.phase =
      body.state === "running"
        ? { kind: "running" }
        : { kind: "queued", position: body.state === "queued" ? body.position : 1,
            eta: body.state === "queued" ? body.eta : undefined };
    setTimeout(() => {
      void this.#poll(jobId, tries - 1, scope, token, exercise, after);
    }, POLL_EVERY);
  }

  /**
   * A QUOTA IS NOT A REFUSAL OF THE CODE. The API already returns `retry_after`;
   * the page used to ignore it and show the raw message in red, where the verdict
   * goes -- "my code was refused". It goes in the service channel, counts down on
   * the button, and reopens on its own: re-clicking only used to be a way to get
   * annoyed.
   */
  startCooldown(seconds: number): void {
    if (this.#cooldownTimer) clearTimeout(this.#cooldownTimer);
    let remaining = Math.max(1, Math.round(seconds));
    const tick = () => {
      if (remaining <= 0) {
        this.idle();
        system.clear();
        return;
      }
      this.phase = { kind: "cooldown", seconds: remaining };
      system.say(
        "Tu as lancé plusieurs tests coup sur coup. Le prochain part dans " +
          remaining +
          " s — ton code est enregistré, tu peux continuer à l'écrire.",
      );
      remaining--;
      this.#cooldownTimer = setTimeout(tick, 1000);
    };
    tick();
  }
}

const isJudgeOutage = (v: Verdict) => v.status === "error" && /juge/.test(v.message || "");

export const submission = new SubmissionState();
