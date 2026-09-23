# The content format

CTester ships no exercises. A content repository supplies them, and the engine reads it
without knowing anything about the course inside. This page describes the format that
repository must follow; [typst.md](typst.md) covers statement presentation.

`scripts/demo_content.py` writes a small example of everything below (all three modes, a
reference solution per exercise, collections and a card) and publishes it through the real
pipeline:

```sh
python3 scripts/demo_content.py --out /tmp/demo   # writes /tmp/demo/content
python3 scripts/validate_content.py /tmp/demo/content
python3 scripts/verify_content.py   /tmp/demo/content
```

Read that tree next to this page. The validator, `worker/content_catalog.py`, is the
final authority: anything it refuses never reaches a student.

## The tree

```
<root>/
  catalog.json                    the skill vocabulary, and the words to show for each
  cards.json                      optional: the collection's cards
  shared/unity/                   Unity's sources, for unity-mode exercises
  collections/<id>.json           how the menu groups exercises
  assignments/<id>.json           optional: team work with one hand-in
  exercises/<id>/
    exercise.json                 the manifest
    statement.md | statement.typ  the brief, exactly one of the two
    public/files.json             the files the student submits
    assessment/
      quiz.json | io.json | unity.json    exactly one: it decides the mode
      test_*.c                            unity mode only
      allowed_includes.txt                optional, both compiled modes
    solution/                     the reference solution
```

`CTESTER_CONTENT` may name several roots joined by `:`; `discover()` merges them into one
flat namespace. Exercise ids must be unique across every root, and a duplicate fails the
publication. Only one root may hold `shared/unity`.

## Identifiers

An exercise id matches `[a-z0-9][a-z0-9-]{0,62}` and the directory must be named after
it. The id travels to the browser, comes back in a submission, and is then joined to a
root path on the server; allowing a slash would reopen the directory traversal the
validation exists to close.

Renaming a directory changes the id, which breaks deep links and orphans anything already
recorded against it. Do it between sessions, not in the middle of one.

Collection and assignment ids use the same pattern. The menu sorts them naturally, so `tp2`
comes before `tp10`.

## `catalog.json`

```json
{
  "schema_version": 1,
  "skills": [
    {"id": "boucles", "label": "boucles"},
    {"id": "entrees-sorties", "label": "entrées/sorties"},
    "tableaux"
  ]
}
```

The skill vocabulary belongs to the content. An entry is an id matching
`[a-z][a-z0-9-]{0,47}`, or that id with the `label` the page should show for it; a bare
string is an id with no label, and an unlabelled skill shows its id. An exercise naming a
skill that is not declared here fails the publication, so a typo cannot invent a skill.

With several roots, the vocabularies are unioned: an exercise may use a skill another
repository declared.

## `exercise.json`

```json
{
  "schema_version": 1,
  "id": "tp1-ex1",
  "title": "Additionner deux entiers",
  "release": {"state": "scheduled", "available_from": "2026-10-09T13:26:39-04:00"},
  "skills": ["entrees-sorties", "types"],
  "difficulty": "intro",
  "contexts": ["general-engineering"]
}
```

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | always `1` |
| `id` | yes | equal to the directory name |
| `title` | yes | shown in the menu |
| `summary` | no | one line under the title |
| `release` | yes | see below |
| `skills` | no | ids declared in `catalog.json`, no duplicates |
| `difficulty` | no | `intro`, `foundation`, `intermediate` or `advanced` |
| `contexts` | no | free-form strings: what the problem is about |
| `prerequisites` | no | exercise ids |
| `verification` | no | boolean: this one counts as a check, not practice |
| `bonus` | no | boolean |

`difficulty` is what the XP table in `app/policy.py` keys on. An unlisted value is refused; a missing one earns the default award.

### `release`

```json
{"state": "available"}
{"state": "scheduled", "available_from": "2026-10-09T13:26:39-04:00"}
{"state": "archived"}
```

