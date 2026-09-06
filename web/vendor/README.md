# Third-party libraries, pinned and served from this repo

These two files are the browser's ONLY third-party dependencies, and they
only serve the forum: `forum.js` fetches them the moment "Discussions" is
opened, never before. Neither the anonymous path, the editor, nor the judge
depend on them.

**Served from this origin, never from a CDN.** The page declares a CSP with
`script-src 'self'` (see `csp()` in `app/csp.py`): a third-party script loaded
from elsewhere would be blocked, and that is intentional. It is also what
keeps the property the README advertises -- *what the repo contains is what
the browser receives*, with no build and no assembly chain.

**The version lives in the file NAME**, and it is repeated in
`config.VENDOR` (served by `app/routers/page.py`) and in `forum.js`. Bumping a
version therefore requires touching all three, which is exactly the point: an
HTML sanitizer upgrade must not be able to happen by accident.

| File | Package | Version | License |
|---|---|---|---|
| `marked-18.0.11.umd.js` | [marked](https://github.com/markedjs/marked) | 18.0.11 | MIT |
| `purify-3.4.14.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 / MPL-2.0 |

SHA-256 of the files as served:

```
438eedfcf932a414d0d0bfeea32dc365c063563b8ca713b4687fc8f8b501e5e4  marked-18.0.11.umd.js
1a83c283c3229acad7ad9f8f874572bcb031df0f79e114318a2957dc2ffcc117  purify-3.4.14.min.js
```

## Reproducing them

```sh
npm pack marked@18.0.11 dompurify@3.4.14
tar xzf marked-18.0.11.tgz && tar xzf dompurify-3.4.14.tgz   # both -> package/
sed '/sourceMappingURL/d' package/lib/marked.umd.js  > marked-18.0.11.umd.js
sed '/sourceMappingURL/d' package/dist/purify.min.js > purify-3.4.14.min.js
```

The only difference from upstream is the removed `sourceMappingURL` line: the
source map is not on the served allow-list, and leaving it in would only
produce a 404 in the console of anyone opening dev tools.

## What replaces them when they do not arrive

Nothing secret depends on them, but rendering SECURITY does. If either one is
missing -- a network outage, a half-copied deploy -- `forum.js` falls back to
`textContent`, i.e. plain text with no Markdown. It NEVER renders HTML
without a sanitizer: `DOMPurify.isSupported` is checked on every render, and
a `false` falls back to plain text too.
