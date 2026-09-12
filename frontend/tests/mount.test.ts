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
    // A BONUS WHOSE TITLE DOES NOT SAY SO -- the real one is "Puissance d'un treuil".
    // The flag is the only thing that may produce the dashes.
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
/** What `/oidc.json` answers. `{}` is a deployment with no sign-in at all. */
let deployment: unknown = {};

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
    // `{}` BY DEFAULT: a deployment with no sign-in, where the whole account block stays
    // inert -- the anonymous path's most important property.
    return Promise.resolve(new Response(JSON.stringify(deployment), { status: 200 }));
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

/**
 * Attend qu'une condition devienne vraie, pour les morceaux chargés à la demande.
 *
 * ON ATTEND LA CONDITION, ON NE DEVINE PAS UN NOMBRE DE TOURS : un `import()`
 * dynamique n'est pas résolu par les micro-tâches, et sous Vitest il faut en
 * plus que le `.svelte` soit transformé à la volée. Un compteur fixe passerait
 * sur une machine et échouerait sur une autre -- c'est-à-dire en CI.
 */
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
  // MOUNTED ONTO THE BODY, exactly as `main.ts` does it. Wrapping the tree in a div here
  // would be a suite that passes while the page collapses -- see the structural checks below.
  document.body.innerHTML = "";
  host = document.body;
  app = null;
  // A FRESH PAGE LOAD, SEEN FROM OUTSIDE. These are per-page-load singletons, which is
  // right in the application and means one test would otherwise inherit the last one's
  // state: the drafts (leaving an exercise saves it, so the previous mount's code would
  // come back as a draft) and what the deployment offers.
  drafts.clearAll();
  session.deployment = null;
  session.setToken(null);
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
  // THESE ARE THE CHECKS THAT WERE MISSING, and their absence shipped a page that did not
  // fill the screen with a sign-in button that looked dead. Asserting that an id EXISTS is
  // not enough: `app.css` is written against a specific NESTING, and every rule below broke
  // while every id was still present.

  it("keeps `#top` and `<main>` as children of BODY, which is the flex column", async () => {
    // `body { display: flex; flex-direction: column; height: 100dvh }` with `#top` at
    // `flex: 0 0 auto` and `main` at `flex: 1 1 auto`. A wrapper element between them breaks
    // the chain at the top: everything collapses to content height and the page stops
    // filling the screen.
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
    // `#travail` is the grid; these are its columns.
    for (const id of ["consigne", "droite", "chatdock"]) {
      expect(document.getElementById(id)!.parentElement, id).toBe(travail);
    }
    // AND THERE ARE EXACTLY THREE OF THEM, IN THIS ORDER. Parenthood alone is not
    // enough and that gap shipped a broken screen: a banner added as a second ROOT
    // of `Statement.svelte` was still leaving `#consigne` a child of `#travail`,
    // but it took the first grid column and pushed every other column one across.
    // `grid-template-columns` is written against these three children and nothing
    // else, so the count is the invariant, not the nesting.
    expect([...travail.children].map((el) => el.id)).toEqual([
      "consigne",
      "droite",
      "chatdock",
    ]);
  });

  it("keeps the three floating panels INSIDE `#top`, which is what they anchor to", async () => {
    // Each is `position: absolute; top: 100%` and `#top` is the only `position: relative`
    // ancestor. Rendered elsewhere, `top: 100%` resolves against the initial containing
    // block: the panel lands one full viewport down, off-screen, and the button that opened
    // it looks dead. That is exactly what shipped.
    await render();
    const bar = document.getElementById("top")!;
    expect(document.getElementById("consentement")!.parentElement).toBe(bar);
    // The other two live in the chat's lazy chunk, so they are only in the DOM once it is
    // loaded -- `barPanel` is what puts all three here.
  });

  it("opens the consent panel where it can be seen, and closes it again", async () => {
    // A deployment that DOES offer sign-in, which is what puts the button in the bar.
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
    // LA LÉGENDE A DISPARU, ET C'EST CE QUI EST ÉPROUVÉ MAINTENANT. Elle expliquait
    // cinq styles de bordure en permanence à l'écran ; une interface qui a besoin
    // d'une clé pour lire une rangée de boutons est une interface ratée. Ce qui la
    // remplace se lit sans clé -- `✓` et fond teinté, `🔒` et sa date, bordure épaisse
    // pour « ouvert ici » -- et les deux CATÉGORIES qu'aucun symbole ne dit portent
    // leur mot SUR la tuile, ce qui est la moitié qui rend la suppression gratuite.
    expect(document.getElementById("striplegend")).toBeNull();
    // `#labcontext` a fondu dans la bande pour la même raison : son nom de labo était
    // déjà dans `#now`, et ses deux boutons ouvraient le même menu.
    expect(document.getElementById("labcontext")).toBeNull();
    expect(strip.textContent).toContain("Tous les exercices");
  });

  it("porte le mot des deux catégories sur la tuile, puisqu'il n'y a plus de légende", async () => {
    await render();
    // LE CONTRÔLE QUI REMPLACE LA LÉGENDE. Sans ce mot, supprimer `#striplegend` était
    // une perte : les tirets d'un bonus ne se devinent pas. Avec lui, ils sont une
    // redondance utile plutôt que le seul porteur de l'information.
    const strip = document.getElementById("bandelabo")!;
    const bonus = [...strip.querySelectorAll<HTMLElement>(".tile")].find((b) =>
      b.title.startsWith("ex.3"),
    )!;
    expect(bonus.textContent).toContain("bonus");
  });

  it("dashes the bonus tile from the flag, layered over its progress class", async () => {
    await render();
    // THE WIRING, WHICH IS WHERE THIS BROKE. `catalog.test.ts` proves the flag survives
    // `normalize`; only a mounted strip proves it reaches the class that draws the dashes.
    // It did not: the class was guessed from the title, and the one exercise carrying the
    // flag is called "Puissance d'un treuil".
    // `.tile` ET PAS `button` : la bande porte aussi le bouton « Tous les exercices »
    // depuis que `#labcontext` a fondu dedans. Un sélecteur sur `button` le ramasserait,
    // et les deux `find` ci-dessous ne tiendraient plus que par le fait que son `title`
    // ne commence pas par « ex. » -- c'est-à-dire par chance.
    const tiles = [...document.getElementById("bandelabo")!.querySelectorAll<HTMLElement>(".tile")];
    const bonus = tiles.find((b) => b.title.startsWith("ex.3"))!;
    expect([...bonus.classList]).toContain("bonus");
    // LAYERED LIKE `courant`, never instead of: a solved bonus must keep its tinted
    // ground, which the old exclusive class took away.
    expect([...bonus.classList]).toContain("afaire");
    // AND THE WORD TRAVELS WITH THE BORDER. A legend is not read by a screen reader.
    expect(bonus.title).toContain("bonus facultatif");
    const ordinary = tiles.find((b) => b.title.startsWith("ex.2"))!;
    expect([...ordinary.classList]).not.toContain("bonus");
    expect(ordinary.title).not.toContain("bonus");
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

  it("unlocks that same row for a moderator, lock and date still shown", async () => {
    // THE WIRING, NOT THE RULE. `catalog.test.ts` proves `normalize(release, true)` keeps
    // the locked exercise; this proves the component tree actually reads `catalog.staff`
    // -- the half that, if it were missing, would leave a "not-allowed" cursor on a
    // moderator's screen with every test still green.
    await render();
    const { catalog } = await import("../src/lib/state/catalog.svelte");
    catalog.setStaff(true);
    flushSync();
    const locked = document.querySelector('#exliste [data-id="tp9-ex1"]')!;
    expect(locked.getAttribute("aria-disabled")).toBeNull();
    expect(locked.className).not.toContain("verrouille");
    // The date is the information the instructor came for: it stays.
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

// --- LES RACCOURCIS DE LA PAGE ---------------------------------------------
//
// La table est éprouvée en l'appelant (`shortcuts.test.ts`), les commandes
// aussi (`keys.test.ts`). Ce qui se vérifie ICI, c'est ce que seule la page
// montée peut dire : que le gestionnaire de fenêtre existe, qu'il RESPECTE le
// contrat `defaultPrevented` avec la surface, et qu'il tient la portée de vue
// qui empêche Ctrl+Entrée de soumettre depuis un écran sans éditeur.

/** Une frappe sur le document, comme le navigateur la fait remonter. */
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
    // L'ancienne condition comparait `event.key !== "k"` : Verr.Maj le tuait.
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
    // Sur le chemin anonyme le bandeau porte déjà « il manque ta clé d'accès ».
    // C'est donc le cas réel de l'invariant : le flash EMPRUNTE le bandeau et le
    // remet tel qu'il l'a trouvé, au lieu d'effacer un message que personne
    // n'avait lu.
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
    // Le contrat entre les deux écouteurs. Sans le `defaultPrevented` en tête,
    // une frappe traitée dans l'éditeur serait traitée une seconde fois ici.
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
    // ET IL EST BIEN SOUS LA BARRE : `top: 100%` ne se résout que contre `#top`.
    expect(panel?.parentElement?.id).toBe("top");

    key("Escape");
    flushSync();
    expect(document.querySelector("#raccourcis")?.hasAttribute("hidden")).toBe(true);
  });

  it("dit ce qu'il ne prend PAS au navigateur", async () => {
    // La première question devant un éditeur dans une page web est « est-ce que
    // Ctrl+Z marche ici ? », et la seule réponse rassurante est de l'écrire.
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
    // La non-régression qui compte : `CodeSurface` pose son drapeau `escaped`
    // pour qu'un Tab suivant SORTE du champ. Si la fenêtre prévenait ici, les
    // deux se marcheraient dessus et on ne pourrait plus quitter l'éditeur.
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
