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

describe("a flash on its own", () => {
  it("shows, then clears without being touched", () => {
    system.flash("enregistré", 2000);
    expect(system.text).toBe("enregistré");
    vi.advanceTimersByTime(1999);
    expect(system.text, "encore là juste avant l'échéance").toBe("enregistré");
    vi.advanceTimersByTime(2);
    expect(system.text).toBe("");
  });

  it("is never an outage, even when laid over one", () => {
    system.say("le serveur ne répond pas", true);
    system.flash("enregistré", 2000);
    expect(system.failed).toBe(false);
  });

  it("is announced, and announced again on the next flash", () => {
    system.flash("enregistré", 2000);
    expect(system.announcement).toBe("enregistré");
    vi.advanceTimersByTime(2001);
    expect(system.announcement).toBe("");
  });
});

describe("the banner is borrowed, not taken", () => {
  it("restores a persistent message it covered", () => {
    system.say("quota atteint, réessaie dans 40 s");
    system.flash("enregistré", 2000);
    expect(system.text).toBe("enregistré");
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("quota atteint, réessaie dans 40 s");
  });

  it("also restores its outage state, not only its text", () => {
    system.say("le serveur ne répond pas", true);
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("le serveur ne répond pas");
    expect(system.failed, "a covered outage is still an outage").toBe(true);
  });

  it("restores an empty banner when it found an empty one", () => {
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("");
    expect(system.failed).toBe(false);
  });
});

describe("two overlapping flashes", () => {
  it("restore the original text, never the first flash's", () => {
    system.say("quota atteint");
    system.flash("premier", 2000);
    vi.advanceTimersByTime(500);
    system.flash("second", 2000);
    expect(system.text).toBe("second");
    vi.advanceTimersByTime(2001);
    expect(system.text).toBe("quota atteint");
  });

  it("do not let the first one's timer cut the second", () => {
    system.flash("premier", 2000);
    vi.advanceTimersByTime(1900);
    system.flash("second", 2000);
    vi.advanceTimersByTime(200);
    expect(system.text, "the first one's timer must erase nothing").toBe("second");
  });
});

describe("a real message wins over a flash", () => {
  it("takes over at once and survives the flash's timer", () => {
    system.flash("enregistré", 2000);
    vi.advanceTimersByTime(200);
    system.say("quota atteint", true);
    expect(system.text).toBe("quota atteint");
    vi.advanceTimersByTime(5000);
    expect(system.text).toBe("quota atteint");
    expect(system.failed).toBe(true);
  });

  it("lets `clear()` erase for good", () => {
    system.say("quota atteint");
    system.flash("enregistré", 2000);
    system.clear();
    expect(system.text).toBe("");
    vi.advanceTimersByTime(5000);
    expect(system.text, "nothing may come back").toBe("");
  });
});
