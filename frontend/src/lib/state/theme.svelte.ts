// THE THEME, AND IT LIVES IN TWO PLACES ON PURPOSE.
//
// `localStorage` was per DEVICE, and that is the problem the account fixes: a
// student moving from the lab to their laptop used to start from the default every
// time. But the local copy STAYS, and it is not a duplicate -- it is what
// `public/theme.js` reads before the first paint, and nothing else can arrive
// early enough to avoid the flash. What the server says is therefore copied here:
// not to be read back now, but so the NEXT visit on this device already starts
// from the right theme.
//
// AN EMPTY THEME IS NOT AN OUTAGE, and the two must not be confused: "no choice
// recorded" (200, `theme: ""`) keeps what the device shows and sends that choice
// up; "the database did not answer" (503) touches nothing. Falling back to a
// default at the first outage would flash somebody's page every time Postgres
// coughs.

import { localSet } from "../storage";
import { fetchPreferences, savePreferences } from "../api/account";

export type Theme = "light" | "dark";

const THEME_KEY = "ctester.theme";

/**
 * LE THÈME RÉELLEMENT À L'ÉCRAN, ET IL Y A TROIS CAS, PAS DEUX.
 *
 * `public/theme.js` ne pose l'attribut QUE si un choix a été enregistré. Sans
 * attribut, c'est désormais `prefers-color-scheme` qui peint -- donc lire l'attribut
 * seul rendait « dark » pendant que la page était claire. Le bouton annonçait alors
 * « Passer au thème clair » sur une page déjà claire, et le premier clic ne faisait
 * rien de visible : il écrivait le thème qu'on regardait déjà.
 *
 * L'ordre compte : un choix explicite bat le système, dans les deux sens.
 */
function fromDocument(): Theme {
  if (typeof document === "undefined") return "dark";
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  // Aucun choix enregistré : c'est le système qui décide, comme le CSS.
  if (typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

class ThemeState {
  /** Le thème réellement à l'écran : un choix enregistré, sinon celui du système. */
  current = $state<Theme>(fromDocument());

  apply(name: Theme): void {
    this.current = name;
    if (typeof document !== "undefined") document.documentElement.dataset.theme = name;
  }

  remember(name: Theme): void {
    localSet(THEME_KEY, name);
  }

  /**
   * The button, for everyone -- the anonymous visitor included, who emits no
   * request by clicking it. Nothing is awaited: the theme is already on screen,
   * and a failed round trip must not make it look like the button did not work.
   */
  toggle(signedIn: boolean): void {
    const next: Theme = this.current === "light" ? "dark" : "light";
    this.apply(next);
    this.remember(next);
    if (signedIn) void savePreferences(next);
  }

  /** At the start of a session, the ACCOUNT has the last word. See the note above. */
  async loadFromAccount(): Promise<void> {
    const prefs = await fetchPreferences();
    if (!prefs) return; // mute database: the device decides
    if (!prefs.theme) {
      // A fresh account with no choice yet: give it the one on screen.
      await savePreferences(this.current);
      return;
    }
    const named: Theme = prefs.theme === "light" ? "light" : "dark";
    this.apply(named);
    this.remember(named);
  }
}

export const theme = new ThemeState();
