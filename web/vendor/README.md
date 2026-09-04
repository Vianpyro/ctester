# Bibliothèques tierces, épinglées et servies depuis ce dépôt

Ces deux fichiers sont les SEULES dépendances tierces du navigateur, et ils ne
servent qu'au forum : `forum.js` va les chercher au moment où l'on ouvre
« Discussions », jamais avant. Ni le parcours anonyme, ni l'éditeur, ni le juge
n'en dépendent.

**Servies depuis cette origine, jamais depuis un CDN.** La page déclare une CSP
en `script-src 'self'` (voir `_csp()` dans `app.py`) : un script tiers chargé
d'ailleurs serait bloqué, et c'est voulu. C'est aussi ce qui garde la propriété
que le README annonce — *ce que le dépôt contient est ce que le navigateur
reçoit*, sans build ni chaîne d'assemblage.

**La version est dans le NOM du fichier**, et elle est répétée dans la liste
blanche de `do_GET` et dans `forum.js`. Monter de version demande donc de
toucher aux trois, ce qui est exactement le point : une mise à jour d'un
assainisseur HTML ne doit pas pouvoir se faire par accident.

| Fichier | Paquet | Version | Licence |
|---|---|---|---|
| `marked-18.0.11.umd.js` | [marked](https://github.com/markedjs/marked) | 18.0.11 | MIT |
| `purify-3.4.14.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 / MPL-2.0 |

SHA-256 des fichiers tels qu'ils sont servis :

```
438eedfcf932a414d0d0bfeea32dc365c063563b8ca713b4687fc8f8b501e5e4  marked-18.0.11.umd.js
1a83c283c3229acad7ad9f8f874572bcb031df0f79e114318a2957dc2ffcc117  purify-3.4.14.min.js
```

## Les reproduire

```sh
npm pack marked@18.0.11 dompurify@3.4.14
tar xzf marked-18.0.11.tgz && tar xzf dompurify-3.4.14.tgz   # tous deux -> package/
sed '/sourceMappingURL/d' package/lib/marked.umd.js  > marked-18.0.11.umd.js
sed '/sourceMappingURL/d' package/dist/purify.min.js > purify-3.4.14.min.js
```

Le seul écart avec l'amont est la ligne `sourceMappingURL` retirée : la carte de
source n'est pas publiée par `do_GET`, et l'y laisser ne produirait qu'un 404
dans la console de qui ouvre les outils de développement.

## Ce qui les remplace quand elles n'arrivent pas

Rien de secret ne dépend d'elles, mais la SÉCURITÉ du rendu, si. Si l'une des
deux manque — coupure réseau, déploiement à moitié copié — `forum.js` retombe
sur `textContent`, c'est-à-dire sur du texte brut sans Markdown. Il ne rend
JAMAIS de HTML sans assainisseur : `DOMPurify.isSupported` est vérifié à chaque
rendu, et un `false` retombe sur le texte brut lui aussi.
