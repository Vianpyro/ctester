# CLAUDE.md — notes de travail

Le README est la façade du projet. Ce fichier-ci est pour Claude Code et pour
quiconque modifie le dépôt : ce qu'il faut savoir avant de toucher au code, les
contrôles à repasser avant de déployer, et les pièges déjà payés une fois.

## Où vit quoi

Ce dépôt porte l'application. Le déploiement — gVisor, systemd, Compose, les
deploy keys, le service Postgres, le client Rauthy — vit dans `VHome`, sous
`roles/ctester`. Le serveur clone ce dépôt dans `/opt/ctester/src` et suit
`main` tout seul, à cinq minutes près.

Tout se règle par variables d'environnement. Chaque script porte ses propres
défauts (ceux du rôle Ansible) pour tourner hors déploiement ; c'est ce qui rend
les contrôles ci-dessous exécutables sans rien installer.

Rien à compiler, rien à lier : `app/app.py`, `app/etat.py` et `app/politique.py`
sont bibliothèque standard + `psycopg` (et `psycopg` seulement si
`CTESTER_DB_DSN` est là).

La page est en six fichiers, tous servis par la liste blanche de `do_GET` :
`index.html` (le markup seul), `style.css`, `app.js` (le noyau), puis `quiz.js`,
`compte.js` et `progres.js`, que le noyau va chercher **à la demande**. Rien de
tout ça n'est compilé ni assemblé : ce que le dépôt contient est ce que le
navigateur reçoit.

## Avant de déployer une modif de la page ou du contenu

Sur le contrôleur, jamais sur le Dell (les trois derniers ont besoin de gcc) :

```sh
python3 test_ctester.py          # les défenses et la progression, sans rien installer
node    test_page.js             # le JS de la page, sur un DOM en carton
python3 valider_contenu.py ../unittests
python3 test_bac_a_sable.py      # les deux build.sh, vrai gcc, sans Docker
```

- **`test_ctester.py`** — le parsing des verdicts et la frontière du catalogue
  (`publish_catalogue`, `public_quiz` : aucune clé `answer` ne survit). Pur
  Python, tourne partout, y compris sur le Dell. Il couvre aussi la
  progression : que `politique.py` reste le SEUL endroit où vit un chiffre
  d'équilibrage, qu'un sondage rejoué ou une réussite refaite n'accorde pas
  deux fois, qu'un échec n'accorde rien, et que `forget()` efface **chaque**
  table du schéma — ce dernier contrôle lit `schema.sql` et `etat.py`, donc
  ajouter une table sans l'effacer le fait échouer tout seul.
- **`test_bac_a_sable.py`** — prend `build-unity.sh` / `build-io.sh` tels quels,
  les exécute avec un vrai gcc, chemins déplacés, sans Docker. C'est le seul
  contrôle qui **éprouve l'invariant de confidentialité** au lieu d'en parler :
  il soumet un module qui déborde d'un tableau et vérifie qu'en mode unity le
  verdict ne contient aucun identifiant du fichier de test — ni le rapport
  d'ASan, dont la pile d'appels nommerait la fonction de test appelante.
- **`valider_contenu.py`** — compile la solution de référence de chaque exercice
  et la passe dans le vrai juge (il **importe `runner.py`**, il ne refait pas ses
  vérifications). Un exercice sans corrigé apparaît « non prouvé » : rien ne
  garantit alors que son test soit juste. Appelle `catalogue(tout=True)` pour
  qu'un exercice qui ouvre en novembre soit prouvé en septembre.
- **`test_page.js`** — exécute le JS contre un DOM en carton et vérifie que la
  soumission part vraiment. **`node --check` ne suffit pas** : la seule panne que
  cette page ait connue en production était une `ReferenceError` de zone morte
  temporelle (une variable redéclarée dans un bloc `try` qui masquait la charge
  utile utilisée deux lignes plus haut). Le `fetch` ne partait jamais, le `catch`
  affichait « le serveur ne répond pas », et les logs du conteneur étaient vides.

Après chaque `ansible-playbook … --tags tests` :

```sh
grep -rl answer /opt/ctester/src/app/*.json /opt/ctester/src/app/quiz/ \
                /opt/ctester/src/app/tp/      # DOIT ne rien trouver
```

