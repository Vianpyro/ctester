import { describe, expect, it } from "vitest";
import { prepareTypstHtml } from "../src/lib/typstHtml";

const page = (body: string) =>
  `<!DOCTYPE html><html><head><style>x{}</style></head><body>${body}</body></html>`;

const dom = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host;
};

describe("prepareTypstHtml", () => {
  it("adds a Copy button to code blocks, but NOT to the ones to retype by hand", () => {
    const { html } = prepareTypstHtml(
      page(
        `<pre><code data-lang="c">int x;</code></pre>` +
          `<div class="typ-retype"><pre><code>for (;;);</code></pre></div>`,
      ),
    );
    const host = dom(html);
    const [free, retyped] = host.querySelectorAll("pre");
    expect(free!.querySelector("button.copy")).not.toBeNull();
    expect(retyped!.querySelector("button.copy")).toBeNull();
    expect(free!.querySelector("code")!.textContent).toBe("int x;");
  });

  it("drops scripts, styles and event handlers", () => {
    const { html } = prepareTypstHtml(
      page(`<p onclick="alert(1)">a</p><script>alert(2)</script><a href="javascript:x">b</a>`),
    );
    expect(html).not.toMatch(/script|onclick|javascript:|<style/i);
    expect(dom(html).textContent).toContain("a");
  });

  it("replaces Typst's dark inline colours with the page's own highlighter", () => {
    const { html } = prepareTypstHtml(
      page(`<pre><code><span style="color: #7fb0f2">int</span> x;</code></pre>`),
    );
    expect(html).not.toContain("style=");
    expect(dom(html).querySelector("code")!.textContent).toBe("int x;");
  });

  it("turns data: images into blob: URLs, which img-src allows", () => {
    const { html, blobs } = prepareTypstHtml(
      page(`<img src="data:image/svg+xml;base64,${btoa("<svg/>")}">`),
    );
    expect(blobs).toHaveLength(1);
    expect(dom(html).querySelector("img")!.getAttribute("src")).toBe(blobs[0]);
  });
});
