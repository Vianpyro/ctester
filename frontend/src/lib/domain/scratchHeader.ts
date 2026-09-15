// The Console's optional header. Same rule as HEADER_RE in app/services/scratch.py and
// gate::valid_header_name in the judge.
const HEADER_NAME = /^[A-Za-z0-9_]{1,32}\.h$/;

export const HEADER_NAME_HINT =
  "Nom invalide : lettres, chiffres ou _, puis .h (32 caractères au plus), par exemple pile.h.";

export function validHeaderName(name: string): boolean {
  return HEADER_NAME.test(name);
}

export function headerTemplate(name: string): string {
  let guard = name.slice(0, -2).toUpperCase() + "_H";
  if (/^[0-9]/.test(guard)) guard = "H_" + guard;
  return (
    `#ifndef ${guard}\n#define ${guard}\n\n` +
    "/* Déclare ici tes constantes, tes types et tes prototypes. */\n\n" +
    `#endif /* ${guard} */\n`
  );
}
