# Translations

Everything a student reads comes from one file per language in
[frontend/src/locales/](../frontend/src/locales/). The page, the API and the judge send no
sentences: the API answers with keys (`{"error": "db_down"}`, plus `params` when the wording
needs values), and the judge with codes (`"reason": "interrupted"`). The page words both.

## The files

- **`en.json` is the source.** It has every key, and any key another language lacks falls back to
  it. New text is added here first.
- **The format is i18next JSON v4**: flat keys, `{{name}}` placeholders, and plural forms as
  suffixes (`_one`, `_other`, and `_zero`, `_two`, `_few`, `_many` where the language uses them).
  The page chooses the form with the browser's `Intl.PluralRules`, the same way i18next does.
  Weblate and Crowdin both read this format directly.
- **Keys never change once shipped.** A translation platform tracks keys, and the API's error
  keys, the judge's codes and the policy ids (`achievement.<id>`, `band.<id>`, …) are all part of
  that contract.

## Adding a language

1. Copy `en.json` to `<code>.json`: `de.json`, or `pt-BR.json` for a regional variant.
2. Translate the values. Keep every `{{placeholder}}` as it is, and give each plural key the forms
   your language needs. A key you leave out falls back to English.
3. Run `npm test`. `frontend/tests/i18n.test.ts` fails on a key `en.json` does not have and on a
   placeholder that differs from English.

The file is enough: the language selector lists every file in `locales/` by its own name (from
the browser's `Intl.DisplayNames`), and each file is its own chunk, fetched only by the students
who use it.

## The instance's language

`CTESTER_LANG` (default `en`) is the language a student sees before choosing one. It is baked into
the page at build time, like `CTESTER_TITLE`, and the build refuses a value that has no file. The
content service reads it too, for the Typst package's hyphenation and default block titles.

A student's choice is kept in the browser and, once they are signed in, on their account
(`display_preference.lang`). Only an explicit choice is saved, so changing `CTESTER_LANG` still
reaches everyone who never picked.

## Not translated here

- **Content**: statements, `catalog.json`, `cards.json` and quiz labels are written in the content
  repository's own language.
- **The teacher's dashboard** (`admin/`) and the Discord bridge's names.
- **Leaderboard aliases** (`policy.py`): they are names, and stay the same in every language.
