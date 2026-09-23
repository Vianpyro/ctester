// Every string the page shows comes from frontend/src/locales/<lang>.json, in i18next v4
// JSON (flat keys, {{name}} placeholders, _one/_other plural suffixes) so a translation
// platform such as Weblate can edit the files directly. en.json is the source: complete,
// and the fallback for any key another language has not translated yet.
import { localGet, localSet } from "./storage";

declare const __LANG__: string;

export type Messages = Record<string, string>;
export type Params = Record<string, string | number>;

// One chunk per language, fetched before mount: none of them sits in the eager bundle.
const FILES = import.meta.glob<Messages>("../locales/*.json", { import: "default" });
const codeOf = (path: string) => path.slice(path.lastIndexOf("/") + 1, -".json".length);
const LOADERS = new Map(Object.entries(FILES).map(([path, load]) => [codeOf(path), load]));

export const SOURCE = "en";
export const LANGUAGES = [...LOADERS.keys()].sort();
const LANG_KEY = "ctester.lang";

const known = (lang: string | null | undefined): lang is string =>
  Boolean(lang) && LOADERS.has(lang!);

// The instance's language (CTESTER_LANG), unless it names a file this build lacks.
export const DEFAULT_LANG = known(typeof __LANG__ === "string" ? __LANG__ : "")
  ? __LANG__
  : SOURCE;

// A language's name written in that language, from the browser: no list to maintain.
export function languageName(lang: string): string {
  try {
    const name = new Intl.DisplayNames([lang], { type: "language" }).of(lang) ?? lang;
    return name.charAt(0).toLocaleUpperCase(lang) + name.slice(1);
  } catch {
    return lang;
  }
}

class I18nState {
  lang = $state(DEFAULT_LANG);
  messages = $state.raw<Messages>({});
  source: Messages = {};
  #rules = new Intl.PluralRules(DEFAULT_LANG);
  #sourceRules = new Intl.PluralRules(SOURCE);

  // Installs tables already in hand: the loader below, and the tests.
  use(lang: string, messages: Messages, source: Messages): void {
    this.source = source;
    this.#rules = new Intl.PluralRules(lang);
    this.lang = lang;
    this.messages = messages;
    if (typeof document !== "undefined") document.documentElement.lang = lang;
  }

  // The browser fetches a module once, so asking for the source again costs nothing.
  async load(lang: string): Promise<void> {
    if (!known(lang)) lang = DEFAULT_LANG;
    const [messages, source] = await Promise.all([LOADERS.get(lang)!(), LOADERS.get(SOURCE)!()]);
    this.use(lang, messages, source);
  }

  // What the student picked on this browser, if anything. Only an explicit pick is saved to
  // the account, so changing CTESTER_LANG still reaches everyone who never chose.
  chosen(): string {
    const stored = localGet(LANG_KEY);
    return known(stored) ? stored : "";
  }

  initial(): string {
    return this.chosen() || DEFAULT_LANG;
  }

  async choose(lang: string | undefined): Promise<boolean> {
    if (!known(lang) || lang === this.lang) return false;
    localSet(LANG_KEY, lang);
    await this.load(lang);
    return true;
  }

  translate(key: string, params: Params = {}): string {
    const count = typeof params.count === "number" ? params.count : undefined;
    const text =
      pick(this.messages, this.#rules, key, count) ??
      pick(this.source, this.#sourceRules, key, count) ??
      key;
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (whole, name: string) =>
      name in params ? String(params[name]) : whole,
    );
  }

  has(key: string): boolean {
    return key in this.messages || key in this.source;
  }
}

function pick(
  table: Messages,
  rules: Intl.PluralRules,
  key: string,
  count: number | undefined,
): string | undefined {
  if (count !== undefined) {
    const plural = table[`${key}_${rules.select(count)}`] ?? table[`${key}_other`];
    if (plural !== undefined) return plural;
  }
  return table[key];
}

export const i18n = new I18nState();

export const t = (key: string, params?: Params): string => i18n.translate(key, params);
