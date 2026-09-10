// THE PAGE ACTUALLY RUNS, AND THIS IS THE CHECK THE OLD HARNESS EXISTED FOR.
//
// Its whole reason to be was that `node --check` could not catch the one failure this page
// ever had in production: a `ReferenceError` at RUN time, in a promise nobody read, which
// left the button silent and the container's logs empty. Types catch that class now -- but
// only the class that is expressible in types. Mounting the real component tree against a
// real DOM is what catches an effect that throws, a store read before it exists, or a
// template that references something that is not there.
//
// IT IS THE ANONYMOUS PATH, deliberately: the default path, and the one that must never
// depend on a token. What it asserts is what a student sees before touching anything, and
// which requests that costs.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import App from "../src/App.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";

const RELEASE = {
  collections: [
    { id: "tp2", title: "TP 2", items: ["tp2-ex1", "tp2-ex2"], access: "available" },
    {
      id: "tp9",
      title: "TP 9",
      items: ["tp9-ex1"],
      access: "scheduled",
      release: { available_from: "2026-11-18T08:00:00-05:00" },
    },
  ],
  exercises: [
    {
      id: "tp2-ex1",
      title: "ex.1 conversion",
      mode: "io",
      files: [{ name: "submission.c" }],
      skills: ["printf"],
      access: "available",
    },
    { id: "tp2-ex2", title: "ex.2 boucle", mode: "io", access: "available" },
    {
      id: "tp9-ex1",
      title: "ex.1 matrices",
      mode: "unity",
      access: "scheduled",
      release: { available_from: "2026-11-18T08:00:00-05:00" },
    },
  ],
  assignments: [],
};

let asked: string[] = [];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  asked.push(url);
  if (url === "catalog.json") {
    return Promise.resolve(new Response(JSON.stringify(RELEASE), { status: 200 }));
  }
  if (url.startsWith("tp/")) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          statement: "Convertis des degrés.",
          files: [{ name: "submission.c", template: "// écris ici" }],
        }),
        { status: 200 },
      ),
    );
  }
  if (url === "oidc.json") {
    // A DEPLOYMENT WITH NO SIGN-IN: the whole account block stays inert, which is the
    // anonymous path's most important property.
    return Promise.resolve(new Response("{}", { status: 200 }));
  }
  if (url.startsWith("live?")) {
    return Promise.resolve(new Response(JSON.stringify({ n: 3 }), { status: 200 }));
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
}

/** Let the startup sequence's awaits resolve. */
const settle = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
  flushSync();
};

let host: HTMLElement;
let app: Record<string, unknown> | null = null;

beforeEach(() => {
  asked = [];
  vi.stubGlobal("fetch", fakeFetch);
  document.body.innerHTML = "";
  host = document.createElement("div");
  host.id = "app";
  document.body.append(host);
  app = null;
  // A FRESH PAGE LOAD, SEEN FROM OUTSIDE. Without this, `exercise.open()` would first save
  // what the PREVIOUS mount's editor still held -- which is correct behaviour (leaving an
  // exercise saves it) and would hand the next test that test's code as a draft.
  drafts.clearAll();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
});

async function render() {
  app = mount(App, { target: host }) as Record<string, unknown>;
  await settle();
  await settle();
}

