// UN ÉNONCÉ TYPST RENDU EN HTML, PRÉPARÉ AVANT D'ÊTRE ÉCRIT DANS LA PAGE.
//
// ESSAI : l'export HTML de Typst 0.15 est expérimental, et le SVG reste le
// défaut. Le fichier vient du dépôt privé de contenu, relu -- la même confiance
// que `statement.md` --, et la CSP `script-src 'self'` bloque déjà tout inline.
// On retire quand même ce qui n'a rien à faire dans une consigne : c'est cinq
// lignes, et DOMPurify n'est pas dans le paquet de l'anonyme.
//
// `DOMParser` N'EXÉCUTE RIEN ET NE CHARGE RIEN : c'est ce qui permet de
// réécrire les images AVANT qu'elles n'atteignent le document.

import { highlight } from "./domain/highlight";

const RETIRES = "script, style, link, meta, base, iframe, object, embed, form";

export interface Prepared {
  html: string;
  /** Les `blob:` créés pour les images : à révoquer au démontage. */
  blobs: string[];
}

export function prepareTypstHtml(source: string): Prepared {
  const doc = new DOMParser().parseFromString(source, "text/html");
  const body = doc.body;
  body.querySelectorAll(RETIRES).forEach((el) => el.remove());
  for (const el of body.querySelectorAll("*")) {
    for (const { name, value } of [...el.attributes]) {
      if (name.startsWith("on") || /^\s*javascript:/i.test(value)) el.removeAttribute(name);
    }
  }

  // LES IMAGES ARRIVENT EN `data:`, ET `img-src` LES REFUSE -- exprès, un test
  // y tient. On les convertit en `blob:`, que la CSP autorise déjà pour
  // l'aperçu enseignant.
  const blobs: string[] = [];
  for (const img of body.querySelectorAll("img")) {
    const m = /^data:([^;,]+)(;base64)?,(.*)$/s.exec(img.getAttribute("src") ?? "");
    if (!m) continue;
    const texte = m[2] ? atob(m[3]!) : decodeURIComponent(m[3]!);
    const octets = Uint8Array.from(texte, (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([octets], { type: m[1] }));
    blobs.push(url);
    img.setAttribute("src", url);
  }

  // LA COLORATION DE TYPST EST PEINTE EN `style` INLINE, AUX COULEURS DU THÈME
  // SOMBRE : illisible en clair. On la remplace par `highlight()`, dont les
  // classes suivent le thème de la page -- comme pour le Markdown.
  for (const code of body.querySelectorAll("pre > code")) {
    // Le `\n` final de `highlight()` sert à la superposition de l'éditeur ;
    // ici il ajouterait une ligne vide au bloc et au presse-papiers.
    code.innerHTML = highlight(code.textContent ?? "").replace(/\n$/, "");
  }

  // UN BOUTON « COPIER » PAR BLOC, SAUF CEUX À RECOPIER À LA MAIN.
  for (const pre of body.querySelectorAll("pre")) {
    if (pre.closest(".typ-recopier")) continue;
    const bouton = doc.createElement("button");
    bouton.type = "button";
    bouton.className = "copier";
    bouton.textContent = "Copier";
    pre.prepend(bouton);
  }
  return { html: body.innerHTML, blobs };
}
