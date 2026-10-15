import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import App from "../src/App.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";
import { submission } from "../src/lib/state/submission.svelte";

const RELEASE = {
  collections: [
    { id: "tp2", title: "TP 2", items: ["tp2-ex1", "tp2-ex2", "tp2-ex3"], access: "available" },
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
    { id: "tp2-ex3", title: "ex.3 treuil", mode: "io", bonus: true, access: "available" },
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
let deployment: unknown = {};
// The judge's side of a test: /submit and the polls of /r/<job>, when a case needs them.
let judge: ((url: string) => Promise<Response> | null) | null = null;

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  asked.push(url);
  const judged = judge?.(url);
  if (judged) return judged;
  if (url === "catalog.json") {
    return Promise.resolve(new Response(JSON.stringify(RELEASE), { status: 200 }));
  }
  if (url.startsWith("exercise/")) {
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
    return Promise.resolve(new Response(JSON.stringify(deployment), { status: 200 }));
  }
  if (url.startsWith("live?")) {
    return Promise.resolve(new Response(JSON.stringify({ n: 3 }), { status: 200 }));
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
}

const settle = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
  flushSync();
};

async function until(what: string, ready: () => boolean): Promise<void> {
  for (let i = 0; i < 200; i++) {
    flushSync();
    if (ready()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  flushSync();
  throw new Error("jamais arrivé : " + what);
}

let host: HTMLElement;
let app: Record<string, unknown> | null = null;

beforeEach(() => {
  asked = [];
  deployment = {};
  judge = null;
  sessionStorage.removeItem("ctester.key");
  vi.stubGlobal("fetch", fakeFetch);
  document.body.innerHTML = "";
  host = document.body;
  app = null;
  drafts.clearAll();
  session.deployment = null;
  session.setToken(null);
  localStorage.removeItem("ctester.exercise");
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  submission.reset();
});

async function render() {
  app = mount(App, { target: host }) as Record<string, unknown>;
  await settle();
  await settle();
}

describe("the page's structure, which the stylesheet depends on", () => {
  it("keeps `#top` and `<main>` as children of body, the flex column", async () => {
    await render();
    const bar = document.getElementById("top")!;
    const main = document.querySelector("main")!;
    expect(bar.parentElement).toBe(document.body);
    expect(main.parentElement).toBe(document.body);
  });

  it("keeps the workbench inside `<main>`, and its three columns inside it", async () => {
    await render();
    const travail = document.getElementById("work")!;
    expect(travail.parentElement).toBe(document.querySelector("main"));
    for (const id of ["statement", "right", "chatdock"]) {
      expect(document.getElementById(id)!.parentElement, id).toBe(travail);
    }
    expect([...travail.children].map((el) => el.id)).toEqual([
      "statement",
      "right",
      "chatdock",
    ]);
  });

  it("keeps the three floating panels inside `#top`, which is what they anchor to", async () => {
    await render();
    const bar = document.getElementById("top")!;
    expect(document.getElementById("consent")!.parentElement).toBe(bar);
  });

  it("opens the consent panel where it can be seen, and closes it again", async () => {
    deployment = { issuer: "https://auth.exemple.test", client_id: "ctester" };
    await render();
    const panel = document.getElementById("consent")!;
    expect(panel.hidden).toBe(true);
    (document.getElementById("login") as HTMLButtonElement).click();
    flushSync();
    expect(panel.hidden).toBe(false);
    expect(panel.parentElement).toBe(document.getElementById("top"));
    (document.getElementById("consentno") as HTMLButtonElement).click();
    flushSync();
    expect(panel.hidden).toBe(true);
  });
});

describe("the anonymous page", () => {
  it("mounts, and draws the workbench", async () => {
    await render();
    expect(document.getElementById("work")).not.toBeNull();
    expect(document.getElementById("code")).not.toBeNull();
    expect(document.getElementById("out")).not.toBeNull();
    expect(document.getElementById("go")).not.toBeNull();
  });

  it("opens the first exercise and fills the editor from its template", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    expect(zone.value).toBe("// écris ici");
    expect(document.getElementById("statementtext")!.textContent).toBe("Convertis des degrés.");
    expect(document.getElementById("now")!.textContent).toContain("TP2 : ex.1 conversion");
  });

  it("draws the strip with the locked lab's neighbours left out of the flat list", async () => {
    await render();
    const strip = document.getElementById("labband")!;
    expect(strip.hidden).toBe(false);
    expect(strip.textContent).toContain("ex.1");
    expect(strip.textContent).toContain("ex.2");
    expect(document.getElementById("striplegend")).toBeNull();
    expect(document.getElementById("labcontext")).toBeNull();
    expect(strip.textContent).toContain("Tous les exercices");
  });

  it("puts the word for both categories on the tile, since there is no legend anymore", async () => {
    await render();
    const strip = document.getElementById("labband")!;
    const bonus = [...strip.querySelectorAll<HTMLElement>(".tile")].find((b) =>
      b.title.startsWith("ex.3"),
    )!;
    expect(bonus.textContent).toContain("bonus");
  });

  it("dashes the bonus tile from the flag, layered over its progress class", async () => {
    await render();
    const tiles = [...document.getElementById("labband")!.querySelectorAll<HTMLElement>(".tile")];
    const bonus = tiles.find((b) => b.title.startsWith("ex.3"))!;
    expect([...bonus.classList]).toContain("bonus");
    expect([...bonus.classList]).toContain("todo");
    expect(bonus.title).toContain("bonus facultatif");
    const ordinary = tiles.find((b) => b.title.startsWith("ex.2"))!;
    expect([...ordinary.classList]).not.toContain("bonus");
    expect(ordinary.title).not.toContain("bonus");
  });

  it("returns to the exercise when the title is clicked, from any screen", async () => {
    await render();
    const { view } = await import("../src/lib/state/view.svelte");
    view.show("progress");
    flushSync();
    expect(document.getElementById("work")!.hidden).toBe(true);
    (document.getElementById("home") as HTMLButtonElement).click();
    flushSync();
    expect(document.getElementById("work")!.hidden).toBe(false);
    expect(view.current).toBe("");
  });

  it("reopens the last exercise on reload, and the deep link beats it", async () => {
    localStorage.setItem("ctester.exercise", "tp2-ex3");
    await render();
    expect(document.getElementById("now")!.textContent).toContain("ex.3");

    unmount(app!);
    app = null;
    document.body.innerHTML = "";
    host = document.body;
    history.replaceState({}, "", "/?tp=tp2-ex2");
    await render();
    expect(document.getElementById("now")!.textContent).toContain("ex.2");
    history.replaceState({}, "", "/");
  });

  it("falls back to the first exercise when the last one can no longer be opened", async () => {
    localStorage.setItem("ctester.exercise", "tp9-ex1");
    await render();
    expect(document.getElementById("now")!.textContent).toContain("ex.1 conversion");
  });

  it("keeps the menu's locked exercise reachable, with its date", async () => {
    await render();
    const menu = document.getElementById("exlist")!;
    expect(menu.textContent).toContain("TP 9");
    const locked = menu.querySelector('[data-id="tp9-ex1"]')!;
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked.hasAttribute("disabled")).toBe(false);
    expect(locked.textContent).toContain("ouvre le");
  });

  it("unlocks that same row for a moderator, lock and date still shown", async () => {
    await render();
    const { catalog } = await import("../src/lib/state/catalog.svelte");
    catalog.setStaff(true);
    flushSync();
    const locked = document.querySelector('#exlist [data-id="tp9-ex1"]')!;
    expect(locked.getAttribute("aria-disabled")).toBeNull();
    expect(locked.className).not.toContain("locked");
    expect(locked.textContent).toContain("ouvre le");
    catalog.setStaff(false);
    flushSync();
    expect(
      document.querySelector('#exlist [data-id="tp9-ex1"]')!.getAttribute("aria-disabled"),
    ).toBe("true");
  });

  it("starts on the idle verdict, and not on three failed stages", async () => {
    await render();
    const out = document.getElementById("out")!;
    expect(out.className).toBe("idle");
    expect(out.textContent).toContain("Pas encore testé.");
    expect(out.querySelector(".steps")).toBeNull();
  });

  it("says the access key is missing at load time, not at the first submission", async () => {
    await render();
    const banner = document.getElementById("system")!;
    expect(banner.hidden).toBe(false);
    expect(banner.textContent).toContain("clé d'accès");
    expect(banner.textContent).toContain("depuis ton cours");
  });

  it("shows the presence counter to the anonymous visitor", async () => {
    await render();
    const live = document.getElementById("live")!;
    expect(live.hidden).toBe(false);
    expect(live.textContent).toContain("3 personnes en ligne");
  });

  it("offers no account button on a deployment with no issuer", async () => {
    await render();
    expect(document.getElementById("login")).toBeNull();
    expect(document.getElementById("accountmenu")).toBeNull();
    expect(document.getElementById("myprogress")).toBeNull();
    expect(document.getElementById("discussions")).toBeNull();
  });

  it("emits nothing outside four kinds of request", async () => {
    await render();
    const kinds = new Set(asked.map((u) => u.split("?")[0]!.replace(/^exercise\/.*/, "exercise/")));
    for (const kind of kinds) {
      expect(["catalog.json", "live", "oidc.json", "exercise/"], kind).toContain(kind);
    }
    expect(kinds.has("catalog.json")).toBe(true);
    expect(kinds.has("oidc.json")).toBe(true);
    expect(kinds.has("live")).toBe(true);
  });

  it("colours the code, and escapes what a student types", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = 'int main(void){ printf("<b>hi</b>"); }';
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    const painted = document.getElementById("hlcode")!;
    expect(painted.querySelector(".tk")).not.toBeNull();
    expect(painted.querySelector(".tf")).not.toBeNull();
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

  it("shows what the checker finds in the exercise's editor", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = "int main(void) {\n    int x = 1\n    return 0;\n}\n";
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    await until("the checker speaks", () => !!document.querySelector(".diag"));
    expect(document.querySelector(".diag")?.textContent).toContain("ligne 2");
  });

  it("keeps the chat dock closed and empty", async () => {
    await render();
    const dock = document.getElementById("chatdock")!;
    expect(dock.hidden).toBe(true);
    expect(dock.textContent).toBe("");
    expect(document.getElementById("work")!.className).toBe("");
  });
});

function key(
  k: string,
  mods: Partial<Record<"ctrlKey" | "shiftKey" | "altKey" | "metaKey", boolean>> = {},
) {
  const event = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...mods });
  (document.activeElement ?? document.body).dispatchEvent(event);
  flushSync();
  return event;
}

