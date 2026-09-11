// THE STATEMENT'S FORMULAS. Assertions are on the DOM and not on the string, for the
// same reason as `statement.test.ts` and `markdown.test.ts`: `&amp;` as escaped TEXT
// is the right outcome for a bitwise AND, and a substring search would call it a
// failure. The SHAPE of the tree is also the only honest way to test precedence --
// a string comparison would pass on markup that draws the wrong thing.
//
// HALF THE CASES KEEP A SILENCE. `renderMath` returns `null` for anything its
// grammar does not know, and the caller then falls back to a code span -- which is
// exactly what the statement showed before this module existed. Every construct that
// renders therefore has a twin that must NOT.

import { describe, expect, it } from "vitest";
import { renderMath } from "../src/lib/domain/math";

/** The output, parsed the way the browser will parse it. */
function parsed(source: string): HTMLElement {
  const html = renderMath(source);
  expect(html, `renderMath(${JSON.stringify(source)}) returned null`).not.toBeNull();
  const host = document.createElement("div");
  host.innerHTML = html!;
  return host;
}

/** The tag names of one element's children, which is what "precedence" means here. */
const shape = (el: Element | null) => Array.from(el?.children ?? []).map((c) => c.tagName.toLowerCase());

describe("the six formulas the course actually writes", () => {
  it("tp2-ex3 -- `I = V / R` is a fraction, not a slash", () => {
    const host = parsed("I = V / R");
    const frac = host.querySelector("mfrac");
    expect(frac).not.toBeNull();
    expect(frac!.children[0]!.textContent).toBe("V");
    expect(frac!.children[1]!.textContent).toBe("R");
  });

  it("tp2-ex4 -- `A = pi * r^2` is a superscript and a Greek pi", () => {
    const host = parsed("A = pi * r^2");
    expect(host.querySelector("msup")?.textContent).toBe("r2");
    expect(host.textContent).toContain("π");
    expect(host.textContent).not.toContain("pi");
  });

  it("asks for DISPLAY STYLE, without which a fraction is drawn at script size", () => {
    // NOT COSMETIC. `<mfrac>` shrinks both halves unless the root is in display
    // style: at 1.1em that put `2·m·g` at ~10.5px and the `2` of `r²` at ~7.5px, and
    // the radical of `tp2-ex5` could no longer be scoped by eye. The attribute rides
    // in the markup so it also holds where the stylesheet does not reach.
    const root = parsed("V = racine(a / b)").querySelector("math");
    expect(root?.getAttribute("displaystyle")).toBe("true");
  });

  it("tp2-ex5 -- a radical OVER a fraction, and the redundant parentheses DROP", () => {
    // THE CASE THIS MODULE EXISTS FOR. `racine( 2*m*g / (0,5 * rho * pi * r^2 ))`:
    // the outer parens belong to the call, the inner ones to the denominator -- and
    // `mfrac` groups already, so neither pair may survive as an <mo>.
    const host = parsed("V = racine( 2*m*g / (0,5 * rho * pi * r^2 ))");
    const sqrt = host.querySelector("msqrt");
    expect(sqrt).not.toBeNull();
    // THE RADICAL COVERS THE WHOLE FRACTION, not just the numerator -- the question
    // the rendering has to answer at a glance. Both halves live INSIDE the `msqrt`,
    // and nothing of the expression lives outside it but `V =`.
    const frac = sqrt!.querySelector("mfrac");
    expect(frac).not.toBeNull();
    expect(frac!.children[0]!.textContent).toBe("2⋅m⋅g");
    expect(frac!.children[1]!.textContent).toBe("0,5⋅ρ⋅π⋅r2");
    expect(sqrt!.textContent).not.toContain("(");
    expect(sqrt!.textContent).not.toContain(")");
    // `0,5` is ONE number: the decimal comma is French.
    expect(Array.from(host.querySelectorAll("mn")).map((n) => n.textContent)).toContain("0,5");
  });

  it("tp2-ex8 and tp3-ex3 -- `R = V * L / v` puts V·L over v", () => {
    const frac = parsed("R = V * L / v").querySelector("mfrac");
    expect(frac!.children[0]!.textContent).toBe("V⋅L");
    expect(frac!.children[1]!.textContent).toBe("v");
  });

  it("bonus-1 -- `P = F * v` has no fraction at all", () => {
    const host = parsed("P = F * v");
    expect(host.querySelector("mfrac")).toBeNull();
    expect(host.textContent).toBe("P=F⋅v");
  });
});