`app/` est tout ce que le conteneur exposé peut lire ; aucun corrigé n'a le
droit d'y être. **Le grep porte sur les fichiers PUBLIÉS, pas sur `app/` entier**
: le code source y écrit légitimement `answers` (la fonction qui relève les
réponses saisies, le champ `answers` d'une soumission), donc un `grep -rl answer
app/` tout court trouve toujours quelque chose et n'apprend rien. Ce qu'on
vérifie, c'est que la clé `answer` d'un corrigé n'a pas franchi la frontière.

## Les quatre soumissions hostiles

À repasser après toute modification du bac à sable — elles sont la seule preuve
que les défenses tiennent encore.

| Soumission | Attendu |
|---|---|
| `while (1) fork();` | `timeout`, l'hôte ne bouge pas |
| `system("curl http://exemple");` | échoue, `--network=none` |
| `while (1);` | `timeout` à 5 s |
| `#include <unistd.h>` hors liste blanche | rejeté avant même de lancer un conteneur |

Sur la fork bomb, **vérifier le résultat et pas le mécanisme** : sous `runsc`,
les processus créés dans le bac à sable sont internes à gVisor, donc
`--pids-limit` (un contrôle cgroup) ne les compte pas forcément. Ce qui l'arrête
alors est le plafond mémoire du sandbox et le chronomètre. Les deux options
restent en place — l'une couvre `runc`, l'autre `runsc` — et ce qui compte est
que `uptime` sur le Dell ne bronche pas.

## Ajouter ou modifier un TP

Pousser sur le dépôt privé de tests, puis :

```sh
ansible-playbook playbooks/ctester.yml --tags tests --ask-vault-pass
```

Ça met à jour le clone et redémarre les workers, ce qui republie le catalogue.
Refaire ensuite la vérification `grep -rl answer` ci-dessus.

### Voir un TP avant son ouverture

Pour éprouver ses corrigés dans la vraie page, avec les vrais tests, avant les
étudiants : `CTESTER_APERCU=1` fait tomber le filtre `available_from`. Il agit
sur `catalogue()`, donc sur le menu **et** `tp_path()` en même temps — un
exercice qu'on voit est un exercice qu'on peut soumettre.

```sh
CTESTER_APERCU=1 CTESTER_TESTS=../unittests CTESTER_APP=app \
  python3 -c 'import runner; runner.publish_catalogue()'
CTESTER_KEY=dev CTESTER_STATIC=app python3 app/app.py
```

Pour de vrais verdicts il faut en plus un worker (Docker + gVisor) ; sans eux,
`valider_contenu.py` reste le contrôle qui dit si un test est juste. Ce n'est
**pas** un réglage de production : le déploiement ne le définit pas, et
`publish_catalogue()` l'annonce dans le journal quand il est actif. Republier
sans la variable remet le semestre en ordre.

## Écrire un test Unity

Le fichier de test fournit `main()`, `setUp()` et `tearDown()` ; le fichier de
l'étudiant ne doit pas définir `main()` (sinon : erreur d'édition de liens, et le
message générique le mentionne). Les noms de test doivent tenir dans
`[A-Za-z0-9_]{1,64}` pour remonter à l'étudiant — ce sont eux qu'il verra, donc
autant les écrire pour lui : `test_pop_pile_vide` plutôt que `test_3b`.

## Pièges de compilation déjà payés

- **`-std=gnu23`, pas `c23`** — coûté un exercice. Un mode ISO strict définit
  `__STRICT_ANSI__`, la glibc désactive alors `_DEFAULT_SOURCE`, et `M_PI`
  disparaît de `<math.h>` (`M_PI` est une extension POSIX). Du code correct, qui
  compile dans CLion (`CMAKE_C_EXTENSIONS` = `ON` par défaut), était refusé avec
  `'M_PI' undeclared`. Le juge doit accepter ce que l'outil de l'étudiant
  accepte. `-D_DEFAULT_SOURCE` aurait soigné le symptôme sans traiter la cause.
  Ce n'était **pas** `-lm` (le juge le passe déjà ; la glibc moderne a fusionné
  libm dans libc, et l'erreur était de compilation).
- **`-DUNITY_INCLUDE_DOUBLE` est obligatoire et son absence ne se voit pas** —
  Unity 2.6 définit `UNITY_EXCLUDE_DOUBLE` par défaut ; sans la macro,
  `TEST_ASSERT_DOUBLE_WITHIN` compile (souche) et **échoue**. Le juge annoncerait
  un test raté sur une solution correcte. Mesuré : sans la macro, 1 échec sur 2.
  Tous les labos de calcul (5, 9, 10) et le devoir en dépendent.
