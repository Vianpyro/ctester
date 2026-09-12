// LA PAGE ENTIÈRE, AVEC UNE CONSIGNE TYPST. Le jumeau de `mount.test.ts`, et il
// vit dans SON PROPRE FICHIER pour une raison mécanique : le cache de détails de
// `catalog` est un singleton de chargement de page, partagé par tous les tests
// d'un même fichier. Un exercice déjà ouvert par un test voisin reviendrait
// depuis ce cache, en Markdown, et celui-ci n'éprouverait plus rien. Vitest
// isole les modules PAR FICHIER : un fichier de plus est la remise à zéro, et
// elle ne coûte aucune méthode ajoutée au code de production pour un test.
//
// CE QU'IL ÉPROUVE, c'est le CÂBLAGE : que `statement_format` traverse le
// client, l'état et le composant jusqu'à des `<img>` dans le panneau, et que la
// grille de `#travail` n'ait pas bougé. Le rendu lui-même est éprouvé là où il
// est produit -- `test_ctester.py` compile la fixture pour de vrai.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import App from "../src/App.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";

const RELEASE = {
  collections: [{ id: "tp2", title: "TP 2", items: ["tp2-ex1"], access: "available" }],
  exercises: [
    {
      id: "tp2-ex1",
      title: "ex.1 conversion",
      mode: "io",
      files: [{ name: "submission.c" }],
      access: "available",
    },
  ],
  assignments: [],
};

/** Ce que `/tp/<id>.json` répond : un énoncé Typst de deux pages. */
const DETAIL = {
  statement: "",
  statement_format: "typst",
  statement_pages: 2,
  files: [{ name: "submission.c", template: "// écris ici" }],
};

let asked: string[] = [];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  asked.push(url);
  if (url === "catalog.json") {
    return Promise.resolve(new Response(JSON.stringify(RELEASE), { status: 200 }));
  }
  if (url.startsWith("tp/")) {
    return Promise.resolve(new Response(JSON.stringify(DETAIL), { status: 200 }));
  }
  if (url === "oidc.json") {
    return Promise.resolve(new Response("{}", { status: 200 }));
  }
  if (url.startsWith("live")) {
    return Promise.resolve(new Response(JSON.stringify({ n: 1 }), { status: 200 }));
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
}

let host: HTMLElement;
let app: Record<string, unknown> | null = null;

const settle = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
  flushSync();
};

beforeEach(() => {
  asked = [];
  vi.stubGlobal("fetch", fakeFetch);
  document.body.innerHTML = "";
  host = document.body;
  app = null;
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

describe("a Typst statement, all the way to the page", () => {
  it("draws the pages as images instead of rendered Markdown", async () => {
    await render();
    const panneau = document.getElementById("consignetexte")!;
    // PAS LA CLASSE `md` : c'est celle du rendu Markdown, et elle porte un
    // padding et une police qu'un SVG déjà peint ne doit pas recevoir.
    expect(panneau.classList.contains("md")).toBe(false);
    const images = [...panneau.querySelectorAll("img")];
    expect(images).toHaveLength(2);
    expect(images.map((img) => img.getAttribute("src"))).toEqual([
      "statement/tp2-ex1/dark-1.svg",
      "statement/tp2-ex1/dark-2.svg",
    ]);
  });

  it("keeps the workspace grid at exactly three columns", async () => {
    // UN SECOND ÉLÉMENT RACINE DANS `Statement.svelte` prendrait la première
    // colonne de la grille et pousserait tout le reste d'un cran. C'est déjà
    // arrivé, et c'est pour ça que ce contrôle existe dans `mount.test.ts`.
    // Il est rejoué ici parce que la branche Typst est un nouveau chemin de
    // rendu dans ce même composant.
    await render();
    const travail = document.getElementById("travail")!;
    expect([...travail.children].map((el) => el.id)).toEqual([
      "consigne",
      "droite",
      "chatdock",
    ]);
  });

  it("fills the editor anyway: the statement's format decides nothing else", async () => {
    await render();
    expect((document.getElementById("code") as HTMLTextAreaElement).value).toBe(
      "// écris ici",
    );
  });

  it("emits no request for the pages: an <img> is the browser's business", async () => {
    // LES SVG NE PASSENT PAS PAR `fetch` sur le chemin public -- ils sont des
    // `<img src>`, donc mis en cache et revalidés par le navigateur. Le
    // contrat de `mount.test.ts` (« rien hors de quatre sortes de requête »)
    // tient donc tel quel, sans une cinquième entrée.
    await render();
    const kinds = new Set(asked.map((u) => u.split("?")[0]!.replace(/^tp\/.*/, "tp/")));
    for (const kind of kinds) {
      expect(["catalog.json", "live", "oidc.json", "tp/"], kind).toContain(kind);
    }
    expect(asked.some((u) => u.includes(".svg"))).toBe(false);
  });
});
