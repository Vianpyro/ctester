import { beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "../src/lib/auth/session.svelte";
import { submission } from "../src/lib/state/submission.svelte";
import { system } from "../src/lib/state/system.svelte";
import type { Verdict } from "../src/lib/api/types";

const EXERCISE = { id: "tp2-ex3", mode: "io" };
const KEY = "cle-de-session";

interface Call {
  url: string;
  body: string;
  headers: Record<string, string>;
}

interface Answer {
  status: number;
  body: unknown;
}

let calls: Call[] = [];
let accepted: Answer[] = [];
let polled: Record<string, Answer[]> = {};

const OK: Verdict = { state: "done", status: "ok", kind: "io", total: 3, passed: 3 };

const job = (letter: string) => letter.repeat(32);

function queue(letter: string, ...answers: Answer[]): void {
  accepted.push({ status: 200, body: { ids: [job(letter)] } });
  polled[job(letter)] = answers;
}

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  calls.push({
    url,
    body: String(init?.body ?? ""),
    headers: Object.fromEntries(Object.entries((init?.headers ?? {}) as Record<string, string>)),
  });
  const pending = url.startsWith("submit") ? accepted : (polled[url.slice(2)] ??= []);
  const next = pending.shift() ?? { status: 200, body: OK };
  return Promise.resolve(new Response(JSON.stringify(next.body), { status: next.status }));
}

let variant = 0;
const uniqueCode = () => ({ "submission.c": `int main(void){return ${++variant};}` });

const noop = async () => {};

/** One exercise, the shape almost every check here uses. */
const send = (
  body: { files?: Record<string, string>; answers?: Record<string, string> },
  scope: Parameters<typeof submission.submit>[0][0]["scope"] = null,
  after: () => Promise<void> = noop,
  exercise: { id: string; mode: string } = EXERCISE,
) => submission.submit([{ exercise, body, scope }], KEY, after);

beforeEach(() => {
  calls = [];
  accepted = [];
  polled = {};
  vi.stubGlobal("fetch", fakeFetch);
  session.deployment = {};
  session.setToken(null);
  submission.reset();
  system.clear();
});

const submits = () => calls.filter((c) => c.url.startsWith("submit"));

describe("a submission that lands", () => {
  it("goes idle -> done and carries the verdict", async () => {
    queue("a", { status: 200, body: OK });
    expect(submission.phase.kind).toBe("idle");
    await send({ files: uniqueCode() });
    expect(submission.phase).toEqual({ kind: "done", verdict: OK, scope: null });
    expect(submission.busy).toBe(false);
  });

  it("clears the system banner: two screens must not say opposite things", async () => {
    system.say("Le serveur ne répond pas.", true);
    queue("b", { status: 200, body: OK });
    await send({ files: uniqueCode() });
    expect(system.text).toBe("");
  });

  it("keeps the verdict for a discussion thread to quote", async () => {
    queue("c", { status: 200, body: OK });
    await send({ files: uniqueCode() });
    expect(submission.lastVerdict).toEqual({ exercise: "tp2-ex3", title: "3 / 3 cas réussis" });
  });

  it("re-reads the projections AFTER the verdict, and survives their failure", async () => {
    queue("d", { status: 200, body: OK });
    await send({ files: uniqueCode() }, null, async () => {
      throw new Error("une projection qui lève");
    });
    expect(submission.phase.kind).toBe("done");
  });

  it("attaches the token when there is one, and stays anonymous when there is not", async () => {
    queue("e", { status: 200, body: OK });
    await send({ files: uniqueCode() });
    expect(submits()[0]!.headers.Authorization).toBeUndefined();

    session.setToken("jeton-1");
    queue("f", { status: 200, body: OK });
    await send({ files: uniqueCode() });
    expect(submits()[1]!.headers.Authorization).toBe("Bearer jeton-1");
  });

  it("sends the key and the exercise, and never an identity", async () => {
    queue("z", { status: 200, body: OK });
    await send({ files: uniqueCode() });
    const sent = JSON.parse(submits()[0]!.body) as { key: string; items: unknown[] };
    expect(Object.keys(sent).sort()).toEqual(["items", "key"]);
    expect(Object.keys(sent.items[0] as object).sort()).toEqual(["exercise_id", "files"]);
  });
});