- **En mode unity, le fichier étudiant est en `-std=gnu23` ; les tests et Unity
  sont compilés à part, `-std` par défaut.** Deux unités de traduction, deux
  normes, une seule édition de liens. Si Unity finit par ne pas aimer C23, ça ne
  touche pas le cours.
- **`build-unity.sh` et `build-io.sh` ne sont pas interchangeables.**
  `build-unity.sh` tait la stderr de l'édition de liens (elle citerait le code
  des tests) ; `build-io.sh` la laisse passer entière (il ne voit aucun secret —
  les valeurs attendues restent dans `io.json`, sur l'hôte). Les fusionner ferait
  dépendre la confidentialité d'un `if` bien placé. Même logique pour ASan : en
  mode io le rapport complet remonte, en mode unity seul le fait (code 86).

## Le cache des fichiers servis

`no-cache`, **pas** `no-store`, et la nuance est tout le sujet : `no-cache` veut
dire « garde-le, mais redemande-moi avant de t'en servir ». Le navigateur
revalide donc à chaque visite — un correctif déployé se voit toujours tout de
suite, ce que `no-store` protégeait, et c'est intact — mais un fichier inchangé
revient en 304 vide au lieu de repartir en entier. La page, sa feuille et son
script font 65 Ko, et un étudiant recharge beaucoup.

`no-store` interdisait **aussi** le cache aller-retour du navigateur (bfcache) :
avec lui, le bouton Retour refaisait toute la page. Lighthouse le signalait.

L'ETag est un SHA-256 tronqué du corps, **calculé par représentation** : la
version gzip porte un suffixe `-gz`. Deux corps différents pour une même URL ne
peuvent pas partager une étiquette — un cache intermédiaire servirait l'un en
croyant valider l'autre. `do_HEAD` sur `/` passe par le même code que `do_GET`,
sans le corps : un HEAD qui annoncerait une autre politique serait un piège à
revalidation.

Les réponses d'API (`/r/<id>`, `/etats`, `/pratique`, `/progres`,
`/brouillon`, `/oidc.json`) restent en `no-store`. Ce sont des données de
compte, pas des fichiers.

**La compression est faite ici, à partir de 1 Ko.** Reste à mesurer si
Cloudflare ne la refaisait pas déjà en amont — `curl -sI -H 'Accept-Encoding:
gzip, br' https://<hôte>/app.js` : s'il répond `content-encoding: br` sur une
origine non compressée, les quelques lignes de `_send_file` sont à supprimer.
Même curl à faire pour l'autre constat Lighthouse resté ouvert : 268 Ko de JS à
minifier et 328 Ko inutilisé, alors que tout notre JS fait 30 Ko non minifié.
Le suspect est **Rocket Loader** (Speed → Optimization dans le tableau de bord
Cloudflare), qui réécrit les `<script>` de la page et pourrait aussi expliquer
les erreurs console et l'API dépréciée du rapport.

Le `noindex` du `<head>` est **délibéré** : site temporaire, les étudiants ont
le lien, et rester hors des moteurs limite le trafic sur une infra personnelle.
Le score SEO de Lighthouse (54, « Page is blocked from indexing ») est donc le
résultat attendu — ne pas le « corriger ».

## La progression (phase 1 de la gamification)

Pour les comptes connectés SEULEMENT. L'anonyme ne télécharge rien de tout ça
et n'émet aucune requête : `test_page.js` le vérifie, c'est la raison d'être du
découpage.

**Les chiffres sont dans `app/politique.py`, et nulle part ailleurs.** Montants
d'XP par difficulté, plafond quotidien, seuils de niveau, identifiants et
libellés de succès, plus la `version` qui les date. Piloter le semestre, c'est
éditer ce fichier et redémarrer le conteneur `web` — aucune migration, aucun
changement de logique. Un test refuse qu'un montant réapparaisse en dur dans
`app.py` : sans lui, la politique deviendrait décorative.

