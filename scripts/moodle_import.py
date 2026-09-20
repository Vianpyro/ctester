#!/usr/bin/env python3
"""Turns a Moodle XML question bank into CTester quiz.json files.

Standard library only, like the rest of the content pipeline: it runs with the host Python
on the Dell and imports worker/content_catalog.py to apply the very same checks the
publication does, so it can never write a quiz that validate_content.py would refuse.

What Moodle can express and CTester cannot is reported, never dropped in silence.
"""

import argparse
import html.parser
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "worker"))

import content_catalog  # noqa: E402

# Moodle writes a gap as [[1]] in gapselect and ddwtos; CTester writes it as ___.
PLACEHOLDER_RE = re.compile(r"\[\[(\d+)\]\]")
CLOZE_RE = re.compile(r"\{\s*\d*\s*:\s*(SHORTANSWER|SA|MW|MULTICHOICE|MC|MCH|MCV|MCVS|"
                      r"NUMERICAL|NM)\s*:(.*?)\}", re.IGNORECASE | re.DOTALL)

REFUSED = {
    "essay": "manual grading, which CTester has no place for",
    "calculated": "a dataset and per-student randomisation",
    "calculatedsimple": "a dataset and per-student randomisation",
    "calculatedmulti": "a dataset and per-student randomisation",
    "ddimageortext": "positional dragging on an image",
    "ddmarker": "positional dragging on an image",
    "random": "it resolves against the bank at run time",
    "randomsamatch": "it resolves against the bank at run time",
}


