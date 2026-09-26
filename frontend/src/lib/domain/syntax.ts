import { t } from "../i18n.svelte";

export type Level = "error" | "hint";

export interface Issue {
  from: number;
  to: number;
  level: Level;
  message: string;
}

const MAX_ISSUES = 10;

const OPENERS: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
const CLOSERS: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

interface Literal {
  from: number;
  text: string;
}

interface Scanned {
  blanked: string;
  literals: Literal[];
  // Character constants, 'x', kept apart: only the multi-character check reads them.
  quoted: Literal[];
  issues: Issue[];
}

function scan(src: string): Scanned {
  const chars = src.split("");
  const literals: Literal[] = [];
  const quoted: Literal[] = [];
  const issues: Issue[] = [];
  const stack: { at: number; ch: string }[] = [];

  const blank = (from: number, to: number) => {
    for (let k = from; k < to && k < chars.length; k++) if (chars[k] !== "\n") chars[k] = " ";
  };
  const lineEnd = (from: number) => {
    const nl = src.indexOf("\n", from);
    return nl < 0 ? src.length : nl;
  };
  const derailed = (): Scanned => ({ blanked: chars.join(""), literals, quoted, issues });

  let i = 0;
  while (i < src.length) {
    const c = src[i]!;

    if (c === "/" && src[i + 1] === "/") {
      const end = lineEnd(i);
      blank(i, end);
      i = end;
      continue;
    }

    if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      if (end < 0) {
        issues.push({
          from: i,
          to: i + 2,
          level: "error",
          message: t("syntax.open_comment"),
        });
        blank(i, src.length);
        return derailed();
      }
      blank(i, end + 2);
      i = end + 2;
      continue;
    }

    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < src.length && src[j] !== c && src[j] !== "\n") {
        if (src[j] === "\\") {
          if (j + 1 >= src.length || src[j + 1] === "\n") break;
          j += 2;
        } else {
          j++;
        }
      }
      if (j >= src.length || src[j] !== c) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message:
            c === '"' ? t("syntax.open_string") : t("syntax.open_char"),
        });
        blank(i, lineEnd(i));
        return derailed();
      }
      (c === '"' ? literals : quoted).push({ from: i, text: src.slice(i + 1, j) });
      blank(i, j + 1);
      i = j + 1;
      continue;
    }

    if (OPENERS[c]) {
      stack.push({ at: i, ch: c });
    } else if (CLOSERS[c]) {
      const top = stack.pop();
      if (!top) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message: t("syntax.stray_closer", { closer: c, opener: CLOSERS[c]! }),
        });
      } else if (top.ch !== CLOSERS[c]) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message: t("syntax.crossed", { closer: c, opener: top.ch }),
        });
      }
    }
    i++;
  }

  for (const open of stack) {
    issues.push({
      from: open.at,
      to: open.at + 1,
      level: "error",
      message: t("syntax.unclosed", { opener: open.ch }),
    });
  }

  return derailed();
}

function matching(text: string, open: number, pair = "()"): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === pair[0]) depth++;
    else if (text[i] === pair[1] && --depth === 0) return i;
  }
  return -1;
}

type Params = Record<string, string | number>;

function say(issues: Issue[], level: Level, from: number, to: number, key: string, params: Params = {}) {
  issues.push({ from, to, level, message: t(`syntax.${key}`, params) });
}

// Pasted from a document or a slide: gcc answers "stray '\342' in program".
const TYPOGRAPHIC = /[‘’“”«»  ​﻿]/g;

function typographic(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(TYPOGRAPHIC)) {
    say(issues, "error", m.index, m.index + 1, "typographic");
  }
}

const DIRECTIVES = new Set([
  "include", "define", "undef", "if", "ifdef", "ifndef", "elif", "elifdef", "elifndef", "else",
  "endif", "pragma", "error", "warning", "line", "embed",
]);

