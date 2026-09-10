// THE SESSION, AND THE TOKEN THAT IS NOT ONE.
//
// This is the behaviour the old harness ran in its own process to reach, and it is the
// half of the application where a mistake signs a student out mid-lecture or, worse, hands
// the next person at a lab machine a working session. Every assertion below is one of
// those.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { EXPIRY_KEY, REFRESH_KEY, TOKEN_KEY } from "../src/lib/auth/keys";
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
  session.deployment = { issuer: ISSUER, client_id: "ctester" };
  session.setToken("jeton-1");
  sessionStorage.setItem(REFRESH_KEY, "refresh-1");
  sessionStorage.setItem(EXPIRY_KEY, String(seconds() + 3600));
});

const tokenCalls = () => calls.filter((c) => c.url === TOKEN_ENDPOINT);

describe("where the credentials live", () => {
  it("keeps all of it in sessionStorage and NOTHING in localStorage", () => {
    // On a shared lab machine, a refresh token outliving the tab is a session offered to
    // whoever sits down next.
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("jeton-1");
    expect(Object.keys(localStorage)).not.toContain(REFRESH_KEY);
    expect(Object.keys(localStorage)).not.toContain(TOKEN_KEY);
  });
});

describe("ensureValid", () => {
  it("does NOT renew a token that is still good -- a request would be pure load", () => {
    return ensureValid().then((ok) => {
      expect(ok).toBe(true);
      expect(tokenCalls()).toHaveLength(0);
    });
  });

  it("renews a MINUTE BEFORE expiry rather than after a 401", async () => {
    // A 401 costs a round trip and, on a WebSocket, a whole reconnection.
    sessionStorage.setItem(EXPIRY_KEY, String(seconds() + 30));
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(1);
    expect(session.token).toBe("jeton-2");
  });

  it("treats an UNKNOWN lifetime as usable, not as expired", async () => {
    // A provider that omits `expires_in` leaves 0, and renewing on every request would turn
    // one student's page into a load generator aimed at the issuer.
    sessionStorage.setItem(EXPIRY_KEY, "0");
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
    expect(sessionStorage.getItem(REFRESH_KEY)).toBe("refresh-2");
  });

  it("keeps the one it has when the answer carries no new refresh token", async () => {
    // Absent means "keep using the one you have", not "forget it".
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await renew();
    expect(sessionStorage.getItem(REFRESH_KEY)).toBe("refresh-1");
  });

  it("dates the expiry from `expires_in`", async () => {
    grants = [{ access_token: "jeton-2", expires_in: 120 }];
    await renew();
    const at = Number(sessionStorage.getItem(EXPIRY_KEY));
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
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("is not a refusal when there is nothing to renew WITH", async () => {
    // An issuer that declined `offline_access`, or a session opened before this existed:
    // the page then behaves exactly as it did before, and nothing signs itself out.
    sessionStorage.removeItem(REFRESH_KEY);
    expect(await renew()).toBe(false);
    expect(session.token).toBe("jeton-1");
    expect(tokenCalls()).toHaveLength(0);
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
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull();
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

describe("a deployment with no issuer", () => {
  it("renews nothing and refuses nothing: the token lives its life", async () => {
    session.deployment = {};
    session.setToken("jeton-1");
    sessionStorage.setItem(EXPIRY_KEY, String(seconds() - 10));
    // Nearly expired, but there is no OIDC on this deployment at all.
    expect(await ensureValid()).toBe(true);
    expect(await renew()).toBe(false);
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBe("jeton-1");
  });
});
