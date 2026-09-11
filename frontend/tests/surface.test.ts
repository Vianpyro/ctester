// THE SHARED SURFACE IS REALLY SHARED, and this is the check that says so.
//
// The exercise editor and the Console were two copies of the same three elements,
// and the second one silently fell behind: the Tab key, the auto-closing pairs and
// the syntax checker were each written once and reached only one of them. They are
// one component now, so what has to be guarded is the WIRING -- that the checker
// reaches the gutter and the list, and that mounting it twice does not produce two
// elements wearing the same id.
//
// `keyEdit` itself is tested by calling it (`keys.test.ts`), and the checker by
// calling it (`syntax.test.ts`). Nothing here re-tests either.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import CodeSurface from "../src/components/CodeSurface.svelte";
import { system } from "../src/lib/state/system.svelte";

let host: HTMLDivElement;
const mounted: ReturnType<typeof mount>[] = [];

/** Mounts a surface and runs past the checker's 600 ms pause. */
function surface(value: string, idPrefix = "") {
  const app = mount(CodeSurface, {
    target: host,
    props: { value, label: "Code", placeholder: "", idPrefix },
  });
  mounted.push(app);
  flushSync();
  vi.advanceTimersByTime(700);
  flushSync();
  return app;
}

beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
});

afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  host.remove();
  vi.useRealTimers();
});

describe("the surface renders the editor", () => {
  it("numbers the gutter one line at a time", () => {
    surface("int a;\nint b;\nint c;\n");
    expect(host.querySelector("#gutter")?.textContent).toBe("1\n2\n3\n4\n");
  });

  it("puts the coloured layer and the textarea in the same pane", () => {
    surface("int x;\n");
    const pane = host.querySelector(".pane");
    expect(pane?.querySelector("pre.hl")).toBeTruthy();
    expect(pane?.querySelector("textarea.codein")).toBeTruthy();
  });
});

describe("the checker reaches the screen", () => {
  it("says nothing about correct code", () => {
    surface("int main(void) {\n    return 0;\n}\n");
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(true);
    expect(host.querySelector(".gutter .error")).toBeNull();
  });

  it("flags the gutter line AND lists the fault", () => {
    surface("int main(void) {\n    return 0;\n");
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(false);
    // The unclosed brace is on line 1, and it is certain, so the number is red.
    const flagged = host.querySelectorAll(".gutter .error");
    expect(flagged).toHaveLength(1);
    expect(flagged[0]!.textContent).toBe("1");
    expect(host.querySelector(".diag")?.textContent).toContain("ligne 1");
  });

  it("tells a hint from a certain fault, because they are not equally sure", () => {
    surface("int main(void) {\n    if (x = 3) return 1;\n    return 0;\n}\n");
    expect(host.querySelector(".diag.hint")).toBeTruthy();
    expect(host.querySelector(".diag.error")).toBeNull();
  });

  it("SAYS NOTHING BEFORE THE PAUSE -- it must not scold while one types", () => {
    mounted.push(
      mount(CodeSurface, {
        target: host,
        props: { value: "int main(void) {\n", label: "Code", placeholder: "" },
      }),
    );
    flushSync();
    vi.advanceTimersByTime(300);
    flushSync();
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(true);
  });
});

describe("two editors, one document", () => {
  it("KEEPS THE IDS APART -- `#travail` is hidden, not unmounted", () => {
    surface("int x;\n");
    surface("int y;\n", "scratch");
    for (const id of ["edwrap", "gutter", "pane", "hl", "hlcode", "code"]) {
      expect(host.querySelectorAll("#" + id)).toHaveLength(1);
      expect(host.querySelectorAll("#scratch" + id)).toHaveLength(1);
    }
  });

  it("gives each its own underline layer, so the class is not an id", () => {
    surface("int main(void) {\n", "");
    surface("int main(void) {\n", "scratch");
    expect(host.querySelectorAll(".squiggles")).toHaveLength(2);
  });
});

// --- LES RACCOURCIS D'UN IDE -----------------------------------------------
//
// `commandEdit` est éprouvée en l'appelant (`keys.test.ts`) et la table en
// l'appelant aussi (`shortcuts.test.ts`). Ce qui se vérifie ICI est le CÂBLAGE :
// que la frappe atteigne bien la commande, qu'elle passe par le `apply()` qui
// garde la pile d'annulation et le diff CRDT, et que ce qui n'est pas à nous
// reparte intact vers le navigateur.
//
// ⚠ jsdom N'A PAS `execCommand`, donc tout ce qui suit éprouve le CHEMIN DE
// REPLI de `apply()` (l'écriture directe). Le vrai `insertText` ne se vérifie
// que dans un navigateur -- c'est écrit dans le plan, et c'est pour ça que la
// passe manuelle n'est pas décorative.

