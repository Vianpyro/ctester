import { highlight } from "./domain/highlight";

const STRIPPED = "script, style, link, meta, base, iframe, object, embed, form";

export interface Prepared {
  html: string;
  blobs: string[];
}

export function prepareTypstHtml(source: string): Prepared {
  // DOMParser neither runs scripts nor loads resources.
  const doc = new DOMParser().parseFromString(source, "text/html");
  const body = doc.body;
  body.querySelectorAll(STRIPPED).forEach((el) => el.remove());
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
    const text = m[2] ? atob(m[3]!) : decodeURIComponent(m[3]!);
    const bytes = Uint8Array.from(text, (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: m[1] }));
    blobs.push(url);
    img.setAttribute("src", url);
  }

  for (const code of body.querySelectorAll("pre > code")) {
    code.innerHTML = highlight(code.textContent ?? "").replace(/\n$/, "");
  }

  for (const pre of body.querySelectorAll("pre")) {
    if (pre.closest(".typ-retype")) continue;
    const button = doc.createElement("button");
    button.type = "button";
    button.className = "copy";
    button.textContent = "Copier";
    pre.prepend(button);
  }
  return { html: body.innerHTML, blobs };
}