`scheduled` requires an ISO 8601 `available_from` with a timezone. Until that moment
the catalogue omits the entry: it is not in the menu and a deep link does not resolve.
`tests/vectors/release_access.json` binds the Python and Rust readings of this rule.

## The mode comes from the file

The mode is deduced from which file is present in `assessment/`; there is no field for it.

| File | Mode | What the student submits |
|---|---|---|
| `quiz.json` | quiz | answers typed into fields |
| `io.json` | io | a whole program, with its `main()` |
| `unity.json` + `test_*.c` | unity | a module, without `main()` |

Exactly one of the three per exercise. In unity mode `unity.json` is usually `{}`: it
only selects the mode.

## `public/files.json`

```json
{"files": [
  {"name": "calcul.h", "template": "#ifndef CALCUL_H\n..."},
  {"name": "calcul.c", "template": "#include \"calcul.h\"\n"}
]}
```

Each entry becomes an editor tab, pre-named and pre-filled with its optional `template`.
A name matches `[A-Za-z0-9_]{1,32}\.[ch]`; anything resembling a path is refused.

The names are imposed: the student's own `#include "calcul.h"`, and the test file's, only
resolve if the file has exactly that name.

No `files.json` means a single `submission.c`.

## `io.json` — whole programs

```json
{
  "note": "a comment for you, never shown to the student",
  "tolerance": 0.005,
  "cases": [
    {"stdin": "12\n4\n", "expect": [3]},
    {"stdin": "5\n2\n",  "expect": [2.5]}
  ]
}
```

The program is compiled with its `main()`, then run once per case with `stdin` on
standard input.

The output is compared by its numbers. A brief says "print the current" without fixing a
format, so one student writes `I = 2.50 A` and another `2.5`. The judge extracts every
number from the output and checks that the `expect` values appear in order, as a
subsequence, within `tolerance` (relative, 0.005 by default). Prompts, units, re-printed
inputs and extra decimals all pass.

When writing cases:

- Keep expected values above 1 in absolute value. A student printing `%.2f` is off by up to
  0.005, which is within the tolerance only above 1.
- Write floats in decimal (`0.000001`), never in scientific notation.
- Include a case that catches a classic mistake: `5 / 2` fails under integer division.

For a program that draws at random, there is no expected value, only bounds:

```json
{"stdin": "", "in_range": [1, 6], "count": 5}
```

means at least 5 of the printed numbers fall between 1 and 6. It is "at least" because a
prompt such as "rolling 100 times" prints a 100 too.

For textual rather than numeric output:

```json
{"stdin": "1\n", "contains": "laminaire", "absent": ["turbulent", "transitoire"]}
```

`contains` ignores case and accents. `absent` matters: without it, a program whose
prompt lists all three words passes every case without computing anything.

On failure the student sees the case number, their input and their own output. The expected
value is never shown, or students would print constants.

## `unity.json` + `test_*.c` — modules

The student writes a module: a `.h` and a `.c` whose prototypes the statement dictates.
The `test_*.c` files next to `unity.json` supply `main()`, `setUp()` and `tearDown()`.

The test file may `#include "calcul.h"`: the sandbox compiles with `-I` on the student's
sources, so the student's own header is included.

`-DUNITY_INCLUDE_DOUBLE` is on. Unity 2.6 defines `UNITY_EXCLUDE_DOUBLE` by default, and
without the macro `TEST_ASSERT_DOUBLE_WITHIN` compiles but always fails, so add it when you
compile a test by hand.

For any floating value use `TEST_ASSERT_DOUBLE_WITHIN` (or `TEST_ASSERT_FLOAT_WITHIN`)
with a tolerance, never `TEST_ASSERT_EQUAL`.

Test names must fit `[A-Za-z0-9_]` and 64 characters: they are what the student sees when
they fail, so name them for the student: `test_pop_pile_vide` rather than `test_3b`.

