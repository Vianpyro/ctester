import { describe, expect, it } from "vitest";
import {
  exportableExercises,
  fold,
  gridLabel,
  isGroupExportable,
  lockNote,
  matchesFilter,
  normalize,
  stripLabel,
  stripNeighbors,
  tileState,
  type Exercise,
} from "../src/lib/domain/catalog";
import type { PublishedRelease } from "../src/lib/api/types";

const SCHEDULED = "2026-11-18T08:00:00-05:00";

const release: PublishedRelease = {
  collections: [
    { id: "tp2", title: "TP 2", items: ["tp2-ex0", "tp2-ex1", "tp2-verif"], access: "available" },
    {
      id: "tp10",
      title: "TP 10",
      items: ["tp10-ex1"],
      access: "scheduled",
      release: { available_from: SCHEDULED },
    },
    { id: "revision", title: "Révision", items: ["tp2-ex1"], access: "available" },
    { id: "vide", title: "Vide", items: ["absent"], access: "available" },
  ],
  exercises: [
    { id: "tp2-ex0", title: "ex.0 préambule", mode: "io", skills: ["printf"], access: "available" },
    {
      id: "tp2-ex1",
      title: "ex.1 bonus vitesse",
      mode: "io",
      files: [{ name: "submission.c" }],
      access: "available",
    },
    { id: "tp2-verif", title: "vérif", mode: "quiz", verification: true, access: "available" },
    {
      id: "tp10-ex1",
      title: "ex.1 matrices",
      mode: "unity",
      access: "scheduled",
      release: { available_from: SCHEDULED },
    },
    { id: "orphelin", title: "ex.9 seul", mode: "io", access: "available" },
  ],
  assignments: [{ id: "devoir", title: "Analyseur", team: { min: 3, max: 4 } }],
};

const model = normalize(release);
const byId = (id: string): Exercise => model.catalog.find((e) => e.id === id)!;

describe("normalize", () => {
  it("keeps every exercise in the menu tree and only the open ones in the flat list", () => {
    expect(model.collections.map((c) => c.title)).toEqual([
      "TP 2",
      "TP 10",
      "Révision",
      "Autres",
    ]);
    expect(model.collections[1]!.items.map((e) => e.id)).toEqual(["tp10-ex1"]);
    expect(model.catalog.map((e) => e.id)).not.toContain("tp10-ex1");
  });

  it("hands the instructor the locked ones too, and only when told to", () => {
    const staff = normalize(release, true);
    expect(staff.catalog.map((e) => e.id)).toContain("tp10-ex1");
    expect(staff.collections.map((c) => c.title)).toEqual(model.collections.map((c) => c.title));
    expect(lockNote(staff.catalog.find((e) => e.id === "tp10-ex1")!)).toMatch(/^ouvre le /);
  });

  it("drops a collection whose items were never published rather than showing an empty one", () => {
    expect(model.collections.map((c) => c.title)).not.toContain("Vide");
  });

  it("puts an exercise with no collection into Autres instead of losing it", () => {
    expect(model.collections[3]!.items.map((e) => e.id)).toEqual(["orphelin"]);
    expect(model.catalog.map((e) => e.id)).toContain("orphelin");
  });

  it("shows a shared exercise twice in the menu but counts it once", () => {
    const inMenu = model.collections.flatMap((c) => c.items).filter((e) => e.id === "tp2-ex1");
    expect(inMenu).toHaveLength(2);
    expect(model.catalog.filter((e) => e.id === "tp2-ex1")).toHaveLength(1);
  });

  // Ten labs have an ex.1.
  it("qualifies `label` and leaves `short` bare", () => {
    expect(byId("tp2-ex1").short).toBe("ex.1 bonus vitesse");
    expect(byId("tp2-ex1").label).toBe("TP2 : ex.1 bonus vitesse");
  });

  it("carries only file names: a server path never crosses the publication", () => {
    expect(byId("tp2-ex1").files).toEqual([{ name: "submission.c" }]);
  });

  it("keeps assignments in their own list, not folded into collections", () => {
    expect(model.assignments.map((a) => a.id)).toEqual(["devoir"]);
    expect(model.collections.map((c) => c.title)).not.toContain("Analyseur");
  });
});

describe("lockNote", () => {
  it("says a date and not only that it is closed", () => {
    const note = lockNote({ access: "scheduled", available_from: SCHEDULED });
    expect(note).toMatch(/^ouvre le /);
    expect(note).toMatch(/18/);
    expect(note).toBe("ouvre le 18 novembre");
  });

  it("falls back to a word rather than an Invalid Date", () => {
    expect(lockNote({ access: "scheduled", available_from: "pas une date" })).toBe("à venir");
    expect(lockNote({ access: "archived" })).toBe("archivé");
  });

  it("says nothing at all for an open entry", () => {
    expect(lockNote({ access: "available" })).toBe("");
    expect(lockNote(null)).toBe("");
  });
});

