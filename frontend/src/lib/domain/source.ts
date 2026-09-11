/**
 * La forme canonique d'une source, côté page. Le jumeau de
 * `app/services/source.py`, et `frontend/tests/fixtures/source.json` est ce
 * qui tient les deux honnêtes : ni ce fichier ni le test ne gardent leur
 * propre copie des attentes.
 *
 * LE SERVEUR FAIT AUTORITÉ. Rien ici n'est une barrière : `validate_files`
 * canonise de toute façon ce qu'il stocke. Ces deux fonctions existent pour
 * deux gains que le serveur ne peut pas obtenir depuis sa place.
 *
 * LE NOMBRE DE LIGNES NE CHANGE JAMAIS -- hormis le `\r` isolé, qui en devient
 * un vrai et fait alors s'accorder la gouttière et le compilateur. C'est
 * l'invariant qui rend tout ceci invisible : la gouttière de
 * `CodeSurface.svelte` est `value.split("\n").length`, donc un `\n` de plus ou
 * de moins est un NUMÉRO DE LIGNE qui apparaît ou disparaît sous les yeux de
 * l'étudiant.
 */

/** Le BOM et les fins de ligne : des faits sur le DISQUE, pas sur le code. */
function normalizeEncoding(text: string): string {
  const sansBom = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  return sansBom.includes("\r") ? sansBom.replace(/\r\n?/g, "\n") : sansBom;
}

/**
 * Ce qu'« ouvrir un fichier » veut dire, et RIEN DE PLUS.
 *
 * C'est le seul endroit du système où des octets étrangers entrent. Un `.c`
 * écrit par Visual Studio ou par le Bloc-notes arrive avec une marque d'ordre
 * et des CRLF ; les laisser passer les fait vivre dans `editor.sources`, partir
 * vers `/submit` et `/brouillon`, et -- dans un devoir d'équipe -- entrer dans
 * le `Y.Doc` où les TROIS AUTRES coéquipiers en héritent. Le serveur peut
 * canoniser ce qu'il stocke ; il ne peut pas aller retirer un CRLF d'un CRDT
 * déjà en vol.
 *
 * ELLE EN FAIT DÉLIBÉRÉMENT MOINS QUE `canonicalize` : couper les espaces morts
 * ICI modifierait le fichier de l'étudiant à l'instant où il le regarde
 * arriver, et ce qu'il voit sur son disque ne correspondrait plus à ce qu'il
 * voit ici. Le serveur les coupe à l'ÉCRITURE, ce qui est invisible.
 */
export function decodeImported(text: string): string {
  return normalizeEncoding(text);
}

/**
 * La règle entière, pour ce qu'on ENVOIE -- jamais pour ce qu'on affiche.
 *
 * Elle sert au raccourci « même code que ta dernière soumission » : sans elle,
 * une modification qui ne touche qu'un espace de fin reprend une place dans la
 * file et un cooldown pour un verdict que la page tient déjà. La clé et le
 * corps envoyé sont canonisés ENSEMBLE, donc la page envoie exactement ce
 * qu'elle a comparé -- elle n'affirme toujours rien au serveur, elle décide
 * seulement de ne pas le déranger.
 *
 * LA LIGNE QUI FINIT PAR UNE CONTRE-OBLIQUE N'EST PAS TOUCHÉE : `\` suivi
 * d'espaces puis d'un retour est un raccord de lignes que gcc accepte EN LE
 * SIGNALANT. Couper ces espaces ferait taire le diagnostic sans rien réparer.
 */
export function canonicalize(text: string): string {
  const s = normalizeEncoding(text);
  if (!s.includes(" \n") && !s.includes("\t\n") && !/[ \t]$/.test(s)) return s;
  return s
    .split("\n")
    .map((line) => {
      const cut = line.replace(/[ \t]+$/, "");
      return cut !== line && cut.endsWith("\\") ? line : cut;
    })
    .join("\n");
}

/** Le même geste sur un {nom: texte}. Un NOUVEL objet. */
export function canonicalizeFiles(files: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, text] of Object.entries(files)) out[name] = canonicalize(text);
  return out;
}
