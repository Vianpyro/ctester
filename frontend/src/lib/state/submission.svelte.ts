import { poll as pollJob, submit as postSubmission } from "../api/submission";
import { verdictHeadline, type Scope } from "../domain/verdict";
import { canonicalizeFiles } from "../domain/source";
import type { PollResult, SubmissionBody, SubmissionItem, Verdict } from "../api/types";
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

/** One exercise of the page being tested. A page holding two exercises has two legs. */
export interface Leg {
  exercise: string;
  title: string;
  phase: Phase;
  scope: Scope | null;
  token: number;
}

/** What the caller hands over for one exercise of the batch. */
export interface Asked {
  exercise: { id: string; mode: string; short?: string };
  body: Omit<SubmissionBody, "key" | "exercise_id" | "items">;
  scope: Scope | null;
}

// Most jobs finish in well under a second: a fixed 2 s step showed their verdict ~2 s late.
// The judge only writes a file, so there is no event to wait on; polling fast early is cheap.
const POLL_STEPS = [250, 250, 500, 500, 1000];
const POLL_EVERY = 2000;
const POLL_TRIES = 150 + POLL_STEPS.length;

const BUSY = new Set(["sending", "queued", "running", "cooldown"]);

const seen = (exercise: string, key: string) => exercise + "\u0000" + key;

function stationId(): string {
  const held = localGet("ctester.station");
  if (held) return held;
  const fresh = randomId();
  localSet("ctester.station", fresh);
  return fresh;
}

class SubmissionState {
  legs = $state<Leg[]>([]);

  lastVerdict = $state<{ exercise: string; title: string } | null>(null);

  /** Seconds left before the server will take another submission; 0 when it will. */
  cooldown = $state(0);

  get busy(): boolean {
    return this.cooldown > 0 || this.legs.some((leg) => BUSY.has(leg.phase.kind));
  }

  /** The first leg, for the readers that only ever face a single exercise. */
  get phase(): Phase {
    return this.legs[0]?.phase ?? { kind: "idle" };
  }

  // Identical answers are not sent again. This only skips a request: nothing is claimed to
  // the server, which never accepts a verdict or a hash from the page.
  #known = new Map<string, { key: string; verdict: Verdict }>();
  // Which submission is live per exercise. Deliberately NOT tied to what is on screen: a
  // job that stops being polled is never recorded, and `GET /r/{job}` is the only writer
  // of XP and solved state. Leaving a page must not cost a student their attempt.
  #alive = new Map<string, number>();
  #forced = new Set<string>();
  #sent = new Map<string, string>();
  #next = 0;
  #cooldownTimer: ReturnType<typeof setTimeout> | null = null;

  idle(): void {
    this.legs = [];
    this.#stopCooldown();
  }

  #stopCooldown(): void {
    if (this.#cooldownTimer) clearTimeout(this.#cooldownTimer);
    this.#cooldownTimer = null;
    this.cooldown = 0;
  }

  /**
   * Show only these exercises. Anything else stops being displayed but keeps polling to
   * the end: only a new submission for the same exercise supersedes a running one.
   */
  reset(keep: string[] = []): void {
    const held = new Set(keep);
    this.legs = this.legs.filter((leg) => held.has(leg.exercise));
    // A page keeping some of its exercises keeps waiting with them; only a full reset
    // calls the wait off.
    if (!held.size) this.#stopCooldown();
  }

