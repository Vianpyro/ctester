"""The content security policy. STANDARD LIBRARY ONLY.

THIS MODULE IMPORTS NOTHING BESIDES `re` AND `config`, AND THAT IS NOT AN
ACCIDENT. `test_ctester.py` is run by `pull.sh` and by the Ansible
verification with the HOST'S PYTHON -- not the container's, so without
`PYTHONPATH=/deps` and without starlette. Leaving it in `headers.py` made the
automatic deployment fail every five minutes, on an `ImportError`, with
nothing deployed.

The rule to keep: whatever `test_ctester.py` imports must stay runnable on
the Dell without installing anything.
"""

import re

import config


# NO INLINE SCRIPT ANYWHERE IN THE PAGE, so no hash to keep up to date. That
# is what lets the same policy hold in a header here AND in `index.html`'s
# `<meta>`, which GitHub Pages serves with no way to set a header. The theme
# bootstrap lives in `web/config.js`, loaded at the top of `<head>` with no
# `defer`: it therefore runs before the first paint, like the inline script
# it replaces. An inline script added back by mistake is then blocked loudly,
# instead of going through a copied hash that silently goes stale.
_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                               re.DOTALL | re.IGNORECASE)

def csp(body, issuer=""):
    """The content security policy for THIS HTML document.

    IT MUST SAY THE SAME THING AS `index.html`'s `<meta>`, except for
    `frame-ancestors`: a `<meta>` cannot carry it, and that is the only real
    loss from the move to GitHub Pages (to be restored by a Cloudflare
    Transform Rule, `X-Frame-Options: DENY`). Here it stays, since this
    server can set headers.

    `style-src` keeps `'unsafe-inline'`: the page sets computed `style`
    attributes (a gauge's width, a verdict check's rank). These are styles,
    not scripts, and removing them would require rewriting three components
    for zero gain against the threat this targets.

    `connect-src` must contain the OIDC issuer: `compte.js` fetches the
    discovery document there, then the token. Without it, sign-in fails
    silently -- exactly the kind of failure a CSP produces without saying so.
    It must also contain the API: during the move, this server still serves
    the page while `config.js` already calls `tch099`.

    `body` IS READ ONLY TO REFUSE AN INLINE SCRIPT. The page no longer has
    any; one that came back would not be hashed on the sly, it would fail
    `test_csp_du_document`.
    """
    if any(bloc.strip() for bloc in _INLINE_SCRIPT_RE.findall(body)):
        raise ValueError(
            "un <script> inline est apparu dans la page : `script-src 'self'` "
            "le bloque, ici comme dans le <meta> servi par GitHub Pages. "
            "Sortir le code dans un fichier, comme web/config.js.")
    origines = []
    if config.API_ORIGIN:
        # L'API, ET LA MEME EN `wss://`. La collaboration d'equipe ouvre une
        # WebSocket vers cette origine-la, et une CSP qui l'oublie la bloque
        # EN SILENCE -- exactement le genre de panne que ce fichier existe
        # pour eviter. CSP niveau 3 fait deja correspondre `https:` a `wss:`,
        # mais l'ecrire coute vingt-cinq octets et ne depend plus de la
        # version du navigateur qu'un etudiant a sur son portable.
        origines.append(config.API_ORIGIN)
        origines.append("wss://" + config.API_ORIGIN.split("://", 1)[-1])
    if issuer.startswith("https://"):
        # PAS DE `wss://` POUR L'EMETTEUR : on ne lui parle qu'en HTTP (la
        # decouverte, puis le jeton). Une origine de plus dans une CSP est une
        # origine de plus a laquelle la page a le droit de parler.
        origines.append("/".join(issuer.split("/")[:3]))
    return "; ".join([
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        " ".join(["connect-src 'self'"] + origines),
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])