Unity's own sources (v2.6.1, MIT) go in `shared/unity/` at the root. The engine does not
ship them; `tests/fixture/unity/` is a minimal stand-in for CTester's own checks.

## `quiz.json` — questions

```json
{
  "label": "TP1: number encodings",
  "questions": [
    {"id": "e1-23", "group": "Exercise 1: decimal to binary (8 bits)",
     "label": "23", "type": "bin8", "answer": "00010111"}
  ]
}
```

`group` is the section heading; `label` is what sits left of the field. `id` must be
unique and stable: it travels between the browser and the server.

`type` is one of `int`, `bin`, `bin8`, `hex8`, `choice`, `multi`, `bool`, `text`,
`number`, `match`, `order`, `cloze`, and decides what is accepted:

| type | accepts | refuses |
|---|---|---|
| `bin8` | `00010111`, `0001 0111`, `0b00010111` | `10111` (the student is told the brief asks for 8 bits) |
| `hex8` | `17`, `0x17`, `0X17`, `17h`, lowercase, leading zeros | a numerically different value |
| `int` | `-49`, `+84`, `84`, surrounding spaces | anything that is not an integer |

A `cloze` marks its gaps with three or more underscores (`___`). The student learns which
questions are wrong, never the right answer.

## `allowed_includes.txt`

One header per line. Its presence limits the submitted file's `#include`s to that list;
its absence disables the check.

## `solution/` — the reference solution

One correct solution per exercise, to prove the tests are right: a wrong test sends students
hunting a bug that does not exist.

```sh
python3 scripts/verify_content.py <root>
```

compiles each solution against its own tests, in the real judge, and demands that it
pass. Exercises with no `solution/` are reported as unproven. `CTESTER_SOLUTIONS` points
at an outside tree holding `<that root>/<exercise id>/` instead.

A solution is never catalogued, never published and never mounted in the sandbox: only
`assessment/` and `shared/unity/` are. A test asserts that it cannot reach the published
tree, and `worker/typst_build.py` keeps it out of the directory Typst renders in.

## `collections/<id>.json`

```json
{"schema_version": 1, "id": "tp1", "title": "TP 1", "description": "",
 "items": ["tp1-ex1", "tp1-ex2"], "release": {"state": "available"}}
```

`items` are exercise ids, in the order the menu shows them; an unknown id fails the
publication. An exercise in no collection lands in a trailing "Others" group.

## `assignments/<id>.json`

Team work: the same shape as a collection, plus `team` (`min`, `max`, `count`) and
`handin`, which describes the ZIP the team hands in:

```json
"handin": {"root": "Devoir", "files": [
  {"name": "main.c", "exercise_id": "dev-a", "file": "main.c"}
]}
```

An exercise may belong to at most one assignment.

## `cards.json` — the collection

Optional. Without `cards.json`, the collection screen is empty.

```json
{"schema_version": 1, "cards": [
  {"id": "D-01", "name": "Compas", "family": "atelier", "art": "gear",
   "exercises": ["tp1-ex1"], "condition": "Réussir le premier exercice"}
]}
```

A card drops when the student has solved every exercise it names. `condition` is the
sentence shown while it is locked; `art` names one of the drawings the page ships
(`resistor`, `bearing`, `relay`, `gear`, `cylinder`, `diode`, `spring`, `sensor`); an
unknown one draws nothing.

Card ids are stored against the accounts that earned them, so they must never change. A card naming an exercise that does not exist fails the publication rather than
becoming quietly unobtainable.

## What the engine defines, and what you do

| The engine fixes | You choose |
|---|---|
| the four `difficulty` values, and the XP each is worth | which exercise is which |
| the three modes and their file names | which mode each exercise uses |
| the twelve quiz types | the questions |
| the achievements, levels, divisions and mastery bands | nothing: they count generically |
| the eight card drawings | the cards, their names and their conditions |
| the comparison rules for `io` output | the cases |
| — | every skill id and its wording |

Nothing in `app/`, `worker/` or `judge/` names an exercise, a collection or a skill.