describe("a submission that does not", () => {
  it("puts a QUOTA in the service channel and counts it down on the button", async () => {
    accepted = [{ status: 429, body: { error: "trop de soumissions", retry_after: 8 } }];
    await send({ files: uniqueCode() });
    expect(submission.phase).toEqual({ kind: "cooldown", seconds: 8 });
    expect(submission.busy).toBe(true);
    expect(system.failed).toBe(false);
    expect(system.text).toMatch(/ton code est enregistré/);
    submission.reset();
  });

  it("says the server is unreachable and goes idle rather than freezing on `Envoi…`", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("hors ligne")));
    await send({ files: uniqueCode() });
    expect(submission.phase.kind).toBe("idle");
    expect(system.failed).toBe(true);
    expect(system.text).toMatch(/enregistré/);
  });

  it("reuses the API's own refusal message", async () => {
    accepted = [{ status: 400, body: { error: "TP inconnu" } }];
    await send({ files: uniqueCode() });
    expect(system.text).toBe("TP inconnu");
    expect(submission.phase.kind).toBe("idle");
  });

  it("calls a LOST verdict a service failure, not a judgment on the code", async () => {
    queue("g", { status: 404, body: { state: "gone" } });
    await send({ files: uniqueCode() });
    expect(submission.phase.kind).toBe("lost");
    expect(system.failed).toBe(true);
    expect(system.text).toMatch(/relance simplement le test/);
  });

  it("keeps a JUDGE failure out of the verdict channel entirely", async () => {
    queue("h", {
      status: 200,
      body: { state: "done", status: "error", kind: "io", message: "Erreur interne du juge." },
    });
    await send({ files: uniqueCode() });
    expect(submission.phase.kind).toBe("idle");
    expect(system.failed).toBe(true);
    expect(system.text).toMatch(/Ton code est enregistré/);
  });
});

describe("the queue", () => {
  it("reports the position and the ETA the server sent, then the verdict", async () => {
    vi.useFakeTimers();
    queue(
      "i",
      { status: 200, body: { state: "queued", position: 4, eta: 45 } },
      { status: 200, body: { state: "running" } },
      { status: 200, body: OK },
    );
    const done = send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(0);
    expect(submission.phase).toEqual({ kind: "queued", position: 4, eta: 45 });
    await vi.advanceTimersByTimeAsync(250);
    expect(submission.phase.kind).toBe("running");
    await vi.advanceTimersByTimeAsync(250);
    await done;
    expect(submission.phase.kind).toBe("done");
    vi.useRealTimers();
  });

  it("shows a FAST job's verdict a quarter second later, not two", async () => {
    vi.useFakeTimers();
    queue("p", { status: 200, body: { state: "running" } }, { status: 200, body: OK });
    const done = send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(0);
    expect(submission.phase.kind).toBe("running");
    await vi.advanceTimersByTimeAsync(250);
    await done;
    expect(submission.phase.kind).toBe("done");
    vi.useRealTimers();
  });

  it("slows down to one poll every 2 s for a LONG job", async () => {
    vi.useFakeTimers();
    const running = { status: 200, body: { state: "running" } };
    queue("q", ...Array.from({ length: 40 }, () => running));
    void send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(10_000);
    // One at once, five in the first 2.5 s, then one every 2 s.
    expect(calls.filter((c) => c.url.startsWith("r/")).length).toBe(1 + 5 + 3);
    submission.reset();
    vi.useRealTimers();
  });

  it("still calls a job LOST when the server forgets it mid-way", async () => {
    vi.useFakeTimers();
    queue(
      "s",
      { status: 200, body: { state: "running" } },
      { status: 200, body: { state: "running" } },
      { status: 404, body: { state: "gone" } },
    );
    const done = send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(500);
    await done;
    expect(submission.phase.kind).toBe("lost");
    vi.useRealTimers();
  });

  it("keeps a STALE poll silent -- an abandoned test's verdict arrives LAST", async () => {
    vi.useFakeTimers();
    queue(
      "j",
      { status: 200, body: { state: "queued", position: 9 } },
      { status: 200, body: { state: "done", status: "compile_error", kind: "io" } },
    );
    queue("k", { status: 200, body: OK });
    const first = send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(0);
    const second = send({ files: uniqueCode() });
    await vi.advanceTimersByTimeAsync(4000);
    await Promise.all([first, second]);
    expect(submission.phase).toEqual({ kind: "done", verdict: OK, scope: null });
    vi.useRealTimers();
  });
});

