# Third-party libraries, pinned and served from this repo

These three files are the browser's ONLY third-party dependencies, and each is
fetched by exactly one lazily-loaded module: `marked` and `DOMPurify` the
moment "Discussions" is opened, Yjs the moment a team assignment's workspace
is opened. Neither the anonymous path, the editor, nor the judge depends on
any of them.

**Served from this origin, never from a CDN.** The page declares a CSP with
`script-src 'self'` (see `csp()` in `app/csp.py`): a third-party script loaded
from elsewhere would be blocked, and that is intentional. It is also what
keeps the property the README advertises -- *what the repo contains is what
the browser receives*, with no build and no assembly chain.

**The version lives in the file NAME**, and it is repeated in
`config.VENDOR` (served by `app/routers/page.py`) and in the module that loads
it (`forum.js`, `team.js`). Bumping a version therefore requires touching all
three, which is exactly the point: neither an HTML sanitizer nor the library
that decides what four students see in their shared editor should be upgraded
by accident.

| File | Package | Version | License | Loaded by |
|---|---|---|---|---|
| `marked-18.0.11.umd.js` | [marked](https://github.com/markedjs/marked) | 18.0.11 | MIT | `forum.js` |
| `purify-3.4.14.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 / MPL-2.0 | `forum.js` |
| `yjs-13.6.32.iife.js` | [Yjs](https://github.com/yjs/yjs) | 13.6.32 | MIT | `team.js` |

SHA-256 of the files as served:

```
438eedfcf932a414d0d0bfeea32dc365c063563b8ca713b4687fc8f8b501e5e4  marked-18.0.11.umd.js
1a83c283c3229acad7ad9f8f874572bcb031df0f79e114318a2957dc2ffcc117  purify-3.4.14.min.js
3744a0ea66eb1863220fb7f912987fca1487ea68c740519297a3eabf2a28f49f  yjs-13.6.32.iife.js
```

## Reproducing them

```sh
npm pack marked@18.0.11 dompurify@3.4.14
tar xzf marked-18.0.11.tgz && tar xzf dompurify-3.4.14.tgz   # both -> package/
sed '/sourceMappingURL/d' package/lib/marked.umd.js  > marked-18.0.11.umd.js
sed '/sourceMappingURL/d' package/dist/purify.min.js > purify-3.4.14.min.js
```

Yjs is the one that needs a bundler, and that deserves a sentence rather than
a shrug: it publishes ESM only, and its `dist/` imports `lib0` at a dozen
paths. There is no upstream file that a `<script src>` can load. So it is
rolled once, by hand, into a self-contained IIFE that defines the `Y` global
-- the same shape as the two files above:

```sh
npm i --no-save yjs@13.6.32 esbuild
echo "export * from 'yjs';" > entry.mjs
npx esbuild entry.mjs --bundle --format=iife --global-name=Y --minify \
    --footer:js='if(typeof window!=="undefined")window.Y=Y;' \
    --outfile=yjs-13.6.32.iife.js
sed -i '/sourceMappingURL/d' yjs-13.6.32.iife.js
```

**The footer is load-bearing, not cosmetic.** A top-level `var Y` becomes
`window.Y` in a document, which is all a browser needs — but `test_page.js`
evaluates an injected `<script src>` inside a function scope, where `var`
stays local and `window.Y` would never be set. The harness would then report
"the library did not arrive" for a file that arrived perfectly.
`--global-name=window.Y` looks like the fix and is not: esbuild emits
`var window;(window||={}).Y=…`, which shadows the real one.

**The bundling happens here, once, and the OUTPUT is committed** -- it is not
a build step of this repository. `npm ci` still installs test dependencies
only, `node test_page.js` still runs against the files as served, and a
deployment still copies the repo and serves it. The rule the project holds is
"what the repo contains is what the browser receives", not "no tool was ever
run"; the command above exists so the next person can reproduce the byte
sequence rather than trust it.

The only difference from upstream, for all three, is the removed
`sourceMappingURL` line: source maps are not on the served allow-list, and
leaving them in would only produce a 404 in the console of anyone opening dev
tools.

## What replaces them when they do not arrive

**`marked` / `DOMPurify`.** Nothing secret depends on them, but rendering
SECURITY does. If either one is missing -- a network outage, a half-copied
deploy -- `forum.js` falls back to `textContent`, i.e. plain text with no
Markdown. It NEVER renders HTML without a sanitizer: `DOMPurify.isSupported`
is checked on every render, and a `false` falls back to plain text too.

**Yjs.** There is no fallback, and there must not be one: without a CRDT there
is no safe way for four people to edit one document, and a "best effort" that
silently replaced the shared file with the last textarea value would destroy
work rather than degrade. `team.js` therefore says so plainly, leaves the
editor read-only, and offers the exercise's individual draft path instead --
which still saves, and still tests.