class _Text(html.parser.HTMLParser):
    """Moodle question text is HTML. Only the words survive; an image is reported lost."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.images = 0

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images += 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li"):
            self.parts.append("\n")


def plain(node, report=None, name=""):
    """The <text> of a Moodle element, as words."""
    found = node.find("text") if node is not None else None
    raw = (found.text or "") if found is not None else ""
    reader = _Text()
    reader.feed(raw)
    reader.close()
    text = re.sub(r"\n{2,}", "\n", "".join(reader.parts)).strip()
    if reader.images and report is not None:
        report.lost(name, "%d image(s) dropped: the statement is plain text here"
                    % reader.images)
    return text


def fraction(answer):
    try:
        return float(answer.get("fraction", "0"))
    except ValueError:
        return 0.0


def slug(text):
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                     if not unicodedata.combining(c))
    cut = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:63]
    return cut or "quiz"


class Report:
    def __init__(self):
        self.lines = []
        self.refused = 0

    def lost(self, name, what):
        self.lines.append("  %-40s %s" % (name[:40], what))

    def refuse(self, name, why):
        self.refused += 1
        self.lines.append("  %-40s REFUSED: needs %s" % (name[:40], why))

    def show(self):
        if not self.lines:
            print("nothing was lost in translation")
            return
        print("%d note(s), %d question(s) refused:" % (len(self.lines), self.refused))
        for line in self.lines:
            print(line)


def _accept(texts):
    return {"accept": texts} if len(texts) > 1 else texts[0]


def _answers(node):
    return node.findall("answer")


def _partial(question, name, report):
    odd = [a for a in _answers(question) if 0.0 < fraction(a) < 100.0]
    if odd:
        report.lost(name, "partial credit on %d answer(s) is lost: CTester grades a "
                          "question all-or-nothing" % len(odd))


def _feedback(question, name, report):
    texts = [plain(f) for f in question.findall(".//feedback")]
    texts += [plain(f) for f in question.findall("generalfeedback")]
    kept = [t for t in texts if t]
    if kept:
        report.lost(name, "%d feedback text(s) have no home; the first reads: %r"
                    % (len(kept), kept[0][:60]))


def convert(question, report):
    """One Moodle <question> as a CTester question, or None when it cannot travel."""
    kind = question.get("type", "")
    name = plain(question.find("name")) or "(sans nom)"
    if kind in REFUSED:
        report.refuse(name, REFUSED[kind])
        return None
    if plain(question.find("hidden")) == "1" or (question.findtext("hidden") or "").strip() == "1":
        report.lost(name, "hidden in Moodle: skipped")
        return None

    label = plain(question.find("questiontext"), report, name)
    out = {"label": label or name}
    right = [a for a in _answers(question) if fraction(a) >= 100.0]

    if kind == "truefalse":
        true_answer = next((a for a in _answers(question)
                            if plain(a).strip().lower() in ("true", "vrai")), None)
        if true_answer is None:
            report.refuse(name, "a true/false pair")
            return None
        out.update(type="bool", answer=fraction(true_answer) >= 100.0)
    elif kind == "multichoice":
        options = [plain(a) for a in _answers(question)]
        if len(set(options)) < 2:
            report.refuse(name, "at least two distinct options")
            return None
        _partial(question, name, report)
        single = (question.findtext("single") or "true").strip().lower() == "true"
        chosen = [plain(a) for a in _answers(question) if fraction(a) > 0.0]
        if not chosen:
            report.refuse(name, "at least one correct option")
            return None
        if single:
            if len(right) != 1:
                report.refuse(name, "exactly one 100% option")
                return None
            out.update(type="choice", options=options, answer=plain(right[0]))
        else:
            if len(chosen) == len(set(options)):
                report.refuse(name, "at least one wrong option")
                return None
            out.update(type="multi", options=options, answer=chosen)
    elif kind == "shortanswer":
        spellings = [plain(a) for a in right]
        if not spellings:
            report.refuse(name, "at least one 100% answer")
            return None
        _partial(question, name, report)
        out.update(type="text", answer=_accept(spellings))
        if (question.findtext("usecase") or "0").strip() == "1":
            out["answer"] = {"accept": spellings, "strict": True}
    elif kind == "numerical":
        if not right:
            report.refuse(name, "a correct value")
            return None
        try:
            value = float(plain(right[0]).replace(",", "."))
        except ValueError:
            report.refuse(name, "a numeric answer")
            return None
        margin = 0.0
        raw = right[0].findtext("tolerance")
        if raw:
            try:
                margin = abs(float(raw.replace(",", ".")))
            except ValueError:
                margin = 0.0
        units = [plain(u.find("unit_name")) for u in question.findall(".//unit")]
        units = [u for u in units if u]
        if units:
            report.lost(name, "unit %r is not graded; it was added to the label" % units[0])
            out["label"] = "%s (%s)" % (out["label"], units[0])
        out.update(type="number", answer={"value": value, "margin": margin})
    elif kind == "matching":
        pairs, distractors = {}, []
        for sub in question.findall("subquestion"):
            left = plain(sub)
            partner = plain(sub.find("answer"))
            if not partner:
                continue
            if left:
                pairs[left] = partner
            else:
                distractors.append(partner)
        if len(pairs) < content_catalog.MATCH_MIN:
            report.refuse(name, "at least %d pairs" % content_catalog.MATCH_MIN)
            return None
        out.update(type="match", answer=pairs)
        if distractors:
            out["options"] = distractors
    elif kind == "ordering":
        items = [plain(a) for a in sorted(_answers(question), key=fraction)]
        items = [one for one in items if one]
        if len(set(items)) < content_catalog.ORDER_MIN:
            report.refuse(name, "at least %d distinct items" % content_catalog.ORDER_MIN)
            return None
        out.update(type="order", answer=items)
    elif kind in ("gapselect", "ddwtos"):
        template, gaps = _gapselect(question, label, report, name)
        if template is None:
            return None
        out.update(type="cloze", label=name, template=template, answer=gaps)
    elif kind == "cloze" or kind == "multianswer":
        template, gaps = _embedded(question, label, report, name)
        if template is None:
            return None
        out.update(type="cloze", label=name, template=template, answer=gaps)
    else:
        report.refuse(name, "a CTester equivalent for Moodle type %r" % kind)
        return None

    _feedback(question, name, report)
    if (question.findtext("shuffleanswers") or "").strip() in ("1", "true"):
        report.lost(name, "shuffleanswers is ignored: the publication fixes the order")
    return out


def _gapselect(question, label, report, name):
    """[[1]] placeholders plus <selectoption> groups."""
    groups = {}
    for option in question.findall("selectoption"):
        groups.setdefault((option.findtext("group") or "1").strip(), []).append(plain(option))
    numbers = PLACEHOLDER_RE.findall(label)
    if not numbers:
        report.refuse(name, "at least one [[n]] gap")
        return None, None
    gaps = []
    for number in numbers:
        # Moodle groups the choices; the first of a group is the correct one.
        choices = groups.get(number) or groups.get("1") or []
        if len(set(choices)) < 2:
            report.refuse(name, "at least two choices per gap")
            return None, None
        gaps.append({"accept": [choices[0]], "choices": choices})
    return PLACEHOLDER_RE.sub("___", label), gaps


def _embedded(question, label, report, name):
    """Inline {1:SHORTANSWER:=right~wrong} fields."""
    gaps = []
    for _kind, body in CLOZE_RE.findall(label):
        right = [one.lstrip("=").split("#")[0].strip()
                 for one in body.split("~") if one.strip().startswith("=")]
        if not right:
            report.refuse(name, "a marked = answer in every embedded field")
            return None, None
        gaps.append(_accept(right) if len(right) > 1 else {"accept": right})
    if not gaps:
        report.refuse(name, "at least one embedded field")
        return None, None
    return CLOZE_RE.sub("___", label), gaps


def read(path, report, group_from="category"):
    """Every convertible question of a Moodle export, grouped by its Moodle category."""
    root = ET.parse(path).getroot()
    grouped, category = {}, "Questions"
    counter = 0
    for question in root.findall("question"):
        if question.get("type") == "category":
            category = (plain(question.find("category")) or category).split("/")[-1]
            continue
        counter += 1
        converted = convert(question, report)
        if converted is None:
            continue
        ident = (question.findtext("idnumber") or "").strip()
        if not content_catalog.QUESTION_ID_RE.match(ident or ""):
            ident = "q%d" % counter
        converted["id"] = ident
        converted["group"] = category if group_from == "category" else converted["label"][:60]
        grouped.setdefault(category, []).append(converted)
    return grouped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", help="the Moodle XML file")
    parser.add_argument("--out", required=True,
                        help="the content root's exercises/ directory")
    parser.add_argument("--exercise-id", default="",
                        help="fold every category into this one exercise")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing quiz.json")
    args = parser.parse_args(argv)

    report = Report()
    grouped = read(args.export, report)
    if not grouped:
        report.show()
        print("nothing could be converted")
        return 1

    if args.exercise_id:
        grouped = {args.exercise_id: [q for one in grouped.values() for q in one]}

    written = 0
    for category, questions in sorted(grouped.items()):
        exercise_id = args.exercise_id or slug(category)
        if not content_catalog.EXERCISE_RE.match(exercise_id):
            print("skipped %r: %r is not a usable exercise id" % (category, exercise_id))
            continue
        quiz = {"label": category, "questions": questions}

        # The same checks the publication runs: this tool cannot write content that
        # validate_content.py would then refuse.
        errors = []
        content_catalog._quiz(quiz, "%s/assessment/quiz.json" % exercise_id, errors)
        if errors:
            print("refused %s, it would not publish:" % exercise_id)
            for one in errors:
                print("  " + one)
            continue

        target = os.path.join(args.out, exercise_id, "assessment", "quiz.json")
        if os.path.exists(target) and not args.force:
            print("skipped %s: %s already exists (use --force)" % (exercise_id, target))
            continue
        print("%s: %d question(s) -> %s" % (exercise_id, len(questions), target))
        if args.dry_run:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(quiz, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        written += 1

    report.show()
    if not args.dry_run and written:
        print("\nexercise.json and statement.md are still yours to write for each exercise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
