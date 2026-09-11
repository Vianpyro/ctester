// THE ANONYMOUS PATH DOWNLOADS NOTHING ACCOUNT-RELATED, AND THIS IS WHERE THAT IS PROVEN.
//
// It used to be a property of a hand-rolled `<script>` loader, checked by watching which
// URLs a fake DOM requested. It is now a property of the BUNDLE, so it is checked on the
// build itself: whatever the entry chunk and its eagerly preloaded dependencies contain is
// exactly what a student with no account pays for.
//
// THIS SUITE READS `dist/`, so it only runs after `npm run build`. It SKIPS rather than
// fails when there is none: `npm test` on a fresh clone must not demand a build, and CI
// builds before it runs (see `.github/workflows/ci.yml`).

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIST = join(import.meta.dirname, "..", "dist");
const built = existsSync(join(DIST, "index.html"));

const document_ = () => readFileSync(join(DIST, "index.html"), "utf8");

/** The chunks the browser fetches BEFORE anything is clicked: the entry plus its
 *  `modulepreload` links. Everything else arrives on a click, or never. */
function eagerChunks(): string[] {
  const html = document_();
  const names = new Set<string>();
  for (const m of html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)) names.add(m[1]!);
  return [...names];
}

const eagerSource = () =>
  eagerChunks()
    .map((name) => readFileSync(join(DIST, "assets", name), "utf8"))
    .join("\n");

const allChunks = () =>
  readdirSync(join(DIST, "assets")).filter((n) => n.endsWith(".js") && !n.endsWith(".map"));

describe.skipIf(!built)("the built document", () => {
  it("carries NO inline script: `script-src 'self'` needs no hash, and none is copied", () => {
    // A `<meta>` cannot carry a hash computed on the served body; copying one by hand goes
    // stale at the first changed comma, silently, and takes the theme down with it.
    const html = document_();
    expect(html).toMatch(/<script[^>]+src=/);
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i);
  });

  it("keeps the pre-paint theme script a CLASSIC script with a stable name", () => {
    // A module script is deferred by spec and would run after the first paint, bringing the
    // dark-to-light flash back.
    const html = document_();
    expect(html).toContain('<script src="/theme.js"></script>');
    const themeTag = html.match(/<script src="\/theme\.js"[^>]*>/)![0];
    expect(themeTag).not.toContain("defer");
    expect(themeTag).not.toContain("type=");
  });

  it("keeps the CSP `<meta>` right after `<meta charset>`", () => {
    // A browser only applies the policy from the moment it reads it.
    const html = document_();
    const charset = html.indexOf("<meta charset");
    const policy = html.indexOf("Content-Security-Policy");
    expect(charset).toBeGreaterThan(-1);
    expect(policy).toBeGreaterThan(charset);
    // Nothing it governs comes before it.
    expect(html.indexOf("<script")).toBeGreaterThan(policy);
    expect(html.indexOf("<link rel=\"stylesheet\"")).toBeGreaterThan(policy);
  });

  it("ships the files GitHub Pages needs at the apex, and the custom domain", () => {
    expect(existsSync(join(DIST, "CNAME"))).toBe(true);
    expect(readFileSync(join(DIST, "CNAME"), "utf8").trim()).toBe("tch009.thevhome.com");
    expect(existsSync(join(DIST, "favicon.svg"))).toBe(true);
    expect(existsSync(join(DIST, "theme.js"))).toBe(true);
  });

  it("references its assets from the ROOT, which is what the custom domain serves", () => {
    // A repository-name prefix (`/ctester/`) would 404 on every asset; the CNAME is what
    // makes `/` right.
    for (const path of document_().match(/(?:src|href)="[^"]+"/g) ?? []) {
      expect(path).toMatch(/="\/(assets\/|favicon\.svg|theme\.js)/);
    }
  });
});