describe("tileState", () => {
  it("keeps progress and location as separate axes", () => {
    expect(tileState(byId("tp2-ex1"), false, { "tp2-ex1": "solved" })).toEqual({
      cls: "solved",
      word: "réussi",
    });
  });

  it("lets locked beat everything: there is nothing to report about an unopenable one", () => {
    expect(tileState(byId("tp2-ex1"), true, { "tp2-ex1": "solved" }).word).toBe(
      "pas encore ouvert",
    );
  });

  it("marks a verification so it is recognizable before being opened", () => {
    expect(tileState(byId("tp2-verif"), false, {}).cls).toBe("verification");
  });
});

describe("labels", () => {
  it("shortens a strip tile to ex.N, keeping the number the statement uses", () => {
    expect(stripLabel(byId("tp2-ex1"))).toBe("ex.1");
    expect(stripLabel(byId("tp2-ex0"))).toBe("ex.0");
  });

  it("keeps the ellipsis, because a flat cut reads as a display bug", () => {
    const long = { ...byId("tp2-ex1"), short: "convertir_en_radians_et_afficher" };
    expect(stripLabel(long)).toMatch(/…$/);
  });

  it("labels a grid tile with the bare number, and a verification with its word", () => {
    expect(gridLabel(byId("tp2-ex1"))).toBe("1");
    expect(gridLabel(byId("tp2-verif"))).toBe("vérif");
  });

  it("takes a bonus from the catalog's flag, and never from a word in a title", () => {
    expect(byId("tp2-ex1").bonus).toBe(false);
    const flagged = normalize({
      collections: [{ id: "tp2", title: "TP 2", items: ["bonus-1"], access: "available" }],
      exercises: [
        {
          id: "bonus-1",
          title: "Puissance d'un treuil",
          mode: "io",
          bonus: true,
          access: "available",
        },
      ],
    } as PublishedRelease);
    expect(flagged.catalog[0]!.bonus).toBe(true);
  });
});

describe("the menu filter", () => {
  it("is accent-insensitive, or the student concludes the search is broken", () => {
    expect(fold("réussi")).toBe(fold("reussi"));
  });

  it("matches the title, the id or the collection", () => {
    const ex = byId("tp2-ex1");
    expect(matchesFilter(ex, "TP 2", fold("vitesse"))).toBe(true);
    expect(matchesFilter(ex, "TP 2", fold("tp2"))).toBe(true);
    expect(matchesFilter(ex, "TP 2", fold("matrices"))).toBe(false);
  });

  it("matches everything when empty", () => {
    expect(matchesFilter(byId("tp2-ex1"), "TP 2", "")).toBe(true);
  });
});

describe("stripNeighbors", () => {
  it("keeps locked exercises and deduplicates a shared one", () => {
    const rows = stripNeighbors(model.collections, "TP 2");
    expect(rows.map((e) => e.id)).toEqual(["tp2-ex0", "tp2-ex1", "tp2-verif"]);
    expect(stripNeighbors(model.collections, "TP 10").map((e) => e.id)).toEqual(["tp10-ex1"]);
  });
});

describe("what the one-piece main.c may bundle", () => {
  const catalog: Exercise[] = [
    { ...byId("tp2-ex0") },
    { ...byId("tp2-ex1") },
    { ...byId("tp2-verif"), group: "TP 2" },
    { ...byId("tp2-ex1"), id: "devoir-a", group: "TP 2", assignment: "devoir" },
    { ...byId("tp2-ex1"), id: "tp2-mod", group: "TP 2", mode: "unity" },
    { ...byId("tp2-ex1"), id: "tp2-bonus", group: "TP 2", bonus: true },
  ];

  it("takes io exercises only, and neither a verification, a bonus nor an assignment's", () => {
    expect(exportableExercises(catalog, "TP 2").map((e) => e.id)).toEqual([
      "tp2-ex0",
      "tp2-ex1",
    ]);
  });

  it("needs two: a file bundling one bundles nothing the student cannot already see", () => {
    expect(isGroupExportable(catalog, "TP 2")).toBe(true);
    expect(isGroupExportable([catalog[0]!], "TP 2")).toBe(false);
    expect(isGroupExportable([catalog[0]!, catalog[catalog.length - 1]!], "TP 2")).toBe(false);
    expect(isGroupExportable(catalog, "TP 10")).toBe(false);
  });
});
