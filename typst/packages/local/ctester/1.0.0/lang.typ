// The instance's language (CTESTER_LANG), passed by worker/typst_build.py: it sets
// hyphenation and the default block titles. English is the fallback, as on the page.
#let lang = sys.inputs.at("lang", default: "en")

#let _words = (
  en: (note: "Note", attention: "Warning", example: "Example", diagram: "Diagram"),
  fr: (note: "Note", attention: "Attention", example: "Exemple", diagram: "Diagramme"),
)

#let word(key) = _words.at(lang, default: _words.en).at(key)