**Ce qui produit de la valeur, c'est le SERVEUR en lisant le verdict**, dans
`_result()` — jamais le navigateur. Une seule règle : la **première** réussite
complète d'un exercice publié. Un échec ne rapporte rien, refaire le même
exercice non plus, un sondage rejoué non plus. Les trois tiennent par la même
chose : l'identifiant d'événement vaut `reussite:<exercice>` et sa clé primaire
refuse le doublon. C'est pour ça qu'on peut laisser la pratique illimitée sans
la rendre farmable.

**Les récompenses commencent à l'activation.** Rien ne relit les anciennes
`tentative_pratique` pour distribuer de l'XP rétroactivement. Un exercice
réussi avant la phase 1 puis refait après rapporte une fois, et c'est le
comportement voulu — l'inverse punirait ceux qui ont travaillé tôt.

**Rien n'est mis en cache en base.** Solde, niveau, compétences pratiquées et
recommandation sont recalculés à chaque `GET /progres` depuis trois tables de
faits et le catalogue public. Il n'y a donc pas de projection à reconstruire, et
changer la politique ne demande pas de migration — seules les transactions déjà
écrites gardent la version qui les a produites.

**« Pratiquée » n'est pas « maîtrisée »**, et l'interface doit continuer de le
dire. Le juge est en libre service : une réussite prouve qu'on a soumis quelque
chose qui passe, pas qu'on saurait le refaire seul. La vérification indépendante
est la phase 2 (`docs/gamification/mastery.md`), elle n'existe pas encore.

Trois tables s'ajoutent au schéma : `evenement_progression` (le journal),
`transaction_xp` et `succes_obtenu`, toutes en ajout seul. Côté `VHome`, elles
ont leur propre `GRANT` **sans UPDATE** : l'API n'en a pas besoin, et c'est
Postgres qui tient alors la propriété d'ajout seul. Ajouter une table sans
l'ajouter au `GRANT` la rend muette ; sans l'ajouter à `forget()`, `python3
test_ctester.py` échoue.

## Exploitation (runbook)

**Rotation de la clé** (entre deux sessions, ou si un lien fuite trop loin) :

```sh
openssl rand -hex 24
ansible-vault edit inventory/group_vars/ctester_hosts/vault.yml   # dans VHome
ansible-playbook playbooks/ctester.yml --ask-vault-pass
```

Les anciens liens cessent immédiatement de fonctionner.

**Charge.** `ctester_workers` (2) = compilations simultanées = cœurs que le juge
peut prendre au Dell (chaque conteneur est plafonné à 1 CPU). Ce sont les mêmes
cœurs que Kea et AdGuard : ne pas monter cette valeur sans regarder ce qu'ils
laissent libre. Réduire `ctester_workers` **ne désactive pas** les instances déjà
activées — `systemctl disable --now ctester-runner@3` à la main. Le reste se
règle par variables : `ctester_cooldown_seconds` (15), `ctester_hourly_quota`
(40), `ctester_queue_max` (60, au-delà duquel `/submit` répond 503).

**Diagnostic**, dans l'ordre où ça casse :

```sh
docker info --format '{{json .Runtimes}}'      # runsc enregistré ?
systemctl status 'ctester-runner@*'            # les workers tournent ?
journalctl -u 'ctester-runner@*' -n 50         # ce que dit un job en erreur
docker logs ctester-web-1                      # l'API (silencieuse si tout va bien)
ls /opt/ctester/spool                          # la file, vide au repos
docker exec nginx-manager-npm-1 getent hosts ctester-web-1   # NPM résout-il ?
python3 /opt/ctester/src/test_ctester.py       # les défenses tiennent-elles ?
grep -rl answer /opt/ctester/src/app/*.json /opt/ctester/src/app/quiz/ \
                /opt/ctester/src/app/tp/     # DOIT ne rien trouver
```

## La page — ce qui est fragile

Cinq fichiers, `no-cache` (voir plus bas). `index.html` n'a **aucun
commentaire** : le garder mince est un objectif. Ce qu'il faut savoir avant d'y
toucher :

### index.html

- **`<script id="theme-init">` doit rester INLINE dans le `<head>`.** C'est lui
  qui pose le thème avant le premier rendu ; sorti dans un fichier, il
  arriverait après, et le flash sombre→clair serait déjà passé. Trois lignes,
  elles restent là. (L'attribut `id` n'est plus load-bearing : `test_page.js`
  lisait la page par une expression rationnelle qui exigeait une balise `script`
  sans attribut, et il lit maintenant `app.js` directement.)
