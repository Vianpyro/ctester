import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIST = join(import.meta.dirname, "..", "dist");
const built = existsSync(join(DIST, "index.html"));

const document_ = () => readFileSync(join(DIST, "index.html"), "utf8");

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
    const html = document_();
    expect(html).toMatch(/<script[^>]+src=/);
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i);
  });

  it("keeps the pre-paint theme script a CLASSIC script with a stable name", () => {
    const html = document_();
    expect(html).toContain('<script src="/theme.js"></script>');
    const themeTag = html.match(/<script src="\/theme\.js"[^>]*>/)![0];
    expect(themeTag).not.toContain("defer");
    expect(themeTag).not.toContain("type=");
  });

  it("keeps the CSP `<meta>` right after `<meta charset>`", () => {
    const html = document_();
    const charset = html.indexOf("<meta charset");
    const policy = html.indexOf("Content-Security-Policy");
    expect(charset).toBeGreaterThan(-1);
    expect(policy).toBeGreaterThan(charset);
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
    for (const path of document_().match(/(?:src|href)="[^"]+"/g) ?? []) {
      expect(path).toMatch(/="\/(assets\/|favicon\.svg|theme\.js)/);
    }
  });
});

describe.skipIf(!built)("what a student with no account pays for", () => {
  const DEFERRED = [
    "DOMPurify",
    "3.4.14",
    "marked(): input",
    "Yjs was already",
  ];

  it("keeps the third-party libraries out of the eager chunks", () => {
    const source = eagerSource();
    for (const marker of DEFERRED) {
      expect(source, marker).not.toContain(marker);
    }
  });

  it("keeps the account, forum, team, progress and console screens out of them", () => {
    const source = eagerSource();
    for (const sentence of [
      "openid profile offline_access",
      "Ce qui se publie ici",
      "Historique partagé",
      "Maîtrise vérifiée",
      "Réponds à ton programme",
      "Divisions du cours",
      "privée par défaut",
    ]) {
      expect(source, sentence).not.toContain(sentence);
    }
  });

  it("still carries everything the anonymous path DOES need", () => {
    const source = eagerSource();
    for (const sentence of [
      "catalog.json",
      "En attente d'une soumission.",
      "Il manque ta clé d'accès",
      "personnes en ligne",
      "Importer un fichier",
    ]) {
      expect(source, sentence).toContain(sentence);
    }
  });

  it("stays under 145 KB of eager JavaScript", () => {
    const bytes = eagerChunks().reduce(
      (n, name) => n + readFileSync(join(DIST, "assets", name)).byteLength,
      0,
    );
    expect(bytes).toBeLessThan(145_000);
  });

  it("keeps the shortcuts WORKING but the cheat sheet DEFERRED", () => {
    const source = eagerSource();
    expect(source, "the matcher runs on every keystroke").toContain("commentBlock");
    expect(source, "so do the transforms").toContain("completeStatement");
    for (const prose of ["Dupliquer la ligne", "clavier canadien-français", "Désindenter"]) {
      expect(source, prose).not.toContain(prose);
    }
    const panel = allChunks().find((name) => name.startsWith("ShortcutsPanel"));
    expect(panel, "the cheat sheet must exist as its own chunk").toBeTruthy();
    expect(readFileSync(join(DIST, "assets", panel!), "utf8")).toContain("Dupliquer la ligne");
  });

  it("really did split: the deferred screens exist as their own chunks", () => {
    expect(allChunks().length).toBeGreaterThan(10);
    const all = allChunks()
      .map((name) => readFileSync(join(DIST, "assets", name), "utf8"))
      .join("\n");
    for (const marker of DEFERRED) {
      expect(all, marker).toContain(marker);
    }
  });
});