function directives(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/^[ \t]*#[ \t]*(\w+)/gm)) {
    const word = m[1]!;
    const at = m.index + m[0].length - word.length;
    if (!DIRECTIVES.has(word)) say(issues, "error", at, at + word.length, "directive", { word });
  }
  for (const m of blanked.matchAll(/^[ \t]*#[ \t]*include[ \t]*<([^>\n]*[ \t][^>\n]*)>/gm)) {
    const at = m.index + m[0].indexOf("<");
    say(issues, "error", at, m.index + m[0].length, "header_space", { name: m[1]!.replace(/[ \t]+/g, "") });
  }
}

const QUALIFIERS = new Set([
  "const", "volatile", "restrict", "static", "register", "signed", "unsigned", "long", "short",
  "int", "char", "float", "double",
]);

// int calories par seconde = ...; gcc only says "expected '=', ',', ';' ... before 'par'".
function spacedName(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\b(?:int|char|float|double)[ \t]+([A-Za-z_]\w*(?:[ \t]+\w+)+)[ \t]*(?=[=;,[])/g)) {
    const words = m[1]!.split(/[ \t]+/);
    if (words.some((w) => QUALIFIERS.has(w))) continue;
    const from = m.index + m[0].indexOf(m[1]!);
    say(issues, "error", from, from + m[1]!.length, "spaced_name", {
      words: words.join(" "),
      joined: words.join("_"),
    });
  }
}

// scanf(...); above main: gcc only says "expected declaration specifiers or '...'".
function callOutsideFunction(blanked: string, issues: Issue[]): void {
  let depth = 0;
  let at = 0;
  for (const line of blanked.split("\n")) {
    const call = /^([ \t]*)([A-Za-z_]\w*)\s*\(.*\)\s*;\s*$/.exec(line);
    if (!depth && call) say(issues, "error", at + call[1]!.length, at + call[1]!.length + call[2]!.length, "outside_function");
    for (const c of line) depth += c === "{" ? 1 : c === "}" ? -1 : 0;
    at += line.length + 1;
  }
}

function forSemicolons(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\bfor\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    const close = matching(blanked, open);
    if (close < 0) continue;
    let depth = 0;
    let count = 0;
    for (let i = open + 1; i < close; i++) {
      const c = blanked[i];
      if (c === "(" || c === "[") depth++;
      else if (c === ")" || c === "]") depth--;
      else if (c === ";" && depth === 0) count++;
    }
    if (count !== 2) say(issues, "error", open, close + 1, "for_semicolons");
  }
}

function structSemicolon(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\b(struct|union|enum)\s+\w*\s*\{/g)) {
    const close = matching(blanked, m.index + m[0].length - 1, "{}");
    if (close < 0) continue;
    // "} p;" or "} Point;" declares something; "}" then "int f(" on the next line does not.
    if (/^\s*(?:;|\**\s*\w+\s*[;,=[])/.test(blanked.slice(close + 1))) continue;
    say(issues, "error", close, close + 1, "struct_semicolon", { keyword: m[1]! });
  }
}

function assignmentInCondition(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\b(?:if|while)\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    let depth = 0;
    for (let i = open; i < blanked.length; i++) {
      const c = blanked[i]!;
      if (c === "(") {
        depth++;
      } else if (c === ")") {
        if (--depth === 0) break;
      } else if (c === "=" && depth === 1) {
        if (blanked[i + 1] === "=") {
          i++;
          continue;
        }
        if ("=!<>+-*/%&|^".indexOf(blanked[i - 1]!) >= 0) continue;
        say(issues, "hint", i, i + 1, "assign_in_test");
      }
    }
  }
}

function emptyBody(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\b(if|for|while)\s*\(/g)) {
    // The while that ends a do ... while is followed by ";" by design.
    if (m[1] === "while" && /\}\s*$/.test(blanked.slice(0, m.index))) continue;
    const close = matching(blanked, m.index + m[0].length - 1);
    if (close < 0) continue;
    const rest = blanked.slice(close + 1);
    const gap = rest.length - rest.replace(/^\s*/, "").length;
    if (rest[gap] !== ";") continue;
    // while (getchar() != '\n'); is an idiom: a loop is only wrong when a block follows it.
    if (m[1] !== "if" && !/^\s*\{/.test(rest.slice(gap + 1))) continue;
    say(issues, "hint", close + 1 + gap, close + 2 + gap, m[1] === "if" ? "empty_if" : "empty_loop");
  }
}

