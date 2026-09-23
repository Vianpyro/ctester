import { localSet } from "../storage";
import { fetchPreferences, savePreferences } from "../api/account";
import { i18n } from "../i18n.svelte";

export type Theme = "light" | "dark";

const THEME_KEY = "ctester.theme";

function fromDocument(): Theme {
  if (typeof document === "undefined") return "dark";
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  if (typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

class ThemeState {
  current = $state<Theme>(fromDocument());

  apply(name: Theme): void {
    this.current = name;
    if (typeof document !== "undefined") document.documentElement.dataset.theme = name;
  }

  remember(name: Theme): void {
    localSet(THEME_KEY, name);
  }

  toggle(signedIn: boolean): void {
    const next: Theme = this.current === "light" ? "dark" : "light";
    this.apply(next);
    this.remember(next);
    if (signedIn) void savePreferences({ theme: next });
  }

  // The language rides along: both are display preferences kept in the same row.
  async loadFromAccount(): Promise<void> {
    const prefs = await fetchPreferences();
    if (!prefs) return;
    if (prefs.lang) await i18n.choose(prefs.lang);
    const lang = prefs.lang ? undefined : i18n.chosen() || undefined;
    if (!prefs.theme || lang) {
      await savePreferences({ theme: prefs.theme || this.current, lang });
    }
    if (!prefs.theme) return;
    const named: Theme = prefs.theme === "light" ? "light" : "dark";
    this.apply(named);
    this.remember(named);
  }
}

export const theme = new ThemeState();