/** Une frappe sur le textarea, et ce que le navigateur en retiendrait. */
function press(
  area: HTMLTextAreaElement,
  key: string,
  mods: Partial<Record<"ctrlKey" | "shiftKey" | "altKey" | "metaKey", boolean>> = {},
) {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...mods });
  area.dispatchEvent(event);
  flushSync();
  return event;
}

/** Une surface montée avec un rappel `onInput` qu'on peut compter. */
function typing(value: string, props: Record<string, unknown> = {}) {
  const seen: string[] = [];
  const app = mount(CodeSurface, {
    target: host,
    props: { value, label: "Code", placeholder: "", onInput: (t: string) => seen.push(t), ...props },
  });
  mounted.push(app);
  flushSync();
  // LE DERNIER, pas le premier : plusieurs surfaces partagent l'hôte dans un
  // même cas, et `querySelector` rendrait celle d'avant.
  const areas = host.querySelectorAll("textarea");
  return { area: areas[areas.length - 1]!, seen };
}

describe("les commandes atteignent l'éditeur", () => {
  it("duplique la ligne, et n'annonce le changement QU'UNE FOIS", () => {
    // L'appel unique EST le contrat CRDT : `applyLocal()` dérive un seul delete
    // et un seul insert. Deux appels feraient deux transactions Yjs par frappe
    // et replieraient les curseurs des coéquipiers à chaque geste.
    const { area, seen } = typing("int a;");
    area.setSelectionRange(6, 6);
    press(area, "d", { ctrlKey: true });
    expect(area.value).toBe("int a;\nint a;");
    expect(seen).toHaveLength(1);
  });

  it("commente la ligne", () => {
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    press(area, "/", { ctrlKey: true });
    expect(area.value).toBe("// int a;");
  });

  it("commente aussi quand Maj est tenu -- le clavier canadien-français", () => {
    // `/` s'y tape `Maj+3`, donc il ARRIVE avec Maj. Sans ce cas, la moitié de
    // la cohorte n'aurait jamais pu commenter une ligne.
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    press(area, "/", { ctrlKey: true, shiftKey: true });
    expect(area.value).toBe("// int a;");
  });

  it("supprime la ligne par ses DEUX chords", () => {
    const first = typing("a\nb");
    first.area.setSelectionRange(0, 0);
    press(first.area, "k", { ctrlKey: true, shiftKey: true });
    expect(first.area.value).toBe("b");

    const second = typing("a\nb");
    second.area.setSelectionRange(0, 0);
    press(second.area, "D", { ctrlKey: true, shiftKey: true });
    expect(second.area.value, "Ctrl+Maj+D, pour Firefox").toBe("b");
  });

  it("prévient le défaut MÊME quand la commande ne fait rien", () => {
    // Alt+Maj+↑ sur la première ligne : sans `preventDefault`, le navigateur
    // étendrait la sélection par-dessus le bloc qu'on essaie de déplacer.
    const { area } = typing("a\nb");
    area.setSelectionRange(0, 0);
    const event = press(area, "ArrowUp", { altKey: true, shiftKey: true });
    expect(area.value).toBe("a\nb");
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("SILENCE : ce qui n'est pas à nous repart intact", () => {
  it("ne touche pas à Ctrl+Z, et ne le prévient pas", () => {
    const { area, seen } = typing("int a;");
    area.setSelectionRange(0, 0);
    const event = press(area, "z", { ctrlKey: true });
    expect(area.value).toBe("int a;");
    expect(seen).toHaveLength(0);
    expect(event.defaultPrevented, "Ctrl+Z doit rester au navigateur").toBe(false);
  });

  it("ne prend pas une frappe AltGr pour un raccourci", () => {
    // Sous Windows AltGr se rapporte `ctrlKey && altKey`.
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    const event = press(area, "d", { ctrlKey: true, altKey: true });
    expect(area.value).toBe("int a;");
    expect(event.defaultPrevented).toBe(false);
  });

  it("laisse Ctrl+S et Ctrl+Entrée remonter jusqu'à la fenêtre", () => {
    // Si la surface les réclamait, ils seraient morts là où le curseur est.
    const { area } = typing("int a;");
    for (const key of ["s", "Enter"]) {
      expect(press(area, key, { ctrlKey: true }).defaultPrevented, key).toBe(false);
    }
  });

  it("garde Échap-puis-Tab, l'échappatoire clavier", () => {
    // La non-régression qui compte : Échap ne doit rien prévenir ici, sinon
    // `App.svelte` et ce drapeau se marcheraient dessus.
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    expect(press(area, "Escape").defaultPrevented).toBe(false);
    expect(press(area, "Tab").defaultPrevented, "Tab doit SORTIR du champ").toBe(false);
    expect(area.value, "et ne rien indenter").toBe("int a;");
  });
});

describe("un document verrouillé", () => {
  it("refuse l'édition EN LE DISANT, et prévient quand même le défaut", () => {
    // Prévenir compte : un Ctrl+D non prévenu ouvrirait la boîte de favoris de
    // Chrome. Et un refus muet se lit comme une page cassée.
    const { area, seen } = typing("int a;", { readOnly: true });
    area.setSelectionRange(0, 0);
    const event = press(area, "d", { ctrlKey: true });
    expect(area.value).toBe("int a;");
    expect(seen).toHaveLength(0);
    expect(event.defaultPrevented).toBe(true);
    expect(system.text).toContain("lecture seule");
    system.clear();
  });

  it("laisse la NAVIGATION marcher : on peut lire ce qu'on ne peut pas écrire", () => {
    const { area } = typing("int a;", { readOnly: true });
    press(area, "g", { ctrlKey: true });
    expect(host.querySelector(".aller"), "Ctrl+G doit ouvrir le champ").not.toBeNull();
  });
});

describe("aller à la ligne", () => {
  it("n'est PAS dans le document tant qu'on ne l'a pas demandé", () => {
    const { area } = typing("a\nb\nc");
    expect(host.querySelector(".aller")).toBeNull();
    press(area, "g", { ctrlKey: true });
    expect(host.querySelector(".aller")).not.toBeNull();
  });

  it("sélectionne la ligne demandée et referme", () => {
    const { area } = typing("aa\nbbb\nc");
    press(area, "g", { ctrlKey: true });
    const field = host.querySelector<HTMLInputElement>(".aller input")!;
    field.value = "2";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    flushSync();
    expect(area.selectionStart).toBe(3);
    expect(area.selectionEnd).toBe(6);
    expect(host.querySelector(".aller")).toBeNull();
  });

  it("rend le focus au code sur Échap, et ne bouge pas la sélection", () => {
    const { area } = typing("aa\nbbb\nc");
    area.setSelectionRange(1, 1);
    press(area, "g", { ctrlKey: true });
    const field = host.querySelector<HTMLInputElement>(".aller input")!;
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    flushSync();
    expect(host.querySelector(".aller")).toBeNull();
    expect(document.activeElement).toBe(area);
    expect(area.selectionStart).toBe(1);
  });
});

describe("la faute suivante (F2)", () => {
  it("pose le curseur sur une faute", () => {
    const { area } = typing("int a = 1\nint b = 2;\n");
    vi.advanceTimersByTime(700);
    flushSync();
    area.setSelectionRange(0, 0);
    const event = press(area, "F2");
    expect(event.defaultPrevented).toBe(true);
    expect(area.selectionEnd, "la sélection doit avoir bougé").toBeGreaterThan(0);
  });

  it("SILENCE quand le code est juste : la sélection ne bouge pas", () => {
    const { area } = typing("int a = 1;\n");
    vi.advanceTimersByTime(700);
    flushSync();
    area.setSelectionRange(3, 3);
    press(area, "F2");
    expect(area.selectionStart).toBe(3);
    expect(area.selectionEnd).toBe(3);
  });
});

describe("les deux surfaces à la fois", () => {
  it("pilote la Console sans toucher à l'exercice", () => {
    // C'est la propriété pour laquelle ce fichier existe : une fonctionnalité
    // ajoutée ici apparaît dans les deux, ou dans aucune.
    const exercise = typing("int a;");
    const console_ = mount(CodeSurface, {
      target: host,
      props: { value: "int b;", label: "Console", placeholder: "", idPrefix: "scratch" },
    });
    mounted.push(console_);
    flushSync();
    const area = host.querySelector<HTMLTextAreaElement>("#scratchcode")!;
    area.setSelectionRange(0, 0);
    press(area, "d", { ctrlKey: true });
    expect(area.value).toBe("int b;\nint b;");
    expect(exercise.area.value, "l'exercice ne doit pas bouger").toBe("int a;");
  });
});
