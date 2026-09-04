# Séparer la page de l'API : GitHub Pages devant, `app.py` derrière

## Contexte

Aujourd'hui `app/app.py` fait deux métiers : il sert sept fichiers statiques +
deux bibliothèques vendor par une liste blanche (`do_GET`, `_send_file`, ETag,
gzip, CSP calculée), et il expose l'API (soumissions, progression, forum). Tout
passe par le Dell, derrière Cloudflare, sur un seul cœur partagé avec Kea et
AdGuard. Les étudiants paient donc un aller-retour vers une infra personnelle
pour 65 Ko de fichiers qui ne changent qu'entre deux commits.

Le but est la **performance perçue par les étudiants** : la page part d'un CDN
(GitHub Pages + Cloudflare), l'origine ne répond plus que sur des données. En
prime : un déploiement front automatique sur push, une CI Lighthouse qui dit
quoi améliorer, et la fin du `ASSET_REVISION` recopié à la main dans deux
fichiers.

Le dépôt reste un **monorepo**. Rien n'est compilé ni assemblé : ce que le dépôt
contient reste ce que le navigateur reçoit.

### Décisions déjà prises

| Point | Décision |
|---|---|
| Domaines | `tch009.thevhome.com` → GitHub Pages (CNAME) ; **`tch099.thevhome.com`** → l'origine actuelle. Le nom que les étudiants connaissent ne bouge PAS : leur `localStorage`, leur session et la `redirect_uri` de Rauthy sont conservés. `api.tch009` est écarté — le certificat universel de Cloudflare ne couvre qu'une étiquette (`*.thevhome.com`), pas deux. |
| Catalogue (`tps.json`, `tp/*.json`, `quiz/*.json`) | Reste servi par l'API. Aucun secret ne s'approche de Pages ; `publish_catalogue()` ne change pas. |
| Clé `?k=` | Inchangée, sur l'URL Pages. |
| Lighthouse | Informatif d'abord (2–3 semaines), puis on fige les seuils observés en assertions bloquantes. |

## Ce qui change, dossier par dossier

### 1. Découpage du dépôt

```
web/                      # ← nouveau, ce que GitHub Pages publie
  index.html  style.css  favicon.svg
  app.js  quiz.js  compte.js  progres.js  forum.js
  config.js               # ← nouveau : résolution de l'origine API
  vendor/{marked,purify}  + README.md
  CNAME                   # tch009.thevhome.com
app/                      # ← reste le back-end seul
  app.py  etat.py  politique.py  schema.sql
  tps.json  tp/  quiz/    # toujours générés par le worker, toujours .gitignore
```

`app/` ne contient plus aucun fichier de page. Les fichiers déplacés le sont
**tels quels** (`git mv`) — aucune réécriture au même commit, pour que la revue
voie le déplacement et le changement séparément.

Conséquences à traiter dans le même lot :
- `test_page.js` lit `app/index.html`, `app/app.js` et les modules → repointer
  sur `web/`.
- `runner.py publish_catalogue()` écrit sous `CTESTER_APP` (défaut `app`) :
  inchangé, le catalogue reste côté API.
- Côté `VHome`, `roles/ctester` : le conteneur `web` ne monte plus que `app/`,
  et `CTESTER_STATIC` disparaît des variables d'environnement une fois la
  phase 5 faite.

### 2. `web/config.js` — l'origine de l'API, une seule fois

Aucune constante en dur dans `app.js`. Un fichier versionné, lisible, qui mappe
l'hôte courant vers l'origine API :

```js
// Un seul endroit où vit l'adresse de l'API. Pas de build, pas de substitution.
window.CTESTER_API = (() => {
  const h = location.hostname;
  if (h === "tch009.thevhome.com")      return "https://tch099.thevhome.com";
  if (h.endsWith(".github.io"))       return "https://tch099.thevhome.com";
  return "";   // dev local : app.py sert encore la page, chemins relatifs
})();
```

Le `""` en repli est ce qui garde le mode « je lance `python3 app/app.py` et je
teste » vivant, et ce qui rend la bascule réversible.

### 3. Les ~14 appels `fetch` à rebaser

Ils sont tous **relatifs** aujourd'hui (`fetch("tps.json")`, pas `/tps.json`),
et il y en a **8**, pas 14.
Introduire un seul helper dans `app.js`, exposé sur `window.ctester` :

```js
const API = (chemin) => (window.CTESTER_API || "") + "/" + chemin;
```