const CONVERSION = /%(?:%|[-+ #0]*[0-9*]*(?:\.[0-9*]+)?(hh|h|ll|l|L|z|j|t)?(.))/g;

interface Span {
  from: number;
  to: number;
}

interface FormatCall {
  name: string;
  at: number;
  format: string;
  args: Span[];
}

// The printf and scanf calls whose format is a single string literal.
function formatCalls(blanked: string, literals: Literal[]): FormatCall[] {
  const calls: FormatCall[] = [];
  for (const m of blanked.matchAll(/\b(printf|scanf)\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    const close = matching(blanked, open);
    if (close < 0) continue;

    const args: Span[] = [];
    let depth = 0;
    let start = open + 1;
    for (let i = open + 1; i <= close; i++) {
      const c = blanked[i];
      if (i === close) {
        args.push({ from: start, to: i });
        break;
      }
      if (c === "(" || c === "[") depth++;
      else if (c === ")" || c === "]") depth--;
      else if (c === "," && depth === 0) {
        args.push({ from: start, to: i });
        start = i + 1;
      }
    }
    const first = args.shift()!;
    const format = literals.filter((l) => l.from >= first.from && l.from < first.to);
    // Two literals are a concatenation, and none is a format held in a variable.
    // The literal is blanked, so anything left in the argument is code around it.
    if (format.length !== 1 || blanked.slice(first.from, first.to).trim()) continue;
    calls.push({ name: m[1]!, at: m.index, format: format[0]!.text, args });
  }
  return calls;
}

function scanfWithoutAmpersand(blanked: string, calls: FormatCall[], issues: Issue[]): void {
  for (const call of calls) {
    if (call.name !== "scanf") continue;
    let k = 0;
    for (const conv of call.format.matchAll(CONVERSION)) {
      const letter = conv[2];
      if (letter === undefined) continue;
      if (k >= call.args.length) break;
      const arg = call.args[k++]!;
      if (letter === "s" || letter === "[") continue;
      const slice = blanked.slice(arg.from, arg.to);
      const name = slice.trim();
      if (!/^[A-Za-z_]\w*$/.test(name)) continue;
      say(issues, "hint", arg.from + slice.indexOf(name), arg.to, "scanf_ampersand", { name });
    }
  }
}

function formatCount(calls: FormatCall[], issues: Issue[]): void {
  for (const call of calls) {
    // A * width takes an argument of its own; counting it is not worth the guess.
    if (call.format.includes("*")) continue;
    const wanted = [...call.format.matchAll(CONVERSION)].filter((c) => c[2] !== undefined).length;
    if (wanted === call.args.length) continue;
    say(issues, "hint", call.at, call.at + call.name.length, "format_count", {
      count: wanted,
      given: call.args.length,
    });
  }
}

type Scalar = "int" | "char" | "float" | "double";

// ponytail: one type per name for the whole file, scopes ignored; a name declared with two
// types is dropped. A real symbol table is the upgrade if shadowing starts to mislead.
function declaredTypes(blanked: string): Map<string, Scalar | null> {
  const types = new Map<string, Scalar | null>();
  const declaration = /(?:^|[;{}(\n])\s*(?:const\s+)?(int|char|float|double)\s+([^;(){}]*);/g;
  for (const m of blanked.matchAll(declaration)) {
    for (const part of m[2]!.split(",")) {
      const d = /^\s*(\**)\s*([A-Za-z_]\w*)\s*(\[)?/.exec(part);
      if (!d) continue;
      const type = d[1] || d[3] ? null : (m[1] as Scalar);
      const name = d[2]!;
      types.set(name, types.has(name) && types.get(name) !== type ? null : type);
    }
  }
  return types;
}

const FLOATING = new Set(["f", "e", "g", "E", "G"]);

function wantedConversion(call: string, type: Scalar, length: string, letter: string): string | null {
  const integer = letter === "d" || letter === "i";
  const floating = FLOATING.has(letter);
  const real = type === "float" || type === "double";
  if (type === "int" && floating) return "%d";
  if (call === "printf") return real && integer ? "%f" : null;
  if (type === "double" && (integer || (floating && length !== "l"))) return "%lf";
  if (type === "float" && (integer || (floating && length === "l"))) return "%f";
  return null;
}

function formatType(blanked: string, calls: FormatCall[], issues: Issue[]): void {
  const types = declaredTypes(blanked);
  for (const call of calls) {
    let k = 0;
    for (const conv of call.format.matchAll(CONVERSION)) {
      const [given, length = "", letter] = conv;
      if (letter === undefined) continue;
      if (k >= call.args.length) break;
      const arg = call.args[k++]!;
      const text = blanked.slice(arg.from, arg.to).trim();
      const name = call.name === "scanf" ? /^&\s*([A-Za-z_]\w*)$/.exec(text)?.[1] : text;
      const type = name ? types.get(name) : undefined;
      if (!type) continue;
      const wanted = wantedConversion(call.name, type, length, letter);
      if (wanted) say(issues, "hint", arg.from, arg.to, "format_type", { type, wanted, given });
    }
  }
}

const HEADERS: Record<string, string[]> = {
  "stdio.h": ["printf", "scanf", "puts", "putchar", "getchar", "fgets", "fopen", "fclose"],
  "math.h": ["sqrt", "pow", "fabs", "floor", "ceil", "round", "sin", "cos", "tan", "exp", "log"],
  "stdlib.h": ["malloc", "calloc", "realloc", "free", "rand", "srand", "exit", "abs", "atoi"],
  "string.h": ["strlen", "strcmp", "strncmp", "strcpy", "strncpy", "strcat"],
};

// ponytail: only a file with main() and no header of its own, since a student's header may
// bring the standard ones in. Following it is the upgrade if that proves too timid.
function missingInclude(src: string, blanked: string, issues: Issue[]): void {
  if (!/\bmain\s*\(/.test(blanked)) return;
  const included = [...src.matchAll(/^\s*#\s*include\s*([<"])\s*([^>"\s]+)/gm)];
  if (included.some((m) => m[1] === '"')) return;
  const have = new Set(included.map((m) => m[2]));
  for (const [header, names] of Object.entries(HEADERS)) {
    if (have.has(header)) continue;
    const use = new RegExp(`\\b(${names.join("|")})\\s*\\(`).exec(blanked);
    if (!use) continue;
    say(issues, "hint", use.index, use.index + use[1]!.length, "missing_include", {
      name: use[1]!,
      header,
    });
  }
}

function stringCompare(blanked: string, literals: Literal[], issues: Issue[]): void {
  for (const l of literals) {
    const end = l.from + l.text.length + 2;
    const before = /[!=]=\s*$/.test(blanked.slice(Math.max(0, l.from - 8), l.from));
    if (before || /^\s*[!=]=/.test(blanked.slice(end, end + 8))) {
      say(issues, "hint", l.from, end, "string_compare");
    }
  }
}

const COMPARISON = /(?<![<>-])(?:<=?|>=?)(?![<>])/g;

function chainedCompare(blanked: string, issues: Issue[]): void {
  let at = 0;
  for (const line of blanked.split("\n")) {
    const offset = at;
    at += line.length + 1;
    if (/^\s*#/.test(line)) continue;
    let start = 0;
    for (const piece of line.split(/&&|\|\||[(),;?:{}]/)) {
      const from = offset + line.indexOf(piece, start);
      start = from - offset + piece.length;
      const ops = [...piece.matchAll(COMPARISON)];
      if (ops.length < 2) continue;
      const last = ops[ops.length - 1]!;
      say(issues, "hint", from + ops[0]!.index, from + last.index + last[0].length, "chained_compare");
    }
  }
}

function caretPower(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/[\w)\]]\s*\^\s*[23](?![\w.])/g)) {
    const at = m.index + m[0].indexOf("^");
    say(issues, "hint", at, at + 1, "caret_power");
  }
}

// Only a division that truncates: 10 / 2 is exact, 1 / 2 is the classic 0.
function integerDivision(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/(?<![\w.])(\d+)\s*\/\s*(\d+)(?![\w.])/g)) {
    const a = Number(m[1]);
    const b = Number(m[2]);
    if (b === 0 || a % b === 0) continue;
    say(issues, "hint", m.index, m.index + m[0].length, "integer_division", { a: m[1]!, b: m[2]! });
  }
}

function arrayBound(blanked: string, issues: Issue[]): void {
  const declared = blanked.matchAll(/\b(?:int|char|float|double|long|short)\s+\w+\s*\[\s*(\w+)\s*\]/g);
  const sizes = new Set([...declared].map((m) => m[1]));
  if (!sizes.size) return;
  for (const m of blanked.matchAll(/\bfor\s*\(([^;]*);([^;]*);/g)) {
    // Only a loop from 0: one from 1 to N is how a sum is written, not an index.
    if (!/=\s*0\s*$/.test(m[1]!)) continue;
    const bound = /<=\s*(\w+)(?!\s*[-+*/\w])/.exec(m[2]!);
    if (!bound || !sizes.has(bound[1]!)) continue;
    const from = m.index + m[0].indexOf(";") + 1 + bound.index;
    say(issues, "hint", from, from + bound[0].length, "array_bound", { size: bound[1]! });
  }
}

const CAPITALISED =
  /\b(If|Else|While|For|Do|Switch|Case|Return|Int|Float|Double|Char|Void|Printf|Scanf|Main|Include|Define)\b/g;

function capitalisedKeyword(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(CAPITALISED)) {
    say(issues, "hint", m.index, m.index + m[0].length, "case_keyword", { word: m[1]!.toLowerCase() });
  }
}

function voidMain(blanked: string, issues: Issue[]): void {
  const m = /\bvoid\s+main\b/.exec(blanked);
  if (m) say(issues, "hint", m.index, m.index + m[0].length, "void_main");
}

// gcc reads else (x) { as a missing ";" and says so, which sends the student the wrong way.
function elseCondition(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\belse\s*\(/g)) say(issues, "hint", m.index, m.index + 4, "else_condition");
}

const TYPO_TARGETS = ["printf", "scanf"];
// Real library functions one letter away from a target.
const LOOKALIKES = new Set(["fprintf", "sprintf", "dprintf", "vprintf", "wprintf", "fscanf", "sscanf", "vscanf", "wscanf"]);

// One insertion, deletion, substitution or swap of neighbours; a change of case alone is
// case_keyword's business.
function oneEdit(a: string, b: string): boolean {
  if (a.toLowerCase() === b.toLowerCase() || Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  while (a[i] === b[i]) i++;
  if (a.length > b.length) return a.slice(i + 1) === b.slice(i);
  if (a.length < b.length) return a.slice(i) === b.slice(i + 1);
  if (a.slice(i + 1) === b.slice(i + 1)) return true;
  return a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2);
}

function nearMiss(blanked: string, issues: Issue[]): void {
  const defs = [...blanked.matchAll(/\b([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{/g)];
  const defined = new Set(defs.map((m) => m[1]!));
  for (const m of blanked.matchAll(/\b([A-Za-z_]\w*)\s*\(/g)) {
    const name = m[1]!;
    if (defined.has(name) || LOOKALIKES.has(name)) continue;
    const target = TYPO_TARGETS.find((known) => oneEdit(name, known));
    if (target) say(issues, "hint", m.index, m.index + name.length, "near_miss", { name: target });
  }
  // A unity exercise has no main, but its functions take parameters; int maint(void) is main.
  if (defined.has("main")) return;
  for (const m of defs) {
    if (!/^\s*(?:void)?\s*$/.test(m[2]!) || !oneEdit(m[1]!, "main")) continue;
    say(issues, "hint", m.index, m.index + m[1]!.length, "near_miss", { name: "main" });
  }
}

function slashN(literals: Literal[], issues: Issue[]): void {
  for (const l of literals) {
    const at = l.text.search(/(?<!\/)\/n(?![a-z])/i);
    if (at >= 0) say(issues, "hint", l.from + 1 + at, l.from + 3 + at, "slash_n");
  }
}

function multiChar(quoted: Literal[], issues: Issue[]): void {
  for (const q of quoted) {
    if (q.text.replace(/\\(x[0-9a-fA-F]+|[0-7]{1,3}|.)/g, "x").length < 2) continue;
    say(issues, "hint", q.from, q.from + q.text.length + 2, "multi_char");
  }
}

const UNFINISHED = /[,;:{}\\?+\-*/%=<>&|!([]$/;
const NO_SEMICOLON =
  /^\s*(?:#|\/\/|(?:if|else|for|while|switch|do|case|default|struct|union|enum|typedef)\b)/;
const CONTINUED = /^\s*[{})\].?:+\-*/%=<>&|,]/;

// A "}" that closes an initializer or an enum ends a list, whose last item takes no ";".
// One that closes a block ends statements, which do.
function closesList(blanked: string, close: number): boolean {
  let depth = 0;
  for (let i = close; i >= 0; i--) {
    if (blanked[i] === "}") depth++;
    else if (blanked[i] === "{" && --depth === 0) {
      return /(?:=|\benum\b[^;{}]*)\s*$/.test(blanked.slice(0, i));
    }
  }
  return false;
}

function missingSemicolon(blanked: string, issues: Issue[]): void {
  const lines = blanked.split("\n");
  const starts: number[] = [];
  let at = 0;
  for (const line of lines) {
    starts.push(at);
    at += line.length + 1;
  }
  for (let n = 0; n < lines.length; n++) {
    const offset = starts[n]!;
    const code = lines[n]!.replace(/\s+$/, "");
    if (!code.trim()) continue;
    if (NO_SEMICOLON.test(code)) continue;
    // i++ and i-- end a statement; a lone + or - leaves an expression open.
    if (UNFINISHED.test(code) && !/(\+\+|--)$/.test(code)) continue;
    if (/^\s*[A-Za-z_]\w*\s*:\s*$/.test(code)) continue;
    let depth = 0;
    for (const c of code) {
      if (c === "(" || c === "[") depth++;
      else if (c === ")" || c === "]") depth--;
    }
    if (depth !== 0) continue;

    let next = n + 1;
    while (next < lines.length && !lines[next]!.trim()) next++;
    if (next < lines.length && CONTINUED.test(lines[next]!)) {
      const brace = lines[next]!.search(/\S/);
      if (lines[next]![brace] !== "}" || closesList(blanked, starts[next]! + brace)) continue;
    }

    say(issues, "hint", offset + code.length - 1, offset + code.length, "missing_semicolon");
  }
}

export function check(src: string): Issue[] {
  const { blanked, literals, quoted, issues } = scan(src);
  typographic(blanked, issues);
  if (!issues.length) {
    directives(blanked, issues);
    spacedName(blanked, issues);
    callOutsideFunction(blanked, issues);
    forSemicolons(blanked, issues);
    structSemicolon(blanked, issues);
  }
  // A certain error silences every heuristic: guesses on broken code only add noise.
  if (!issues.length) {
    const calls = formatCalls(blanked, literals);
    missingInclude(src, blanked, issues);
    voidMain(blanked, issues);
    capitalisedKeyword(blanked, issues);
    assignmentInCondition(blanked, issues);
    emptyBody(blanked, issues);
    chainedCompare(blanked, issues);
    stringCompare(blanked, literals, issues);
    scanfWithoutAmpersand(blanked, calls, issues);
    formatCount(calls, issues);
    formatType(blanked, calls, issues);
    caretPower(blanked, issues);
    integerDivision(blanked, issues);
    arrayBound(blanked, issues);
    multiChar(quoted, issues);
    elseCondition(blanked, issues);
    nearMiss(blanked, issues);
    slashN(literals, issues);
    missingSemicolon(blanked, issues);
  }
  return issues.sort((a, b) => a.from - b.from).slice(0, MAX_ISSUES);
}

export function nextIssue(issues: Issue[], caret: number): Issue | null {
  if (!issues.length) return null;
  const sorted = [...issues].sort((a, b) => a.from - b.from);
  return sorted.find((issue) => issue.from > caret) ?? sorted[0]!;
}
