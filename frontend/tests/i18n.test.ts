import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { i18n, LANGUAGES, SOURCE, t, type Messages } from "../src/lib/i18n.svelte";

const SRC = join(import.meta.dirname, "..", "src");
const LOCALES = join(SRC, "locales");
const read = (lang: string): Messages =>
  JSON.parse(readFileSync(join(LOCALES, lang + ".json"), "utf8"));
const en = read(SOURCE);
const fr = read("fr");

// i18next v4 plural forms: a key with any of these suffixes is one entry of a plural.
const PLURAL = /_(zero|one|two|few|many|other)$/;
const base = (key: string) => key.replace(PLURAL, "");
const placeholders = (text: string) =>
  [...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort();

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "locales" ? [] : sources(path);
    return /\.(ts|svelte)$/.test(entry.name) ? [path] : [];
  });
}

afterAll(() => i18n.use("fr", fr, en));

describe("the locale files", () => {
  it("offers every file in locales/ as a language, the source among them", () => {
    expect(LANGUAGES).toContain(SOURCE);
    expect(LANGUAGES).toEqual(
      readdirSync(LOCALES).map((name) => name.replace(".json", "")).sort(),
    );
  });

  it("are flat string tables, which is what translation platforms edit", () => {
    for (const lang of LANGUAGES) {
      for (const [key, value] of Object.entries(read(lang))) {
        expect(typeof value, `${lang}: ${key}`).toBe("string");
      }
    }
  });

  it("translate only keys the source has, with the same placeholders", () => {
    const bases = new Set(Object.keys(en).map(base));
    for (const lang of LANGUAGES) {
      for (const [key, text] of Object.entries(read(lang))) {
        expect(bases.has(base(key)), `${lang}: unknown key ${key}`).toBe(true);
        const reference = en[key] ?? en[base(key) + "_other"] ?? en[base(key)];
        const wanted = placeholders(reference).filter((name) => name !== "count");
        const got = placeholders(text).filter((name) => name !== "count");
        expect(got, `${lang}: ${key}`).toEqual(wanted);
      }
    }
  });

  it("name every literal key the code asks for", () => {
    const missing: string[] = [];
    for (const file of sources(SRC)) {
      const code = readFileSync(file, "utf8");
      for (const m of code.matchAll(/\bt\(\s*["'`]([\w.-]+)["'`]/g)) {
        const key = m[1];
        // `t("error." + code)` builds its key: only a whole literal is checked here.
        if (key.endsWith(".")) continue;
        if (!(key in en) && !(key + "_other" in en)) {
          missing.push(`${relative(SRC, file)}: ${key}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});

describe("t()", () => {
  it("falls back to English, then to the key itself", () => {
    i18n.use("fr", { "a.only_fr": "seulement" }, { "a.only_fr": "only", "a.only_en": "english" });
    expect(t("a.only_fr")).toBe("seulement");
    expect(t("a.only_en")).toBe("english");
    expect(t("a.nowhere")).toBe("a.nowhere");
  });

  it("fills placeholders and leaves unknown ones visible", () => {
    i18n.use("en", {}, { greet: "hi {{name}}, {{ other }}" });
    expect(t("greet", { name: "Ada" })).toBe("hi Ada, {{ other }}");
  });

  it("picks the plural form by the language's own rules", () => {
    const source = { "n.items_one": "{{count}} item", "n.items_other": "{{count}} items" };
    i18n.use("en", source, source);
    expect(t("n.items", { count: 0 })).toBe("0 items");
    expect(t("n.items", { count: 1 })).toBe("1 item");
    i18n.use("fr", { "n.items_one": "{{count}} élément", "n.items_other": "{{count}} éléments" }, source);
    // French counts zero as singular; English does not.
    expect(t("n.items", { count: 0 })).toBe("0 élément");
    expect(t("n.items", { count: 2 })).toBe("2 éléments");
  });

  it("uses the English plural when the language has none yet", () => {
    i18n.use("fr", {}, { "n.items_one": "{{count}} item", "n.items_other": "{{count}} items" });
    expect(t("n.items", { count: 3 })).toBe("3 items");
  });
});
