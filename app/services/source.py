"""Canonical form of submitted source: BOM, CR/CRLF and trailing blanks removed.

No imports on purpose: the host-side checks import this without dependencies.
The line count never changes, so compiler line numbers still match the editor.
"""

_DEAD = " \t"


def canonicalize(text):
    if not text:
        return text
    if text[0] == "\ufeff":
        text = text[1:]
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if (" \n" not in text and "\t\n" not in text
            and not text.endswith(" ") and not text.endswith("\t")):
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        cut = line.rstrip(_DEAD)
        # A backslash-newline splice keeps its blanks: gcc warns about them there.
        if cut != line and not cut.endswith("\\"):
            lines[i] = cut
    return "\n".join(lines)


def canonicalize_files(files):
    return {name: canonicalize(text) for name, text in files.items()}
