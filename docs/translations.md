# Translations

Everything a student reads comes from one file per language in
[frontend/src/locales/](../frontend/src/locales/). The API and the judge send keys and codes
rather than sentences (`{"error": "db_down"}`, `"reason": "interrupted"`, with `params` when the
wording needs values), and the page words them.

## The files

`en.json` is the source. It has every key, other languages fall back to it for any key they
lack, and new text goes there first.

The files use the i18next JSON v4 format, which Weblate and Crowdin read directly: flat keys,
`{{name}}` placeholders, and plural forms as suffixes (`_one`, `_other`, plus `_zero`, `_two`,
`_few` and `_many` where a language needs them). The page picks the form with
`Intl.PluralRules`, as i18next does.

Keys do not change once shipped, since a translation platform tracks them. That includes the
API's error keys, the judge's codes and the policy ids (`achievement.<id>`, `band.<id>`…).

## Adding a language

1. Copy `en.json` to `<code>.json`: `de.json`, or `pt-BR.json` for a regional variant.
2. Translate the values. Keep every `{{placeholder}}`, and give each plural key the forms your
   language needs. Missing keys fall back to English.
3. Run `npm test`: `frontend/tests/i18n.test.ts` fails on keys `en.json` does not have and on
   placeholders that differ from English.

Nothing else is needed. The language selector lists every file in `locales/` under its own name
(from `Intl.DisplayNames`), and each file is loaded only by the students who use it.

## The instance's language

`CTESTER_LANG` (default `en`) is the language a student sees before choosing one. It is baked into
the page at build time, and the build refuses a value that has no file. The content service also
reads it for the Typst package's hyphenation and default block titles.

A student's choice is kept in the browser and, once signed in, on their account
(`display_preference.lang`). Only an explicit choice is saved, so changing `CTESTER_LANG` still
reaches everyone who never picked one.

## Not translated here

- Content: statements, `catalog.json`, `cards.json` and quiz labels stay in the content
  repository's own language.
- The teacher's dashboard (`admin/`) and the names the Discord bridge posts under.
- Leaderboard aliases (`policy.py`), which are names.
