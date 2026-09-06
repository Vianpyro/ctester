// EXPORTING A LAB AS A SINGLE `main.c`, in the hand-in format: a
// `#define exercice N` at the top choosing the compiled exercise, one
// `#if exercice == N ... #endif` per exercise, and `#include` directives
// hoisted once above everything. This is the format the instructor hands out
// and expects back; CTester itself keeps one exercise per draft, and without
// this button the student copy-pastes eight times by hand the night before
// the deadline.
//
// LOADED ON DEMAND, like the other modules: neither the anonymous visitor
// nor a student working an exercise with nothing to hand in downloads it.
//
// ONE WAY, NEVER A CYCLE: `window.ctester` carries the shared state (the
// catalog, the drafts, the token) and the core's functions; this file is
// never imported by app.js, it registers itself into it.
(function (ctester) {

// THE FILE SHIPS IN UTF-8 WITH ITS BYTE ORDER MARK. Without it, Visual
// Studio reads a header-less file in the system code page (cp1252 on the
// lab's Windows machines) and every accented character in the comments --
// the student's own, not ours -- turns to gibberish on open. This is exactly
// what shows up in the course's own template file. gcc and CLion skip the
// mark without a word.
const UTF8_BOM = "﻿";

const NUM_RE = /-ex(\d+)$/;
const INCLUDE_RE = /^[ \t]*#[ \t]*include\b/;
// THE INCLUDED HEADER, NOT THE WHOLE LINE. This is the deduplication key:
// `#include <stdio.h>  // pour printf` and `#include <stdio.h>` are the SAME
// include, and keeping both because a student commented theirs would defeat
// exactly what the button promises.
const HEADER_RE = /^[ \t]*#[ \t]*include[ \t]*(<[^>]*>|"[^"]*")/;
const OPEN_RE = /^[ \t]*#[ \t]*(if|ifdef|ifndef)\b/;
const CLOSE_RE = /^[ \t]*#[ \t]*endif\b/;
const CRT_RE = /^[ \t]*#[ \t]*define[ \t]+_CRT_SECURE_NO_WARNINGS\b/;

const NO_CODE =
  "    /* Aucun code enregistré pour cet exercice dans CTester :\n"
+ "       rien n'y a été écrit, ou le brouillon est resté sur un autre poste\n"
+ "       parce qu'il n'était pas connecté. */";

const twoDigits = (n) => String(n).padStart(2, "0");

// THE READER'S DATE, NOT UTC'S. `toISOString()` in the evening in Montreal
// dates the file to the next day, and a hand-in dated one day ahead is
// exactly the kind of detail that comes up out loud.
function today() {
  const t = new Date();
  return t.getFullYear() + "-" + twoDigits(t.getMonth() + 1)
       + "-" + twoDigits(t.getDate());
}

// THE NUMBER COMES FROM THE ID, not from the rank: `tp2-ex0` is the preamble
// and it must stay the statement's 0, or the whole file shifts by one
// compared to what the instructor reads. The rank is only a safety net for
// an id that would not end in `-exN` -- none today, and every "io" exercise
// has one.
function numberOf(tp, rank) {
  const found = NUM_RE.exec(tp.id);
  return found ? Number(found[1]) : rank;
}

function labelForNumbers(numbers) {
  if (!numbers.length) return "Aucun exercice";
  if (numbers.length === 1) return "Exercice " + numbers[0];
  const contiguous = numbers.every((n, i) => i === 0 || n === numbers[i - 1] + 1);
  return contiguous
    ? "Exercices " + numbers[0] + " à " + numbers[numbers.length - 1]
    : "Exercices " + numbers.join(", ");
}

// SEPARATING WHAT GETS HOISTED FROM WHAT STAYS. `#include` directives are
// hoisted to the top of the file and deduplicated -- that is what the format
// asks for, and two `#include <stdio.h>` in two `#if` blocks bother nobody
// but the same header eight times makes the file unreadable.
//
// ONLY AT THE TOP LEVEL, AND THAT IS THE SUBTLETY. A `#include` already
// inside a student `#if` is there FOR that condition: hoisting it would make
// it unconditional and change the meaning of their code. So we count
// conditional nesting depth instead of scanning the text blindly.
//
// `#define` directives stay where they are: two exercises in the same lab
// commonly define the same constants (`DIMANCHE`, `LUNDI`, ...) and it is
// precisely the `#if` that keeps them from clashing. Only
// `_CRT_SECURE_NO_WARNINGS` leaves, because the file already sets it at the
// top.
function disassemble(code) {
  const includes = [];
  const lines = [];
  let depth = 0;
  for (const line of code.split(/\r?\n/)) {
    if (CLOSE_RE.test(line)) {
      depth = Math.max(0, depth - 1);
      lines.push(line);
      continue;
    }
    if (depth === 0 && INCLUDE_RE.test(line)) {
      // The LINE is kept as-is -- its comment belongs to the student -- but
      // it is the header that identifies the duplicate.
      const found = HEADER_RE.exec(line);
      includes.push({ cle: found ? found[1] : line.trim(),
                      ligne: line.trim() });
      continue;
    }
    if (depth === 0 && CRT_RE.test(line)) continue;
    if (OPEN_RE.test(line)) depth += 1;
    lines.push(line);
  }
  return { includes: includes, corps: lines.join("\n") };
}

// THE HOLE INCLUDES LEAVE BEHIND. Removing three lines from a header block
// leaves three blank lines in their place, and the handed-in file opens on
// an accordion of blanks. Runs of blank lines are folded to one, along with
// leading and trailing blanks.
const trim = (text) => text
  .replace(/^(?:[ \t]*\r?\n)+/, "")
  .replace(/\s+$/, "")
  .replace(/\n(?:[ \t]*\n){2,}/g, "\n\n");

// The code for ONE exercise, in its declared files' order. An "io" exercise
// fits in a single file (`submission.c`) and that is the normal case; the
// day it has two, they get glued back together with their name as a
// comment rather than silently dropped.
function codeOf(tp, sources) {
  const files = (tp.files && tp.files.length)
    ? tp.files : [{ name: "submission.c" }];
  const pieces = [];
  for (const file of files) {
    const text = sources && sources[file.name];
    if (typeof text !== "string" || !text.trim()) continue;
    pieces.push(files.length > 1
      ? "/* " + file.name + " */\n" + text : text);
  }
  return pieces.join("\n\n");
}

// THE LOCAL DRAFT FIRST, THE ACCOUNT NEXT. `localStorage` has everything
// this device has seen, which covers the vast majority of cases; exercises
// worked on elsewhere only live on the account.
//
// ONE AT A TIME, NOT IN PARALLEL: `/brouillon` goes through `state.py`'s
// single Postgres connection, behind its global lock. Firing ten requests at
// once would not go any faster and would take the queue away from everyone
// while another student submits. Worst case, it costs one second on a
// download button.
async function gather(exercises) {
  const found = {};
  const missing = [];
  for (const tp of exercises) {
    const local = ctester.brouillon(tp.id);
    if (local && codeOf(tp, local)) found[tp.id] = local;
    else missing.push(tp);
  }
  if (!missing.length || !ctester.token() || !ctester.compte) return found;
  for (const tp of missing) {
    const response = await ctester.compte.getJson(
      "brouillon?ex=" + encodeURIComponent(tp.id));
    if (response && response.sources) found[tp.id] = response.sources;
  }
  return found;
}

// THE NAME PRE-FILLS, IT DOES NOT IMPOSE ITSELF. CTester only ever knows a
// student by an opaque `sub`: the only name it ever has is the one typed
// into "Mon identité", or the suggestion Rauthy reports. Same treatment as
// the identity form -- a field the student rereads before handing it in is
// pre-filled, in a file that goes onto THEIR OWN disk and nowhere else.
// Nothing is published, and the field stays empty when unknown.
async function author() {
  const config = ctester.oidc();
  if (!ctester.token() || !ctester.compte || !(config && config.forum)) return "";
  const profile = await ctester.compte.getJson("forum/profil");
  if (!profile || typeof profile !== "object") return "";
  return String(profile.display_name || profile.suggestion || "").trim();
}

function header(name, group, numbers, first) {
  return [
    "/*",
    "Fichier : main.c",
    "Auteur : " + name,
    "Date : " + today(),
    "Description : " + labelForNumbers(numbers) + " — " + group + " — TCH009",
    "*/",
    "/* *******************************************************",
    "* Commande de preprocesseur",
    "******************************************************* */",
    "#define _CRT_SECURE_NO_WARNINGS",
    "/* Ce numéro choisit l'exercice qui sera compilé : change-le pour tester",
    "   un autre exercice de ce fichier. */",
    "#define exercice " + first,
  ].join("\n");
}

// THE WHOLE FILE, from the catalog and the drafts. Rendered separately from
// the download so it can be tested: this is the text checked in
// `test_page.js`, not the click.
function build(exercises, sources, name, group) {
  const includes = [];
  const blocks = [];
  const numbers = [];
  const empty = [];
  // `null`, AND ESPECIALLY NOT `0`. Lab 2's preamble is exercise NUMBER 0:
  // with a counter starting at zero, `if (!first)` would take it for
  // "nothing found yet" and the file would open on the following block.
  let first = null;
  exercises.forEach((tp, rank) => {
    const number = numberOf(tp, rank + 1);
    numbers.push(number);
    const code = codeOf(tp, sources[tp.id]);
    const title = "/* Exercice " + number + " — " + (tp.short || tp.id) + " */";
    if (!code) {
      empty.push(number);
      blocks.push(title + "\n#if exercice == " + number
               + "\n" + NO_CODE + "\n#endif");
      return;
    }
    // THE FIRST EXERCISE THAT HAS CODE, not simply the first one: a file
    // that opens on an empty block does not compile, and the student
    // concludes the export is broken.
    if (first === null) first = number;
    const piece = disassemble(code);
    for (const inc of piece.includes) {
      if (!includes.some((seen) => seen.cle === inc.cle)) includes.push(inc);
    }
    blocks.push(title + "\n#if exercice == " + number
             + "\n" + trim(piece.corps) + "\n#endif");
  });
  const text = [
    header(name, group, numbers,
           first === null ? (numbers[0] === undefined ? 1 : numbers[0]) : first),
    includes.map((inc) => inc.ligne).join("\n"),
    blocks.join("\n\n"),
  ].filter(Boolean).join("\n\n") + "\n";
  return { texte: text, vides: empty, total: exercises.length };
}

// ONLY ONE LIVE URL AT A TIME. `revokeObjectURL` right after the click
// chases the download the browser just started; putting it on a timer works
// but leaves a timer lying around. We revoke the PREVIOUS one at the start
// of the next export: never a race, never more than one live blob.
let previousUrl = null;

function download(file, text) {
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  const blob = new Blob([UTF8_BOM + text], { type: "text/plain;charset=utf-8" });
  previousUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = previousUrl;
  link.download = file;
  document.body.append(link);
  link.click();
  link.remove();
}

// `announce(text, failed)`: THE CALLER SAYS WHERE IT DISPLAYS. The action
// bar's button writes on the draft's line, "Mes progrès"'s button next to
// itself -- and `#brouillon` is not even on screen from the list view. A
// module choosing its own spot would write into the void half the time.
async function exportGroup(group, announce) {
  const exercises = ctester.exercicesExportables(group);
  if (!exercises.length) {
    announce("rien à exporter pour " + group, true);
    return null;
  }
  announce("assemblage de " + group + "…");
  const sources = await gather(exercises);
  const built = build(exercises, sources, await author(), group);
  if (built.vides.length === built.total) {
    announce("aucun code enregistré pour " + group + " : rien à exporter", true);
    return built;
  }
  try {
    download("main.c", built.texte);
  } catch (e) {
    announce("le téléchargement a échoué — copie ton code à la main", true);
    return built;
  }
  const written = built.total - built.vides.length;
  announce("main.c exporté — " + written + " exercice"
         + (written > 1 ? "s" : "") + " sur " + built.total
         + (built.vides.length
            ? " (rien pour : " + built.vides.join(", ") + ")" : ""));
  return built;
}

ctester.exporter = {
  exporter: exportGroup,
  // Exposed for the test harness: the produced text is what matters, and it
  // must be testable with no click and no blob involved.
  construire: build,
  demonter: disassemble,
};
})(window.ctester);
