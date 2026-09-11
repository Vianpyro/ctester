// THE STATEMENT'S FORMULAS, AS MathML -- AND WITHOUT KaTeX.
//
// KaTeX is refused for three INDEPENDENT reasons, any one of which is enough: the
// CSP is `default-src 'none'` with NO `font-src`, so its woff2 faces are blocked;
// that policy exists in two copies, one of them a `<meta>` served by GitHub Pages
// where no header can be set, and `test_csp_du_document` compares them directive by
// directive; and its 280 KB would land on the ANONYMOUS path, where `marked` was
// already refused at 74 KB. MathML is drawn by the browser: no library, no font, no
// directive.
//
// `$...$` CHANGES THE LAYOUT, NOT THE VOCABULARY. Every operator keeps the spelling
// a student TYPES in C. Only what C cannot write on one line changes shape: the
// fraction bar, the exponent, the radical, the floor and ceiling fences. `&&` drawn
// as an `∧` would be a second notation to learn for nothing; a fraction is not.
//
// ONE SPELLING EXCEPTION, `*` -> `·`, and it is earned: in a C course an asterisk at
// text height reads as a pointer star, and a middle dot is not a notation anyone has
// to be taught. It is also the only substitution the content already asks for.
//
// `^` IS THE EXPONENT AND EXCLUSIVE-OR IS SPELLED `xor`. That is the one ambiguity
// this notation carries, and it is settled this way because the content already
// writes `pi * r^2`, `m/s^2`, `kg/m^3` -- a hundred percent exponents, zero XOR. A
// teacher who writes `$a ^ b$` meaning XOR gets a superscript: a VISIBLE failure,
// not a plausible-looking wrong one. Same mechanic for `|`, which is bitwise OR and
// therefore infix only: absolute value is `abs(x)`. A delimiter that is also an
// operator cannot be told apart without guessing, so we do not guess.
//
// FAILURE RETURNS `null`, never an exception and never half a document. The caller
// then falls back to `<code>` with the escaped source -- which is EXACTLY what the
// statement shows today, so the degradation is the status quo rather than a hole.
//
// Security is `highlight()`'s contract, and the bitwise operators make it less
// theoretical: `&`, `<` and `>` are precisely the characters an escape misses. Every
// leaf goes through the SAME `escapeHtml()`, so there is no second escaping rule to
// keep in step, and the tag names come from this file and nowhere else.

import { escapeHtml } from "./highlight";

/** A closed vocabulary, applied ONLY inside `$...$` -- nothing typed elsewhere can
 *  reach it. Same reason as the leaderboard's closed alias list. */
const GREEK: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", zeta: "ζ",
  eta: "η", theta: "θ", iota: "ι", kappa: "κ", lambda: "λ", mu: "μ",
  nu: "ν", xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ",
  phi: "φ", chi: "χ", psi: "ψ", omega: "ω",
  Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π",
  Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
};

/** The three fenced functions, and the fences they stretch. `abs` is here rather
 *  than as a `|...|` delimiter because `|` is bitwise OR -- see the header. */
const FENCES: Record<string, [string, string]> = {
  floor: ["⌊", "⌋"],
  ceil: ["⌈", "⌉"],
  abs: ["|", "|"],
};

/** Everything else that may be called. A name outside this list FAILS the parse, so
 *  it falls back to `<code>`: closed, like the Greek vocabulary above. */
const CALLS = ["min", "max", "log", "ln", "exp", "sin", "cos", "tan", "mod"];

// LONGEST FIRST. Reading `a << 2` as two comparisons is the kind of mistake that
// produces a PLAUSIBLE formula, which is worse than one that fails.
const OPERATORS = [
  "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
  "+", "-", "*", "/", "%", "^", "_", "&", "|", "~", "!", "<", ">", "=", "(", ")", ",",
];

type Token = { kind: "num" | "name" | "op"; text: string };

/** `null` on any character the grammar does not know -- the caller falls back. */
function lex(src: string): Token[] | null {
  const out: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i]!;
    if (c === " " || c === "\t") {
      i++;
      continue;
    }
    // THE DECIMAL COMMA IS FRENCH: `0,5` and `9,81` are ONE number. A comma that is
    // not between digits stays an argument separator.
    const num = /^\d+(?:[.,]\d+)?/.exec(src.slice(i));
    if (num) {
      out.push({ kind: "num", text: num[0] });
      i += num[0].length;
      continue;
    }
    const name = /^[A-Za-z][A-Za-z0-9]*/.exec(src.slice(i));
    if (name) {
      out.push({ kind: "name", text: name[0] });
      i += name[0].length;
      continue;
    }
    const op = OPERATORS.find((o) => src.startsWith(o, i));
    if (!op) return null;
    out.push({ kind: "op", text: op });
    i += op.length;
  }
  return out;
}

/** A rendered subtree, plus the one thing its parent needs to know. */
type Node = {
  /** The MathML, already escaped. */
  html: string;
  /** REDUNDANT PARENTHESES DROP. A group that becomes a whole numerator, denominator
   *  or radicand does not need them: `mfrac` and `msqrt` already group. This is what
   *  makes `racine(a / (b*c))` a radical over a BARE fraction. */
  bare?: string;
};

const mi = (s: string) => "<mi>" + escapeHtml(s) + "</mi>";
const mn = (s: string) => "<mn>" + escapeHtml(s) + "</mn>";
const mo = (s: string) => "<mo>" + escapeHtml(s) + "</mo>";
const row = (s: string) => "<mrow>" + s + "</mrow>";

/** What a parent should use when it supplies its own grouping. */
const inner = (n: Node) => n.bare ?? n.html;

class Parser {
  private at = 0;

