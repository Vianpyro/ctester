import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(import.meta.dirname, "..", "src", "app.css"), "utf8");

function body(selector: string): string {
  const pattern = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/,\s*/g, ",\\s*");
  const start = CSS.search(new RegExp("(?:^|\\n)" + pattern + "\\s*\\{"));
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

describe("the editor's metric contract", () => {
  const gutter = body(".gutter");
  const overlay = body(".hl, .codein");

  it("gives the gutter and the overlay THE SAME `font` shorthand", () => {
    expect(prop(gutter, "font")).toBe(prop(overlay, "font"));
  });

  it("keeps that `font` as a SHORTHAND, with its line-height slot and its literal stack", () => {
    const expected = /^400 \d+(?:\.\d+)?px\/1\.5 ui-monospace, SFMono-Regular, Consolas, monospace$/;
    expect(prop(overlay, "font")).toMatch(expected);
    expect(prop(gutter, "font")).toMatch(expected);
  });

  it("keeps both layers stackable: same padding, same border, same box", () => {
    expect(prop(overlay, "padding")).toBe(".5rem .7rem");
    expect(prop(overlay, "border")).toBe("1px solid transparent");
    expect(prop(overlay, "box-sizing")).toBe("border-box");
    expect(prop(overlay, "margin")).toBe("0");
    expect(prop(overlay, "white-space")).toBe("pre");
    expect(prop(overlay, "tab-size")).toBe("4");
  });

  it("aligns the gutter VERTICALLY with them, without requiring the same side gutter", () => {
    const vertical = (p: string) => p.split(" ")[0];
    expect(vertical(prop(gutter, "padding"))).toBe(vertical(prop(overlay, "padding")));
    expect(prop(gutter, "margin")).toBe("0");
    expect(prop(gutter, "white-space")).toBe("pre");
    expect(prop(gutter, "border")).toBe("1px solid transparent");
  });
});
