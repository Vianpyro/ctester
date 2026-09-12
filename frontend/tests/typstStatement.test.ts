// LE COMPOSANT D'UNE CONSIGNE TYPST. Ce qu'il y a à éprouver tient en peu de
// choses, et c'est voulu : il ne décide de rien. Les pages ont été rendues au
// build, il choisit un thème, écrit des `<img>` et dit ce qui manque.
//
// CE QUI N'EST PAS ÉPROUVÉ ICI, EXPRÈS : le rendu lui-même. Un SVG de Typst se
// vérifie là où il est produit -- `test_ctester.py` compile la fixture pour de
// vrai. jsdom ne peint rien, donc une assertion sur l'image serait une
// assertion sur jsdom.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import TypstStatement from "../src/components/TypstStatement.svelte";
import { theme } from "../src/lib/state/theme.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { EXPIRY_KEY } from "../src/lib/auth/keys";

let host: HTMLElement;
let app: ReturnType<typeof mount> | null = null;

const images = () => [...host.querySelectorAll("img")] as HTMLImageElement[];
const sources = () => images().map((img) => img.getAttribute("src"));

function render(props: { id: string; pages: number; staff: boolean; title: string }) {
  app = mount(TypstStatement, { target: host, props });
  flushSync();
}

beforeEach(() => {
  document.body.innerHTML = "";
  host = document.createElement("div");
  document.body.appendChild(host);
  theme.apply("dark");
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  session.setToken(null);
});

describe("a Typst statement is a stack of pre-rendered pages", () => {
  it("draws one image per page, in order", () => {
    render({ id: "tp2-ex3", pages: 3, staff: false, title: "TP2 : ex.3" });
    expect(images()).toHaveLength(3);
    expect(sources()).toEqual([
      "statement/tp2-ex3/dark-1.svg",
      "statement/tp2-ex3/dark-2.svg",
      "statement/tp2-ex3/dark-3.svg",
    ]);
  });

  it("builds the URL from the id, never from something the server handed it", () => {
    // Le serveur envoie un NOMBRE, pas un chemin : rien de ce qui vient du fil
    // ne devient une URL. Un identifiant exotique est donc encodé, pas collé.
    render({ id: "a b/c", pages: 1, staff: false, title: "x" });
    expect(sources()[0]).toBe("statement/a%20b%2Fc/dark-1.svg");
  });

  it("loads the first page eagerly and the rest lazily", () => {
    // La première page est ce qu'on lit ; les suivantes sont sous le pli d'une
    // colonne qui défile, et un étudiant n'y descend pas toujours.
    render({ id: "x", pages: 3, staff: false, title: "x" });
    expect(images().map((img) => img.getAttribute("loading"))).toEqual([
      "eager",
      "lazy",
      "lazy",
    ]);
  });

  it("follows the theme, because a painted SVG cannot", () => {
    render({ id: "x", pages: 2, staff: false, title: "x" });
    expect(sources()).toEqual(["statement/x/dark-1.svg", "statement/x/dark-2.svg"]);
    theme.apply("light");
    flushSync();
    expect(sources()).toEqual(["statement/x/light-1.svg", "statement/x/light-2.svg"]);
  });

  it("says which page did not load instead of leaving a hole", () => {
    // UN TROU BLANC EST LA PIRE RÉPONSE : l'étudiant ne sait pas s'il manque
    // quelque chose. Même raison que les trois états de `Statement.svelte`.
    render({ id: "x", pages: 2, staff: false, title: "x" });
    images()[0]!.dispatchEvent(new Event("error"));
    flushSync();
    expect(host.textContent).toContain("La page 1 de la consigne n'a pas pu être chargée");
    // L'autre page reste là : une image ratée n'emporte pas la consigne.
    expect(images()).toHaveLength(1);
    expect(sources()).toEqual(["statement/x/dark-2.svg"]);
  });

  it("labels the block and each page", () => {
    // CE N'EST PAS UNE SOLUTION D'ACCESSIBILITÉ, et la doc le dit : Typst
    // vectorise ses glyphes, donc le TEXTE de la consigne n'est lisible par
    // aucune synthèse vocale. Ces étiquettes disent seulement ce que le bloc
    // est et combien il a de pages -- c'est ce qui reste possible.
    render({ id: "x", pages: 2, staff: false, title: "TP2 : ex.3" });
    const figure = host.querySelector("figure")!;
    expect(figure.getAttribute("aria-label")).toBe("Consigne de TP2 : ex.3, 2 page(s)");
    expect(images().map((img) => img.getAttribute("alt"))).toEqual([
      "Consigne, page 1 sur 2",
      "Consigne, page 2 sur 2",
    ]);
  });
});

describe("the instructor's preview needs a token, so it needs a second path", () => {
  it("fetches a staff page and shows it as a blob, never as a bare src", async () => {
    // UN `<img>` NE PORTE PAS D'`Authorization`. Un exercice pas encore ouvert
    // n'existe que sous `staff/` et n'est servi qu'à un modérateur : sans ce
    // second chemin, l'enseignant verrait une image cassée exactement là où il
    // vient vérifier son rendu.
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      asked.push(String(input));
      return new Response("<svg/>", { status: 200, headers: { "content-type": "image/svg+xml" } });
    });
    // UNE SESSION VIVANTE, sinon `authFetch` sort en 401 sans rien demander --
    // et le test éprouverait le refus, pas le chemin qu'il vise. L'échéance est
    // posée loin devant pour qu'aucun renouvellement ne parte.
    session.setToken("jeton-de-prof");
    localStorage.setItem(EXPIRY_KEY, String(Math.floor(Date.now() / 1000) + 3600));

    const urls: string[] = [];
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: (b: Blob) => {
        const u = "blob:fake/" + urls.length + "/" + b.size;
        urls.push(u);
        return u;
      },
      revokeObjectURL: (u: string) => urls.splice(urls.indexOf(u), 1),
    });

    render({ id: "ferme", pages: 2, staff: true, title: "x" });
    for (let i = 0; i < 40 && images().length < 2; i++) {
      await Promise.resolve();
      flushSync();
    }

    expect(sources()).toEqual(["blob:fake/0/6", "blob:fake/1/6"]);
    // Et c'est bien la route de l'énoncé qui a été demandée, avec son thème.
    expect(asked.some((u) => u.includes("statement/ferme/dark-1.svg"))).toBe(true);
  });
});
