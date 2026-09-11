"""The canonical form of a student's source. NO IMPORTS, NOT EVEN `re`.

Three transformations, all of them invisible on screen: a leading UTF-8 BOM is
dropped, CRLF and lone CR become LF, and dead whitespace at the end of a line
is cut. Nothing else. It is applied at the HTTP boundary, so what Postgres
stores, what the spool holds and what gcc compiles are all the same canonical
bytes.

THE LINE COUNT NEVER CHANGES, AND THAT IS WHAT MAKES THIS INVISIBLE. The
editor's gutter is `value.split("\\n").length` (`CodeSurface.svelte`): one `\\n`
more or less is a line NUMBER appearing or disappearing under the student's
eyes. It is also what keeps gcc's line numbers pointing at the line the
student is looking at -- the verdict names a line, and that line must be the
one they see.

IT CAN ONLY EVER SHRINK, and that is what lets it sit BEFORE the `MAX_CODE`
bound in `validate_files`: the function measures the bytes it returns. A
transform that could grow the payload would have to be bounded twice, and
`scratch_draft`'s `CHECK (length(code) <= 65536)` would turn that one extra
byte into "la base ne répond pas" on a notepad the student wrote correctly.

NO IMPORT AT ALL, and that is not an accident -- same reason as `app/csp.py`.
`test_ctester.py` is run by `pull.sh` and by the Ansible verification with the
HOST'S python, without `PYTHONPATH=/deps`. One import too many there does not
fail a test: it blocks the automatic deployment every five minutes on an
`ImportError`, with nothing deployed. A module that imports nothing can never
be that module. It is also why the Console can call this without reaching
into `services.catalog`, which reads a published release -- a console has no
exercise.

FOUR TRANSFORMATIONS DELIBERATELY REFUSED, each because it would be SEEN:

  - Trailing BLANK LINES at end of file. 38 of the 89 non-empty templates in
    the course end with one on purpose -- it is the empty line where the
    student is meant to type (`devoir-ascension/matrac_lib.c` and friends).
    Cutting it moves their caret and takes a gutter row with it. And the
    other half of that rule buys nothing: NOT ONE template lacks a final
    newline, and no build script passes `-pedantic`, so there is no
    "no newline at end of file" diagnostic to spare anyone.
  - Tabs to spaces, and blank lines collapsed inside the file: both change
    what is drawn.
  - NBSP and zero-width spaces. Inside a string literal they are the
    student's data, and this function does not lex -- it cannot tell.
  - Anything on the forum. Two trailing spaces there are a hard line break
    in Markdown: cutting them would rewrite what someone wrote on purpose.
"""

# What gets cut at the end of a line. NEITHER \v NOR \f: a form feed in an
# old source is a character someone put there, not an editor artefact, and it
# costs one byte.
_DEAD = " \t"


def canonicalize(text):
    """The text, without a BOM, in LF, with no dead whitespace at line ends.

    A LINE ENDING IN A BACKSLASH IS LEFT ALONE. `\\` followed by spaces then a
    newline is a line splice that gcc accepts WHILE REPORTING IT ("backslash
    and newline separated by space"): cutting those spaces would silence the
    diagnostic without fixing anything, and the student would lose a warning
    rather than gain a correction. It covers multi-line `#define`s and spliced
    string literals for free, where the trailing blank is INSIDE the literal.

    The lone-CR rule is the one place the line count can move, and it moves it
    toward the truth: a bare `\\r` is one line to gcc and a line break to the
    textarea, so converting it makes the gutter and the verdict agree.
    """
    if not text:
        return text
    if text[0] == "\ufeff":
        text = text[1:]
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    # FAST PATH, WITHOUT `re`. A line with dead whitespace necessarily ends in
    # " \n" or "\t\n", and a last line without a terminator in " " or "\t".
    # Almost every submission takes this branch and is returned untouched.
    if (" \n" not in text and "\t\n" not in text
            and not text.endswith(" ") and not text.endswith("\t")):
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        cut = line.rstrip(_DEAD)
        if cut != line and not cut.endswith("\\"):
            lines[i] = cut
    return "\n".join(lines)


def canonicalize_files(files):
    """The same gesture over a {name: text} mapping. A NEW dict."""
    return {name: canonicalize(text) for name, text in files.items()}
