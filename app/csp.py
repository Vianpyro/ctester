# Standard library only: test_ctester.py imports this on the host, without /deps.
import re

import config


_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                               re.DOTALL | re.IGNORECASE)


def csp(body, issuer=""):
    if any(block.strip() for block in _INLINE_SCRIPT_RE.findall(body)):
        raise ValueError(
            "inline <script> found: `script-src 'self'` blocks it here and in the "
            "<meta> copy served by GitHub Pages. Move it to a file like public/theme.js.")
    origins = []
    if config.API_ORIGIN:
        origins.append(config.API_ORIGIN)
        origins.append("wss://" + config.API_ORIGIN.split("://", 1)[-1])
    if issuer.startswith("https://"):
        origins.append("/".join(issuer.split("/")[:3]))
    return "; ".join([
        "default-src 'none'",
        "script-src 'self'",
        # Without it the service worker falls back through child-src to script-src, which
        # not every browser does. app/routers/page.py serves sw.js from the root.
        "worker-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        " ".join(["img-src 'self'"] + ([config.API_ORIGIN] if config.API_ORIGIN else [])
                 + ["blob:"]),
        " ".join(["connect-src 'self'"] + origins),
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])
