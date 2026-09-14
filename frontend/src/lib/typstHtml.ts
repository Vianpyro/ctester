import { highlight } from "./domain/highlight";

const RETIRES = "script, style, link, meta, base, iframe, object, embed, form";

export interface Prepared {
  html: string;
  blobs: string[];
}

export function prepareTypstHtml(source: string): Prepared {
  // DOMParser neither runs scripts nor loads resources.
  const doc = new DOMParser().parseFromString(source, "text/html");
  const body = doc.body;
  body.querySelectorAll(RETIRES).forEach((el) => el.remove());
  for (const el of body.querySelectorAll("*")) {
    for (const { name, value } of [...el.attributes]) {
      if (name.startsWith("on") || /^\s*javascript:/i.test(value)) el.removeAttribute(name);
    }
  }

  // img-src refuses data: URIs, so embedded images are turned into blob: URLs.
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

  for (const code of body.querySelectorAll("pre > code")) {
    code.innerHTML = highlight(code.textContent ?? "").replace(/\n$/, "");
  }

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