describe("precedence is C's, and the SHAPE of the tree is what says so", () => {
  it("puts only the neighbouring term over the bar: `a + b / c`", () => {
    // The twin of the case above -- if `/` bound loosest, `a + b` would be the
    // numerator and the formula would say something else entirely.
    const frac = parsed("a + b / c").querySelector("mfrac");
    expect(frac!.children[0]!.textContent).toBe("b");
    expect(frac!.parentElement?.tagName.toLowerCase()).toBe("math");
  });

  it("binds `&` tighter than `|`", () => {
    // `a | b & c` is `a | (b & c)`, so the AND is NOT the top-level operator.
    const host = parsed("a | b & c");
    expect(host.querySelector("math")!.textContent).toBe("a|b&c");
    const ops = Array.from(host.querySelectorAll("mo")).map((o) => o.textContent);
    expect(ops).toEqual(["|", "&"]);
  });

  it("binds `+` tighter than `<<`, which is C and surprises people", () => {
    expect(parsed("a << 2 + 1").querySelector("math")!.textContent).toBe("a<<2+1");
  });

  it("makes the exponent right-associative", () => {
    const outer = parsed("a^b^c").querySelector("msup")!;
    expect(shape(outer)).toEqual(["mrow", "mrow"]);
    expect(outer.children[1]!.querySelector("msup")).not.toBeNull();
  });
});

describe("the lexer reads the LONGEST operator first", () => {
  // Reading `a << 2` as two comparisons produces a PLAUSIBLE formula, which is worse
  // than one that fails. Each pair here is a twin: the long form and the short one.
  const pairs: [string, string][] = [
    ["a << 2", "a<<2"],
    ["a < 2", "a<2"],
    ["a <= 2", "a<=2"],
    ["a >> 2", "a>>2"],
    ["a >= 2", "a>=2"],
    ["a && b", "a&&b"],
    ["a & b", "a&b"],
    ["a || b", "a||b"],
    ["a | b", "a|b"],
    ["a == b", "a==b"],
    ["a = b", "a=b"],
    ["a != b", "a!=b"],
  ];
  for (const [source, text] of pairs) {
    it(`reads \`${source}\` as one operator`, () => {
      const host = parsed(source);
      expect(host.querySelector("math")!.textContent).toBe(text);
      expect(host.querySelectorAll("mo")).toHaveLength(1);
    });
  }
});

describe("escaping, which the bitwise operators stop making theoretical", () => {
  it("escapes `&`, `<` and `>` instead of breaking the document", () => {
    // These three are exactly the characters an escape misses. The assertion is on
    // the DOM: three operators, and not one stray element.
    const host = parsed("a & b << 2 > c");
    expect(Array.from(host.querySelectorAll("mo")).map((o) => o.textContent)).toEqual([
      "&",
      "<<",
      ">",
    ]);
    expect(host.querySelectorAll("math > *")).toHaveLength(7);
  });

  it("cannot be made to emit a tag from a name", () => {
    // `script` is not in the closed call list, so this fails the parse outright.
    expect(renderMath("script(x)")).toBeNull();
  });
});

