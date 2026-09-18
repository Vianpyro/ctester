import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import CodeSurface from "../src/components/CodeSurface.svelte";
import { system } from "../src/lib/state/system.svelte";

let host: HTMLDivElement;
const mounted: ReturnType<typeof mount>[] = [];

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

function typing(value: string, props: Record<string, unknown> = {}) {
  const seen: string[] = [];
  const app = mount(CodeSurface, {
    target: host,
    props: { value, label: "Code", placeholder: "", onInput: (t: string) => seen.push(t), ...props },
  });
  mounted.push(app);
  flushSync();
  const areas = host.querySelectorAll("textarea");
  return { area: areas[areas.length - 1]!, seen };
}

describe("les commandes atteignent l'éditeur", () => {
  it("duplique la ligne, et n'annonce le changement QU'UNE FOIS", () => {
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
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    const event = press(area, "d", { ctrlKey: true, altKey: true });
    expect(area.value).toBe("int a;");
    expect(event.defaultPrevented).toBe(false);
  });

  it("laisse Ctrl+S et Ctrl+Entrée remonter jusqu'à la fenêtre", () => {
    const { area } = typing("int a;");
    for (const key of ["s", "Enter"]) {
      expect(press(area, key, { ctrlKey: true }).defaultPrevented, key).toBe(false);
    }
  });

  it("garde Échap-puis-Tab, l'échappatoire clavier", () => {
    const { area } = typing("int a;");
    area.setSelectionRange(0, 0);
    expect(press(area, "Escape").defaultPrevented).toBe(false);
    expect(press(area, "Tab").defaultPrevented, "Tab doit SORTIR du champ").toBe(false);
    expect(area.value, "et ne rien indenter").toBe("int a;");
  });
});

describe("un document verrouillé", () => {
  it("refuse l'édition EN LE DISANT, et prévient quand même le défaut", () => {
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
    expect(host.querySelector(".goto"), "Ctrl+G doit ouvrir le champ").not.toBeNull();
  });
});

describe("aller à la ligne", () => {
  it("n'est PAS dans le document tant qu'on ne l'a pas demandé", () => {
    const { area } = typing("a\nb\nc");
    expect(host.querySelector(".goto")).toBeNull();
    press(area, "g", { ctrlKey: true });
    expect(host.querySelector(".goto")).not.toBeNull();
  });

  it("sélectionne la ligne demandée et referme", () => {
    const { area } = typing("aa\nbbb\nc");
    press(area, "g", { ctrlKey: true });
    const field = host.querySelector<HTMLInputElement>(".goto input")!;
    field.value = "2";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    flushSync();
    expect(area.selectionStart).toBe(3);
    expect(area.selectionEnd).toBe(6);
    expect(host.querySelector(".goto")).toBeNull();
  });

  it("rend le focus au code sur Échap, et ne bouge pas la sélection", () => {
    const { area } = typing("aa\nbbb\nc");
    area.setSelectionRange(1, 1);
    press(area, "g", { ctrlKey: true });
    const field = host.querySelector<HTMLInputElement>(".goto input")!;
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    flushSync();
    expect(host.querySelector(".goto")).toBeNull();
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
