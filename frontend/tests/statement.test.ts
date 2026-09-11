// THE STATEMENT'S MARKDOWN. The dangerous half is the escaping, so the assertions are
// on the DOM and not on the text -- exactly as in `markdown.test.ts`, and for the same
// reason: `&lt;script&gt;` as escaped TEXT is the right outcome, and a substring search
// would read it as a failure.
//
// HALF THE CASES KEEP A SILENCE, and they are the ones that matter. `renderStatement`
// implements no emphasis on purpose: `*` is C's dereference and multiplication
// operator, and `marked` would eat the asterisks out of `mets *quotient et *reste a 0`.
// A twin test sits next to every construct that could swallow one.

import { describe, expect, it } from "vitest";
import { renderStatement } from "../src/lib/domain/statement";

/** The output, parsed the way the browser will parse it. */
function parsed(source: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderStatement(source);
  return host;
}

const text = (source: string) => parsed(source).textContent ?? "";

describe("nothing a statement carries can become a tag", () => {
  it("keeps `#include <stdio.h>` in a code block as TEXT, not as an element", () => {
    const host = parsed("\t#include <stdio.h>");
    expect(host.querySelector("pre code")).not.toBeNull();
    expect(host.textContent).toContain("#include <stdio.h>");
    expect(host.querySelector("stdio")).toBeNull();
  });

  it("does not let a `<script>` in prose become one", () => {
    const host = parsed("Ne tape pas <script>alert(1)</script> ici.");
    expect(host.querySelector("script")).toBeNull();
    expect(host.textContent).toContain("<script>alert(1)</script>");
  });

  it("does not let a `<img onerror>` in a code block become one", () => {
    const host = parsed('\t<img src=x onerror="alert(1)">');
    expect(host.querySelector("img")).toBeNull();
    expect(host.innerHTML).not.toContain("onerror=\"alert");
  });

  it("escapes an ampersand rather than reviving an entity", () => {
    expect(text("a &lt; b")).toContain("a &lt; b");
  });
});

describe("the asterisks survive -- there is no emphasis, and that is the point", () => {
  it("leaves a dereference pair alone where `marked` would eat both", () => {
    expect(text("si diviseur vaut 0, mets *quotient et *reste a 0")).toContain(
      "mets *quotient et *reste a 0",
    );
  });

  it("leaves the multiplications of a formula alone", () => {
    expect(text("mois >= 3 : (23*m/9 + d + 4) % 7 et (23*m/9 + d)")).toContain(
      "(23*m/9 + d + 4) % 7 et (23*m/9 + d)",
    );
  });

  it("renders no `em` or `strong`, however the source is written", () => {
    const host = parsed("du *texte* et du **gras** et du _souligne_");
    expect(host.querySelector("em")).toBeNull();
    expect(host.querySelector("strong")).toBeNull();
    expect(host.textContent).toContain("*texte*");
  });
});

describe("code blocks", () => {
  const C = "int main(void) { return 0; }";

  it("reads a tab-indented block and a fenced block the same way", () => {
    expect(parsed("\t" + C).querySelector("pre code")).not.toBeNull();
    expect(parsed("```\n" + C + "\n```").querySelector("pre code")).not.toBeNull();
  });

  it("reads a four-space block too: 56 of the 77 statements are written that way", () => {
    expect(parsed("    " + C).querySelector("pre code")).not.toBeNull();
  });

  it("colours what is inside, with the editor's own classes", () => {
    const host = parsed("\t" + C);
    expect(host.querySelector("pre code span.tk")?.textContent).toBe("int");
  });

  it("does NOT colour prose: a paragraph carries no span at all", () => {
    expect(parsed("Elle retourne un int et un return.").querySelector("span")).toBeNull();
  });

  it("removes the common indentation but keeps the inner alignment", () => {
    // `tp2-ex8` lines its arrows up with tabs INSIDE the line; `tab-size` renders that.
    const host = parsed("\tR < 2000\t-> laminaire\n\tsinon\t\t-> transitoire");
    expect(host.querySelector("pre code")?.textContent).toBe(
      "R < 2000\t-> laminaire\nsinon\t\t-> transitoire",
    );
  });

  it("does not end the block on a blank line inside it", () => {
    const host = parsed("\tint a;\n\n\tint b;\n\nDu texte.");
    expect(host.querySelectorAll("pre").length).toBe(1);
    expect(host.querySelectorAll("p").length).toBe(1);
  });
});

describe("prose reflows, and that is not `breaks: true`", () => {
  it("joins the lines of a paragraph with a SPACE, never with a `<br>`", () => {
    // The statements are hard-wrapped at about sixty columns, wider than the column
    // they are read in: honouring those newlines would break every line twice.
    const host = parsed("Elle fournit a l'appelant le quotient ET le reste de la\ndivision entiere.");
    expect(host.querySelector("br")).toBeNull();
    expect(host.textContent).toBe("Elle fournit a l'appelant le quotient ET le reste de la division entiere.");
  });

  it("starts a new paragraph on a blank line", () => {
    expect(parsed("Un.\n\nDeux.").querySelectorAll("p").length).toBe(2);
  });
});

describe("lists win over the indentation, because they are lists", () => {
  it("reads a four-space bullet list as a list and not as code", () => {
    const host = parsed("    - verifie D'ABORD ;\n    - retourne vrai.");
    expect(host.querySelector("pre")).toBeNull();
    expect(host.querySelectorAll("ul li").length).toBe(2);
  });

  it("reads a tab-indented numbered list as an `ol`", () => {
    // Left as a code block, `highlight()` would colour "l'annee ... de l'usager" as a
    // character literal -- two French apostrophes on one line.
    const host = parsed("\t1. l'annee actuelle\n\t2. l'annee de naissance de l'usager");
    expect(host.querySelectorAll("ol li").length).toBe(2);
    expect(host.querySelector("span")).toBeNull();
  });

  it("folds a continuation line into the item above it", () => {
    const host = parsed("  - retourne une valeur vraie si elle a eu lieu, fausse\n    sinon.");
    expect(host.querySelectorAll("li").length).toBe(1);
    expect(host.querySelector("li")?.textContent).toBe(
      "retourne une valeur vraie si elle a eu lieu, fausse sinon.",
    );
  });
});

describe("headings and inline code", () => {
  it("reads a setext underline as a heading -- `verif-tp2` writes its four that way", () => {
    const host = parsed("Programme A\n-----------");
    expect(host.querySelector("h2")?.textContent).toBe("Programme A");
    expect(host.textContent).not.toContain("---");
  });

  it("reads an atx heading too", () => {
    expect(parsed("## Programme B").querySelector("h2")?.textContent).toBe("Programme B");
  });

  it("renders a backtick span as `code`, and leaves an asterisk inside it alone", () => {
    const host = parsed("la force `F` et le pointeur `*quotient`");
    expect([...host.querySelectorAll("code")].map((n) => n.textContent)).toEqual([
      "F",
      "*quotient",
    ]);
  });

  it("leaves a lone backtick as text rather than swallowing the rest", () => {
    expect(text("un ` seul backtick")).toContain("un ` seul backtick");
  });
});

describe("it never throws and never loops", () => {
  it("survives an unclosed fence", () => {
    expect(parsed("```\nint a;").querySelector("pre code")?.textContent).toBe("int a;");
  });

  it("survives an empty statement", () => {
    expect(renderStatement("")).toBe("");
  });

  it("survives a line that looks like a marker but has nothing after it", () => {
    expect(() => renderStatement("-\n")).not.toThrow();
  });
});
