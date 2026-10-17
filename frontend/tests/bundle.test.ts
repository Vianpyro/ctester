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
  it("carries no inline script: `script-src 'self'` needs no hash, and none is copied", () => {
    const html = document_();
    expect(html).toMatch(/<script[^>]+src=/);
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i);
  });

  it("keeps the pre-paint theme script a classic script with a stable name", () => {
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

  it("ships the files GitHub Pages needs at the apex, and the configured domain", () => {
    expect(existsSync(join(DIST, "favicon.svg"))).toBe(true);
    expect(existsSync(join(DIST, "theme.js"))).toBe(true);
    // The domain is a deployment setting: no CTESTER_PAGES_DOMAIN, no CNAME to ship.
    const domain = (process.env.CTESTER_PAGES_DOMAIN ?? "").replace(/\/+$/, "");
    expect(existsSync(join(DIST, "CNAME"))).toBe(Boolean(domain));
    if (domain) {
      expect(readFileSync(join(DIST, "CNAME"), "utf8").trim()).toBe(domain);
    }
  });

  it("references its assets from the root, which is what the custom domain serves", () => {
    // preconnect and dns-prefetch name an origin to warm, not an asset to load.
    const loaded = document_().replace(/<link rel="(?:preconnect|dns-prefetch)"[^>]*>/g, "");
    for (const path of loaded.match(/(?:src|href)="[^"]+"/g) ?? []) {
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
      "openid profile email offline_access groups",
      "forum.rules",
      "team.shared_history",
      "progress.mastery",
      "console.input_label",
      "leaderboard.divisions",
      "collection.held",
    ]) {
      expect(source, sentence).not.toContain(sentence);
    }
  });

  it("keeps a verdict's details and the lab export out: they wait for a test or a click", () => {
    const source = eagerSource();
    for (const sentence of ["verdict.receives", "verdict.failed_checks", "export.building"]) {
      expect(source, sentence).not.toContain(sentence);
    }
  });

  it("still carries everything the anonymous path does need", () => {
    const source = eagerSource();
    for (const sentence of [
      "catalog.json",
      "verdict.idle",
      "access.missing_key",
      "presence.online",
      "actions.import",
    ]) {
      expect(source, sentence).toContain(sentence);
    }
  });

  it("keeps every language in its own chunk, fetched before mount but never eager", () => {
    const source = eagerSource();
    for (const lang of readdirSync(join(import.meta.dirname, "..", "src", "locales"))) {
      const tagline = JSON.parse(
        readFileSync(join(import.meta.dirname, "..", "src", "locales", lang), "utf8"),
      )["app.tagline"];
      expect(source, lang).not.toContain(tagline);
      expect(allChunks().some((name) => name.startsWith(lang.replace(".json", ""))), lang).toBe(true);
    }
  });

  it("keeps Svelte's transition runtime out: Rolldown hoists it into the shared eager chunk", () => {
    // `playState` only appears in svelte/internal's transitions.js. Motion uses CSS and Web
    // Animations instead of in:, out: and animate:, wherever the component lives.
    expect(eagerSource()).not.toContain("playState");
  });

  // 151 KB since the motion work: the View Transitions, the theme reveal and the deferred
  // celebration's loader cost about 0.5 KB here. Everything else that moves is CSS or deferred.
  // 153 KB since the responsive work: the bar's measured fold and the phone's pane switcher
  // must be there at the first paint, about 1.6 KB together.
  it("stays under 153 KB of eager JavaScript", () => {
    const bytes = eagerChunks().reduce(
      (n, name) => n + readFileSync(join(DIST, "assets", name)).byteLength,
      0,
    );
    expect(bytes).toBeLessThan(153_000);
  });

  it("keeps the quiz widgets out: most exercises are not a quiz", () => {
    expect(eagerSource(), "the quiz nav is only for a quiz").not.toContain("quiz.previous");
    const panel = allChunks().find((name) => name.startsWith("QuizPanel"));
    expect(panel, "the quiz panel must exist as its own chunk").toBeTruthy();
    expect(readFileSync(join(DIST, "assets", panel!), "utf8")).toContain("quiz.previous");
  });

  it("keeps the shortcuts working but the cheat sheet deferred", () => {
    const source = eagerSource();
    expect(source, "the matcher runs on every keystroke").toContain("commentBlock");
    expect(source, "so do the transforms").toContain("completeStatement");
    for (const key of ["shortcuts.group.write", "shortcuts.already", "outdent"]) {
      expect(source, key).not.toContain(key);
    }
    const panel = allChunks().find((name) => name.startsWith("ShortcutsPanel"));
    expect(panel, "the cheat sheet must exist as its own chunk").toBeTruthy();
    expect(readFileSync(join(DIST, "assets", panel!), "utf8")).toContain("shortcuts.group.write");
  });

  it("keeps the deferred screens' rules out of the eager stylesheet", () => {
    const links = [...document_().matchAll(/href="\/assets\/([^"]+\.css)"/g)].map((m) => m[1]!);
    expect(links.length).toBeGreaterThan(0);
    const eager = links.map((name) => readFileSync(join(DIST, "assets", name), "utf8")).join("\n");
    for (const selector of [".metrowrap", ".chatflux", ".scratchprompt", ".qpages", ".divisions"]) {
      expect(eager, selector).not.toContain(selector);
    }
    const lazy = readdirSync(join(DIST, "assets"))
      .filter((name) => name.endsWith(".css") && !links.includes(name))
      .map((name) => readFileSync(join(DIST, "assets", name), "utf8"))
      .join("\n");
    expect(lazy).toContain(".metrowrap");
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