describe("do not ask again for what was just asked", () => {
  it("redisplays without sending, and ASSERTS NOTHING to the server", async () => {
    const files = uniqueCode();
    queue("l", { status: 200, body: OK });
    await send({ files });
    expect(submits()).toHaveLength(1);

    await send({ files });
    expect(submits()).toHaveLength(1);
    expect(submission.phase.kind).toBe("done");
    expect(system.text).toMatch(/Même code que ta dernière soumission/);
  });

  it("SENDS ANYWAY on the second click -- the escape hatch is not optional", async () => {
    const files = uniqueCode();
    queue("m", { status: 200, body: OK });
    queue("n", { status: 200, body: OK });
    await send({ files });
    await send({ files });
    await send({ files });
    expect(submits()).toHaveLength(2);
  });

  it("KEEPS ONLY WHAT THE SERVER AGREES TO KEEP: `rerun` is never memoized", async () => {
    const files = uniqueCode();
    queue("o", { status: 200, body: { ...OK, rerun: true } });
    queue("p", { status: 200, body: OK });
    await send({ files });
    await send({ files });
    expect(submits()).toHaveLength(2);
  });

  it("A TRAILING SPACE IS NOT DIFFERENT CODE", async () => {
    const files = uniqueCode();
    queue("ws1", { status: 200, body: OK });
    await send({ files });
    expect(submits()).toHaveLength(1);

    const space = { "submission.c": files["submission.c"] + "   " };
    await send({ files: space });
    expect(submits()).toHaveLength(1);
    expect(system.text).toMatch(/Même code que ta dernière soumission/);
  });

  it("but a REAL extra line is", async () => {
    const files = uniqueCode();
    queue("ws2", { status: 200, body: OK });
    queue("ws3", { status: 200, body: OK });
    await send({ files });
    const line = { "submission.c": files["submission.c"] + "\n" };
    await send({ files: line });
    expect(submits()).toHaveLength(2);
  });

  it("keeps one memo per exercise, not one for the page", async () => {
    const files = uniqueCode();
    queue("q", { status: 200, body: OK });
    queue("r", { status: 200, body: OK });
    await send({ files });
    await send({ files }, null, noop, { id: "tp2-ex4", mode: "io" });
    expect(submits()).toHaveLength(2);
  });
});

