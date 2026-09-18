import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(import.meta.dirname, "..", "src", "app.css"), "utf8");

function body(selector: string): string {
  const start = CSS.indexOf(selector + " {");
  expect(start, "règle introuvable dans app.css : " + selector).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start);
  const close = CSS.indexOf("}", open);
  expect(close, "règle non fermée : " + selector).toBeGreaterThan(open);
  return CSS.slice(open + 1, close);
}

function prop(ruleBody: string, name: string): string {
  const match = new RegExp("(?:^|;)\\s*" + name + "\\s*:\\s*([^;]+)").exec(ruleBody);
  expect(match, "propriété « " + name + " » absente de la règle").not.toBeNull();
  return match![1]!.trim().replace(/\s+/g, " ");
}

describe("le contrat métrique de l'éditeur", () => {
  const gutter = body(".gutter");
  const overlay = body(".hl, .codein");

  it("donne à la gouttière et à la superposition LE MÊME raccourci `font`", () => {
    expect(prop(gutter, "font")).toBe(prop(overlay, "font"));
  });

  it("garde ce `font` en RACCOURCI, avec sa fente line-height et sa pile littérale", () => {
    const expected = /^400 \d+(?:\.\d+)?px\/1\.5 ui-monospace, SFMono-Regular, Consolas, monospace$/;
    expect(prop(overlay, "font")).toMatch(expected);
    expect(prop(gutter, "font")).toMatch(expected);
  });

  it("garde les deux couches superposables : même padding, même bordure, même boîte", () => {
    expect(prop(overlay, "padding")).toBe(".5rem .7rem");
    expect(prop(overlay, "border")).toBe("1px solid transparent");
    expect(prop(overlay, "box-sizing")).toBe("border-box");
    expect(prop(overlay, "margin")).toBe("0");
    expect(prop(overlay, "white-space")).toBe("pre");
    expect(prop(overlay, "tab-size")).toBe("4");
  });

  it("aligne la gouttière VERTICALEMENT sur elles, sans exiger la même gouttière latérale", () => {
    const vertical = (p: string) => p.split(" ")[0];
    expect(vertical(prop(gutter, "padding"))).toBe(vertical(prop(overlay, "padding")));
    expect(prop(gutter, "margin")).toBe("0");
    expect(prop(gutter, "white-space")).toBe("pre");
    expect(prop(gutter, "border")).toBe("1px solid transparent");
  });
});
