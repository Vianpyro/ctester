import { describe, expect, it } from "vitest";
import { renderMath } from "../src/lib/domain/math";

function parsed(source: string): HTMLElement {
  const html = renderMath(source);
  expect(html, `renderMath(${JSON.stringify(source)}) returned null`).not.toBeNull();
  const host = document.createElement("div");
  host.innerHTML = html!;
  return host;
}

const shape = (el: Element | null) => Array.from(el?.children ?? []).map((c) => c.tagName.toLowerCase());

describe("the six formulas the course actually writes", () => {
  it("tp2-ex3: `I = V / R` is a fraction, not a slash", () => {
    const host = parsed("I = V / R");
    const frac = host.querySelector("mfrac");
    expect(frac).not.toBeNull();
    expect(frac!.children[0]!.textContent).toBe("V");
    expect(frac!.children[1]!.textContent).toBe("R");
  });

  it("tp2-ex4: `A = pi * r^2` is a superscript and a Greek pi", () => {
    const host = parsed("A = pi * r^2");
    expect(host.querySelector("msup")?.textContent).toBe("r2");
    expect(host.textContent).toContain("π");
    expect(host.textContent).not.toContain("pi");
  });

  it("asks for display style, without which a fraction is drawn at script size", () => {
    const root = parsed("V = racine(a / b)").querySelector("math");
    expect(root?.getAttribute("displaystyle")).toBe("true");
  });

  it("tp2-ex5: a radical over a fraction, and the redundant parentheses drop", () => {
    const host = parsed("V = racine( 2*m*g / (0,5 * rho * pi * r^2 ))");
    const sqrt = host.querySelector("msqrt");
    expect(sqrt).not.toBeNull();
    const frac = sqrt!.querySelector("mfrac");
    expect(frac).not.toBeNull();
    expect(frac!.children[0]!.textContent).toBe("2⋅m⋅g");
    expect(frac!.children[1]!.textContent).toBe("0,5⋅ρ⋅π⋅r2");
    expect(sqrt!.textContent).not.toContain("(");
    expect(sqrt!.textContent).not.toContain(")");
    expect(Array.from(host.querySelectorAll("mn")).map((n) => n.textContent)).toContain("0,5");
  });

  it("tp2-ex8 and tp3-ex3: `R = V * L / v` puts V·L over v", () => {
    const frac = parsed("R = V * L / v").querySelector("mfrac");
    expect(frac!.children[0]!.textContent).toBe("V⋅L");
    expect(frac!.children[1]!.textContent).toBe("v");
  });

  it("bonus-1: `P = F * v` has no fraction at all", () => {
    const host = parsed("P = F * v");
    expect(host.querySelector("mfrac")).toBeNull();
    expect(host.textContent).toBe("P=F⋅v");
  });
});

describe("precedence is C's, and the shape of the tree is what says so", () => {
  it("puts only the neighbouring term over the bar: `a + b / c`", () => {
    const frac = parsed("a + b / c").querySelector("mfrac");
    expect(frac!.children[0]!.textContent).toBe("b");
    expect(frac!.parentElement?.tagName.toLowerCase()).toBe("math");
  });

  it("binds `&` tighter than `|`", () => {
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

describe("the lexer reads the longest operator first", () => {
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
    const host = parsed("a & b << 2 > c");
    expect(Array.from(host.querySelectorAll("mo")).map((o) => o.textContent)).toEqual([
      "&",
      "<<",
      ">",
    ]);
    expect(host.querySelectorAll("math > *")).toHaveLength(7);
  });

  it("cannot be made to emit a tag from a name", () => {
    expect(renderMath("script(x)")).toBeNull();
  });
});

describe("`^` is the exponent and exclusive-or is spelled `xor`", () => {
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

  it("reads `|` as bitwise OR; absolute value is `abs(x)`", () => {
    expect(parsed("a | b").querySelector("mo")?.textContent).toBe("|");
    expect(parsed("abs(x)").textContent).toBe("|x|");
  });
});

describe("floor and ceil, which is what makes C's truncation visible", () => {
  it("wraps a real fraction in stretchy fences: `floor(23*m/9)`", () => {
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

describe("calls, and the list of them is closed", () => {
  it("draws `pow(a, b)` as an exponent: C has no power operator", () => {
    expect(parsed("pow(a, b)").querySelector("msup")?.textContent).toBe("ab");
  });

  it("keeps a two-argument call upright", () => {
    expect(parsed("max(a, b)").textContent).toBe("max(a,b)");
  });

  it("refuses a name that is not on the list", () => {
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
    expect(parsed("v").textContent).toBe("v");
  });
});

describe("what must return null, so the caller can fall back", () => {
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