describe.skipIf(!built)("what a student with no account pays for", () => {
  /**
   * Nothing an anonymous visitor can reach may pull these in.
   *
   * THEY ARE STRING LITERALS, NOT IDENTIFIERS, and that is the point: the build minifies,
   * so `Y.Doc` and `DOMPurify` are renamed and a check on them would pass by accident
   * forever. A string a library carries in its own source survives, and DOMPurify's is its
   * VERSION -- so this pins the bundled version as well.
   */
  const DEFERRED = [
    // The two rendering libraries: 74 KB, and only the chat needs them. The STATEMENT is
    // Markdown too, and deliberately does NOT use them -- `lib/domain/statement.ts` renders
    // it in the eager chunk for 1.6 KB, which is why this assertion still holds.
    "DOMPurify",
    "3.4.14",
    "marked(): input",
    // The CRDT: 92 KB, and only a team assignment needs it.
    "Yjs was already",
  ];

  it("keeps the third-party libraries out of the eager chunks", () => {
    const source = eagerSource();
    for (const marker of DEFERRED) {
      expect(source, marker).not.toContain(marker);
    }
  });

  it("keeps the account, forum, team, progress and console screens out of them", () => {
    // Each of these strings is a sentence only its own screen can say. If one appears in the
    // eager chunks, that screen is being downloaded by somebody who cannot open it.
    const source = eagerSource();
    for (const sentence of [
      "openid profile offline_access", // the OIDC flow
      "Ce qui se publie ici", // the charter
      "Historique partagé", // the team band
      "Maîtrise vérifiée", // the progress projection
      "Réponds à ton programme", // the Console
      "Divisions du cours", // the leaderboard
      "privée par défaut", // the collection
    ]) {
      expect(source, sentence).not.toContain(sentence);
    }
  });

  it("still carries everything the anonymous path DOES need", () => {
    // The other half of the same property: the split must not have deferred the workbench.
    const source = eagerSource();
    for (const sentence of [
      "catalog.json", // the catalog
      "En attente d'une soumission.", // the idle verdict
      "Il manque ta clé d'accès", // the missing session key
      "personnes en ligne", // the presence counter
      "Importer un fichier", // the action bar
    ]) {
      expect(source, sentence).toContain(sentence);
    }
  });

  it("stays under 140 KB of eager JavaScript", () => {
    // NOT A BUDGET FOR ITS OWN SAKE. It sits a few percent above what the build currently
    // produces (~135 KB raw), so a jump past it means something was accidentally pulled
    // into the entry -- which is the only way this number moves by a lot.
    //
    // IT MOVED ONCE, DELIBERATELY, AND HERE IS WHAT MOVED IN: the IDE keyboard
    // shortcuts (+7.5 KB) -- the chord table and its matcher, the seven text
    // transforms of `domain/keys.ts`, and the go-to-line field. They are eager
    // because AN ANONYMOUS STUDENT EDITS CODE: deferring them would mean the
    // shortcuts do not work until something else has been clicked. What did NOT
    // move in is the cheat sheet itself -- its French prose is a chunk of its
    // own, asserted below -- and that split is the reason the number is 140 and
    // not 145.
    //
    // For scale: the page it replaces shipped a 108 KB `app.js` to the same visitor,
    // before its stylesheet, and rendering the statement with `marked` instead of
    // `lib/domain/statement.ts` would have added 74 KB here on its own.
    const bytes = eagerChunks().reduce(
      (n, name) => n + readFileSync(join(DIST, "assets", name)).byteLength,
      0,
    );
    expect(bytes).toBeLessThan(140_000);
  });

  it("keeps the shortcuts WORKING but the cheat sheet DEFERRED", () => {
    // The two halves of the same decision, and they pull in opposite directions:
    // the matcher has to be there before the first keystroke, while the panel that
    // EXPLAINS the shortcuts is prose nobody reads until they press F1. Asserting
    // only the first half would let the labels drift back into the entry and cost
    // every anonymous visitor two kilobytes of French they never see.
    const source = eagerSource();
    expect(source, "the matcher runs on every keystroke").toContain("commentBlock");
    expect(source, "so do the transforms").toContain("completeStatement");
    for (const prose of ["Dupliquer la ligne", "clavier canadien-français", "Désindenter"]) {
      expect(source, prose).not.toContain(prose);
    }
    // And it really is a chunk, rather than simply absent.
    const panel = allChunks().find((name) => name.startsWith("ShortcutsPanel"));
    expect(panel, "the cheat sheet must exist as its own chunk").toBeTruthy();
    expect(readFileSync(join(DIST, "assets", panel!), "utf8")).toContain("Dupliquer la ligne");
  });

  it("really did split: the deferred screens exist as their own chunks", () => {
    // If code splitting silently stopped working, every check above would pass by having
    // put EVERYTHING in one file -- so this is the assertion that keeps them honest.
    expect(allChunks().length).toBeGreaterThan(10);
    const all = allChunks()
      .map((name) => readFileSync(join(DIST, "assets", name), "utf8"))
      .join("\n");
    for (const marker of DEFERRED) {
      expect(all, marker).toContain(marker);
    }
  });
});
