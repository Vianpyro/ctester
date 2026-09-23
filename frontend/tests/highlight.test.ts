import { describe, expect, it } from "vitest";
import { escapeHtml, highlight } from "../src/lib/domain/highlight";

describe("escaping", () => {
  it("escapes the three characters that could open a tag or an entity", () => {
    expect(escapeHtml("<a & b>")).toBe("&lt;a &amp; b&gt;");
  });

  it("escapes a student's markup in code, strings and comments", () => {
    for (const source of [
      "<script>alert(1)</script>",
      'printf("<script>alert(1)</script>");',
      "// <script>alert(1)</script>",
      "/* <img src=x onerror=alert(1)> */",
      "#define X <script>",
      "int main(void){} <svg onload=alert(1)>",
    ]) {
      const out = highlight(source);
      expect(out, source).not.toMatch(/<script/i);
      expect(out, source).not.toMatch(/<img/i);
      expect(out, source).not.toMatch(/<svg/i);
      for (const tag of out.match(/<[a-z/][^>]*>/gi) ?? []) {
        expect(tag, source).toMatch(/^<(span class="t[a-z]"|\/span)>$/);
      }
    }
  });

  it("loses not one character of the source", () => {
    const source = 'int x = 1; /* é */\nprintf("a<b&c>d");';
    const host = document.createElement("div");
    host.innerHTML = highlight(source);
    expect(host.textContent).toBe(source + "\n");
  });
});

describe("the grammar", () => {
  const classes = (source: string) =>
    Array.from(highlight(source).matchAll(/class="(t[a-z])"/g)).map((m) => m[1]);

  it("colours a keyword, a number, a call and an upper-case macro", () => {
    expect(classes("int x = 42;")).toContain("tk");
    expect(classes("int x = 42;")).toContain("tn");
    expect(classes("printf(\"a\");")).toContain("tf");
    expect(classes("#define MAX_SIZE 10\nint x = MAX_SIZE;")).toContain("tu");
  });

  it("does not mistake the `//` of a URL for a comment", () => {
    const out = highlight('printf("https://exemple.test/a");');
    expect(out).toContain('<span class="ts">"https://exemple.test/a"</span>');
    expect(out).not.toContain('class="tc"');
  });

  it("leaves a double quote alone, and that is correct rather than an oversight", () => {
    expect(escapeHtml('say "hi"')).toBe('say "hi"');
  });

  it("keeps a quote inside a character literal from opening a string", () => {
    const out = highlight("char q = '\"'; int after = 1;");
    expect(classes("char q = '\"'; int after = 1;")).toContain("tk");
    expect(out).toContain("after");
  });

  it("survives a French apostrophe in a comment", () => {
    const out = highlight("// on n'affiche rien\nint x = 1;");
    expect(classes("// on n'affiche rien\nint x = 1;")).toContain("tk");
    expect(out).toContain("x = ");
  });

  it("handles an unterminated string without swallowing the file", () => {
    expect(() => highlight('printf("pas fermé')).not.toThrow();
  });

  it("colours a preprocessor line only at the start of a line", () => {
    expect(classes("#include <stdio.h>")).toContain("tp");
    expect(classes("int x = a # b;")).not.toContain("tp");
  });
});
