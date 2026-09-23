process.env.TZ = "America/Toronto";

import { beforeEach, vi } from "vitest";
import { i18n } from "../src/lib/i18n.svelte";
import en from "../src/locales/en.json";
import fr from "../src/locales/fr.json";

// The component tests read the French the ÉTS instance shows; i18n.test.ts covers the rest.
i18n.use("fr", fr, en);

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});