- **`<link rel="stylesheet">` reste en tout début de `<head>`.** La feuille est
  externe désormais : plus elle est demandée tôt, moins il y a de risque de voir
  la page non stylée avant qu'elle n'arrive.
- **`<script src="app.js">` reste en FIN de `<body>`**, sans `defer` : le script
  travaille sur le DOM dès son exécution.

### style.css

- **L'éditeur coloré = un `<pre>` (`#hl`) derrière un `<textarea>` (`#code`) au
  texte transparent.** `#hl` et `#code` doivent garder des métriques
  **identiques** : police, taille, interligne, `padding`, bordure, `tab-size`,
  `white-space`. Tout ce qui décale le texte d'un pixel décale les couleurs. La
  gouttière `#gutter` est un troisième texte à aligner, posée **à côté** de la
  superposition, jamais dedans — son contrat est plus court (même `font-size`,
  `line-height`, padding vertical, bordure haute) et tient parce que `#code` est
  en `white-space: pre`.
### app.js

- **Dans le handler de `#go`, la réponse `fetch` est parsée dans un `let out`
  local.** Ne pas réutiliser un nom déjà pris dans la portée (la payload
  `body`) : c'est exactement la `ReferenceError` de zone morte temporelle qui a
  fait la seule panne prod. La réponse n'est pas toujours du JSON (page de
  blocage Cloudflare, erreur nginx en HTML) — d'où le `try/catch` autour de
  `r.json()`.
- **« Tester l'exercice » restreint la LECTURE, jamais la correction.** Le
  juge reçoit toujours les 40 réponses et note le quiz entier — c'est de ce
  verdict complet que l'API dérive `valide`. `restreindre()` ne fait que
  refiltrer `wrong` sur les identifiants de la page affichée. Envoyer un
  sous-ensemble au serveur ferait valider un TP sur un exercice juste.
- **`recordState()` — la page déclare son propre verdict** (`valide` / `essaye`).
  Un étudiant peut se marquer « validé » depuis la console ; sans note en jeu, il
  ne trompe que son propre tableau de bord. Dériver le statut de `result.json`
  côté serveur le jour où ça compte.
- **Tout le bloc connexion est inerte** tant que `/oidc.json` ne renvoie pas
  d'`issuer`. Le jeton vit dans `sessionStorage` (meurt avec l'onglet). Le
  contrôle `state` au retour d'OIDC est un anti-CSRF, pas une décoration : sans
  lui, un lien portant le `code` de quelqu'un d'autre ferait finir la connexion
  sous ce compte.
- **`textContent`, jamais `innerHTML`, pour tout ce qui vient du juge ou du dépôt
  de tests** (consignes pleines de `*` et de chevrons, sortie de programme
  étudiant). La coloration syntaxique échappe **après** le découpage, jamais
  avant.
- **Le catalogue vient de `tps.json`** : `[{id, mode, label, group, short,
  learning, files}]`, où `files` ne porte que des **noms**. Le `mode` décide de
  tout ce que la page affiche et envoie. Le chemin serveur (`path`) est retiré
  avant publication.
- **La consigne et les gabarits viennent de `tp/<id>.json`, à la demande.** Ils
  faisaient les trois quarts du catalogue pour 73 exercices dont un seul est
  ouvert. `chargerDetail()` les garde en mémoire, et **ne met PAS en cache le
  repli** : un réseau qui revient doit pouvoir réessayer. Un détail qui n'arrive
  pas ne bloque rien — les noms de fichiers viennent du catalogue, donc
  l'étudiant peut coller son code et soumettre.
- **`afficherVue()` est le seul arbitre des trois écrans** (exercice, « Mes
  exercices », « Mes progrès »), et il vit dans le noyau. Les deux vues sont
  dans deux modules chargés séparément : si chacun masquait l'autre de son
  côté, en ouvrir une par-dessus l'autre laisserait deux moitiés à l'écran.
  Revenir depuis « Mes progrès » ne repasse PAS par `switchMode()` : c'est ce
  qui garde l'éditeur et le verdict exactement où on les avait laissés.
- **`currentId` est ce que l'ÉDITEUR tient, pas ce que le menu montre**, et
  c'est `setupFiles()` qui le pose. Le remplissage passe par le réseau : le
  poser dans `switchMode()` ferait attribuer le code de l'exercice précédent,
  toujours affiché, à l'identifiant du nouveau dès le prochain `saveDraft()`.

