import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { system } from "../src/lib/state/system.svelte";

beforeEach(() => {
  vi.useFakeTimers();
  system.clear();
  system.announce("");
});

afterEach(() => {
  system.clear();
  vi.useRealTimers();
});

describe("un flash tout seul", () => {
  it("s'affiche, puis s'efface sans qu'on y touche", () => {
    system.flash("enregistré", 2000);
    expect(system.text).toBe("enregistré");
    vi.advanceTimersByTime(1999);
    expect(system.text, "encore là juste avant l'échéance").toBe("enregistré");
    vi.advanceTimersByTime(2);
    expect(system.text).toBe("");
  });

  it("n'est jamais une panne, même posé par-dessus une", () => {
    system.say("le serveur ne répond pas", true);
    system.flash("enregistré", 2000);
    expect(system.failed).toBe(false);
  });

  it("est annoncé, et le redevient au flash suivant", () => {
    system.flash("enregistré", 2000);
    expect(system.announcement).toBe("enregistré");
    vi.advanceTimersByTime(2001);
    expect(system.announcement).toBe("");
  });
});

describe("le bandeau est EMPRUNTÉ, pas pris", () => {
  it("rend un message persistant qu'il a recouvert", () => {
    system.say("quota atteint, réessaie dans 40 s");
    system.flash("enregistré", 2000);
    expect(system.text).toBe("enregistré");
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("quota atteint, réessaie dans 40 s");
  });

  it("rend aussi son état de PANNE, et pas seulement son texte", () => {
    system.say("le serveur ne répond pas", true);
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("le serveur ne répond pas");
    expect(system.failed, "une panne recouverte reste une panne").toBe(true);
  });

  it("rend un bandeau VIDE quand il en a trouvé un vide", () => {
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("");
    expect(system.failed).toBe(false);
  });
});

describe("deux flashes qui se chevauchent", () => {
  it("restaurent le texte D'ORIGINE, jamais celui du premier flash", () => {
    system.say("quota atteint");
    system.flash("premier", 2000);
    vi.advanceTimersByTime(500);
    system.flash("second", 2000);
    expect(system.text).toBe("second");
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("quota atteint");
  });

  it("ne laissent pas le minuteur du premier couper le second", () => {
    system.flash("premier", 2000);
    vi.advanceTimersByTime(1900);
    system.flash("second", 2000);
    vi.advanceTimersByTime(200);
    expect(system.text, "le minuteur du premier ne doit rien effacer").toBe("second");
  });
});

describe("un vrai message gagne sur un flash", () => {
  it("s'installe tout de suite ET SURVIT au minuteur du flash", () => {
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(200);
    system.say("quota atteint", true);
    expect(system.text).toBe("quota atteint");
    vi.advanceTimersByTime(5000);
    expect(system.text).toBe("quota atteint");
    expect(system.failed).toBe(true);
  });

  it("laisse `clear()` effacer pour de bon", () => {
    system.say("quota atteint");
    system.flash("enregistré", 2000);
    system.clear();
    expect(system.text).toBe("");
    vi.advanceTimersByTime(5000);
    expect(system.text, "rien ne doit ressusciter").toBe("");
  });
});
