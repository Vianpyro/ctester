import { escapeHtml } from "./highlight";

const GREEK: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", zeta: "ζ",
  eta: "η", theta: "θ", iota: "ι", kappa: "κ", lambda: "λ", mu: "μ",
  nu: "ν", xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ",
  phi: "φ", chi: "χ", psi: "ψ", omega: "ω",
  Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π",
  Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
};

const FENCES: Record<string, [string, string]> = {
  floor: ["⌊", "⌋"],
  ceil: ["⌈", "⌉"],
  abs: ["|", "|"],
};

const CALLS = ["min", "max", "log", "ln", "exp", "sin", "cos", "tan", "mod"];

const OPERATORS = [
  "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
  "+", "-", "*", "/", "%", "^", "_", "&", "|", "~", "!", "<", ">", "=", "(", ")", ",",
];

type Token = { kind: "num" | "name" | "op"; text: string };

function lex(src: string): Token[] | null {
  const out: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i]!;
    if (c === " " || c === "\t") {
      i++;
      continue;
    }
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

type Node = {
  html: string;
  bare?: string;
};

const mi = (s: string) => "<mi>" + escapeHtml(s) + "</mi>";
const mn = (s: string) => "<mn>" + escapeHtml(s) + "</mn>";
const mo = (s: string) => "<mo>" + escapeHtml(s) + "</mo>";
const row = (s: string) => "<mrow>" + s + "</mrow>";

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
      const isWord = tok.kind === "name" && tok.text === "xor";
      const found = ops.find((o) => (isWord ? o === tok.text : tok.kind === "op" && o === tok.text));
      if (!found) break;
      this.at++;
      const right = this.binary(level + 1);
      if (!right) return null;
      if (found === "/") {
        left = { html: "<mfrac>" + row(inner(left)) + row(inner(right)) + "</mfrac>" };
        continue;
      }
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
      if (tok.text === "xor") return null;
      this.at++;
      if (this.eat("(")) return this.call(tok.text);
      return { html: mi(GREEK[tok.text] ?? tok.text) };
    }

    if (this.eat("(")) {
      const body = this.equation();
      if (!body || !this.eat(")")) return null;
      return { html: mo("(") + body.html + mo(")"), bare: inner(body) };
    }

    return null;
  }

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
    if (name === "pow" && args.length === 2) {
      return { html: "<msup>" + row(inner(args[0]!)) + row(inner(args[1]!)) + "</msup>" };
    }
    const fence = FENCES[name];
    if (fence && args.length === 1) {
      const open = '<mo stretchy="true">' + escapeHtml(fence[0]) + "</mo>";
      const close = '<mo stretchy="true">' + escapeHtml(fence[1]) + "</mo>";
      return { html: row(open + inner(args[0]!) + close) };
    }
    if (!CALLS.includes(name)) return null;

    const body = args.map((a) => inner(a)).join(mo(","));
    return { html: mi(name) + mo("(") + body + mo(")") };
  }
}

export function renderMath(source: string): string | null {
  const tokens = lex(source);
  if (!tokens || !tokens.length) return null;
  const parser = new Parser(tokens);
  const node = parser.equation();
  if (!node || !parser.done()) return null;
  return (
    // displaystyle keeps both halves of a fraction at full size.
    '<math displaystyle="true" xmlns="http://www.w3.org/1998/Math/MathML">' +
    node.html +
    "</math>"
  );
}
