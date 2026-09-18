import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import App from "../src/App.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";

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

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  asked.push(url);
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
  vi.stubGlobal("fetch", fakeFetch);
  document.body.innerHTML = "";
  host = document.body;
  app = null;
  drafts.clearAll();
  session.deployment = null;
  session.setToken(null);
  localStorage.removeItem("ctester.exercice");
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

describe("the page's structure, which the stylesheet depends on", () => {
  it("keeps `#top` and `<main>` as children of BODY, which is the flex column", async () => {
    await render();
    const bar = document.getElementById("top")!;
    const main = document.querySelector("main")!;
    expect(bar.parentElement).toBe(document.body);
    expect(main.parentElement).toBe(document.body);
  });

  it("keeps the workbench inside `<main>`, and its three columns inside it", async () => {
    await render();
    const travail = document.getElementById("travail")!;
    expect(travail.parentElement).toBe(document.querySelector("main"));
    for (const id of ["consigne", "droite", "chatdock"]) {
      expect(document.getElementById(id)!.parentElement, id).toBe(travail);
    }
    expect([...travail.children].map((el) => el.id)).toEqual([
      "consigne",
      "droite",
      "chatdock",
    ]);
  });

  it("keeps the three floating panels INSIDE `#top`, which is what they anchor to", async () => {
    await render();
    const bar = document.getElementById("top")!;
    expect(document.getElementById("consentement")!.parentElement).toBe(bar);
  });

  it("opens the consent panel where it can be seen, and closes it again", async () => {
    deployment = { issuer: "https://auth.exemple.test", client_id: "ctester" };
    await render();
    const panel = document.getElementById("consentement")!;
    expect(panel.hidden).toBe(true);
    (document.getElementById("connexion") as HTMLButtonElement).click();
    flushSync();
    expect(panel.hidden).toBe(false);
    expect(panel.parentElement).toBe(document.getElementById("top"));
    (document.getElementById("consentnon") as HTMLButtonElement).click();
    flushSync();
    expect(panel.hidden).toBe(true);
  });
});

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
    expect(document.getElementById("striplegend")).toBeNull();
    expect(document.getElementById("labcontext")).toBeNull();
    expect(strip.textContent).toContain("Tous les exercices");
  });

  it("porte le mot des deux catégories sur la tuile, puisqu'il n'y a plus de légende", async () => {
    await render();
    const strip = document.getElementById("bandelabo")!;
    const bonus = [...strip.querySelectorAll<HTMLElement>(".tile")].find((b) =>
      b.title.startsWith("ex.3"),
    )!;
    expect(bonus.textContent).toContain("bonus");
  });

  it("dashes the bonus tile from the flag, layered over its progress class", async () => {
    await render();
    const tiles = [...document.getElementById("bandelabo")!.querySelectorAll<HTMLElement>(".tile")];
    const bonus = tiles.find((b) => b.title.startsWith("ex.3"))!;
    expect([...bonus.classList]).toContain("bonus");
    expect([...bonus.classList]).toContain("afaire");
    expect(bonus.title).toContain("bonus facultatif");
    const ordinary = tiles.find((b) => b.title.startsWith("ex.2"))!;
    expect([...ordinary.classList]).not.toContain("bonus");
    expect(ordinary.title).not.toContain("bonus");
  });

  it("ramene a l'exercice quand on clique le titre, depuis n'importe quel ecran", async () => {
    await render();
    const { view } = await import("../src/lib/state/view.svelte");
    view.show("progres");
    flushSync();
    expect(document.getElementById("travail")!.hidden).toBe(true);
    (document.getElementById("accueil") as HTMLButtonElement).click();
    flushSync();
    expect(document.getElementById("travail")!.hidden).toBe(false);
    expect(view.current).toBe("");
  });

  it("rouvre le dernier exercice au rechargement, et le lien profond le bat", async () => {
    localStorage.setItem("ctester.exercice", "tp2-ex3");
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

  it("retombe sur le premier exercice quand le dernier n'est plus ouvrable", async () => {
    localStorage.setItem("ctester.exercice", "tp9-ex1");
    await render();
    expect(document.getElementById("now")!.textContent).toContain("ex.1 conversion");
  });

  it("keeps the menu's locked exercise reachable, with its date", async () => {
    await render();
    const menu = document.getElementById("exliste")!;
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
    const locked = document.querySelector('#exliste [data-id="tp9-ex1"]')!;
    expect(locked.getAttribute("aria-disabled")).toBeNull();
    expect(locked.className).not.toContain("verrouille");
    expect(locked.textContent).toContain("ouvre le");
    catalog.setStaff(false);
    flushSync();
    expect(
      document.querySelector('#exliste [data-id="tp9-ex1"]')!.getAttribute("aria-disabled"),
    ).toBe("true");
  });

  it("starts on the idle verdict, and NOT on three failed stages", async () => {
    await render();
    const out = document.getElementById("out")!;
    expect(out.className).toBe("idle");
    expect(out.textContent).toContain("En attente d'une soumission.");
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

  it("keeps the chat dock closed and empty", async () => {
    await render();
    const dock = document.getElementById("chatdock")!;
    expect(dock.hidden).toBe(true);
    expect(dock.textContent).toBe("");
    expect(document.getElementById("travail")!.className).toBe("");
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

describe("les raccourcis de la page", () => {
  it("ouvre le catalogue et atterrit dans le filtre", async () => {
    await render();
    expect(key("k", { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBe(true);
  });

  it("l'ouvre AUSSI avec Verr.Maj -- le bogue que la table répare", async () => {
    await render();
    expect(key("K", { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBe(true);
  });

  it("répond à Ctrl+S sans jamais prétendre enregistrer un fichier", async () => {
    await render();
    const event = key("s", { ctrlKey: true });
    expect(event.defaultPrevented, "sinon le navigateur ouvre « Enregistrer la page »").toBe(true);
    expect(document.querySelector("#systeme")?.textContent).toContain("sauvegardé tout seul");
  });

  it("le message de Ctrl+S s'efface tout seul, ET REND LE BANDEAU", async () => {
    await render();
    const banner = () => document.querySelector("#systeme")?.textContent ?? "";
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

  it("SILENCE : une frappe déjà prévenue par la surface n'est pas rejouée", async () => {
    await render();
    const event = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true, cancelable: true });
    event.preventDefault();
    document.body.dispatchEvent(event);
    flushSync();
    expect(document.querySelector("#menuex")?.hasAttribute("open")).toBeFalsy();
  });

  it("SILENCE : rien de ce qui appartient au navigateur n'est prévenu", async () => {
    await render();
    for (const k of ["z", "c", "v", "f", "a", "y"]) {
      expect(key(k, { ctrlKey: true }).defaultPrevented, "Ctrl+" + k).toBe(false);
    }
  });
});

describe("l'aide-mémoire", () => {
  it("s'ouvre à F1, se ferme à Échap, et arrive en morceau séparé", async () => {
    await render();
    expect(document.querySelector("#raccourcis")).toBeNull();
    expect(key("F1").defaultPrevented).toBe(true);
    await until("le panneau des raccourcis", () => !!document.querySelector("#raccourcis"));
    const panel = document.querySelector("#raccourcis");
    expect(panel?.hasAttribute("hidden")).toBe(false);
    expect(panel?.parentElement?.id).toBe("top");

    key("Escape");
    flushSync();
    expect(document.querySelector("#raccourcis")?.hasAttribute("hidden")).toBe(true);
  });

  it("dit ce qu'il ne prend PAS au navigateur", async () => {
    await render();
    key("F1");
    await until("le panneau des raccourcis", () => !!document.querySelector("#raccourcis"));
    const text = document.querySelector("#raccourcis")?.textContent ?? "";
    expect(text).toContain("Annuler");
    expect(text).toContain("Refaire");
    expect(text).toContain("Ctrl+Maj+K est pris par le navigateur");
  });
});

describe("SILENCE : Échap ne casse pas l'échappatoire clavier", () => {
  it("ne prévient rien quand le curseur est dans le code", async () => {
    await render();
    const zone = document.querySelector<HTMLTextAreaElement>("#code")!;
    zone.focus();
    expect(key("Escape").defaultPrevented).toBe(false);
  });

  it("ne prévient rien quand il n'y a rien d'ouvert et qu'on est déjà dans le code", async () => {
    await render();
    document.querySelector<HTMLTextAreaElement>("#code")!.focus();
    expect(key("Escape").defaultPrevented).toBe(false);
  });

  it("ramène au code depuis un bouton de la page", async () => {
    await render();
    document.querySelector<HTMLButtonElement>("#go")!.focus();
    expect(key("Escape").defaultPrevented).toBe(true);
    expect(document.activeElement?.id).toBe("code");
  });
});
