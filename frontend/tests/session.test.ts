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
  whenSessionLost,
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
let grants: (Record<string, unknown> | null)[] = [];
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
  it("survives the tab, because a weekly lab does not fit in one", () => {
    expect(localStorage.getItem(TOKEN_KEY)).toBe("jeton-1");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("covers the ten days the course needs, and no more", () => {
    expect(SESSION_MAX_DAYS).toBe(10);
    const until = Number(localStorage.getItem(DEADLINE_KEY));
    expect(until).toBeGreaterThan(seconds() + 9 * 86400);
    expect(until).toBeLessThanOrEqual(seconds() + 10 * 86400);
  });
});

describe("the renewal window Rauthy actually allows", () => {
  it("keeps the margin strictly inside that window, not on its edge", async () => {
    const { REFRESH_MARGIN, ISSUER_NBF_OFFSET } = await import("../src/lib/auth/oidc");
    expect(ISSUER_NBF_OFFSET).toBe(60);
    expect(REFRESH_MARGIN).toBeLessThan(ISSUER_NBF_OFFSET);
    expect(REFRESH_MARGIN).toBeGreaterThan(0);
  });

  it("does not renew while the token is younger than that window", async () => {
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
  it("does not renew a token that is still good", () => {
    return ensureValid().then((ok) => {
      expect(ok).toBe(true);
      expect(tokenCalls()).toHaveLength(0);
    });
  });

  it("renews before expiry rather than after a 401", async () => {
    localStorage.setItem(EXPIRY_KEY, String(seconds() + 25));
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    expect(await ensureValid()).toBe(true);
    expect(tokenCalls()).toHaveLength(1);
    expect(session.token).toBe("jeton-2");
  });

  it("treats an unknown lifetime as usable, not as expired", async () => {
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
  it("makes one request out of five concurrent callers", async () => {
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    const results = await Promise.all([renew(), renew(), renew(), renew(), renew()]);
    expect(results).toEqual([true, true, true, true, true]);
    expect(tokenCalls()).toHaveLength(1);
  });

  it("follows rotation: a fresh refresh token replaces the old one on the spot", async () => {
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    await renew();
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-2");
  });

  it("keeps the one it has when the answer carries no new refresh token", async () => {
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

  it("sends the refresh token to the issuer and to nobody else", async () => {
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await renew();
    apiStatuses = [200];
    await authRequest("states");
    const leaked = calls.filter(
      (c) => c.url !== TOKEN_ENDPOINT && (c.body.includes("refresh-1") || JSON.stringify(c.headers).includes("refresh-1")),
    );
    expect(leaked).toEqual([]);
  });

  it("signs out when the refresh is refused", async () => {
    grants = [null];
    expect(await renew()).toBe(false);
    expect(session.token).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("is not a refusal when there is nothing to renew with", async () => {
    localStorage.removeItem(REFRESH_KEY);
    expect(await renew()).toBe(false);
    expect(session.token).toBe("jeton-1");
    expect(tokenCalls()).toHaveLength(0);
  });

  it("pushes the deadline back on every successful grant", async () => {
    localStorage.setItem(DEADLINE_KEY, String(seconds() + 120));
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    await renew();
    expect(Number(localStorage.getItem(DEADLINE_KEY))).toBeGreaterThan(seconds() + 9 * 86400);
  });

  it("gives up on a session abandoned past its deadline, without asking the issuer", async () => {
    localStorage.setItem(DEADLINE_KEY, String(seconds() - 1));
    expect(await renew()).toBe(false);
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("drops a late result rather than resurrecting a closed session", async () => {
    grants = [{ access_token: "jeton-2", refresh_token: "refresh-2", expires_in: 3600 }];
    const inFlight = renew();
    signOut();
    expect(await inFlight).toBe(false);
    expect(session.token).toBeNull();
  });
});

describe("authRequest", () => {
  it("carries the access token as a bearer header", async () => {
    apiStatuses = [200];
    await authRequest("states");
    const call = calls.find((c) => c.url.endsWith("states"))!;
    expect(call.headers.Authorization).toBe("Bearer jeton-1");
  });

  it("renews once and retries once on a 401", async () => {
    localStorage.setItem(EXPIRY_KEY, "0");
    apiStatuses = [401, 200];
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    const answer = await authRequest("states");
    expect(answer.ok).toBe(true);
    expect(calls.filter((c) => c.url.endsWith("states"))).toHaveLength(2);
    expect(session.token).toBe("jeton-2");
  });

  it("signs out on a second 401, rather than spinning", async () => {
    localStorage.setItem(EXPIRY_KEY, "0");
    apiStatuses = [401, 401];
    grants = [{ access_token: "jeton-2", expires_in: 3600 }];
    await authRequest("states");
    expect(session.token).toBeNull();
  });

  it("signs out when the renewal after a 401 is refused", async () => {
    localStorage.setItem(EXPIRY_KEY, "0");
    apiStatuses = [401];
    grants = [null];
    await authRequest("states");
    expect(session.token).toBeNull();
  });

  it("never spends the refresh token on a 401 for a token far from expiry", async () => {
    apiStatuses = [401];
    await authRequest("states");
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBeNull();
  });

  it("keeps the whole session while the deployment is still unknown", async () => {
    session.deployment = null;
    apiStatuses = [401];
    const answer = await authRequest("states");
    expect(answer.status).toBe(401);
    expect(session.token).toBe("jeton-1");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-1");
  });

  it("keeps the session on a 503 while the issuer cannot be asked", async () => {
    apiStatuses = [503];
    const answer = await authRequest("states");
    expect(answer.status).toBe(503);
    expect(session.token).toBe("jeton-1");
    expect(tokenCalls()).toHaveLength(0);
  });

  it("says so when a session is lost rather than left", async () => {
    let told = 0;
    const release = whenSessionLost(() => told++);
    apiStatuses = [401];
    await authRequest("states");
    signOut();
    expect(told).toBe(1);
    release();
  });

  it("reports a dead network as status 0 rather than throwing", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("hors ligne")));
    const answer = await authRequest("states");
    expect(answer).toEqual({ ok: false, status: 0, body: null });
  });

  it("does not even leave without a session", async () => {
    session.setToken(null);
    const answer = await authRequest("states");
    expect(answer.status).toBe(401);
    expect(calls.filter((c) => c.url.endsWith("states"))).toHaveLength(0);
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
  const freshSession = async () => {
    vi.resetModules();
    return (await import("../src/lib/auth/session.svelte")).session;
  };

  it("restores a session that is still within its deadline", async () => {
    localStorage.setItem(TOKEN_KEY, "jeton-garde");
    localStorage.setItem(DEADLINE_KEY, String(seconds() + 86400));
    expect((await freshSession()).token).toBe("jeton-garde");
  });

  // A session from before this existed.
  it("restores one with no deadline at all", async () => {
    localStorage.setItem(TOKEN_KEY, "jeton-ancien");
    localStorage.removeItem(DEADLINE_KEY);
    expect((await freshSession()).token).toBe("jeton-ancien");
  });

  it("erases an abandoned one instead of opening it", async () => {
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
    expect(await ensureValid()).toBe(true);
    expect(await renew()).toBe(false);
    expect(tokenCalls()).toHaveLength(0);
    expect(session.token).toBe("jeton-1");
  });
});
