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

const POLL_EVERY = 2000;
const POLL_TRIES = 150;

function stationId(): string {
  const held = localGet("ctester.station");
  if (held) return held;
  const fresh = randomId();
  localSet("ctester.station", fresh);
  return fresh;
}

class SubmissionState {
  phase = $state<Phase>({ kind: "idle" });

  lastVerdict = $state<{ exercise: string; title: string } | null>(null);

  get busy(): boolean {
    const k = this.phase.kind;
    return k === "sending" || k === "queued" || k === "running" || k === "cooldown";
  }

  // Identical code is not sent again. This only skips a request: nothing is claimed to the
  // server, which never accepts a verdict or a hash from the page.
  #known = new Map<string, { key: string; verdict: Verdict }>();
  #forcedResend: string | null = null;
  #inFlight: { token: number; exercise: string; key: string } | null = null;
  #token = 0;
  #cooldownTimer: ReturnType<typeof setTimeout> | null = null;

  idle(): void {
    this.phase = { kind: "idle" };
  }

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

  async submit(
    exercise: { id: string; mode: string },
    key: string,
    body: Omit<SubmissionBody, "key" | "exercise_id">,
    scope: Scope | null,
    after: () => Promise<void>,
  ): Promise<void> {
    const sent = body.files ? { ...body, files: canonicalizeFiles(body.files) } : body;
    const payload: SubmissionBody = { key, exercise_id: exercise.id, ...sent };
    const submissionKey = JSON.stringify(payload.answers ?? payload.files);
    const held = this.#known.get(exercise.id);
    if (held && held.key === submissionKey && this.#forcedResend !== submissionKey) {
      // A second click resends: a test fixed since then can make the kept verdict wrong.
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
    // /submit ignores an expired token instead of refusing it: the attempt would lose its owner.
    if (session.token) await ensureValid();
    const answer = await postSubmission(payload, stationId());
    if (token !== this.#token) return;
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
      system.clear();
      if (isJudgeOutage(verdict)) {
        system.say((verdict.message ?? "") + " Ton code est enregistré.", true);
        this.idle();
        return;
      }
      this.#record(verdict, scope, exercise);
      const flight = this.#inFlight;
      if (flight && flight.token === token && !verdict.rerun && verdict.status !== "error") {
        this.#known.set(flight.exercise, { key: flight.key, verdict });
      }
      try {
        await after();
      } catch {
      }
      return;
    }
    if (answer.status === 404 || tries <= 0) {
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
