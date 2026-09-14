import DOMPurify from "dompurify";
import { marked } from "marked";

const TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "blockquote", "code", "a"];
const ATTRS = ["href", "rel"];

const CLEAN = {
  ALLOWED_TAGS: TAGS,
  ALLOWED_ATTR: ATTRS,
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
};

const MARKDOWN = { gfm: true, breaks: true };

// Escaped before marked runs, so no tag typed by a student reaches the parser.
// ">" is left alone: blockquotes need it and a tag cannot start with it.
export const escapeAngle = (s: string): string => s.replace(/</g, "&lt;");

let hookInstalled = false;

function sanitizer(): typeof DOMPurify | null {
  // Without a DOM, DOMPurify returns its input untouched; callers then render plain text.
  if (!DOMPurify.isSupported || typeof DOMPurify.sanitize !== "function") return null;
  if (!hookInstalled && typeof DOMPurify.addHook === "function") {
    hookInstalled = true;
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if ((node as Element).tagName === "A") {
        (node as Element).setAttribute("rel", "noopener noreferrer");
        (node as Element).removeAttribute("target");
      }
    });
  }
  return DOMPurify;
}

export const renderAvailable = (): boolean => !!sanitizer();

export function renderMarkdown(source: string): string | null {
  const purify = sanitizer();
  if (!purify) return null;
  try {
    return purify.sanitize(marked.parse(escapeAngle(source), MARKDOWN) as string, CLEAN);
  } catch {
    return null;
  }
}