Sites d'appel à convertir (le motif est identique partout — préfixer par `API()`) :

| Fichier | Appels |
|---|---|
| `web/app.js` | `tps.json`, `tp/<id>.json`, `oidc.json`, `r/<id>`, `submit`, `live?id=` |
| `web/quiz.js` | `quiz/<id>.json` |
| `web/compte.js` | `authFetch` seul — un point de passage, pas trois. Les deux `fetch` OIDC (découverte, token endpoint) portent des URL absolues : **ne pas** les préfixer. |
| `web/progres.js`, `web/forum.js` | rien à toucher — ils appellent `ctester.compte.*` |

`charger()` **ne change pas** : les modules et les deux vendor sont sur Pages,
donc relatifs, donc corrects.

Trois points à vérifier explicitement pendant l'implémentation :
- `compte.js:111` `redirectUri = () => location.origin + location.pathname` —
  aucun changement de code, mais **l'URI doit être réenregistrée dans Rauthy**
  sur l'origine Pages, et l'ancienne retirée à la fin.
- ~~`sessionStorage` et `localStorage` perdus le jour de la bascule~~ :
  **plus le cas**, l'origine de la page reste `tch009.thevhome.com`. C'est
  l'API qui déménage. Rien à annoncer aux étudiants.
- ~~`app.py` n'a pas de `do_PUT`~~ : **faux**, il existe (`app.py:1419`), ainsi
  que `do_DELETE` (`app.py:1589`). Rien à corriger.

### 4. CORS dans `app.py`

Aujourd'hui : aucun `Access-Control-*`, aucun `do_OPTIONS`. À ajouter,
allow-list par variable d'environnement, jamais `*` (les requêtes portent un
`Authorization`) :

- `CTESTER_ORIGINS` — liste séparée par des virgules, défaut
  `https://tch009.thevhome.com`. Une origine absente de la liste ne reçoit
  **aucun** en-tête CORS (le navigateur bloque de lui-même), et non pas un 403 :
  on ne transforme pas un réglage en panne opaque.
- Une fonction `cors(origine)` près de `csp()`, appelée depuis `_json` et
  `_send_file`, qui pose `Access-Control-Allow-Origin: <l'origine reçue si
  autorisée>` et **`Vary: Origin`** (à fusionner avec le `Vary:
  Accept-Encoding` existant de `_send_file` — deux en-têtes `Vary` séparés se
  perdent dans les caches).