describe("`^` is the exponent and exclusive-or is spelled `xor`", () => {
  // THE ONE AMBIGUITY THIS NOTATION CARRIES, and both halves are asserted so that
  // neither can be "fixed" without the other going red.
  it("reads `a ^ 2` as a superscript, because the content writes `pi * r^2`", () => {
    expect(parsed("a ^ 2").querySelector("msup")).not.toBeNull();
  });

  it("reads `a xor b` as an operator, and never as an identifier", () => {
    const host = parsed("a xor b");
    expect(host.querySelector("msup")).toBeNull();
    expect(host.querySelector("mo")?.textContent).toBe("xor");
    expect(renderMath("xor")).toBeNull();
    expect(renderMath("a xor")).toBeNull();
  });

  it("reads `|` as bitwise OR, absolute value being `abs(x)`", () => {
    expect(parsed("a | b").querySelector("mo")?.textContent).toBe("|");
    expect(parsed("abs(x)").textContent).toBe("|x|");
  });
});

describe("floor and ceil, which is what makes C's truncation visible", () => {
  it("wraps a REAL fraction in stretchy fences: `floor(23*m/9)`", () => {
    // The Zeller formula of `tp3-ex8` means exactly this and its current form does
    // not show it. The fraction must be INSIDE the brackets, not beside them.
    const host = parsed("floor(23*m/9)");
    const fences = host.querySelectorAll('mo[stretchy="true"]');
    expect(Array.from(fences).map((f) => f.textContent)).toEqual(["⌊", "⌋"]);
    expect(fences[0]!.parentElement!.querySelector("mfrac")).not.toBeNull();
  });

  it("does the same upward with `ceil`", () => {
    expect(parsed("ceil(n/2)").textContent).toBe("⌈n2⌉");
  });

  it("reads `%` as C spells it, since `$` changes layout and not vocabulary", () => {
    expect(parsed("(a + b) % 7").querySelector("math")!.textContent).toBe("(a+b)%7");
  });
});

describe("calls, and the list of them is CLOSED", () => {
  it("draws `pow(a, b)` as an exponent: C has no power operator", () => {
    expect(parsed("pow(a, b)").querySelector("msup")?.textContent).toBe("ab");
  });

  it("keeps a two-argument call upright", () => {
    expect(parsed("max(a, b)").textContent).toBe("max(a,b)");
  });

  it("REFUSES a name that is not on the list", () => {
    // The twin of the two above: an unknown call is not drawn as a call, it fails --
    // so the statement falls back to the code span it showed before.
    expect(renderMath("frobnicate(x)")).toBeNull();
    expect(renderMath("printf(x)")).toBeNull();
  });
});

describe("subscripts and Greek, both from a closed vocabulary", () => {
  it("reads `x_1` as a subscript", () => {
    expect(parsed("x_1").querySelector("msub")?.textContent).toBe("x1");
  });

  it("translates only the Greek names it knows, and leaves the rest alone", () => {
    expect(parsed("rho * theta").textContent).toBe("ρ⋅θ");
    // `v` is the viscosity of `tp2-ex8` and stays a Latin v: guessing would rename a
    // variable the statement names in its prose.
    expect(parsed("v").textContent).toBe("v");
  });
});

describe("what must return null, so the caller can fall back", () => {
  // NONE OF THESE MAY THROW. A statement is rendered on the anonymous path, and an
  // exception here would take the whole page's markup with it.
  for (const source of [
    "",
    "   ",
    "(a + b",
    "a + b)",
    "a +",
    "+",
    "a b c )",
    "a ; b",
    "a @ b",
    "3 $ 4",
    "a[0]",
    "{a}",
    "nb_elements(x)",
  ]) {
    it(`returns null for ${JSON.stringify(source)}`, () => {
      expect(renderMath(source)).toBeNull();
    });
  }

  it("never throws on any prefix of a real formula", () => {
    const full = "V = racine( 2*m*g / (0,5 * rho * pi * r^2 ))";
    for (let i = 0; i <= full.length; i++) {
      expect(() => renderMath(full.slice(0, i))).not.toThrow();
    }
  });
});