describe("the page's shortcuts", () => {
  it("opens the catalogue and lands in the filter", async () => {
    await render();
    expect(key("k", { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBe(true);
  });

  it("opens it with Caps Lock on too", async () => {
    await render();
    expect(key("K", { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBe(true);
  });

  it("answers Ctrl+S without ever pretending to save a file", async () => {
    await render();
    const event = key("s", { ctrlKey: true });
    expect(event.defaultPrevented, "otherwise the browser opens \"Save page\"").toBe(true);
    expect(document.querySelector("#system")?.textContent).toContain("sauvegardé tout seul");
  });

  it("the Ctrl+S message clears by itself and gives the banner back", async () => {
    await render();
    const banner = () => document.querySelector("#system")?.textContent ?? "";
    const before = banner();
    expect(before, "ce cas n'a de sens que si le bandeau parlait déjà").not.toBe("");

    vi.useFakeTimers();
    try {
      key("s", { ctrlKey: true });
      expect(banner()).toContain("sauvegardé tout seul");
      vi.advanceTimersByTime(3000);
      flushSync();
      expect(banner()).not.toContain("sauvegardé tout seul");
      expect(banner(), "et le message d'avant est revenu").toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a keystroke already handled by the surface is not replayed", async () => {
    await render();
    const event = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true, cancelable: true });
    event.preventDefault();
    document.body.dispatchEvent(event);
    flushSync();
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBeFalsy();
  });

  it("nothing that belongs to the browser is prevented", async () => {
    await render();
    for (const k of ["z", "c", "v", "f", "a", "y"]) {
      expect(key(k, { ctrlKey: true }).defaultPrevented, "Ctrl+" + k).toBe(false);
    }
  });
});

describe("the cheat sheet", () => {
  it("opens on F1, closes on Escape, and arrives as a separate chunk", async () => {
    await render();
    expect(document.querySelector("#shortcuts")).toBeNull();
    expect(key("F1").defaultPrevented).toBe(true);
    await until("le panneau des raccourcis", () => !!document.querySelector("#shortcuts"));
    const panel = document.querySelector("#shortcuts");
    expect(panel?.hasAttribute("hidden")).toBe(false);
    expect(panel?.parentElement?.id).toBe("top");

    key("Escape");
    flushSync();
    expect(document.querySelector("#shortcuts")?.hasAttribute("hidden")).toBe(true);
  });

  it("says what it does not take from the browser", async () => {
    await render();
    key("F1");
    await until("le panneau des raccourcis", () => !!document.querySelector("#shortcuts"));
    const text = document.querySelector("#shortcuts")?.textContent ?? "";
    expect(text).toContain("Annuler");
    expect(text).toContain("Refaire");
    expect(text).toContain("Ctrl+Maj+K est pris par le navigateur");
  });
});

describe("Escape does not break the keyboard escape hatch", () => {
  it("prevents nothing when the caret is in the code", async () => {
    await render();
    const zone = document.querySelector<HTMLTextAreaElement>("#code")!;
    zone.focus();
    expect(key("Escape").defaultPrevented).toBe(false);
  });

  it("prevents nothing when nothing is open and focus is already in the code", async () => {
    await render();
    document.querySelector<HTMLTextAreaElement>("#code")!.focus();
    expect(key("Escape").defaultPrevented).toBe(false);
  });

  it("returns to the code from a button on the page", async () => {
    await render();
    document.querySelector<HTMLButtonElement>("#go")!.focus();
    expect(key("Escape").defaultPrevented).toBe(true);
    expect(document.activeElement?.id).toBe("code");
  });
});

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

// A judge that takes the job at once and answers the first poll with this verdict.
function verdictIs(verdict: Record<string, unknown>): void {
  judge = (url) => {
    if (url.startsWith("submit")) return json({ id: "a".repeat(32) });
    if (url.startsWith("r/")) return json(verdict);
    return null;
  };
}

const out = () => document.getElementById("out")!;
// Fresh code each time: the same code twice is answered from the last verdict, not sent.
let runs = 0;
function test(): void {
  const zone = document.getElementById("code") as HTMLTextAreaElement;
  zone.value = "// essai " + ++runs;
  zone.dispatchEvent(new Event("input", { bubbles: true }));
  (document.getElementById("go") as HTMLButtonElement).click();
}

describe("the critical journeys", () => {
  beforeEach(() => history.replaceState({}, "", "/?k=cle"));
  afterEach(() => history.replaceState({}, "", "/"));

  it("1. a pass is said at once, and moving on never waits for the celebration", async () => {
    verdictIs({ state: "done", status: "ok", kind: "io", total: 7, passed: 7 });
    await render();
    test();
    await until("the verdict", () => out().className === "ok");
    expect(out().querySelectorAll(".steps .step.ok")).toHaveLength(3);
    expect(out().querySelector(".verdict")!.textContent).toContain("7 / 7");
    const next = out().querySelector<HTMLButtonElement>(".suite button.next")!;
    next.focus();
    expect(document.activeElement).toBe(next);
    expect(document.getElementById("notice")!.textContent).toContain("7 / 7");
  });

  it("2. a compile error stops at the first station and leads to the line", async () => {
    verdictIs({
      state: "done",
      status: "compile_error",
      kind: "io",
      gcc: "submission.c:1:12: error: expected ';' before '}' token\n",
    });
    await render();
    test();
    await until("the verdict", () => out().className === "bad");
    const stations = [...out().querySelectorAll(".steps .step")].map((s) => s.className);
    expect(stations).toEqual(["step ko", "step empty", "step empty"]);
    expect(out().querySelector(".gcc pre")!.textContent).toContain("expected ';'");
    let goto: HTMLButtonElement | undefined;
    await until("gcc's help", () => {
      goto = [...out().querySelectorAll<HTMLButtonElement>("button")].find((b) =>
        b.textContent!.includes("ligne 1"),
      );
      return !!goto;
    });
    goto!.click();
    await settle();
    expect(document.activeElement?.id).toBe("code");
  });

  it("3. failed tests after a clean compile read as progress, with the failing case open", async () => {
    verdictIs({
      state: "done",
      status: "ok",
      kind: "io",
      total: 7,
      passed: 5,
      cases: [{ case: 3, reason: "wrong_output", stdin: "2 -3\n", stdout: "5\n" }],
    });
    await render();
    test();
    await until("the verdict", () => out().className === "partial");
    expect(out().querySelector(".verdict")!.textContent).toContain("5 / 7");
    expect(out().querySelectorAll(".ticks i.on")).toHaveLength(5);
    expect(out().querySelectorAll(".ticks i.off")).toHaveLength(2);
    await until("the cases", () => !!out().querySelector("details.case[open]"));
    expect(out().querySelector("details.case[open] pre")!.textContent).toContain("-3");
  });

  it("4. sends one test however often Test is clicked while it is out", async () => {
    let posts = 0;
    judge = (url) => (url.startsWith("submit") ? (posts++, new Promise<Response>(() => {})) : null);
    await render();
    test();
    test();
    test();
    await settle();
    expect(posts).toBe(1);
    expect(document.getElementById("go")!.getAttribute("aria-disabled")).toBe("true");
  });

  it("4. says a failed send beside the Test button, with a way to run it again", async () => {
    judge = (url) => (url.startsWith("submit") ? Promise.reject(new TypeError("hors ligne")) : null);
    await render();
    test();
    await until("the fault", () => out().className === "fault");
    expect(out().textContent).toContain("enregistré");
    expect(document.getElementById("system")!.textContent).not.toContain("ne répond pas");
    expect(out().querySelector("button.retry")).not.toBeNull();
  });

  it("4. keeps what was typed when another exercise is opened at once", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = "// ma réponse";
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    const tile = (name: string) =>
      [...document.querySelectorAll<HTMLElement>("#labband .tile")].find((b) =>
        b.title.startsWith(name),
      )!;
    tile("ex.2").click();
    await until("ex.2", () => document.getElementById("now")!.textContent!.includes("ex.2"));
    tile("ex.1").click();
    await until("ex.1", () => document.getElementById("now")!.textContent!.includes("ex.1"));
    await settle();
    expect((document.getElementById("code") as HTMLTextAreaElement).value).toBe("// ma réponse");
  });

  it("4. keeps the last keystrokes when the tab closes before the autosave", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = "int main(void) { return 42; }";
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    dispatchEvent(new Event("pagehide"));
    const kept = JSON.parse(localStorage.getItem("ctester.drafts")!) as Record<
      string,
      Record<string, string>
    >;
    expect(kept["tp2-ex1"]!["submission.c"]).toContain("return 42");
  });

  it("4. asks before erasing every draft, and erases nothing on a no", async () => {
    await render();
    const zone = document.getElementById("code") as HTMLTextAreaElement;
    zone.value = "// à garder";
    zone.dispatchEvent(new Event("input", { bubbles: true }));
    dispatchEvent(new Event("pagehide"));
    flushSync();
    vi.stubGlobal("confirm", () => false);
    (document.getElementById("purge") as HTMLButtonElement).click();
    expect(localStorage.getItem("ctester.drafts")).toContain("à garder");
    vi.stubGlobal("confirm", () => true);
    (document.getElementById("purge") as HTMLButtonElement).click();
    expect(localStorage.getItem("ctester.drafts")).toBeNull();
  });

  it("6. names the exercise as a heading", async () => {
    await render();
    expect(document.querySelector("#now h2")!.textContent).toContain("ex.1 conversion");
  });

  it("6. moves focus into the consent dialog, and back to Sign in when its button cancels", async () => {
    deployment = { issuer: "https://auth.exemple.test", client_id: "ctester" };
    await render();
    const panel = document.getElementById("consent")!;
    expect(panel.getAttribute("role")).toBe("dialog");
    (document.getElementById("login") as HTMLButtonElement).click();
    flushSync();
    expect(document.activeElement?.id).toBe("consenttitle");
    (document.getElementById("consentno") as HTMLButtonElement).click();
    flushSync();
    expect(document.activeElement?.id).toBe("login");
  });

  it("6. offers a way straight to the code as the very first stop", async () => {
    await render();
    const first = document.body.firstElementChild as HTMLAnchorElement;
    expect(first.className).toBe("skip");
    expect(first.getAttribute("href")).toBe("#code");
  });

  it("6. walks the catalogue from the keyboard, and gives focus back to it after a choice", async () => {
    await render();
    key("k", { ctrlKey: true });
    await settle();
    expect(document.activeElement?.id).toBe("search");
    key("ArrowDown");
    expect((document.activeElement as HTMLElement).dataset.id).toBe("tp2-ex1");
    key("ArrowDown");
    expect((document.activeElement as HTMLElement).dataset.id).toBe("tp2-ex2");
    key("ArrowUp");
    key("ArrowUp");
    expect(document.activeElement?.id).toBe("search");
    key("ArrowDown");
    key("ArrowDown");
    (document.activeElement as HTMLButtonElement).click();
    await until("ex.2", () => document.getElementById("now")!.textContent!.includes("ex.2"));
    expect(document.activeElement?.id).toBe("excurrent");
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBe(false);
  });

  it("6. opens the first match when Enter is pressed in the filter", async () => {
    await render();
    key("k", { ctrlKey: true });
    await settle();
    const search = document.getElementById("search") as HTMLInputElement;
    search.value = "treuil";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    key("Enter");
    await until("ex.3", () => document.getElementById("now")!.textContent!.includes("ex.3"));
  });

  it("6. gives focus back to the Shortcuts button when the sheet closes by its own button", async () => {
    await render();
    key("F1");
    await until("le panneau des raccourcis", () => !!document.querySelector("#shortcuts:not([hidden])"));
    expect(document.getElementById("shortcuts")!.getAttribute("role")).toBe("dialog");
    const buttons = document.querySelectorAll<HTMLButtonElement>("#shortcuts button");
    buttons[buttons.length - 1]!.click();
    flushSync();
    expect(document.activeElement?.id).toBe("shortcutsbutton");
  });
});
