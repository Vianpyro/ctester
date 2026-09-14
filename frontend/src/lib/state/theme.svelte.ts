import { localSet } from "../storage";
import { fetchPreferences, savePreferences } from "../api/account";

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
    if (signedIn) void savePreferences(next);
  }

  async loadFromAccount(): Promise<void> {
    const prefs = await fetchPreferences();
    if (!prefs) return;
    if (!prefs.theme) {
      await savePreferences(this.current);
      return;
    }
    const named: Theme = prefs.theme === "light" ? "light" : "dark";
    this.apply(named);
    this.remember(named);
  }
}

export const theme = new ThemeState();
