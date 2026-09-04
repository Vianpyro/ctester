"""La politique de sécurité du contenu. BIBLIOTHÈQUE STANDARD SEULEMENT.

CE MODULE N'IMPORTE RIEN D'AUTRE QUE `re` ET `config`, ET CE N'EST PAS UN
HASARD. `test_ctester.py` est lancé par `pull.sh` et par la vérification
Ansible avec le PYTHON DE L'HÔTE -- pas celui du conteneur, donc sans
`PYTHONPATH=/deps` et sans starlette. Le laisser dans `headers.py` faisait
échouer le déploiement automatique toutes les cinq minutes, sur un
`ImportError`, sans que rien ne soit déployé.

La règle à tenir : ce que `test_ctester.py` importe doit rester exécutable sur
le Dell sans rien installer.
"""

import re

import config


# AUCUN SCRIPT INLINE DANS LA PAGE, donc aucun hachage à tenir à jour. C'est ce
# qui permet à la même politique de tenir dans un en-tête ici ET dans le
# `<meta>` de `index.html`, que GitHub Pages sert sans pouvoir poser d'en-tête.
# Le bootstrap du thème vit dans `web/config.js`, chargé en tête de `<head>`
# sans `defer` : il tourne donc avant le premier rendu, comme l'inline qu'il
# remplace. Un inline rajouté par distraction est alors bloqué bruyamment, au
# lieu de passer par un hachage recopié qui se périme en silence.
_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                               re.DOTALL | re.IGNORECASE)

def csp(body, issuer=""):
    """La politique de sécurité du contenu pour CE document HTML.

    ELLE DOIT DIRE LA MÊME CHOSE QUE LE `<meta>` de `index.html`, à
    `frame-ancestors` près : un `<meta>` ne peut pas le porter, et c'est la
    seule perte réelle du passage à GitHub Pages (à reposer par une Transform
    Rule Cloudflare, `X-Frame-Options: DENY`). Ici il reste, ce serveur pouvant
    poser des en-têtes.

    `style-src` garde `'unsafe-inline'` : la page pose des attributs `style`
    calculés (la largeur d'une jauge, le rang d'une coche de verdict). Ce sont
    des styles, pas des scripts, et les retirer demanderait de réécrire trois
    composants pour un gain nul face à la menace visée ici.

    `connect-src` doit contenir l'émetteur OIDC : `compte.js` va y chercher le
    document de découverte puis le jeton. Sans lui, la connexion échoue en
    silence -- et c'est le genre de panne qu'une CSP produit sans le dire. Il
    doit aussi contenir l'API : pendant la bascule, ce serveur sert encore la
    page alors que `config.js` appelle déjà `tch099`.

    `body` N'EST PLUS LU QUE POUR REFUSER UN SCRIPT INLINE. La page n'en a plus
    aucun ; un qui reviendrait ne serait pas haché en douce, il ferait échouer
    `test_csp_du_document`.
    """
    if any(bloc.strip() for bloc in _INLINE_SCRIPT_RE.findall(body)):
        raise ValueError(
            "un <script> inline est apparu dans la page : `script-src 'self'` "
            "le bloque, ici comme dans le <meta> servi par GitHub Pages. "
            "Sortir le code dans un fichier, comme web/config.js.")
    origines = [o for o in (config.API_ORIGIN,) if o]
    if issuer.startswith("https://"):
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