  constructor(private readonly t: Token[]) {}

  private peek(): Token | undefined {
    return this.t[this.at];
  }

  private eat(text: string): boolean {
    if (this.peek()?.kind === "op" && this.peek()!.text === text) {
      this.at++;
      return true;
    }
    return false;
  }

  done(): boolean {
    return this.at >= this.t.length;
  }

  /** THE PRECEDENCE IS C'S, weakest first -- so a student reads the drawing the way
   *  the compiler reads the line. `=` sits below everything: it is mathematical
   *  equality here, not assignment. */
  equation(): Node | null {
    return this.binary(0);
  }

  private static readonly LEVELS: string[][] = [
    ["="],
    ["||"],
    ["&&"],
    ["|"],
    ["xor"],
    ["&"],
    ["==", "!="],
    ["<", "<=", ">", ">="],
    ["<<", ">>"],
    ["+", "-"],
    ["*", "/", "%"],
  ];

  private binary(level: number): Node | null {
    if (level >= Parser.LEVELS.length) return this.unary();
    const ops = Parser.LEVELS[level]!;
    let left = this.binary(level + 1);
    if (!left) return null;
    for (;;) {
      const tok = this.peek();
      if (!tok) break;
      // `xor` is the ONLY word operator: `^` is taken by the exponent.
      const isWord = tok.kind === "name" && tok.text === "xor";
      const found = ops.find((o) => (isWord ? o === tok.text : tok.kind === "op" && o === tok.text));
      if (!found) break;
      this.at++;
      const right = this.binary(level + 1);
      if (!right) return null;
      if (found === "/") {
        // THE FRACTION BAR, the whole reason this module exists.
        left = { html: "<mfrac>" + row(inner(left)) + row(inner(right)) + "</mfrac>" };
        continue;
      }
      // `*` -> `·` is the one spelling change; every other operator keeps C's.
      const sign = found === "*" ? "⋅" : found;
      left = { html: left.html + mo(sign) + right.html };
    }
    return left;
  }

  private unary(): Node | null {
    const tok = this.peek();
    if (tok?.kind === "op" && ["-", "+", "!", "~"].includes(tok.text)) {
      this.at++;
      const operand = this.unary();
      if (!operand) return null;
      return { html: mo(tok.text) + operand.html };
    }
    return this.power();
  }

  /** RIGHT-ASSOCIATIVE, like every exponent: `a^b^c` is `a^(b^c)`. */
  private power(): Node | null {
    const base = this.subscript();
    if (!base) return null;
    if (!this.eat("^")) return base;
    const exp = this.unary();
    if (!exp) return null;
    return { html: "<msup>" + row(base.html) + row(inner(exp)) + "</msup>" };
  }

  private subscript(): Node | null {
    const base = this.atom();
    if (!base) return null;
    if (!this.eat("_")) return base;
    const idx = this.atom();
    if (!idx) return null;
    return { html: "<msub>" + row(base.html) + row(inner(idx)) + "</msub>" };
  }

  private atom(): Node | null {
    const tok = this.peek();
    if (!tok) return null;

    if (tok.kind === "num") {
      this.at++;
      return { html: mn(tok.text) };
    }

    if (tok.kind === "name") {
      if (tok.text === "xor") return null; // an operator, never an operand
      this.at++;
      if (this.eat("(")) return this.call(tok.text);
      return { html: mi(GREEK[tok.text] ?? tok.text) };
    }

    if (this.eat("(")) {
      const body = this.equation();
      if (!body || !this.eat(")")) return null;
      // The parenthesised form is what a parent renders INLINE; `bare` is what it
      // renders when it supplies its own grouping.
      return { html: mo("(") + body.html + mo(")"), bare: inner(body) };
    }

    return null;
  }

  /** The opening `(` is already eaten. */
  private call(name: string): Node | null {
    const args: Node[] = [];
    if (!this.eat(")")) {
      for (;;) {
        const arg = this.equation();
        if (!arg) return null;
        args.push(arg);
        if (this.eat(",")) continue;
        if (!this.eat(")")) return null;
        break;
      }
    }

    if ((name === "racine" || name === "sqrt") && args.length === 1) {
      return { html: "<msqrt>" + row(inner(args[0]!)) + "</msqrt>" };
    }
    // C HAS NO POWER OPERATOR, so the course calls `pow` -- and reads an exponent.
    if (name === "pow" && args.length === 2) {
      return { html: "<msup>" + row(inner(args[0]!)) + row(inner(args[1]!)) + "</msup>" };
    }
    const fence = FENCES[name];
    if (fence && args.length === 1) {
      // `stretchy` is what grows the bracket around a fraction, which is the whole
      // point of `floor(23*m/9)`: C's truncation, finally drawn.
      const open = '<mo stretchy="true">' + escapeHtml(fence[0]) + "</mo>";
      const close = '<mo stretchy="true">' + escapeHtml(fence[1]) + "</mo>";
      return { html: row(open + inner(args[0]!) + close) };
    }
    if (!CALLS.includes(name)) return null;

    const body = args.map((a) => inner(a)).join(mo(","));
    return { html: mi(name) + mo("(") + body + mo(")") };
  }
}

/**
 * The MathML for one `$...$`, or `null` when the source is not a formula this
 * grammar knows. NEVER throws, and never returns half a document.
 */
export function renderMath(source: string): string | null {
  const tokens = lex(source);
  if (!tokens || !tokens.length) return null;
  const parser = new Parser(tokens);
  const node = parser.equation();
  if (!node || !parser.done()) return null;
  return '<math xmlns="http://www.w3.org/1998/Math/MathML">' + node.html + "</math>";
}