- `do_OPTIONS` : 204, `Allow-Methods: GET, POST, PUT, DELETE, OPTIONS`
  (**DELETE compris** : `compte.js` supprime un compte, `forum.js` un
  message — l'oublier casse les deux en cross-origin, et seulement là),
  `Allow-Headers: Authorization, Content-Type`, `Max-Age: 86400` (le préflight
  ne repart alors qu'une fois par jour et par méthode — c'est ce qui empêche la
  séparation de coûter un aller-retour de plus par requête).
- **Pas de `Allow-Credentials`** : il n'y a aucun cookie, le jeton voyage en
  en-tête. L'écrire explicitement en commentaire.
- Cloudflare ne doit pas mettre en cache les réponses `api.` : elles sont déjà
  toutes en `no-store` sauf le catalogue — vérifier la règle.

Un test dans `test_ctester.py` : origine autorisée → en-tête présent ; origine
inconnue → absent ; `OPTIONS` → 204 avec les bons en-têtes ; `Vary: Origin`
présent partout où CORS l'est.

### 5. La CSP, ce qu'on perd et ce qu'on garde

GitHub Pages ne permet aucun en-tête de réponse. `csp()` dans `app.py` devient
inutile pour la page.

- La politique passe en **`<meta http-equiv="Content-Security-Policy">`** dans
  `web/index.html`.
- `frame-ancestors` **ne s'applique pas** en `meta` — c'est la seule perte
  réelle. Si Cloudflare est devant Pages, la reposer par une Transform Rule
  (`X-Frame-Options: DENY`). Sinon, l'assumer et l'écrire dans `CLAUDE.md`.
- `connect-src` doit maintenant lister `'self' https://tch099.thevhome.com`
  + l'origine de l'issuer.
- Le **hachage du script `theme-init`** ne peut plus être calculé à la volée.
  Deux options, prendre la première :
  1. `web/csp.py` (ou une fonction de `test_page.js`) calcule le hachage et le
     compare à celui écrit dans le `meta` ; **un test échoue si le `meta` est
     périmé**. Le hachage reste écrit à la main, mais il ne peut plus se
     désynchroniser en silence — c'est exactement la propriété que `csp()`
     donnait.
  2. Générer `index.html` à la CI. Refusé : ça introduit un build, contre le
     principe « ce que le dépôt contient est ce que le navigateur reçoit ».

### 6. `ASSET_REVISION` — le corriger au passage

Le littéral est recopié dans `app.js:15` **et** deux fois dans `index.html`, à
la main, à chaque commit. Sur Pages, les fichiers sont servis avec un ETag et un
`max-age` court : le `?v=` reste utile devant Cloudflare.

Remplacer par une seule source : `index.html` charge `config.js` en premier,
`config.js` porte `window.CTESTER_REV = "<sha|date>"`, et `app.js` +
`index.html` s'en servent. La CI de déploiement **réécrit cette seule ligne**
avec le SHA court du commit avant publication — un `sed` sur une ligne, pas un
bundler. En local, la valeur versionnée sert telle quelle.

## Déploiement automatique

`.github/workflows/pages.yml`, déclenché sur `push` vers `main` avec un filtre
`paths: ['web/**', '.github/workflows/pages.yml']` :

1. `actions/checkout@v7` (`persist-credentials: false`, comme `ci.yml`)
2. Étape « stamp » : `sed` du SHA court dans `web/config.js`
3. `actions/configure-pages@v5`, `actions/upload-pages-artifact@v4` avec
   `path: web`, `actions/deploy-pages@v4`
4. `permissions: { contents: read, pages: write, id-token: write }`,
   `concurrency: { group: pages, cancel-in-progress: true }`

Pas de job de build : l'artefact est le dossier tel quel. `web/CNAME` porte le
domaine. C'est le même schéma que `Vianpyro/Parcello` et `Vianpyro/Penny-Game`,
donc éprouvé.

Le workflow `ci.yml` existant (tests + CodeQL) reste inchangé sauf les chemins
de `test_page.js`, et **doit rester requis avant `pages.yml`** — ajouter
`needs: tests` ou un `workflow_run`, pour qu'une page cassée ne se déploie pas
toute seule.

## CI Lighthouse

`.github/workflows/lighthouse.yml`, sur `pull_request` touchant `web/**` :

1. `npm ci` (jsdom est déjà là ; ajouter `@lhci/cli` en devDependency)
2. Servir `web/` en statique (`npx http-server web -p 8080` ou l'option
   `staticDistDir` de LHCI) — **on mesure la page, pas l'origine du Dell** ;
   les appels API échoueront et c'est voulu, la page doit rester lisible sans.
3. `lhci autorun` avec `lighthouserc.json` : `numberOfRuns: 3`,
   `preset: desktop` + un run `mobile`, upload en `temporary-public-storage`,
   et le lien du rapport en commentaire de PR.

**Phase informative (2–3 semaines).** Toutes les assertions en `warn` sauf deux
planchers durs, parce qu'ils protègent les étudiants et pas l'esthétique :
`categories:accessibility >= 0.9` et `errors-in-console` (une console rouge est
la panne prod qu'on a déjà eue).

**Phase bloquante.** Une fois trois PR de base mesurées, figer dans
`lighthouserc.json` les seuils observés moins une marge (typiquement
`performance >= 0.95`, `best-practices >= 0.95`, LCP et CLS en budget chiffré),
et passer `assertions` en `error`. Écrire dans le fichier la date et le commit
de la ligne de base — sans ça personne ne saura pourquoi le seuil vaut ce qu'il
vaut.

Deux constats Lighthouse déjà ouverts (voir `CLAUDE.md`) se règlent **par la
séparation elle-même** ou juste après ; à revérifier une fois en ligne :
- « 268 Ko de JS à minifier, 328 Ko inutilisé » alors que tout notre JS fait
  30 Ko → suspect **Rocket Loader** de Cloudflare. Sur une zone Pages, le
  désactiver et mesurer avant de toucher au code.
- Le score SEO de 54 (`noindex` délibéré) : mettre `categories:seo` en `off`
  dans les assertions, avec le commentaire qui dit pourquoi.
- La compression : Pages/Cloudflare gzip et brotli d'office → les quelques
  lignes de `_send_file` deviennent mortes pour la page (étape 5 ci-dessous).

## Ordre d'exécution (chaque étape est déployable et réversible)

1. **`git mv` de la page dans `web/`** + repointage de `test_page.js` et du
   montage `CTESTER_STATIC` sur `../web`. Rien d'autre ne bouge : le site tourne
   toujours entièrement sur le Dell. `python3 test_ctester.py`, `node
   test_page.js` verts.
2. **`web/config.js` + le helper `API()`**, avec `CTESTER_API = ""` partout.
   Aucun changement de comportement, tous les tests verts. C'est le commit à
   relire attentivement (14 sites d'appel).
3. **CORS + `do_OPTIONS` + `do_PUT`** dans `app.py`, avec leurs tests. Toujours
   même origine en production, donc invisible.
4. **DNS + workflows.** Dans NPM, `tch099.thevhome.com` est aujourd'hui un
   **redirection host** (308 vers `tch009`, né d'une typo) : le convertir en
   *proxy host* vers `ctester-web-1:8000`, avec son certificat Let's Encrypt
   déjà émis. Puis `tch009.thevhome.com` en CNAME vers Pages ; `pages.yml` et
   `lighthouse.yml`. **La `redirect_uri` de Rauthy ne bouge pas** — l'origine
   de la page est inchangée, c'est l'API qui déménage. Reste UNE ligne à
   changer dans `web/config.js` : `tch009` rend `""` (le Dell sert encore les
   deux) et doit rendre `https://tch099.thevhome.com`. La branche `.github.io`
   pointe déjà l'API : c'est elle qui permet de tout éprouver sur
   `vianpyro.github.io/ctester` AVANT de toucher au DNS.
5. **Nettoyage, après une séance sans incident.** Retirer de `app.py` la liste
   blanche statique, `_file`, `csp()`, la compression et l'ETag de
   `_send_file` (le catalogue JSON garde ce dont il a besoin), et
   `CTESTER_STATIC` du rôle Ansible. Retirer l'ancienne `redirect_uri` de
   Rauthy. Mettre `CLAUDE.md` à jour : la section « La page » et les pièges de
   cache décrivent alors Pages, pas `_send_file`.

## Ce qui ne change pas — à ne pas casser

- `publish_catalogue()`, le `grep -rl answer` sur les fichiers publiés, la
  frontière du catalogue : intacts. Le catalogue reste côté API par décision.
- Le chargement à la demande des modules et des 74 Ko de vendor, et le fait que
  **le parcours anonyme ne télécharge rien** de `compte.js` / `progres.js` /
  `forum.js` — `test_page.js` doit continuer de le prouver après le déplacement.
- Les deux barrières d'assainissement de `forum.js` (échappement de `<` avant
  `marked`, puis DOMPurify) : hors CSP, elles sont la défense principale, et
  elles ne dépendent pas de l'origine.
- `politique.py` reste le seul endroit où vit un chiffre d'équilibrage.

## Vérification

Après chaque étape, sur le contrôleur :

```sh
python3 test_ctester.py          # + les nouveaux tests CORS/OPTIONS/PUT
npm ci && node test_page.js      # chemins web/, parcours anonyme intact
python3 valider_contenu.py ../unittests
python3 test_bac_a_sable.py
```

Après l'étape 4, à la main, contre les vrais domaines :

```sh
# préflight
curl -si -X OPTIONS https://tch099.thevhome.com/forum \
  -H 'Origin: https://tch009.thevhome.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization'   # 204 + Allow-* + Max-Age

# origine inconnue : aucun en-tête CORS
curl -si https://tch099.thevhome.com/tps.json -H 'Origin: https://mechant.example'

# Vary correct (les deux valeurs, un seul en-tête)
curl -si https://tch099.thevhome.com/tps.json -H 'Origin: https://tch009.thevhome.com' | grep -i vary

# ce que Cloudflare fait vraiment devant Pages
curl -sI -H 'Accept-Encoding: gzip, br' https://tch009.thevhome.com/app.js
```

Puis un parcours complet dans un navigateur neuf, sur `https://tch009.thevhome.com/?k=<clé>` :
connexion OIDC (retour sur la bonne URL, `state` vérifié), une soumission qui
donne un vrai verdict, « Mes exercices », « Mes progrès » (aucun chiffre si
l'API tombe — pas de « 0 XP »), « Discussions » (publier, signaler, modérer),
et le bouton Retour du navigateur (bfcache). Console vide.

Enfin, `docker logs ctester-web-1` et `uptime` sur le Dell : la charge statique
doit avoir disparu de l'origine.