  #leg(exercise: string): Leg | undefined {
    return this.legs.find((one) => one.exercise === exercise);
  }

  #set(exercise: string, token: number, phase: Phase): boolean {
    const leg = this.#leg(exercise);
    if (!leg || leg.token !== token) return false;
    leg.phase = phase;
    return true;
  }

  #record(exercise: string, token: number, verdict: Verdict, scope: Scope | null): void {
    this.#set(exercise, token, { kind: "done", verdict, scope });
    this.lastVerdict = { exercise, title: verdictHeadline(verdict, scope) };
  }

  /**
   * Every exercise of the page, in one request. It is a batch and not one request each
   * because the server's per-account cooldown refuses a second `/submit` in the same tick.
   */
  async submit(asked: Asked[], key: string, after: () => Promise<void>): Promise<void> {
    if (!asked.length) return;
    const prepared = asked.map((one) => {
      const body = one.body.files
        ? { ...one.body, files: canonicalizeFiles(one.body.files) }
        : one.body;
      return { ...one, body, key: JSON.stringify(body.answers ?? body.files) };
    });

    this.legs = prepared.map((one) => {
      const token = ++this.#next;
      this.#alive.set(one.exercise.id, token);
      return {
        exercise: one.exercise.id,
        title: one.exercise.short ?? one.exercise.id,
        phase: { kind: "sending" } as Phase,
        scope: one.scope,
        token,
      };
    });

    // An exercise whose answers have not changed keeps its verdict instead of taking a
    // place in the queue. Clicking again on the same page sends it anyway.
    const fresh: typeof prepared = [];
    for (const one of prepared) {
      const held = this.#known.get(one.exercise.id);
      const mark = seen(one.exercise.id, one.key);
      if (held && held.key === one.key && !this.#forced.has(mark)) {
        this.#forced.add(mark);
        const leg = this.#leg(one.exercise.id);
        if (leg) this.#record(one.exercise.id, leg.token, held.verdict, one.scope);
      } else {
        this.#forced.delete(mark);
        fresh.push(one);
      }
    }
    if (!fresh.length) {
      system.say(
        "Même code que ta dernière soumission — voici son verdict, sans reprendre " +
          "de place dans la file. Clique encore pour le renvoyer au juge.",
      );
      return;
    }

    const items: SubmissionItem[] = fresh.map((one) => ({
      exercise_id: one.exercise.id,
      ...one.body,
    }));
    const tokens = new Map(
      fresh.map((one) => [one.exercise.id, this.#leg(one.exercise.id)!.token]),
    );
    const current = () => [...tokens].every(([id, token]) => this.#alive.get(id) === token);
    system.clear();
    // /submit ignores an expired token instead of refusing it: the attempt would lose its owner.
    if (session.token) await ensureValid();
    const answer = await postSubmission({ key, items }, stationId());
    if (!current()) return;

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
    const ids = answer.body?.ids;
    if (!answer.ok || !Array.isArray(ids) || ids.length !== fresh.length) {
      system.say(
        answer.body?.error ||
          `Le serveur a répondu ${answer.status} et n'a pas pris ta soumission. ` +
            `Ton code est enregistré — réessaie dans un instant.`,
        true,
      );
      this.idle();
      return;
    }
    // The legs poll side by side; the call ends when the last verdict is in.
    await Promise.all(
      fresh.map((one, i) => {
        this.#sent.set(one.exercise.id, one.key);
        return this.#poll(
          ids[i]!,
          0,
          one.scope,
          tokens.get(one.exercise.id)!,
          one.exercise.id,
          after,
        );
      }),
    );
  }

  async #poll(
    jobId: string,
    attempt: number,
    scope: Scope | null,
    token: number,
    exercise: string,
    after: () => Promise<void>,
  ): Promise<void> {
    if (this.#alive.get(exercise) !== token) return;
    const answer = await pollJob(jobId);
    if (this.#alive.get(exercise) !== token) return;
    const body: PollResult = answer.body ?? { state: "error" };
    if (body.state === "done") {
      const verdict = body as Verdict;
      system.clear();
      if (isJudgeOutage(verdict)) {
        system.say((verdict.message ?? "") + " Ton code est enregistré.", true);
        this.#set(exercise, token, { kind: "idle" });
        return;
      }
      this.#record(exercise, token, verdict, scope);
      const key = this.#sent.get(exercise);
      if (key && !verdict.rerun && verdict.status !== "error") {
        this.#known.set(exercise, { key, verdict });
      }
      try {
        await after();
      } catch {
        /* the verdict is shown either way */
      }
      return;
    }
    if (answer.status === 404 || attempt >= POLL_TRIES) {
      system.say(
        "Le résultat de ce test s'est perdu. Ton code est enregistré — relance " +
          "simplement le test.",
        true,
      );
      this.#set(exercise, token, { kind: "lost" });
      return;
    }
    this.#set(
      exercise,
      token,
      body.state === "running"
        ? { kind: "running" }
        : {
            kind: "queued",
            position: body.state === "queued" ? body.position : 1,
            eta: body.state === "queued" ? body.eta : undefined,
          },
    );
    setTimeout(() => {
      void this.#poll(jobId, attempt + 1, scope, token, exercise, after);
    }, POLL_STEPS[attempt] ?? POLL_EVERY);
  }

  /** The cooldown belongs to the account, not to one exercise: every leg waits. */
  startCooldown(seconds: number): void {
    if (this.#cooldownTimer) clearTimeout(this.#cooldownTimer);
    let remaining = Math.max(1, Math.round(seconds));
    const tick = () => {
      if (remaining <= 0) {
        this.idle();
        system.clear();
        return;
      }
      this.cooldown = remaining;
      for (const leg of this.legs) leg.phase = { kind: "cooldown", seconds: remaining };
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