describe("a page holding several exercises", () => {
  const QUIZ_A = { id: "quiz-a", mode: "quiz", short: "Ex.1 conversions" };
  const QUIZ_B = { id: "quiz-b", mode: "quiz", short: "Ex.2 masques" };
  // The memo of already-sent answers is a module singleton, so every check needs answers
  // no other check has used.
  let round = 0;
  const pair = () => {
    round++;
    return [`a${round}`, `b${round}`] as const;
  };
  const two = (a: string, b: string) =>
    submission.submit(
      [
        { exercise: QUIZ_A, body: { answers: { q1: a } }, scope: null },
        { exercise: QUIZ_B, body: { answers: { q1: b } }, scope: null },
      ],
      KEY,
      noop,
    );

  it("sends ONE request for the page: two would be refused by the cooldown", async () => {
    accepted = [{ status: 200, body: { ids: [job("A"), job("B")] } }];
    polled[job("A")] = [{ status: 200, body: OK }];
    polled[job("B")] = [{ status: 200, body: OK }];
    await two(...pair());
    expect(submits()).toHaveLength(1);
    const sent = JSON.parse(submits()[0]!.body) as { items: { exercise_id: string }[] };
    expect(sent.items.map((one) => one.exercise_id)).toEqual(["quiz-a", "quiz-b"]);
  });

  it("gives each exercise its own verdict, in the order of the page", async () => {
    const bad: Verdict = { state: "done", status: "ok", kind: "quiz", total: 2, passed: 1 };
    accepted = [{ status: 200, body: { ids: [job("C"), job("D")] } }];
    polled[job("C")] = [{ status: 200, body: OK }];
    polled[job("D")] = [{ status: 200, body: bad }];
    await two(...pair());
    expect(submission.legs.map((one) => one.exercise)).toEqual(["quiz-a", "quiz-b"]);
    expect(submission.legs[0]!.phase).toEqual({ kind: "done", verdict: OK, scope: null });
    expect(submission.legs[1]!.phase).toEqual({ kind: "done", verdict: bad, scope: null });
  });

  it("leaves out only the exercise whose answers have not changed", async () => {
    accepted = [{ status: 200, body: { ids: [job("E"), job("F")] } }];
    polled[job("E")] = [{ status: 200, body: OK }];
    polled[job("F")] = [{ status: 200, body: OK }];
    const [a, b] = pair();
    await two(a, b);

    accepted = [{ status: 200, body: { ids: [job("G")] } }];
    polled[job("G")] = [{ status: 200, body: OK }];
    await submission.submit(
      [
        { exercise: QUIZ_A, body: { answers: { q1: a } }, scope: null },
        { exercise: QUIZ_B, body: { answers: { q1: b + " changé" } }, scope: null },
      ],
      KEY,
      noop,
    );
    const sent = JSON.parse(submits()[1]!.body) as { items: { exercise_id: string }[] };
    expect(sent.items.map((one) => one.exercise_id)).toEqual(["quiz-b"]);
    // The untouched one still shows its verdict: it was graded, just not again.
    expect(submission.legs[0]!.phase.kind).toBe("done");
  });

  it("keeps polling an exercise that leaves the page -- a job never polled is never counted", async () => {
    vi.useFakeTimers();
    accepted = [{ status: 200, body: { ids: [job("H"), job("I")] } }];
    polled[job("H")] = [{ status: 200, body: { state: "running" } }, { status: 200, body: OK }];
    polled[job("I")] = [{ status: 200, body: OK }];
    const done = two(...pair());
    await vi.advanceTimersByTimeAsync(0);
    // The panel narrows the page to one exercise while the other is still judging.
    submission.reset(["quiz-b"]);
    expect(submission.legs.map((one) => one.exercise)).toEqual(["quiz-b"]);
    await vi.advanceTimersByTimeAsync(500);
    await done;
    // Dropped from the display, still polled to the end.
    expect(calls.filter((c) => c.url === "r/" + job("H"))).toHaveLength(2);
    vi.useRealTimers();
  });

  it("refuses the whole page when the server refuses the batch", async () => {
    accepted = [{ status: 413, body: { error: "réponses trop longues" } }];
    await two(...pair());
    expect(submission.legs).toHaveLength(0);
    expect(system.text).toBe("réponses trop longues");
  });
});

describe("busy", () => {
  it("is true for every phase in which something is pending, and false otherwise", () => {
    submission.reset();
    expect(submission.busy).toBe(false);
    submission.startCooldown(3);
    expect(submission.busy).toBe(true);
    submission.reset();
    expect(submission.busy).toBe(false);
  });
});
