import { describe, expect, it } from "vitest";
import { escapeAngle, renderAvailable, renderMarkdown } from "../src/lib/domain/markdown";

describe("the sanitizer is really there", () => {
  it("is available, or every assertion below would prove nothing", () => {
    expect(renderAvailable()).toBe(true);
  });
});

describe("escapeAngle", () => {
  it("escapes `<` BEFORE parsing: a tag that never reaches the parser cannot come out", () => {
    expect(escapeAngle("<script>")).toBe("&lt;script>");
  });

  it("leaves `>` alone -- escaping it broke Markdown blockquotes, which ARE allowed", () => {
    expect(escapeAngle("> comme ceci")).toBe("> comme ceci");
  });

  it("leaves `&` alone: an entity a student typed by hand is text, not a tag", () => {
    expect(escapeAngle("a & b")).toBe("a & b");
  });
});

describe("renderMarkdown", () => {
  const clean = (source: string) => renderMarkdown(source) ?? "";

  function parsed(source: string): HTMLElement {
    const host = document.createElement("div");
    host.innerHTML = clean(source);
    return host;
  }

  it("renders the formatting the page advertises", () => {
    expect(clean("**gras**")).toContain("<strong>gras</strong>");
    expect(clean("*italique*")).toContain("<em>italique</em>");
    expect(clean("- un\n- deux")).toContain("<li>");
    expect(clean("> cité")).toContain("<blockquote>");
    expect(clean("`court`")).toContain("<code>court</code>");
  });

  const HOSTILE = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg/onload=alert(1)>",
    "<iframe src=javascript:alert(1)></iframe>",
    '<a href="javascript:alert(1)">clic</a>',
    "<a href='data:text/html,<script>alert(1)</script>'>clic</a>",
    '<div style="position:fixed;inset:0">plein écran</div>',
    "<form action=/><input name=x></form>",
    "<math><mtext></mtext></math>",
    "<!--<script>alert(1)</script>-->",
    "<SCRIPT>alert(1)</SCRIPT>",
    '<a href="vbscript:alert(1)">clic</a>',
    "<style>body{display:none}</style>",
    "<object data=x></object>",
    "<base href=http://exemple.test/>",
    '<p class="x" id="y" data-z="1">texte</p>',
    "<a href=# onclick=alert(1)>clic</a>",
  ];

  const ALLOWED = [
    "P",
    "BR",
    "STRONG",
    "EM",
    "UL",
    "OL",
    "LI",
    "BLOCKQUOTE",
    "CODE",
    "A",
  ];
  const ALLOWED_ATTRS = ["href", "rel"];

  it.each(HOSTILE)("lets no element or attribute from a student through: %s", (hostile) => {
    const host = parsed(hostile);
    for (const node of Array.from(host.querySelectorAll("*"))) {
      expect(ALLOWED).toContain(node.tagName);
      for (const attribute of Array.from(node.attributes)) {
        expect(ALLOWED_ATTRS).toContain(attribute.name);
      }
      if (node.tagName === "A") {
        const href = node.getAttribute("href");
        if (href !== null) expect(href).toMatch(/^https?:\/\//i);
      }
    }
  });

  it("keeps an absolute http(s) link and stamps `rel` itself", () => {
    const link = parsed("[doc](https://exemple.test/page)").querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://exemple.test/page");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.hasAttribute("target")).toBe(false);
  });

  it("drops the href on anything that is not absolute http(s)", () => {
    for (const source of [
      "[x](javascript:alert(1))",
      "[x](data:text/html,hi)",
      "[x](/relatif)",
      "[x](ftp://exemple.test)",
    ]) {
      const link = parsed(source).querySelector("a");
      if (link) expect(link.hasAttribute("href")).toBe(false);
    }
  });

  it("has no rendered code block: `pre` is not in the allow-list", () => {
    const fenced = "```c\nint main(void){}\n```";
    expect(parsed(fenced).querySelector("pre")).toBeNull();
  });

  it("keeps a student's angle brackets VISIBLE as text rather than dropping them", () => {
    expect(parsed("j'ai écrit <stdio.h>").textContent).toContain("<stdio.h>");
  });
});
