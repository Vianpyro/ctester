// THE RENDERING OF A FORUM MESSAGE, AND THIS IS THE DANGEROUS PART.
//
// Messages are restricted Markdown STORED IN THEIR SOURCE FORM. The server
// renders nothing and sanitizes nothing: it bounds. All rendering happens here,
// on EVERY display -- the thread, the compose preview, the moderation queue.
// Sanitizing once at write time would leave messages already in the database out
// of reach of any rule tightened later.
//
// TWO BARRIERS, IN THIS ORDER:
//   1. raw HTML is ESCAPED BEFORE Markdown parsing, so `marked` never sees a tag
//      and never emits one that came from a student;
//   2. `marked`'s output goes through DOMPurify with a closed allow-list.
// The document's CSP is a third layer, and it is NOT the main defence: these two
// are.
//
// BOTH LIBRARIES ARE PINNED IN `package.json` AND BUNDLED INTO THIS CHUNK. They
// used to be vendored IIFE files pinned by filename and loaded through injected
// `<script>` tags; the pin is now the lockfile, which is stronger, and they are
// still only downloaded with the module that needs them -- the anonymous visitor
// gets none of it.

import DOMPurify from "dompurify";
import { marked } from "marked";

// THE ALLOW-LIST. Nothing else survives: no `style`, `class`, `id` or event
// attribute, no SVG, MathML, image, media, iframe, form or custom element. `pre`
// is not in it either -- there is no rendered code block, so a fenced block falls
// back to plain text.
const TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "blockquote", "code", "a"];
// `href` for links, `rel` because the hook below writes it. No `target`: a forum
// link never opens a named target.
const ATTRS = ["href", "rel"];

const CLEAN = {
  ALLOWED_TAGS: TAGS,
  ALLOWED_ATTR: ATTRS,
  // ABSOLUTE http(s) ONLY. Everything else -- `javascript:`, `data:`,
  // `vbscript:`, a relative URL -- loses its `href` and falls back to text.
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
};

const MARKDOWN = { gfm: true, breaks: true };

/**
 * BEFORE PARSING, NOT AFTER. A `<` that never reaches the parser cannot come back
 * out as a tag, however subtle the Markdown extension of the day.
 *
 * `<` ONLY, AND THAT IS EXACT: an HTML tag starts with `<`, comments and
 * processing instructions included. Escaping `>` as well was tried and broke
 * Markdown blockquotes, which ARE in the allow-list -- that would have removed an
 * advertised feature for zero gain. `marked` escapes the `>` in the text it
 * renders. `&` is left alone too: touching it would break entities a student
 * types by hand, and an entity is text, not a tag.
 */
export const escapeAngle = (s: string): string => s.replace(/</g, "&lt;");

let hookInstalled = false;

/**
 * `isSupported` is false when DOMPurify found no real DOM. In that state
 * `sanitize()` RETURNS ITS INPUT AS-IS -- using it would amount to writing a
 * student's HTML into the page with no filter at all. We would rather render no
 * Markdown.
 */
function sanitizer(): typeof DOMPurify | null {
  if (!DOMPurify.isSupported || typeof DOMPurify.sanitize !== "function") return null;
  if (!hookInstalled && typeof DOMPurify.addHook === "function") {
    hookInstalled = true;
    // `rel` SET HERE AND NEVER HOPED FOR FROM THE AUTHOR: a forum link always
    // comes out with `noopener noreferrer`, and never with a named target --
    // `target` is not in the allow-list anyway, this says so twice.
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if ((node as Element).tagName === "A") {
        (node as Element).setAttribute("rel", "noopener noreferrer");
        (node as Element).removeAttribute("target");
      }
    });
  }
  return DOMPurify;
}

/** True when Markdown can actually be rendered on this page. */
export const renderAvailable = (): boolean => !!sanitizer();

/**
 * SANITIZED HTML, or `null` when it could not be produced. `null` means the
 * caller must fall back to `textContent` -- plain text, never unfiltered HTML.
 *
 * The one place this result may reach `innerHTML` is the component that calls it,
 * AT THAT VERY INSTANT: no variable lying around, no concatenation, no cache.
 */
export function renderMarkdown(source: string): string | null {
  const purify = sanitizer();
  if (!purify) return null;
  try {
    return purify.sanitize(marked.parse(escapeAngle(source), MARKDOWN) as string, CLEAN);
  } catch {
    return null;
  }
}