describe("the anonymous page", () => {
  it("mounts, and draws the workbench", async () => {
    await render();
    expect(document.getElementById("travail")).not.toBeNull();
    expect(document.getElementById("code")).not.toBeNull();
    expect(document.getElementById("out")).not.toBeNull();
    expect(document.getElementById("go")).not.toBeNull();
  });

  it("opens the first exercise and fills the editor from its template", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    expect(zone.value).toBe("// écris ici");
    expect(document.getElementById("consignetexte")!.textContent).toBe("Convertis des degrés.");
    expect(document.getElementById("now")!.textContent).toContain("TP2 : ex.1 conversion");
  });

  it("draws the strip with the locked lab's neighbours left out of the flat list", async () => {
    await render();
    const strip = document.getElementById("bandelabo")!;
    expect(strip.hidden).toBe(false);
    expect(strip.textContent).toContain("ex.1");
    expect(strip.textContent).toContain("ex.2");
    // The legend is what makes those borders readable without colour.
    expect(document.getElementById("striplegend")!.hidden).toBe(false);
  });

  it("keeps the menu's locked exercise reachable, with its date", async () => {
    await render();
    const menu = document.getElementById("exliste")!;
    expect(menu.textContent).toContain("TP 9");
    const locked = menu.querySelector('[data-id="tp9-ex1"]')!;
    // `aria-disabled` AND NOT `disabled`: the opening date is the whole reason the row is
    // still displayed, and a `disabled` button drops out of the tab order.
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked.hasAttribute("disabled")).toBe(false);
    expect(locked.textContent).toContain("ouvre le");
  });

  it("starts on the idle verdict, and NOT on three failed stages", async () => {
    await render();
    const out = document.getElementById("out")!;
    expect(out.className).toBe("idle");
    expect(out.textContent).toContain("En attente d'une soumission.");
    // A strip of three "not reached" before the first submission would announce a failure.
    expect(out.querySelector(".etapes")).toBeNull();
  });

  it("says the access key is missing at LOAD time, not at the first submission", async () => {
    await render();
    const banner = document.getElementById("systeme")!;
    expect(banner.hidden).toBe(false);
    expect(banner.textContent).toContain("clé d'accès");
    expect(banner.textContent).toContain("Moodle");
  });

  it("shows the presence counter to the anonymous visitor", async () => {
    await render();
    const live = document.getElementById("live")!;
    expect(live.hidden).toBe(false);
    expect(live.textContent).toContain("3 personnes en ligne");
  });

  it("offers NO account button on a deployment with no issuer", async () => {
    await render();
    expect(document.getElementById("connexion")).toBeNull();
    expect(document.getElementById("menucompte")).toBeNull();
    expect(document.getElementById("mesprogres")).toBeNull();
    expect(document.getElementById("discussions")).toBeNull();
  });

  it("emits nothing outside four kinds of request", async () => {
    await render();
    // The catalog, one statement, what the deployment offers, and the heartbeat -- which is
    // the single deliberate exception to "the anonymous visitor emits no request". The
    // property worth holding is that NOTHING ELSE leaves: no `etats`, no `pratique`, no
    // `preferences`, no `forum`.
    //
    // The statement may legitimately be absent from the list: its cache lives for the life
    // of a page load, and a suite mounts several pages in one process.
    const kinds = new Set(asked.map((u) => u.split("?")[0]!.replace(/^tp\/.*/, "tp/")));
    for (const kind of kinds) {
      expect(["catalog.json", "live", "oidc.json", "tp/"], kind).toContain(kind);
    }
    expect(kinds.has("catalog.json")).toBe(true);
    expect(kinds.has("oidc.json")).toBe(true);
    expect(kinds.has("live")).toBe(true);
  });

  it("colours the code, and escapes what a student types", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = 'int main(void){ printf("<b>hi</b>"); }';
    // SVELTE 5 DELEGATES `input` to the root, so a synthetic event has to BUBBLE to reach
    // the handler. A non-bubbling one would make this suite green while nothing ran.
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    const painted = document.getElementById("hlcode")!;
    expect(painted.querySelector(".tk")).not.toBeNull(); // `int`
    expect(painted.querySelector(".tf")).not.toBeNull(); // `printf`
    // The student's markup is TEXT, and the only elements are our own colour spans.
    expect(painted.querySelector("b")).toBeNull();
    expect(painted.textContent).toContain("<b>hi</b>");
  });

  it("numbers the gutter as one types", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = "un\ndeux\ntrois";
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(document.getElementById("gutter")!.textContent).toBe("1\n2\n3\n");
  });

  it("keeps the chat dock closed and empty", async () => {
    await render();
    const dock = document.getElementById("chatdock")!;
    expect(dock.hidden).toBe(true);
    expect(dock.textContent).toBe("");
    expect(document.getElementById("travail")!.className).toBe("");
  });
});
