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

Rien à compiler, rien à lier : `app/app.py` et `app/etat.py` sont bibliothèque
standard + `psycopg` (et `psycopg` seulement si `CTESTER_DB_DSN` est là).

## Avant de déployer une modif de la page ou du contenu

Sur le contrôleur, jamais sur le Dell (les trois derniers ont besoin de gcc) :

```sh
python3 test_ctester.py          # les défenses, sans rien installer
node    test_page.js             # le JS de la page, sur un DOM en carton
python3 valider_contenu.py ../unittests
python3 test_bac_a_sable.py      # les deux build.sh, vrai gcc, sans Docker
```

- **`test_ctester.py`** — le parsing des verdicts et la frontière du catalogue
  (`publish_catalogue`, `public_quiz` : aucune clé `answer` ne survit). Pur
  Python, tourne partout, y compris sur le Dell.
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
grep -rl answer /opt/ctester/src/app/     # DOIT ne rien trouver
```

`app/` est tout ce que le conteneur exposé peut lire ; aucun corrigé n'a le
droit d'y être.

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
grep -rl answer /opt/ctester/src/app/          # DOIT ne rien trouver
```

## app/index.html — ce qui est fragile

La page n'a **aucun commentaire** : elle est servie telle quelle, `no-store`, à
chaque visite. La garder mince est un objectif. Ce que les commentaires
disaient, et qu'il faut encore savoir avant d'y toucher :

- **`<script id="theme-init">` — l'attribut `id` est load-bearing.**
  `test_page.js` isole le script de la page par une expression rationnelle qui
  exige une balise `script` **sans** attribut ; une seconde balise nue ferait
  capturer les deux d'un bloc et le harnais compilerait du HTML en croyant
  compiler du JS. Toute balise `script` ajoutée dans `<head>` doit porter un
  attribut.
- **Le thème est posé avant le premier rendu** par ce petit script de `<head>`.
  Plus bas, le flash sombre→clair est déjà arrivé. Trois lignes, elles restent
  là.
- **L'éditeur coloré = un `<pre>` (`#hl`) derrière un `<textarea>` (`#code`) au
  texte transparent.** `#hl` et `#code` doivent garder des métriques
  **identiques** : police, taille, interligne, `padding`, bordure, `tab-size`,
  `white-space`. Tout ce qui décale le texte d'un pixel décale les couleurs. La
  gouttière `#gutter` est un troisième texte à aligner, posée **à côté** de la
  superposition, jamais dedans — son contrat est plus court (même `font-size`,
  `line-height`, padding vertical, bordure haute) et tient parce que `#code` est
  en `white-space: pre`.
- **Dans le handler de `#go`, la réponse `fetch` est parsée dans un `let out`
  local.** Ne pas réutiliser un nom déjà pris dans la portée (la payload
  `body`) : c'est exactement la `ReferenceError` de zone morte temporelle qui a
  fait la seule panne prod. La réponse n'est pas toujours du JSON (page de
  blocage Cloudflare, erreur nginx en HTML) — d'où le `try/catch` autour de
  `r.json()`.
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
  statement, files}]`. Le `mode` décide de tout ce que la page affiche et
  envoie. Le chemin serveur (`path`) est retiré avant publication.

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
