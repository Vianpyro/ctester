import { poll as pollJob, submit as postSubmission } from "../api/submission";
import { t } from "../i18n.svelte";
import { serverMessage } from "../api/client";
import { isJudgeFailure, verdictExplain, verdictHeadline, type Scope } from "../domain/verdict";
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

// Most jobs finish in well under a second: a fixed 2 s step showed their verdict ~2 s late.
// The judge only writes a file, so there is no event to wait on; polling fast early is cheap.
const POLL_STEPS = [250, 250, 500, 500, 1000];
const POLL_EVERY = 2000;
const POLL_TRIES = 150 + POLL_STEPS.length;

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
      system.say(t("submit.same_code"));
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
      system.say(t("submit.no_answer"), true);
      this.idle();
      return;
    }
    if (!answer.ok || !answer.body?.id) {
      system.say(
        serverMessage(answer.body) || t("submit.refused", { status: answer.status }),
        true,
      );
      this.idle();
      return;
    }
    await this.#poll(answer.body.id, 0, scope, token, exercise.id, after);
  }

  async #poll(
    jobId: string,
    attempt: number,
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
      if (isJudgeFailure(verdict)) {
        system.say(verdictExplain(verdict) + t("submit.saved"), true);
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
    if (answer.status === 404 || attempt >= POLL_TRIES) {
      system.say(t("submit.lost"), true);
      this.phase = { kind: "lost" };
      return;
    }
    this.phase =
      body.state === "running"
        ? { kind: "running" }
        : { kind: "queued", position: body.state === "queued" ? body.position : 1,
            eta: body.state === "queued" ? body.eta : undefined };
    setTimeout(() => {
      void this.#poll(jobId, attempt + 1, scope, token, exercise, after);
    }, POLL_STEPS[attempt] ?? POLL_EVERY);
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
      system.say(t("submit.cooldown", { seconds: remaining }));
      remaining--;
      this.#cooldownTimer = setTimeout(tick, 1000);
    };
    tick();
  }
}


export const submission = new SubmissionState();
