// THE SESSION, AND THE TOKEN THAT IS NOT ONE.
//
// This is the behaviour the old harness ran in its own process to reach, and it is the
// half of the application where a mistake signs a student out mid-lecture or, worse, hands
// the next person at a lab machine a working session. Every assertion below is one of
// those.

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEADLINE_KEY,
  EXPIRY_KEY,
  REFRESH_KEY,
  SESSION_MAX_DAYS,
  TOKEN_KEY,
} from "../src/lib/auth/keys";
import {
  authRequest,
  ensureValid,
  renew,
  session,
  signOut,
  whenSignedOut,
} from "../src/lib/auth/session.svelte";

const ISSUER = "https://auth.exemple.test";
const DISCOVERY = ISSUER + "/.well-known/openid-configuration";
const TOKEN_ENDPOINT = ISSUER + "/oidc/token";

interface Exchange {
  url: string;
  body: string;
  headers: Record<string, string>;
}

let calls: Exchange[] = [];
/** What the token endpoint answers next, in order. */
let grants: (Record<string, unknown> | null)[] = [];
/** What our own API answers next, in order. */
let apiStatuses: number[] = [];

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const headers = Object.fromEntries(
    Object.entries((init?.headers ?? {}) as Record<string, string>),
  );
  calls.push({ url, body: String(init?.body ?? ""), headers });
  if (url === DISCOVERY) {
    return Promise.resolve(
      new Response(JSON.stringify({ token_endpoint: TOKEN_ENDPOINT, authorization_endpoint: ISSUER + "/authorize" }), {
        status: 200,
      }),
    );
  }
  if (url === TOKEN_ENDPOINT) {
    const granted = grants.shift();
    if (!granted) return Promise.resolve(new Response("{}", { status: 400 }));
    return Promise.resolve(new Response(JSON.stringify(granted), { status: 200 }));
  }
  const status = apiStatuses.shift() ?? 200;
  return Promise.resolve(new Response(JSON.stringify({ ok: status === 200 }), { status }));
}

const seconds = () => Math.floor(Date.now() / 1000);

beforeEach(() => {
  calls = [];
  grants = [];
  apiStatuses = [];
  vi.stubGlobal("fetch", fakeFetch);
  localStorage.clear();
  sessionStorage.clear();
  session.deployment = { issuer: ISSUER, client_id: "ctester" };
  session.setToken("jeton-1");
  localStorage.setItem(REFRESH_KEY, "refresh-1");
  localStorage.setItem(EXPIRY_KEY, String(seconds() + 3600));
  localStorage.setItem(DEADLINE_KEY, String(seconds() + SESSION_MAX_DAYS * 86400));
});

const tokenCalls = () => calls.filter((c) => c.url === TOKEN_ENDPOINT);