### quiz.js, compte.js et progres.js — chargés à la demande

- **Sens unique, jamais de cycle.** `app.js` détient l'état partagé (jeton,
  catalogue, brouillons) et l'expose une fois dans `window.ctester` ; les deux
  modules lisent ce contexte et y déposent leurs entrées. Ils ne sont jamais
  importés par le noyau. Des modules ES feraient la même chose en liant en
  **zone morte temporelle** sur un import circulaire — la panne exacte que cette
  page a déjà connue en production. D'où l'injection de `<script>`, marquée
  `ponytail:` dans `charger()`.
- **`activerModule()` et pas `activer()`** : `app.js` a déjà une fonction
  `activer`, celle qui change d'onglet dans l'éditeur. Deux déclarations de
  fonction du même nom ne se signalent pas — la dernière gagne, et l'appelant
  reçoit silencieusement l'autre. Ça a coûté une session de débogage.
- **Un échec de chargement n'est pas gardé.** `charger()` oublie la promesse
  rejetée : sans ça, une coupure d'une seconde condamnerait la fonction pour
  toute la visite, le second clic retombant sur le rejet sans jamais retenter.
- **Le parcours anonyme ne télécharge rien de `compte.js` ni de `progres.js`**,
  même sur un déploiement où la connexion est offerte. `test_page.js` le
  vérifie ; c'est la raison d'être du découpage. `progres.js` va plus loin : le
  bouton n'apparaît que connecté, et le fichier ne descend qu'au clic — un
  étudiant connecté qui n'ouvre jamais ses progrès n'en paie rien.
- **`progres.js` ne calcule RIEN.** Solde, niveau, compétences, succès et
  recommandation arrivent tout faits de `GET /progres`. Une page qui calculerait
  son propre XP serait une page où l'on se le donne depuis la console — c'est
  l'erreur que `recordState()` a déjà coûtée, en plus petit.
- **Une projection absente n'est pas un zéro.** Base en panne, API muette :
  la vue affiche un message et AUCUN chiffre. Annoncer « 0 XP » pendant une
  panne, c'est dire à quelqu'un que son travail a disparu.
- **Le contexte expose des FONCTIONS (`ctester.token()`, `ctester.oidc()`,
  `ctester.catalogue()`), jamais des `get`.** `Object.assign` copie la *valeur*
  d'un getter, pas le getter : `ctester.token` est resté figé à `null` pour
  toute la visite, et tout ce qui suit un compte — états, pratique,
  synchronisation des brouillons — tombait en silence. « Mes exercices »
  annonçait « à faire » sur un exercice réussi. Rien ne le signalait parce que
  le harnais n'éprouvait que le parcours anonyme ; il couvre maintenant les
  deux.

## Raccourcis assumés (ponytail)

Marqués `ponytail:` dans le code, rappelés ici pour ne pas les redécouvrir :

- **`app.py`** — cache de jetons : flush complet quand plein, pas de LRU (c'est
  un économiseur d'aller-retour, pas un magasin de sessions). `client_id`
  falsifiable si on tape l'origine sans passer par Cloudflare : régulateur de
  charge, pas contrôle d'accès — la clé de session est le contrôle d'accès.
  Quotas en mémoire, RAZ au redémarrage du conteneur.
- **`etat.py`** — une connexion Postgres derrière un verrou global, pas de pool.
  À 27 étudiants connectés, la file derrière le verrou est vide. `psycopg_pool`
  le jour où elle ne l'est plus.
- **`runner.py`** — le verrou entre workers, c'est `os.mkdir` (atomique, un seul
  hôte). Sondage du spool à 0,5 s ; une unité systemd `.path` le jour où cette
  latence se voit.
- **`etat.py` / `schema.sql`** — progression : trois tables de faits, **aucune
  table de projection**. Le solde est un `sum()` sur quelques dizaines de lignes
  par étudiant ; matérialiser créerait un second endroit où la vérité peut
  diverger. Pas de clé étrangère entre le journal et les XP non plus : les deux
  s'écrivent dans UNE instruction et s'effacent ensemble.
- **`app.js`** — les modules à la demande sont des `<script>` injectés et un
  objet global `window.ctester`, pas des modules ES : voir la section « La page »
  ci-dessus pour la raison (TDZ sur import circulaire). À reprendre le jour où
  l'état partagé est vraiment séparé, pas avant.