describe("where the credentials live", () => {
  // THE LABS ARE A WEEK APART. `sessionStorage` dies with the tab, so a student who
  // closed their browser on Tuesday evening came back the next Tuesday with no refresh
  // token at all -- the renewal was never asked, and looked broken. This is the half of
  // the fix that no amount of refresh-token work could replace.
  it("survives the tab, because a weekly lab does not fit in one", () => {
    expect(localStorage.getItem(TOKEN_KEY)).toBe("jeton-1");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("covers the ten days the course needs, and no more", () => {
    // Seven days between labs, three for whoever finishes late. The number is the
    // calendar, and it must match Rauthy's `refresh_token_lifetime` (240 hours).
    expect(SESSION_MAX_DAYS).toBe(10);
    const until = Number(localStorage.getItem(DEADLINE_KEY));
    expect(until).toBeGreaterThan(seconds() + 9 * 86400);
    expect(until).toBeLessThanOrEqual(seconds() + 10 * 86400);
  });
});

describe("the renewal window Rauthy actually allows", () => {
  // RAUTHY STAMPS `nbf = access_token_lifetime - 60` ON EVERY REFRESH TOKEN
  // (`token_set.rs`), so a refresh token may only be used during the LAST MINUTE of the
  // access token's life. And being early is not a failed request: Rauthy invalidates "not
  // only the token itself, but also all other linked sessions and tokens for this user".
  // One early renewal signs the student out of everything.
  it("keeps the margin strictly INSIDE that window, not on its edge", async () => {
    const { REFRESH_MARGIN, ISSUER_NBF_OFFSET } = await import("../src/lib/auth/oidc");
    expect(ISSUER_NBF_OFFSET).toBe(60);
    // 60 -- what this used to be -- fires at the very first instant the token becomes
    // usable, with nothing left for a clock that moves.
    expect(REFRESH_MARGIN).toBeLessThan(ISSUER_NBF_OFFSET);
    expect(REFRESH_MARGIN).toBeGreaterThan(0);
  });

  it("does not renew while the token is younger than that window", async () => {
    // A minute and one second of life left: Rauthy's `nbf` has not passed, so asking now
    // would be the catastrophic case above rather than a wasted request.
    localStorage.setItem(EXPIRY_KEY, String(seconds() + 61));
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(0);
  });

  it("renews inside it, before the token dies", async () => {
    localStorage.setItem(EXPIRY_KEY, String(seconds() + 20));
    grants = [{ access_token: "jeton-2", expires_in: 9000 }];
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(1);
  });
});

describe("ensureValid", () => {
  it("does NOT renew a token that is still good -- a request would be pure load", () => {
    return ensureValid().then((ok) => {
      expect(ok).toBe(true);
      expect(tokenCalls()).toHaveLength(0);
    });
  });

  it("renews BEFORE expiry rather than after a 401", async () => {
    // A 401 costs a round trip and, on a WebSocket, a whole reconnection. How far before
    // is not free to choose -- see "the renewal window Rauthy actually allows" above.
    localStorage.setItem(EXPIRY_KEY, String(seconds() + 25));
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(1);
    expect(session.token).toBe("jeton-2");
  });

  it("treats an UNKNOWN lifetime as usable, not as expired", async () => {
    // A provider that omits `expires_in` leaves 0, and renewing on every request would turn
    // one student's page into a load generator aimed at the issuer.
    localStorage.setItem(EXPIRY_KEY, "0");
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(0);
  });

  it("answers false with no session at all", async () => {
    session.setToken(null);
    expect(await ensureValid()).toBe(false);
  });
});

describe("renew", () => {
  it("makes ONE request out of five concurrent callers", async () => {
    // With rotation on, the other four would each burn the token the first one is using,
    // and whichever lost the race would sign the student out.
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    const results = await Promise.all([renew(), renew(), renew(), renew(), renew()]);
    expect(results).toEqual([true, true, true, true, true]);
    expect(tokenCalls()).toHaveLength(1);
  });

  it("FOLLOWS ROTATION: a fresh refresh token replaces the old one on the spot", async () => {
    // Keeping the old one works exactly once, then signs the student out an hour later with
    // nothing on screen to explain it.
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    await renew();
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-2");
  });

  it("keeps the one it has when the answer carries no new refresh token", async () => {
    // Absent means "keep using the one you have", not "forget it".
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await renew();
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-1");
  });

  it("dates the expiry from `expires_in`", async () => {
    grants = [{ access_token: "jeton-2", expires_in: 120 }];
    await renew();
    const at = Number(localStorage.getItem(EXPIRY_KEY));
    expect(at).toBeGreaterThan(seconds() + 110);
    expect(at).toBeLessThanOrEqual(seconds() + 120);
  });

  it("sends the refresh token to the ISSUER and to nobody else", async () => {
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await renew();
    apiStatuses = [200];
    await authRequest("etats");
    const leaked = calls.filter(
      (c) => c.url !== TOKEN_ENDPOINT && (c.body.includes("refresh-1") || JSON.stringify(c.headers).includes("refresh-1")),
    );
    expect(leaked).toEqual([]);
  });

  it("signs out when the refresh is REFUSED -- there is nothing else to try", async () => {
    grants = [null];
    expect(await renew()).toBe(false);
    expect(session.token).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("is not a refusal when there is nothing to renew WITH", async () => {
    // An issuer that declined `offline_access`, or a session opened before this existed:
    // the page then behaves exactly as it did before, and nothing signs itself out.
    localStorage.removeItem(REFRESH_KEY);
    expect(await renew()).toBe(false);
    expect(session.token).toBe("jeton-1");
    expect(tokenCalls()).toHaveLength(0);
  });

  it("PUSHES THE DEADLINE BACK on every successful grant", async () => {
    // Sliding, not a countdown from the first sign-in: a student who works every week must
    // never be asked to sign in again, and one who stops must eventually be. This is also
    // what Rauthy's rotating refresh token does, so the two clocks agree by construction.
    localStorage.setItem(DEADLINE_KEY, String(seconds() + 120));
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    await renew();
    expect(Number(localStorage.getItem(DEADLINE_KEY))).toBeGreaterThan(seconds() + 9 * 86400);
  });

  it("gives up on a session abandoned past its deadline, WITHOUT asking the issuer", async () => {
    // This is the deadline doing what the closing tab used to do. Rauthy's own refresh
    // token dies on the same schedule, so asking would only be asking it to refuse.
    localStorage.setItem(DEADLINE_KEY, String(seconds() - 1));
    expect(await renew()).toBe(false);
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("drops a LATE result rather than resurrecting a closed session", async () => {
    // Somebody signed out while this was in flight; on a lab machine, storing its grant
    // would sign the next person in.
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    const inFlight = renew();
    signOut();
    expect(await inFlight).toBe(false);
    expect(session.token).toBeNull();
  });
});

describe("authRequest", () => {
  it("carries the ACCESS token as a bearer header", async () => {
    apiStatuses = [200];
    await authRequest("etats");
    const call = calls.find((c) => c.url.endsWith("etats"))!;
    expect(call.headers.Authorization).toBe("Bearer jeton-1");
  });

  it("renews once and retries once on a 401", async () => {
    apiStatuses = [401, 200];
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    const answer = await authRequest("etats");
    expect(answer.ok).toBe(true);
    expect(calls.filter((c) => c.url.endsWith("etats"))).toHaveLength(2);
    expect(session.token).toBe("jeton-2");
  });

  it("signs out on a SECOND 401, rather than spinning", async () => {
    // A second 401 on a token minted seconds earlier is not a timing problem.
    apiStatuses = [401, 401];
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await authRequest("etats");
    expect(session.token).toBeNull();
  });

  it("signs out when the renewal after a 401 is refused", async () => {
    apiStatuses = [401];
    grants = [null];
    await authRequest("etats");
    expect(session.token).toBeNull();
  });

  it("reports a dead network as status 0 rather than throwing", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("hors ligne")));
    const answer = await authRequest("etats");
    expect(answer).toEqual({ ok: false, status: 0, body: null });
  });

  it("does not even leave without a session", async () => {
    session.setToken(null);
    const answer = await authRequest("etats");
    expect(answer.status).toBe(401);
    expect(calls.filter((c) => c.url.endsWith("etats"))).toHaveLength(0);
  });
});

describe("signOut", () => {
  it("clears the token, the renewal material, and every private screen", () => {
    let forgotten = false;
    const release = whenSignedOut(() => {
      forgotten = true;
    });
    signOut();
    expect(session.token).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    // AND THE DEADLINE, from the core. The credentials outlive the tab now, so a sign-out
    // that left any of the four behind would be a sign-out that only hid the session --
    // on a shared station, for the next person to sit down.
    expect(localStorage.getItem(EXPIRY_KEY)).toBeNull();
    expect(localStorage.getItem(DEADLINE_KEY)).toBeNull();
    expect(forgotten).toBe(true);
    release();
  });

  it("lets one screen's failure to clear itself not stop the others", () => {
    let second = false;
    const a = whenSignedOut(() => {
      throw new Error("un écran qui lève");
    });
    const b = whenSignedOut(() => {
      second = true;
    });
    expect(() => signOut()).not.toThrow();
    expect(second).toBe(true);
    a();
    b();
  });
});

describe("what a page load finds in storage", () => {
  // THE CREDENTIALS OUTLIVE THE BROWSER NOW, so the check that used to be free -- the tab
  // closing -- has to be made explicitly, and it has to be made BEFORE the first paint
  // draws a signed-in bar. `vi.resetModules()` is the only way to reach it: the session is
  // a singleton built at import time, which is exactly the moment being tested.
  const freshSession = async () => {
    vi.resetModules();
    return (await import("../src/lib/auth/session.svelte")).session;
  };

  it("restores a session that is still within its deadline", async () => {
    localStorage.setItem(TOKEN_KEY, "jeton-garde");
    localStorage.setItem(DEADLINE_KEY, String(seconds() + 86400));
    expect((await freshSession()).token).toBe("jeton-garde");
  });

  it("restores one with no deadline at all -- a session from before this existed", async () => {
    localStorage.setItem(TOKEN_KEY, "jeton-ancien");
    localStorage.removeItem(DEADLINE_KEY);
    expect((await freshSession()).token).toBe("jeton-ancien");
  });

  it("ERASES an abandoned one instead of opening it", async () => {
    // Eleven days later on a shared station: the deadline is the whole protection, so it
    // must not merely hide the token -- it has to take the refresh token with it.
    localStorage.setItem(TOKEN_KEY, "jeton-abandonne");
    localStorage.setItem(REFRESH_KEY, "refresh-abandonne");
    localStorage.setItem(DEADLINE_KEY, String(seconds() - 1));
    expect((await freshSession()).token).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(localStorage.getItem(DEADLINE_KEY)).toBeNull();
  });
});

describe("a deployment with no issuer", () => {
  it("renews nothing and refuses nothing: the token lives its life", async () => {
    session.deployment = {};
    session.setToken("jeton-1");
    localStorage.setItem(EXPIRY_KEY, String(seconds() - 10));
    // Nearly expired, but there is no OIDC on this deployment at all.
    expect(await ensureValid()).toBe(true);
    expect(await renew()).toBe(false);
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBe("jeton-1");
  });
});
