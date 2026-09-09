# CLAUDE.md — notes de travail

Le README est la façade du projet. Ce fichier-ci est pour Claude Code et pour
quiconque modifie le dépôt : ce qu'il faut savoir avant de toucher au code, les
contrôles à repasser avant de déployer, et les pièges déjà payés une fois.

## Dépôt et déploiement

Ce dépôt porte l'application. Le déploiement — gVisor, systemd, Compose, les
deploy keys, le service Postgres, le client Rauthy — vit dans `VHome`, sous
`roles/ctester`. Le serveur clone ce dépôt dans `/opt/ctester/src` et suit
`main` tout seul, à cinq minutes près.

Tout se règle par variables d'environnement, et **tous** les réglages vivent
dans `app/config.py`, avec le défaut du rôle Ansible en face de chacun. C'est ce
qui rend les contrôles ci-dessous exécutables hors déploiement.

Rien à compiler, rien à lier, rien à construire : pas de Dockerfile. L'image
officielle `python:3.13-slim` est lancée telle quelle sur un code monté en
lecture seule, et les dépendances de `requirements.txt` (fastapi, uvicorn,
pydantic, starlette, h11, psycopg) vivent à côté dans le volume `ctester_deps`
(`PYTHONPATH=/deps`), posé par une tâche Ansible qui ne rejoue que si le fichier
change. Une CVE dans l'image, c'est `docker compose pull`.

## L'API — un seul point d'entrée

`app/main.py` (FastAPI/uvicorn), servi par `ctester-web-1:8000`, éprouvé par
`test_api.py`. **Aucune règle métier dans `app/routers/`** : la frontière HTTP
d'un côté, `app/services/` de l'autre.

La v1 `http.server` (`app/app.py`), son harnais de parité (`test_parite.py`) et
les trois `test_http_*` de `test_ctester.py` ont été supprimés le 2026-09-04,
après une semaine de v2 routée par NPM. Ils sont dans l'historique git ; le
commit de suppression est le point de retour si quelque chose se découvre tard.

### Où vit quoi

```
app/config.py     tous les réglages, un seul endroit
app/csp.py        la CSP -- BIBLIOTHÈQUE STANDARD SEULEMENT, voir ci-dessous
app/headers.py    CORS, Vary, cache, ETag/gzip -- UN middleware pour toutes les
                  réponses, 304 et erreurs comprises
app/deps.py       Sub / SubForum / SubModerateur, les quotas, la classe Refus
app/security.py   jetons OIDC, current_user, client_id, is_moderator
app/schemas.py    les corps de requête (Pydantic) -- FORME seulement
app/routers/      une frontière HTTP par domaine, aucune règle métier
app/services/     la logique, sans HTTP -- éprouvée par appel direct
app/services/teams.py   la porte d'un devoir d'équipe, l'identité visible
                        par les coéquipiers, et l'archive de remise
app/services/collab.py  les salles de collaboration : un relais, PAS un CRDT
app/services/scratch.py la Console : le protocole d'une session interactive
```

Deux règles qui tiennent le reste :

- **`schemas.py` ne valide que la FORME** (présence, type). Les règles du
  domaine restent dans `services/` parce qu'elles rendent des messages écrits
  POUR L'ÉTUDIANT, que Pydantic remplacerait par un 400 générique.
- **Aucun modèle ne porte de champ d'identité** (`utilisateur`, `sub`, `owner`,
  `moderateur`). Un test le vérifie en balayant `schemas.py` : la seule source
  de `sub` est le jeton validé.

Trois pièges propres à FastAPI, déjà payés :

- **Pas de route `OPTIONS` attrape-tout.** `OPTIONS /{chemin:path}` fait
  répondre **405** à tout chemin inconnu — Starlette retient sa correspondance
  partielle et ne descend jamais au 404. Le préflight est donc traité dans le
  middleware, avant le routeur.
- **`/docs`, `/redoc` et `/openapi.json` sont publics par défaut.**
  `config.DOCS` les retire : la route n'existe pas, il n'y a rien à contourner.
  Ne jamais poser `CTESTER_DOCS=1` en production.
- **Une erreur Pydantic répond 422 avec un corps qui recopie l'entrée.**
  Intercepté et traduit en `400 {"error": "requête malformée"}` — un corps
  refusé peut contenir le code de quelqu'un ou un jeton mal collé.

**Ce que `test_ctester.py` importe doit rester exécutable sur le Dell sans rien
installer.** `pull.sh` et la vérification Ansible le lancent avec le python de
l'HÔTE — pas celui du conteneur, donc sans `PYTHONPATH=/deps`. Un import de trop
n'y casse pas un test : il bloque le déploiement automatique toutes les cinq
minutes sur un `ImportError`, sans que rien ne soit déployé. C'est pour ça que
`csp()` vit dans `app/csp.py` et pas dans `headers.py`, qui importe starlette.
`test_le_controle_de_l_hote_ne_depend_d_aucun_tiers` monte la garde.

Et une non-négociable : **UN SEUL WORKER uvicorn**. Quotas, présence, cache de
jetons **et salles de collaboration** sont en mémoire de processus ; deux
workers doublent chaque quota en silence — et mettent deux membres de la même
équipe dans deux salles différentes, ce qui ressemble exactement à une panne
réseau sans en être une. Le lancement vit dans `app/main.py` et pas dans une ligne de commande
Compose, pour que personne ne le recopie avec `--workers 4`.

**Les endpoints sont `def`, pas `async def`.** Starlette les exécute alors dans
son threadpool, ce qui laisse `etat.py` synchrone — ses CTE modifiantes et ses
GRANT de colonne sont éprouvés contre un vrai Postgres par `test_postgres.py`,
et les réécrire en SQLAlchemy async remplacerait du SQL prouvé par du SQL à
prouver dans la seule couche où une erreur donne accès aux données d'autrui.

**La page vit dans `web/`, l'API dans `app/`**, et c'est la séparation en cours :
`web/` est destiné à GitHub Pages,
`app/` reste sur le Dell. Tant que les deux ne sont pas séparés, l'API sert
encore les deux — la page depuis `CTESTER_PAGE` (`/web`), le catalogue depuis
`CTESTER_PUBLISHED` (`/published`). Deux variables, deux montages : confondre
les deux fait servir un catalogue introuvable, ou une page introuvable.
`CTESTER_STATIC` a disparu avec la phase 8 : il n'y a plus rien à servir sous
`app/`.

La page est en treize fichiers, tous servis par la liste blanche de `app/routers/page.py` :
`index.html` (le markup seul), `style.css`, `config.js` (l'adresse de l'API),
`app.js` (le noyau), puis `quiz.js`, `compte.js`, `progres.js`, `forum.js`,
`exporter.js`, `classement.js`, `collection.js`, `team.js` et `scratch.js`
(la Console), que le noyau va
chercher **à la demande**. S'y ajoutent trois bibliothèques tierces
**épinglées par version** dans `web/vendor/`, servies par la même liste blanche
et chargées seulement quand elles servent : marked et DOMPurify à l'ouverture
des discussions, Yjs à l'ouverture d'un espace d'équipe — voir
`web/vendor/README.md`.
Rien de tout ça n'est compilé ni assemblé : ce que le dépôt contient est ce que
le navigateur reçoit.

## Le contenu (architecture v2)

**Depuis la phase
8 ce n'est plus un refactor en cours mais l'architecture : l'arborescence
historique `tpN/exN` n'est plus lue par rien, et les deux variables ci-dessous
sont obligatoires.** Un worker sans elles LÈVE plutôt que de publier un
catalogue vide ; une API sans `CTESTER_PUBLISHED` répond 404 à `/catalog.json`
et ne résout plus aucun exercice.

| Variable | Qui | Effet |
|---|---|---|
| `CTESTER_CONTENT` | worker | la racine du contenu privé (`catalog.json`, `exercises/`, `shared/unity`) |
| `CTESTER_PUBLISHED` | worker **et** web | le répertoire des releases (`current.json` + une par révision) |

**LE ROLLBACK EST LE POINTEUR, et rien d'autre.** Réécrire `current.json` sur
une révision précédente est instantané et ne redéploie rien. Vider une variable
n'est plus un rollback, c'est une panne.

```sh
python3 validate_content.py  ../unittests/content                 # phase 1
python3 publish_content.py   ../unittests/content /tmp/published  # phase 3
CTESTER_PUBLISHED=/tmp/published CTESTER_KEY=dev CTESTER_PAGE=web python3 app/main.py
```

- **`content_catalog.py`** — le modèle validé, et `find_exercise(model, id)`,
  **la seule porte** : détail, quiz, brouillon, forum et soumission devront
  passer par elle. Elle refuse ce qui n'est pas ouvert, donc un lien profond
  partagé en avance ne résout pas au lieu de contourner. `access()` est la seule
  lecture d'une release : un `scheduled` dont la date est passée EST ouvert,
  sans commit ni tâche périodique le matin du cours.
- **`publish_content.py`** — la projection publique, **jamais une copie
  récursive**. La révision EST le hachage de ce qui est publié : republier un
  contenu inchangé ne crée rien, le changer crée un répertoire de plus, et les
  deux coexistent — le rollback est un pointeur à réécrire. Le pointeur est
  `current.json` et pas un lien symbolique, parce qu'un montage Docker résout le
  lien à l'attache : rebasculer ne se verrait qu'au redémarrage du conteneur.
- **Un contenu invalide ne remplace jamais la publication active** : `discover()`
  lève avant la première écriture, et le pointeur ne bouge qu'en dernier.
- **L'élagage garde les DERNIÈRES PUBLIÉES, et c'est le `manifest.json` qui le
  dit — pas le `mtime`.** Le mtime d'un répertoire a la granularité que lui
  donne le SYSTÈME DE FICHIERS : sur Linux c'est un tick du noyau, donc
  plusieurs publications à quelques millisecondes d'écart le partagent, et le
  tri retombait alors sur le hachage de la révision, c'est-à-dire sur rien —
  il gardait une révision arbitraire et supprimait une de celles qu'il avait
  promis de garder. **Vert sur Windows (100 ns), rouge sur le Dell**, et
  seulement quand les hachages tombaient mal : publier un devoir les a tous
  changés, et le dé est tombé du mauvais côté. `published_at` est écrit par
  `publish()` lui-même, en microsecondes, et ne dépend d'aucune horloge de
  disque. Le test aplatit maintenant les mtime avec `os.utime` pour reproduire
  le Dell **de façon déterministe** : sans ça, il n'échouait qu'un déploiement
  sur quelques-uns.
- **Le catalogue porte TOUS les exercices, ouverts ou non** (cadenas + date) ;
  le détail et le quiz ne sont écrits que pour ce qui est ouvert. Montrer n'est
  pas donner — la v1 les faisait disparaître, ce qui ressemblait à une panne.
- **La ceinture par-dessus les trois projections** : `projection()` relit ce
  qu'elle vient de construire et refuse de publier si une clé `answer`,
  `expect`, `stdin`, `cases`, `path`… y apparaît. Les trois fonctions publiques
  reconstruisent déjà champ à champ ; ce contrôle attrape le champ qu'on leur
  ajoutera demain. `test_ctester.py` l'éprouve, comme la bascule et le rollback.

### Ce que la phase 4 a branché

- **Le worker.** `tp_path()` reste LA porte ; en v2 elle passe par
  `content_catalog.load_exercise()`, qui rejoue la release — le web l'a déjà
  fait, ce processus est root et ne fait confiance à personne. Elle rend
  `exercises/<id>/assessment`, **la même forme qu'un répertoire de TP
  historique** (configuration, `test_*.c`, `allowed_includes.txt` côte à côte),
  donc `detect_mode`, `read_allowed`, `docker_argv` et le bac à sable ne
  changent pas. Unity, lui, est partagé : `unity_dir()` le prend dans
  `shared/unity`.
- **Les gabarits sont publics, donc hors de `assessment/`** :
  `declared_files(conf, tp_dir)` relit `public/files.json` quand la
  configuration de correction ne déclare rien. Sans ça, tout module à deux
  fichiers (`calendrier.h` + `calendrier.c`) retomberait sur `submission.c` et
  ne lierait plus. Un test l'éprouve avec un module.
- **L'API.** `/tp/<id>.json` et `/quiz/<id>.json` sont servis depuis la
  release ; `/catalog.json` la sert telle quelle. *(La projection `_v1()` qui
  rendait la forme v1 le temps de la bascule est partie en phase 8.)*
- **`exercise_id` est le nom du champ.** Il a été introduit ici à côté de `tp`,
  le temps que les pages en cache des étudiants se rechargent : la page est
  servie depuis une autre origine, l'API et le navigateur ne se redéploient pas
  ensemble, et répondre 400 à la page d'hier aurait été une panne. *(La fenêtre
  est refermée en phase 8 : `tp` n'est plus accepté nulle part, ni dans un corps
  de requête, ni dans le spool.)*
- **La publication reste au worker** : `publish_catalogue()` délègue à
  `publish_content.publish()`. C'est ce qui
  garde la republication au changement de jour — un `scheduled` dont la date
  tombe cette nuit s'ouvre parce que le catalogue est reprojeté, pas parce
  qu'un service redémarre. `CTESTER_PREVIEW` s'y traduit en une DATE (l'an 9999)
  plutôt qu'en un second filtre : `access()` reste la seule lecture d'une release.

### Ce que la phase 5 a branché

- **La page lit `/catalog.json`.** `tps.json` en était le repli le temps de la
  bascule, pour les pages restées dans le cache d'un étudiant. *(Repli retiré en
  phase 8 ; un catalogue absent est maintenant un message, éprouvé dans un
  processus à part — `CTESTER_MODE=absent` — parce qu'un catalogue ne se lit
  qu'une fois par chargement de page.)*
- **Les deux `<select>` ont disparu.** Un menu `<details>` par collection dans
  un `<details>` de barre : le navigateur sait replier, il n'y a pas
  d'accordéon en JS ni d'état d'ouverture à tenir. `selection` (le noyau)
  remplace `$("ex").value` comme source de l'exercice choisi, et
  `ctester.exerciceChoisi()` l'expose à `forum.js`.
- **Le menu porte TOUS les exercices, `ctester.catalogue()` seulement les
  ouverts.** Un exercice verrouillé est au menu, désactivé, avec son cadenas et
  sa date — le faire disparaître ressemblait à une panne la veille du cours.
  Mais il ne doit compter ni dans une progression, ni dans un `main.c` de
  remise, et garder les deux listes séparées évite d'ajouter le même filtre
  dans `compte.js`, `progres.js` et `exporter.js`, où il serait oublié une fois
  sur trois.
- **Un exercice peut appartenir à deux collections** (invariant 3) : il
  s'affiche dans les deux, et ne compte qu'une fois. Un exercice sans
  collection tombe dans « Autres » plutôt que de disparaître.
- **Un lien profond verrouillé ouvre le menu sur le cadenas et la date**, pas
  l'exercice. `find_exercise` refuse déjà de le servir ; ce qui manquait,
  c'était de dire pourquoi et jusqu'à quand.

### Ce que la phase 6 a branché (dans `VHome`, pas ici)

- **`ctester_content_v2` est la bascule, et elle est `false`.** Le rôle rend
  les deux variables VIDES tant qu'elle l'est : le worker et l'API lisent
  `tpN/exN` exactement comme avant. La phase 7 est ce booléen dans
  `group_vars`, et le rollback est de le retirer.
- **`/opt/ctester/published` est root, `0755`, monté `:ro` sur `/published`
  MÊME EN V1** — vide. Basculer n'ajoute donc pas un volume, donc ne recrée pas
  un conteneur le matin du cours. Le répertoire ENTIER est monté, pas
  `published/current` : le pointeur est un fichier pour cette raison-là.
- **Le contenu v2 vit dans le clone de tests** (`tests/content`) : même dépôt,
  même deploy key, et le `chmod -R` plus le `find quiz.json -o io.json` du tick
  le couvrent déjà — les noms n'ont pas changé, seuls les chemins.
- **`ReadWritePaths` du worker perd `src/app` en v2** au profit de
  `published/` : le processus root n'écrit plus dans le code que le conteneur
  web exécute.
- **Le témoin du tick porte la DATE en troisième champ.** Sans elle, un contenu
  figé depuis une semaine n'est jamais republié et un `scheduled` qui ouvre ce
  matin reste fermé jusqu'au prochain commit. Une projection par jour, qui ne
  crée rien quand le contenu n'a pas bougé.
- **Le `grep -rl answer` du tick porte sur les deux racines**, v1 et v2 : on n'a
  pas à se souvenir de laquelle est active le jour où l'alerte compte.
- Le runbook des trois rollbacks (pointeur, variable, republication) est dans
  `roles/ctester/README.md` de `VHome`.

### Ce que la phase 7 a branché (la bascule elle-même)

- **`ctester_content_v2: true` vit dans `group_vars/ctester_hosts/vars.yml`,
  pas dans les défauts du rôle** — qui restent `false`. Le rollback est de
  RETIRER la ligne et de reconverger, pas d'en éditer une autre.
- **Le pré-vol qui décidait de la bascule : les 73 identifiants sont
  IDENTIQUES en v1 et en v2.** C'est le seul écart qui aurait compté —
  brouillons, états, XP et forum sont tous clés sur `exercice_id`, et un
  renommage les aurait détachés sans rien casser de visible. Contrôle jetable,
  fait une fois : la v1 disparaît en phase 8, et un golden test v1/v2
  permanent mourrait avec elle.
- **Ce que le même pré-vol a trouvé et qu'on assume** : `_v1()` rendait le titre
  qualifié dans `short` (« TP2 : ex.3 » là où la v1 rendait « ex.3 ») ; la
  consigne v2 garde le saut de ligne final de `statement.md` ; `tp1`, qui est
  un quiz, a `files: []` et une consigne de remplissage. Les trois ne touchaient
  que le repli `tps.json` ou du texte affiché, et `_v1()` est parti en phase 8.
- **Le témoin de la bascule est `/catalog.json`** : 404 en v1, la release en
  v2. C'est lui qu'un moniteur HTTP interroge, pas `/healthz` — un `/healthz`
  vert avec un catalogue absent est précisément la panne que le repli de la
  page rattrapait en silence. Depuis la phase 8 il n'y a plus de repli : le
  moniteur compte double. Le tick, lui, écrit la révision servie dans son
  journal.
- **En v2 le worker ne réécrit plus `app/{tps.json,tp/,quiz/}`** : ces fichiers
  gelaient à la bascule et servaient de repli aux onglets déjà ouverts. La phase
  8 les supprime.

### Ce que la phase 8 a retiré

**NE PAS DÉPLOYER CE CODE AVANT QUE LA v2 NE TOURNE.** Ce dépôt s'applique tout
seul toutes les cinq minutes ; `ctester_content_v2` ne bascule qu'à un
`ansible-playbook`. Poser la phase 8 sur un hôte encore en v1, c'est une API qui
n'a plus rien à servir et une page qui n'a plus de repli — panne totale, sans
que rien de local n'ait changé.

- **`tps.json`, `/tps.json`, `_v1()`, `TP_RE`, `CTESTER_STATIC`,
  `CTESTER_TESTS`, `CTESTER_APP`** — partis. Avec eux, toute la découverte v1
  de `runner.py` (`entrees_brutes`, `catalogue`, `group_of`, `sort_key`,
  `learning_metadata` et les cinq expressions rationnelles `tpN/exN`) : ~340
  lignes. `publish_catalogue()` ne publie plus qu'une release, et **lève** si
  les deux variables manquent — un worker mal configuré doit s'arrêter en le
  disant, pas servir un menu vide à tout le monde.
- **La porte de l'API s'appelle `find_exercise()`**, comme celle du worker, et
  elle n'a plus besoin de `TP_RE` : elle COMPARE à l'identifiant du catalogue au
  lieu de le concaténer, et c'est `source_publiee()` qui reconstruit le chemin
  depuis l'entrée trouvée. Un `..` ne matche aucune entrée ; il n'y a rien à
  filtrer parce qu'il n'y a rien à accepter.
- **Le catalogue publié EST la forme que l'API lit** : `skills` et `difficulty`
  à plat, plus de bloc `learning`. `exercices_ouverts()` remplace `load_tps()`,
  et `progression.py`/`politique.py` lisent les champs v2 directement. Une
  traduction de moins, donc un endroit de moins où les deux formes divergent.
- **`tp` n'est plus accepté nulle part** : ni dans un corps de requête
  (`_AvecExercice` ne porte plus que `exercise_id`), ni dans le spool
  (`job.json` porte `exercise_id`). `extra="ignore"` fait qu'une page vraiment
  ancienne n'est pas rejetée — elle vise l'exercice vide, que `find_exercise`
  refuse en 404.
- **`verify_content.py` et `test_sandbox.py` prennent la racine v2**
  (`../unittests/content`) et cherchent les corrigés à CÔTÉ
  (`CTESTER_SOLUTIONS`, défaut `<racine>/../solutions`) — le gitlink qui les
  montait sous le contenu part avec cette phase. Les deux acceptent encore la
  disposition `tp6/ex1` du dépôt de solutions, qui n'a pas été migré.
- **Ce qui RESTE, exprès** : l'URL `/tp/<id>.json` (elle vit dans le cache des
  étudiants et ne coûte rien ; elle bougera avec les liens profonds
  `/exercise/<id>`), le paramètre `?tp=` d'un lien partagé, les noms de variables
  `tp_dir` dans le worker (ils désignent un répertoire d'assessment), et le
  message « TP inconnu » rendu à l'étudiant.

## Avant de déployer une modif de la page ou du contenu

Sur le contrôleur, jamais sur le Dell (les trois derniers ont besoin de gcc) :

```sh
pip install -r requirements-dev.txt   # UNE FOIS : fastapi, uvicorn, httpx2
npm ci                                # UNE FOIS : jsdom, contrôles XSS du forum

python3 test_ctester.py          # les défenses, la progression, le forum, les équipes
python3 test_api.py              # l'API : frontière HTTP, bornes, valeurs extrêmes
node    test_page.js             # le JS de la page, sur un DOM en carton
python3 verify_content.py   ../unittests/content
python3 validate_content.py  ../unittests/content   # le schéma seul, sans gcc
python3 test_sandbox.py  ../unittests/content   # les trois build.sh, vrai gcc
```

Et avant une cohorte, une fois, avec Docker — pas à chaque modif :

```sh
docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester            -p 55432:5432 postgres:16-alpine
CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester   python3 test_postgres.py

# ET AVEC LE ROLE APPLICATIF, qui rejoue exactement la production. Le CREATE
# ROLE est tout ce qu'il y a a poser : ses droits viennent de schema.sql.
docker exec -i pg psql -U postgres -d ctester -c "CREATE ROLE ctester_app LOGIN PASSWORD 'y'"
CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester   CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester   python3 test_postgres.py
docker stop pg
```

- **`test_ctester.py`** — le parsing des verdicts et la frontière du catalogue
  (`publish_catalogue`, `public_quiz` : aucune clé `answer` ne survit). Pur
  Python, tourne partout, y compris sur le Dell. Il couvre aussi la
  progression : que `politique.py` reste le SEUL endroit où vit un chiffre
  d'équilibrage, qu'un sondage rejoué ou une réussite refaite n'accorde pas
  deux fois, qu'un échec n'accorde rien, et que `forget()` efface **chaque**
  table du schéma — ce dernier contrôle lit `schema.sql` et `etat.py`, donc
  ajouter une table sans l'effacer le fait échouer tout seul. Il couvre aussi le
  forum : forum éteint par défaut, rôle de modération, bornes, quota, absence de
  double signalement, isolement de deux comptes, l'identité choisie (bornes du
  nom et du groupe, visibilité, nom signalé puis effacé), et qu'aucun `sub` ne
  franchisse la frontière.
- **`test_api.py`** — la frontière HTTP de l'API, et surtout **les bornes des
  deux côtés** : la valeur qui passe et la première qui ne passe plus. Corps à
  `MAX_CODE+4096` puis `+1`, `validate_files` pile à `MAX_CODE` puis `+1`, 500
  réponses de quiz gardées et la 501e jetée, quota horaire N puis N+1, `QUEUE_MAX`
  pile, gzip à 1023 puis 1024 octets, `forum_texte` à 0/1/`MAX`/`MAX+1`, groupes
  0/1/99/100, identifiants de 31/32/33 caractères. Un contrôle qui ne vérifie
  qu'un refus laisse passer une borne posée un cran trop serré, et c'est
  l'étudiant qui la découvre à 23 h la veille de la remise. Il éprouve aussi
  l'ordre des refus (forum éteint → 503 avant 401), qu'aucune route n'accepte un
  identifiant dans son corps, et qu'une base muette rend 503 et **aucun chiffre**.
- **`test_sandbox.py`** — prend `build-unity.sh`, `build-io.sh` et
  `build-scratch.sh` tels quels,
  les exécute avec un vrai gcc, chemins déplacés, sans Docker. C'est le seul
  contrôle qui **éprouve l'invariant de confidentialité** au lieu d'en parler :
  il soumet un module qui déborde d'un tableau et vérifie qu'en mode unity le
  verdict ne contient aucun identifiant du fichier de test — ni le rapport
  d'ASan, dont la pile d'appels nommerait la fonction de test appelante.
  **Sa section 0 est celle de la Console, et elle ne lit AUCUN contenu** : une
  console n'a pas d'exercice, donc ces contrôles tournent même sur une machine
  où le dépôt de tests privé n'est pas cloné. C'est aussi le seul harnais qui
  puisse prouver la fonctionnalité elle-même — que l'invite arrive **avant**
  qu'on écrive sur l'entrée standard — et que `while (1);` meurt sur le temps
  CPU pendant qu'un programme bloqué dans `scanf` survit au même plafond.
- **`verify_content.py`** — compile la solution de référence de chaque exercice
  et la passe dans le vrai juge (il **importe `runner.py`**, il ne refait pas ses
  vérifications). Un exercice sans corrigé apparaît « non prouvé » : rien ne
  garantit alors que son test soit juste. Appelle `catalogue(tout=True)` pour
  qu'un exercice qui ouvre en novembre soit prouvé en septembre.
- **`test_postgres.py`** — le SEUL contrôle qui éprouve le SQL. **La refonte y
  a ajouté trois formes qui ne se prouvent qu'en vrai** : l'UPDATE dont le
  `WHERE` porte à la fois le contrôle d'accès et la transition à sens unique
  (`forum_ouvrir_au_groupe`), l'`INSERT ... SELECT` qui refuse son propre
  message par-dessus une clé primaire qui refuse le doublon (`forum_utile`),
  et la jointure LATERAL qui dérive la réponse retenue du journal plutôt que
  d'une colonne (`forum_fil`). Plus la requête du classement, qui empile un
  `DISTINCT ON`, un LEFT JOIN et un `count(...) FILTER`. Les autres
  simulent la base : ils vérifient la frontière HTTP, pas les instructions. Or
  les écritures de progression et de forum ne sont pas du SQL ordinaire — une CTE
  modifiante qui alimente un INSERT, une CTE modifiante qui alimente un UPDATE, un
  `unnest` d'un tableau paramétré, un `INSERT ... SELECT` dont la clause `WHERE`
  EST le contrôle d'accès, douze DELETE dans une seule instruction — et ces formes
  compilent dans la tête puis échouent en production. Il demande un vrai PostgreSQL ; **sans `CTESTER_DB_DSN` il ne fait
  rien et sort en 0**, et il n'est PAS dans la vérification Ansible parce qu'il
  écrit. Avec `CTESTER_DB_ADMIN_DSN` en plus, il rejoue exactement la
  production : schéma posé par `postgres`, tout le reste par `ctester_app` et ses
  seuls GRANT — ce qui prouve du même coup que le GRANT suffit, que Postgres
  refuse bien l'UPDATE sur les trois tables de progression, et que le GRANT DE
  COLONNE du forum laisse passer `masque` en refusant `texte` et `utilisateur`.
- **`test_page.js`** — exécute le JS contre un DOM en carton et vérifie que la
  soumission part vraiment. **`node --check` ne suffit pas** : la seule panne que
  cette page ait connue en production était une `ReferenceError` de zone morte
  temporelle (une variable redéclarée dans un bloc `try` qui masquait la charge
  utile utilisée deux lignes plus haut). Le `fetch` ne partait jamais, le `catch`
  affichait « le serveur ne répond pas », et les logs du conteneur étaient vides.
  **Il refuse aussi qu'un module déclare deux fois la même fonction** : la
  dernière gagne, en silence, et l'appelant reçoit l'autre — c'est la panne qui
  a coûté une session de débogage (`activer` contre `activerModule`), et elle
  s'est reproduite pendant la refonte (un `exportRow` avait survécu à son
  remplaçant). Cinq lignes, en tête du fichier.
  **Il a maintenant UNE dépendance, de test seulement : `jsdom`** (`npm ci`).
  DOMPurify refuse de travailler sans DOM — `isSupported` passe à faux et
  `sanitize()` rend alors son entrée **telle quelle**. Un harnais qui l'utilisait
  dans cet état écrirait « aucune injection ne passe » sans avoir rien assaini,
  c'est-à-dire le pire des contrôles de sécurité : celui qui rassure. Le fichier
  refuse donc de démarrer sans jsdom, en le disant. L'APPLICATION, elle, n'a
  toujours aucune dépendance npm.

Après chaque `ansible-playbook … --tags tests` :

```sh
grep -rl answer /opt/ctester/published/          # DOIT ne rien trouver
```

`/opt/ctester/published` est tout ce que le conteneur exposé peut lire ; aucun
corrigé n'a le droit d'y être. **Le grep porte sur les fichiers PUBLIÉS, jamais
sur le code** : celui-ci écrit légitimement `answers` (la fonction qui relève
les réponses saisies, le champ `answers` d'une soumission), donc un `grep -rl
answer src/` trouve toujours quelque chose et n'apprend rien. Ce qu'on vérifie,
c'est que la clé `answer` d'un corrigé n'a pas franchi la frontière. Le
répertoire porte TOUTES les révisions gardées, pas seulement la courante : une
révision qu'on pourrait repointer doit être propre elle aussi.

## L'attente estimée

`GET /r/<id>` rend `eta` (secondes) à côté de `position`. **C'est une somme, pas
un rang multiplié par une constante** : un quiz se corrige instantanément, un TP
de dix cas paie dix exécutions, et deux files du même rang n'attendent pas la
même chose.

- **Le worker mesure, l'API additionne.** `runner.enregistrer_duree()` tient une
  moyenne glissante PAR EXERCICE dans `<spool>/durees.json` (fenêtre de 20 jobs,
  pour qu'un cas de test ajouté se voie). Les jobs rejetés avant le conteneur
  (en-tête interdit) sont exclus : ils durent des millisecondes et tireraient la
  moyenne vers zéro précisément parce que les étudiants se trompent souvent.
- **Pas de table Postgres.** Le worker est root sur l'hôte et n'a pas de
  connexion à la base ; le spool est déjà le seul canal entre lui et l'API. Le
  fichier est effaçable, et son absence ne coûte que la première estimation.
- **Un exercice jamais mesuré prend la moyenne des autres**, et à défaut 15 s
  (compilation + une exécution). Jamais zéro : annoncer « tout de suite » sur une
  file pleine est pire que de ne rien annoncer.
- **`CTESTER_WORKERS` ne lance rien**, il divise l'ETA. Il doit suivre
  `ctester_workers` du rôle (2), sinon la page promet un verdict plus vite que le
  service ne le rend. Le conteneur web ne voit pas les unités systemd.
- Éprouvé par `test_ctester.py` (la moyenne glissante) et `test_api.py`
  (`test_eta_somme_les_durees_mesurees_et_retombe_sur_une_moyenne`, jusqu'au
  fichier corrompu qui ne doit pas casser le sondage).

## Le cache de verdicts

Pendant un TP, beaucoup de jobs recompilent un code déjà jugé : le même étudiant
qui resoumet, le gabarit non modifié, le copier-coller. `run_job()` sert alors le
verdict en quelques millisecondes au lieu de dépenser un conteneur, et la file se
vide au lieu de se remplir.

**Il vit dans le worker, et c'est structurel.** La révision publiée
(`publish_content.revision()`) ne hache que la PROJECTION PUBLIQUE : corriger un
`test_*.c` ou un `case` de `io.json` ne la change pas. Une clé fondée dessus
servirait l'ancien verdict après une correction de test. Seul le worker monte
`CTESTER_CONTENT` et peut empreindre `assessment/` lui-même — l'API n'a jamais le
droit de lire les tests, donc elle ne peut pas tenir ce cache.

**Le job passe toujours par le spool.** `/submit`, les quotas, `QUEUE_MAX` et le
sondage `/r/<id>` sont inchangés : le conteneur exposé à Internet ne gagne aucune
surface. Un hit se résout si vite que le rang cesse d'être un problème, ce qui
était tout l'objectif.

**Ce que voit `empreinte_juge()`, en plus du code** : tout `assessment/`,
`shared/unity` en mode unity, `public/files.json` (il décide des noms écrits sur
disque), le `build-*.sh` du mode, `IMAGE`, `SANDBOX_ENV`, et **`runner.py`
lui-même** — `verdict_io`, `parse_unity` et la tolérance par défaut vivent
dedans, et une version de cache à incrémenter à la main serait oubliée
exactement le jour où elle compte. L'invalidation est donc automatique : le tick
de cinq minutes corrige un test, l'empreinte change, le verdict est recalculé.

**`normaliser_c()` ne touche QUE la clé, jamais ce qui est compilé.** C'est un
lexeur C : commentaires retirés, indentation et lignes vides sans effet, un
espace gardé seulement là où il sépare deux jetons (`int x` ne doit pas devenir
`intx`). `_juger()` continue d'écrire les octets exacts de l'étudiant dans
`src/`. Un bogue du lexeur ne peut donc produire qu'un mauvais hit — jamais une
compilation faussée ni un code d'étudiant mutilé. Les directives gardent leur fin
de ligne, sans quoi deux `#define` fusionneraient et deux sources distinctes
partageraient une clé.

**Ni clang-format ni AST, et ce n'est pas de la paresse** : clang-format ne
retire pas les commentaires et garde les lignes vides — il ne peut pas livrer ce
qu'on demande — et un AST voudrait dire un parseur C sur une entrée hostile pour
n'ajouter que l'insensibilité aux parenthèses redondantes, alors que deux
étudiants indépendants diffèrent de toute façon par leurs identifiants. Rien non
plus côté page : le hachage est calculé ici, donc un client qui n'envoie rien de
normalisé obtient déjà la même clé. Y retirer les commentaires décalerait les
numéros de ligne de gcc et appauvrirait les sources gardées dans `etat_exercice`,
pour un gain nul.

**CE QUI N'ENTRE JAMAIS DANS LE CACHE.** `timeout`, `compile_timeout` et `error`
ne sont pas des fonctions du code : les trois plafonds sont du temps mural sous
gVisor, et un code limite passe ou échoue selon la charge du Dell. Geler un ÉCHEC
de malchance enfermerait l'étudiant dans un verdict qu'il ne pourrait plus jamais
faire changer.

**`"cache": false` dans `io.json` / `unity.json` pour un exercice dont le
PROGRAMME est aléatoire.** `tp4-ex1` tire des dés (`in_range`), `tp4-ex2` est un
test statistique sur un million de lancers (`tolerance: 0.02`) : les deux le
portent. **Un futur exercice aléatoire doit le porter aussi** — l'oublier gèlerait
un échec de malchance, et c'est le seul dégât que ce cache puisse faire.

**LE FIFO EST CE QUI COÛTE, PAS LE HACHAGE, et c'est `servir_les_connus()` qui
le règle.** Un doublon au rang 42 attendait derrière quarante et une
compilations -- cinq minutes -- un verdict déjà écrit sur le disque, en occupant
tout ce temps une place que `QUEUE_MAX` compte. La boucle sert donc D'ABORD tout
ce qui est déjà connu, **puis compile UN job**, et repasse : le `break` de
`main()` est cette priorité, pas une optimisation. Une signature par job en
attente coûte moins d'une milliseconde contre les quinze secondes qu'elle évite,
et le mémo `_SIGS` ne la recalcule qu'une fois par job — **porté par l'empreinte
du juge**, pour qu'un test corrigé pendant qu'un job attend change bien sa clé.

C'est aussi ce qui couvre **la rafale** : vingt étudiants sur le gabarit non
modifié dans la même minute ne se voient pas les uns les autres, aucun n'ayant
FINI quand les autres sont dépilés. Dès que le premier termine, la passe suivante
les libère tous. `claim()` ferme la course, c'est le verrou de partout ailleurs.
Le verdict est partagé, **l'attribution ne l'est pas** : chaque job garde son
propre `owner`, et rien de ce que le worker écrit n'est spécifique à un compte.
Un verdict non cachable n'est jamais diffusé -- geler un `timeout` sur vingt
étudiants d'un coup serait pire que de les faire attendre.

**Pourquoi pas dans l'API, où le job ne serait même pas créé.** Ce n'est pas le
stockage qui l'empêche : le cache est dans le spool, que le conteneur web monte
déjà. C'est **la clé** — `empreinte_juge()` a besoin de `assessment/`, des
`build-*.sh`, d'`IMAGE`, des `SANDBOX_ENV` et de `runner.py`, dont ce conteneur
ne monte AUCUN, et il ne doit surtout pas les monter. Il faudrait donc que le
worker publie l'empreinte dans le spool, que `normaliser_c()` vive des deux
côtés de la frontière, et accepter une fenêtre pendant laquelle l'API travaille
sur une empreinte périmée -- c'est-à-dire sert un verdict rendu par un test déjà
corrigé. Le tick de tests ne peut pas la publier non plus : il lance
`publish_catalogue()` avec `CTESTER_CONTENT` et `CTESTER_PUBLISHED` seulement,
donc calculerait une empreinte que le worker ne produit jamais -- 0 % de succès,
en silence. Ce qui reste à gagner est qu'un doublon ne compte plus dans
`QUEUE_MAX` ; ce qui est déjà gagné est l'attente.

**L'ETA ne compte pas les hits, exprès.** Un job servi par le cache dure moins
que `DUREE_MIN`, donc `enregistrer_duree()` l'ignore et la moyenne reste celle
d'une vraie compilation. On ne sait pas à l'avance si un job en file sera un hit :
annoncer plus court que le réel est la seule erreur d'estimation qui se remarque.

**Le magasin est `<spool>/cache/<sig>.json`, et `sweep()` l'épargne** — sans
cette ligne, dix minutes de calme le videraient et il ne servirait plus que
pendant une rafale. Le spool est un bind mount de l'hôte, donc il survit aussi
aux redémarrages du conteneur et des workers.

**IL DOIT TENIR UN SEMESTRE, PAS UNE SÉANCE, et c'est ce qui fixe l'éviction.**
En semaine 4 les exercices de la semaine 1 rouvrent pour réviser l'intra : leurs
entrées sont les plus VIEILLES à l'écriture et les plus utiles ce jour-là. On
jette donc les moins récemment **SERVIES** — `cache_lire()` repose la date à
chaque succès, ce qui fait que « récemment servi » et « souvent servi » se
confondent. Mesuré : 20 000 entrées ≈ 46 Mo, une écriture à 0,89 ms, un élagage
à 129 ms payé une fois par `CTESTER_CACHE_PRUNE_EVERY` (500) écritures — le contrôle
de taille N'EST PAS à chaque verdict, un `os.listdir()` par écriture ne se voyait
pas à 5000 entrées et se serait vu à 20 000.

**Et surtout PAS de TTL.** Une entrée ne périme pas : sa clé porte l'empreinte du
juge, donc un test corrigé la rend **inatteignable**, pas fausse. Un TTL ne
jetterait que des entrées valides, c'est-à-dire ne produirait que des
recompilations gratuites. On n'évince que pour la place.

**Ni étage RAM, ni table Postgres.** Le magasin est fait de fichiers : le page
cache du noyau tient déjà les entrées chaudes en mémoire, partagées entre les
deux workers, là où un cache en processus en ferait une copie par unité systemd.
Et le worker est root sur l'hôte, **sans connexion à la base et sans dépendance
Python** — c'est la même raison qui met `durees.json` dans le spool plutôt que
dans une table. Un blob de verdict indexé par un hachage, c'est exactement ce
qu'un système de fichiers est.

`CTESTER_CACHE_MAX=0` l'éteint sans redéployer, et c'est le rollback.

**Le taux de succès se lit dans `journalctl`**, pas dans un compteur :

```sh
journalctl -u 'ctester-runner@*' -n 500 | grep 'ctester: cache '
```

Trois lignes, et c'est leur RAPPORT qui diagnostique :

| ligne | ce qu'elle dit |
|---|---|
| `cache écrit <ex> <sig>` | un verdict vient d'entrer dans le magasin |
| `cache servi <ex> <sig> [file]` | servi par la passe de priorité — le cas normal |
| `cache servi <ex> <sig> [dépilé]` | servi par la boucle de jugement, une course |

Des `écrit` sans aucun `servi` veut dire que **la clé change entre deux
soumissions** : le code diffère vraiment, ou l'empreinte a bougé — et
`runner.py` en fait partie, donc un déploiement entre les deux soumissions rend
la première entrée inatteignable. C'est le faux négatif à connaître quand on
teste le cache juste après avoir poussé. Aucune ligne du tout veut dire que rien
n'est mis en cache : quiz, `"cache": false`, ou un statut exclu.

**LA PAGE NE RENVOIE PAS UN CODE IDENTIQUE, et c'est le seul raccourci qu'un
client puisse se permettre.** Si le code est identique à l'octet près à sa
dernière soumission pour cet exercice, `soumettre()` réaffiche le verdict qu'elle
tient : aucune requête ne part, donc ni cooldown, ni place de file, ni attente de
sondage. **Elle n'affirme rien au serveur en le faisant** — elle décide seulement
de ne pas le déranger. Un hachage envoyé DANS la requête, lui, choisirait quel
verdict stocké on reçoit : du code cassé plus le hachage d'une soumission réussie
donnerait `passed == total`, que `_enregistrer()` transforme en « validé » et en
XP. C'est la différence entre ne pas demander et dicter la réponse.

- **Le second clic renvoie quand même, et cette échappatoire n'est pas
  optionnelle** : un cas de test corrigé par le tick de cinq minutes rend le
  verdict gardé faux, et la page n'a aucun moyen de l'apprendre. Sans elle,
  c'est le bouton qui aurait l'air cassé.
- **`rejouer` vient du SERVEUR.** Le worker le pose sur tout verdict qu'il
  refuse de mettre en cache lui-même — `timeout`, panne du juge, et les
  exercices dont le PROGRAMME est aléatoire (`"cache": false`), que la page n'a
  aucun moyen de reconnaître seule. La règle vit donc à un seul endroit au lieu
  de deux qui divergeraient.
- **En mémoire seulement** : un rechargement de page refait juger. C'est un
  raccourci de session, pas un cache — et c'est le bon défaut.
- Conséquence pour `test_page.js` : **chaque scénario doit soumettre un code
  différent** (`codeUnique()`). Un harnais qui rejouerait le même texte en
  changeant la réponse du serveur éprouverait ce raccourci-là, pas le rendu des
  verdicts qu'il vise.

**Un cache hit ne se voit pas en zéro seconde côté page**, et ce n'est pas une
panne : `poll()` sonde `/r/<id>` toutes les 2 s et son premier sondage part avant
que le worker (0,5 s de scrutation) ait pu répondre. Le plancher observable est
donc ~2,5 s, ~5 s si le sondage tombe mal. La comparaison juste est avec
`durees.json`, pas avec zéro.

```sh
ls /opt/ctester/spool/cache | wc -l
cat /opt/ctester/spool/durees.json     # ce que coûte VRAIMENT cet exercice
```

Éprouvé par `test_ctester.py` : le lexeur et ses pièges (le `//` d'une URL, un
guillemet en littéral, une apostrophe française dans un commentaire), le fait
qu'un cas de test ajouté change la signature, la politique d'exclusion, la purge,
et surtout `test_run_job_sert_le_cache_sans_recompiler` — deux soumissions du
même code ne dépensent qu'un conteneur.

## La Console — un terminal C interactif

Un étudiant ne pouvait exécuter du C que sous forme de **soumission jugée** :
compiler, passer des cas cachés, recevoir un verdict. Nulle part où essayer
trois lignes, ni voir ce que fait `scanf` sur une entrée qu'on choisit. Pire,
sur une soumission **réussie** la page n'affiche aucune sortie (`verdict_io` ne
remonte que les cas ratés). La Console est le bloc-notes exécutable qui
manquait : un programme C quelconque, lancé, et avec lequel on **dialogue**.

**Elle s'appelle « Console », JAMAIS « bac à sable ».** Le bac à sable est le
conteneur gVisor du juge — `build-io.sh` s'ouvre là-dessus, `test_sandbox.py`
l'éprouve, et la section suivante en parle. Réutiliser le mot ferait ce que ce
dépôt refuse ailleurs (« un seul mot par état »). Côté code, tout s'appelle
`scratch` : `web/scratch.js`, `WS /scratch/live`, `app/services/scratch.py`,
`scratch_draft`. Pas `console` — c'est un global JS.

**UNE SESSION EST UN JOB DE LA FILE EXISTANTE, et c'est ce qui rend la
fonctionnalité petite.** Un répertoire de spool ordinaire portant
`{"kind": "console"}`, `job.json` écrit en dernier par un rename atomique. Elle
attend donc son tour derrière les soumissions, avec la position et l'ETA de
`spool.queue_position()` / `spool.eta_secondes()`, et `QUEUE_MAX` la compte.
**Aucun service nouveau, aucune unité systemd de plus** : le worker qui la
dépile entre dans `run_console()` au lieu d'appeler `_juger()`.

**UNE SEULE SESSION SUR TOUT LE SERVICE**, par un `os.mkdir("<spool>/.console")`.
Il y a deux workers ; si les deux ouvraient un terminal, plus personne ne
corrigerait. **Un worker qui n'obtient pas ce verrou SAUTE le job sans le
réclamer** — sinon il poserait un `.lock` sur un job qu'il ne va pas servir, et
l'étudiant lirait « en cours » sans que rien ne se passe.

**LA SOCKET EST LA DURÉE DE VIE, ET C'EST UN `flock` QUI LE DIT.** Un `mkdir`
n'a pas de propriétaire : c'est pour ça que `claim()` a besoin de `LOCK_STALE`,
`reclaim()` et `reprises.json`. Trois minutes d'attente sont acceptables pour un
job en file, pas pour un terminal qu'un humain regarde. Le noyau, lui, relâche
un `flock` à la mort du processus — y compris sur un SIGKILL du conteneur web —
et le fait à travers un bind mount, puisque c'est le même inode. Deux verrous,
sondés en les *essayant* :

- `alive`, tenu par l'API. Relâché → le worker tue le conteneur (mesuré :
  **0,1 s**).
- `claim`, tenu par le worker. Relâché → l'API dit « le service s'est
  interrompu » au lieu de laisser un terminal s'arrêter sans rien dire.

Ça supprime le fichier `close`, la période de battement et le seuil de
péremption : quatre constantes et un mode de panne, contre une primitive
utilisée deux fois.

**ET LES DEUX SONDES OUVRENT EN LECTURE SEULE, ce n'est pas un détail de
style.** Les deux verrous ne sont pas créés par le même utilisateur : `alive`
par l'API (**uid 65534** dans le conteneur, voir `user:` du `compose.yml`),
`claim` par le worker (**root** sur l'hôte), et tous les deux en 0644. Une
sonde qui ouvre en `O_RDWR` demande donc le droit d'écriture sur le fichier de
l'autre : root ouvrait `alive` sans problème, `nobody` prenait un **EACCES**
sur `claim`, et le `except OSError` traduisait ce refus en « personne ne tient
ce verrou ». La session mourait en annonçant « le service de compilation s'est
interrompu » **sur un worker parfaitement vivant** — une panne asymétrique,
donc invisible tant qu'on ne regarde qu'un côté.

`flock` **ne demande aucun droit d'écriture** — contrairement aux verrous
POSIX de `fcntl.lockf`, il porte sur la description de fichier ouverte et pas
sur le contenu. `O_RDONLY` est donc la correction complète : aucun mode de
fichier à changer, aucun uid à aligner.
`test_les_deux_sondes_de_verrou_ouvrent_en_LECTURE_SEULE` lit **les deux**
sources, parce qu'elles sont jumelles de part et d'autre de la frontière et
qu'en corriger une seule laisse exactement la moitié de la panne — celle qu'on
ne reproduit pas.

**LES TROIS HORLOGES NE MESURENT PAS LA MÊME CHOSE.** Le mur
(`CONSOLE_SESSION_MAX`, 180 s) borne le coût ; l'inactivité (`CONSOLE_IDLE_MAX`,
90 s) libère la place ; et **le temps CPU (`ulimit -t`, 10 s, dans
`build-scratch.sh`) est la seule qui distingue « l'étudiant réfléchit » de « le
programme tourne en rond »**. Plus `CONSOLE_OUT_MAX` (1 Mo), le seul plafond qui
arrête `while (1) puts("x");` — il n'est jamais inactif.

**`CONSOLE_SESSION_MAX` DOIT RESTER TRÈS EN DESSOUS DE `SWEEP_AFTER`.**
`sweep()` efface un répertoire de spool sur son **mtime**, et le mtime d'un
répertoire ne bouge plus une fois ses fichiers créés — écrire dans `out` ne le
rajeunit pas. Une session plus longue se ferait effacer le sol sous les pieds,
en pleine frappe, par l'autre worker. Même classe de contrainte que
`LOCK_STALE`, et un test la tient.

**AUCUNE IDENTITÉ NE FRANCHIT LA FRONTIÈRE DU WORKER.** `job.json` porte
`{"kind": "console"}` et **rien d'autre** — ni `owner`, ni `exercise_id`, ni
`sub`. C'est « aucun modèle ne porte de champ d'identité » étendu jusqu'au canal
du worker, et ça achète deux propriétés gratuitement : `_enregistrer()` exige un
owner **et** un exercice, donc il est inatteignable ; et la passe de cache du
worker ignore la session d'elle-même, puisque `_contexte("")` passe par
`tp_path("")` qui ne résout rien. **Pas un seul `if` ajouté pour ça.**

### Ce qu'un programme peut écrire, et où ça finit

« Interdire toute écriture » n'est pas littéralement possible : gcc doit déposer
le binaire quelque part, et le programme doit s'exécuter depuis ce quelque part.
Ce qui l'est, et qui est fait :

| Cible | Résultat, **mesuré depuis l'intérieur** |
|---|---|
| `/etc/passwd`, `/etc/x`, `/x`, `/usr/x` | `EROFS` (`--read-only`) |
| `/in/src/main.c` (son propre source) | `EROFS` (montage `:ro`) |
| `/spool/…` | `ENOENT` — **le spool n'est pas monté** |
| `/work`, `/tmp` | ouverts : tmpfs de 24 Mo et 8 Mo, **en RAM** |
| remplir `/work` | s'arrête à 8 Mo, « File too large » (`--ulimit fsize`) |
| le disque de l'hôte | **inchangé**, aucun conteneur résiduel |

Trois propriétés en découlent : un tmpfs **compte dans `--memory`**, donc un
programme qui tente de le remplir se fait OOM-killer au lieu de remplir quoi que
ce soit ; un tmpfs meurt avec le conteneur, et `--rm` détruit la couche ; et
côté hôte le répertoire de session est balayé par `sweep()`, le journal ne
portant que `sid`, durée et raison — **jamais le code, jamais un `sub`**.

**PAS DE FILTRE SECCOMP, et ce n'est pas un oubli** : `write` ne peut pas être
bloqué — c'est par lui que sort `printf` — et distinguer « écrire sur stdout »
d'« écrire un fichier » demande de raisonner sur la cible d'un descripteur, ce
que seccomp ne sait pas faire. **La frontière est le système de fichiers, qui se
lit dans l'argv**, plutôt qu'un profil qu'il faudrait auditer. Un test balaie
`docker_argv_console()` et refuse tout `-v` sans `:ro` et tout `--tmpfs`
inattendu.

### `build-scratch.sh`, et le constructeur qui EST la fonctionnalité

**Un troisième script, pas un `if` dans `build-io.sh`.** Celui-là implémente un
*protocole de correction* (chronomètre par cas, cadrage `BEGIN`/`END`, valeurs
comparées sur l'hôte) ; celui-ci n'implémente **aucune correction** et n'a
délibérément **aucun chronomètre mural** — attendre un humain est son état
normal. Les fusionner mettrait un `if [ -d /in/cases ]` entre « un verdict
noté » et « un programme libre qui peut bloquer pour toujours ».

**Le script écrit un `ctester_rt.c` de six lignes et le compile avec le code de
l'étudiant** :

```c
__attribute__((constructor)) static void ctester_rt_unbuffer(void)
{ setvbuf(stdout, NULL, _IONBF, 0); setvbuf(stderr, NULL, _IONBF, 0); }
```

**Sans lui, il n'y a pas de fonctionnalité.** La glibc met stdout en tampon de
**bloc** dès qu'il n'est pas un terminal : `printf("Entrez : ")` suivi d'un
`scanf` n'apparaîtrait jamais avant la fin du programme, et le terminal aurait
l'air gelé au moment précis où il demande quelque chose. **Mesuré : aucune
invite en 25 secondes sans, 0,2 s avec.**

- **Pas `stdbuf`** : il agit par `LD_PRELOAD`, à côté du runtime d'ASan, dépend
  de coreutils *dans l'image*, et `test_sandbox.py` (bare gcc, sans Docker)
  éprouverait un autre mécanisme que la production.
- **Et c'est plus fort qu'un vrai TTY** : un terminal donne un tampon de
  **ligne**, qui ne vide toujours pas un `printf` sans `\n`. `_IONBF` met
  l'invite sur le fil quand `printf` revient, que le programme lise ou non.
- **`static`** : le symbole ne peut pas entrer en collision avec celui d'un
  étudiant.

**`ulimit` PUIS `exec`, jamais un sous-shell.** Le programme prend la place de
bash (donc `docker rm -f` et les signaux l'atteignent, et le code de sortie du
conteneur est le sien) ; la rlimit survit à l'exec ; et il ne reste aucun bash
pour rapporter la mort de son enfant — avec un sous-shell, bash écrivait
`build.sh: line NN: 16 Killed ( ulimit ... )` **dans la sortie de l'étudiant**,
des entrailles de script au moment exact où il faut lui expliquer sa boucle
infinie. Mesuré.

**`<nonce> RUN` sépare les deux flux.** Le nonce n'est plus là pour l'intégrité
d'un verdict (il n'y en a pas) mais pour la **séparation de flux** : avant →
`build` (les diagnostics de gcc), après → `out` (le programme). Le worker coupe
**une fois**, sur un préfixe court, en gardant la queue du tampon entre deux
lectures — sans quoi un marqueur à cheval sur deux `os.read` ne serait jamais
reconnu et toute la session s'écrirait dans `build`.

### Pipes et pas PTY

Chaque avantage d'un PTY est ici déjà obtenu ou coûte : un TTY ne donne qu'un
tampon de ligne (le constructeur fait mieux) ; ONLCR injecte un `\r` par ligne
qu'il faudrait retirer ; le mode canonique impose un tampon de 4096 octets qu'un
bloc collé dépasserait **en silence** ; l'écho du TTY concurrencerait celui de
la page. Et mécaniquement, `docker run -t` refuse quand le stdin du client n'est
pas un terminal : il faudrait `pty.openpty()`, passer l'esclave au CLI, laisser
docker mettre le maître en mode brut, et parler à travers son proxy à un
**second** pty alloué par dockerd dans un sentry gVisor qui réimplémente la
discipline de ligne en Go. `ponytail:` — le jour où `isatty()`, Ctrl-C comme
signal ou ncurses comptent, c'est xterm.js **et** un vrai pty, décidés ensemble.

### Il n'y a PAS de liste d'en-têtes autorisés, et c'est un choix

La liste est **pédagogique, pas sécuritaire** : son message est « utilise
seulement ce qui a été vu en cours », et elle vit dans l'`assessment` d'un
**exercice**. Une console n'a pas d'exercice, donc pas de liste. Et elle n'a
jamais été la frontière : `system()` vient de `<stdlib.h>`, que tous les
exercices autorisent. `#include <unistd.h>` compile donc ici, et `fork()` est
arrêté par les plafonds, pas par une expression rationnelle sur du texte brut.
**Un test l'éprouve**, sinon quelqu'un la rajoute « par symétrie » dans six mois
et hérite de deux listes à tenir synchronisées. Si l'enseignant tranche
autrement : **un seul endroit, le worker** — jamais l'API, dont la dérive qui
compte serait d'accepter ce que le worker refuse.

### Ce qui reste à faire au déploiement (`VHome`)

1. **Aucune unité systemd nouvelle**, aucun `ReadWritePaths` à changer.
2. `CTESTER_BUILD_SCRATCH` sur l'unité `ctester-runner@`. **Pas de tâche
   `copy`** : les trois constructeurs sont référencés depuis `ctester_app_dir`,
   c'est-à-dire le clone git que `ctester-pull.timer` met à jour tout seul. Une
   copie serait un second exemplaire à faire dériver.
3. `ctester_scratch: true` dans `group_vars`, qui rend `CTESTER_SCRATCH=1` côté
   web (**absente = Console éteinte**, comme le forum). Le rollback est de
   retirer la ligne. Le rôle **refuse de converger** si `ctester_workers < 2`.
4. **`ctester_workers` doit rester ≥ 2** : avec un seul worker, une session gèle
   toute la correction pendant `CONSOLE_SESSION_MAX`.
5. **NPM : rien.** « Websockets Support » est par proxy host et `/team/live` l'a
   déjà activé — mais le prochain le cherchera, d'où cette ligne.
6. **`wsproto` DOIT ÊTRE DANS `/deps`**, et c'est la panne qui a fait que la
   Console n'a jamais ouvert une seule session. `requirements.txt` refuse
   `uvicorn[standard]` — pour de bonnes raisons, écrites là-bas — mais cet
   extra était aussi ce qui apportait une implémentation WebSocket. Sans elle,
   uvicorn résout son protocole à `None` et répond **501 à chaque poignée de
   main**, sans rien journaliser : `/team/live` et `/scratch/live` ne s'ouvrent
   jamais, le navigateur ne voit qu'une connexion refusée, et **tout le reste
   du site marche parfaitement**. `wsproto` et pas `websockets` : pur Python,
   même raisonnement qu'`h11`, et sa seule dépendance est `h11` déjà épinglé.
   La tâche Ansible rejoue sur la somme de contrôle du fichier, donc il n'y a
   rien de plus à faire — mais le démarrage l'avertit désormais dans
   `docker logs`, et `test_ctester.py` refuse un `requirements.txt` sans
   implémentation WebSocket.

**⚠ CE DÉPLOIEMENT INVALIDE LE CACHE DE VERDICTS, UNE FOIS.**
`empreinte_juge()` hache `runner.py` lui-même : y toucher rend les 20 000
entrées du magasin **inatteignables** (pas fausses), et elles se recompilent à
la demande suivante. C'est le faux négatif déjà documenté plus haut. Coût
unique, **à ne pas payer un matin de séance**.

## Les quatre soumissions hostiles

À repasser après toute modification du bac à sable — elles sont la seule preuve
que les défenses tiennent encore.

| Soumission | Attendu |
|---|---|
| `while (1) fork();` | `timeout`, l'hôte ne bouge pas |
| `system("curl http://exemple");` | échoue, `--network=none` |
| `while (1);` | `timeout` à 5 s |
| `#include <unistd.h>` hors liste blanche | rejeté avant même de lancer un conteneur |

**EN SESSION DE CONSOLE, LA QUATRIÈME LIGNE NE S'APPLIQUE PAS** (il n'y a pas de
liste — voir « La Console »), et la fenêtre d'exposition passe de 5 s par cas à
`CONSOLE_SESSION_MAX`, soit trente-six fois. C'est pourquoi la
mémoire y est **plus serrée** que pour la correction, et pourquoi `while (1);` y
est arrêté par le **temps CPU** et non par un chronomètre mural. À repasser sur
les deux chemins.

**`--pids-limit` N'EST PAS UN PLAFOND DE LA CONSOLE, et l'y serrer a coûté une
soirée.** Sous `runsc` ce cgroup compte les tâches de l'HÔTE — c'est-à-dire les
threads du sentry gVisor — et pas les processus de l'étudiant, qui sont
internes au sandbox. À 32, le sentry ne démarre pas du tout : `docker` rend
« cannot create sandbox: cannot read client sync file: waiting for sandbox to
start: EOF », **avant le premier octet compilé**. `CONSOLE_PIDS` est donc ÉGAL
à `PIDS` (64), le seul plafond de la Console qui ne soit pas en dessous — il
reste posé pour le chemin `runc`, où il compte bien. Ce qui arrête vraiment un
`while (1) fork();` ici, c'est la mémoire et `ulimit -t`.

Sur la fork bomb, **vérifier le résultat et pas le mécanisme** : sous `runsc`,
les processus créés dans le bac à sable sont internes à gVisor, donc
`--pids-limit` (un contrôle cgroup) ne les compte pas forcément. Ce qui l'arrête
alors est le plafond mémoire du sandbox et le chronomètre. Les deux options
restent en place — l'une couvre `runc`, l'autre `runsc` — et ce qui compte est
que `uptime` sur le Dell ne bronche pas.

## Ajouter ou modifier un TP

**Pousser sur le dépôt privé de tests suffit.** `ctester-tests.timer` (dans
`VHome`) tire toutes les cinq minutes, republie le catalogue et refait
lui-même le `grep -rl answer` ci-dessus — un tick qui trouve une clé de corrigé
sort en erreur sans poser son témoin.

**Ce timer ne redémarre rien, et il peut donc tourner en pleine séance.** Rien
entre le disque et l'étudiant ne garde de copie en mémoire : `cases`,
`tolerance` et `quiz.json` passent par `load_config()`, relu **à chaque job** ;
le catalogue par `load_catalog()` dans `app/services/catalogue.py`, relu **à chaque requête**, pointeur compris. Un cas de
test ajouté est en service à la soumission suivante, une consigne corrigée au
rechargement suivant. `publish_catalogue()` y est appelé dans un processus à
part — le redémarrage du worker n'a jamais été qu'un moyen de le déclencher.

Pour ne pas attendre les cinq minutes, ou pour voir ce qu'a dit le dernier tick :

```sh
systemctl start ctester-tests        # sur le Dell
journalctl -u ctester-tests -n 30
```

Et à la main, quand il faut converger pour autre chose en même temps :

```sh
ansible-playbook playbooks/ctester.yml --tags tests --ask-vault-pass
```

### Voir un TP avant son ouverture

Pour éprouver ses corrigés dans la vraie page, avec les vrais tests, avant les
étudiants : `CTESTER_PREVIEW=1` traduit la date d'ouverture en l'an 9999. Il
agit à la publication **et** dans `tp_path()` — un exercice qu'on voit est un
exercice qu'on peut soumettre.

```sh
CTESTER_PREVIEW=1 CTESTER_CONTENT=../unittests/content \
CTESTER_PUBLISHED=/tmp/published \
  python3 -c 'import runner; runner.publish_catalogue()'
CTESTER_KEY=dev CTESTER_PUBLISHED=/tmp/published CTESTER_PAGE=web python3 app/main.py
```

Pour de vrais verdicts il faut en plus un worker (Docker + gVisor) ; sans eux,
`verify_content.py` reste le contrôle qui dit si un test est juste. Ce n'est
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
croyant valider l'autre. Un `HEAD` sur `/` passe par le même code qu'un `GET`,
sans le corps : un HEAD qui annoncerait une autre politique serait un piège à
revalidation.

Les réponses d'API (`/r/<id>`, `/etats`, `/pratique`, `/progres`,
`/brouillon`, `/preferences`, `/oidc.json`, `/forum*`, `/live`) restent en
`no-store`. Ce sont des données de compte (ou, pour `/live`, un compteur
volatil), pas des fichiers.

**La compression est faite ici, à partir de 1 Ko.** Reste à mesurer si
Cloudflare ne la refaisait pas déjà en amont — `curl -sI -H 'Accept-Encoding:
gzip, br' https://<hôte>/app.js` : s'il répond `content-encoding: br` sur une
origine non compressée, les quelques lignes de `headers.fichier()` sont à supprimer.
Même curl à faire pour l'autre constat Lighthouse resté ouvert : 268 Ko de JS à
minifier et 328 Ko inutilisé, alors que tout notre JS fait 30 Ko non minifié.
Le suspect est **Rocket Loader** (Speed → Optimization dans le tableau de bord
Cloudflare), qui réécrit les `<script>` de la page et pourrait aussi expliquer
les erreurs console et l'API dépréciée du rapport.

Le `noindex` du `<head>` est **délibéré** : site temporaire, les étudiants ont
le lien, et rester hors des moteurs limite le trafic sur une infra personnelle.
Le score SEO de Lighthouse (54, « Page is blocked from indexing ») est donc le
résultat attendu — ne pas le « corriger ».

## Le compteur de présence

`GET /live?id=<jeton>` → `{"n": <fenêtres ouvertes>}`, affiché discrètement dans
le bandeau (`#live`) **pour tout le monde, anonyme compris**. C'est la SEULE
entorse à « l'anonyme n'émet aucune requête » — assumée, le battement va vers un
`dict` en mémoire (`deps.presence`, une `Presence`), jamais vers la base ni
un compte, et ne porte aucun jeton.

- **Polling, pas WebSocket.** Un seul worker uvicorn devant une connexion
  Postgres unique : 200 sockets persistantes n'y ont pas leur place.
  Un battement toutes les 60 s × 200 étudiants = ~3 req/s sur une opération de
  dict. `ponytail:` — repasser en WebSocket le jour où « live » doit dire
  quelque chose de plus fin qu'« à la minute ».
- **Le jeton `id` vient du navigateur** (`crypto.randomUUID`, gardé dans
  `sessionStorage`), donc falsifiable et non authentifié : c'est un chiffre
  affiché, pas un contrôle. Sans `id`, `live()` (`routers/sante.py`) retombe
  sur l'IP (une école = une fenêtre) plutôt que d'exposer quoi que ce soit.
- **RAZ au redémarrage du conteneur**, comme les quotas. TTL de 150 s
  (`CTESTER_PRESENCE_TTL`, 2,5 battements) pour qu'un ping raté ne fasse pas
  clignoter le total.
- **Une panne de `/live` ne se voit pas** : `battement()` avale l'erreur et
  `#live` reste caché. Le compteur ne doit jamais gêner un exercice.
- `test_page.js` vérifie qu'il s'affiche pour l'anonyme ; `test_ctester.py`
  (`test_presence_compteur`) vérifie le dédoublonnage et l'expiration.

## La progression (phase 1 de la gamification)

Pour les comptes connectés SEULEMENT. L'anonyme ne télécharge rien de tout ça
et n'émet aucune requête — **à la seule exception du battement `/live`** (voir
« Le compteur de présence » ci-dessous) : `test_page.js` le vérifie, c'est la
raison d'être du découpage.

**Les chiffres sont dans `app/politique.py`, et nulle part ailleurs.** Montants
d'XP par difficulté, plafond quotidien, seuils de niveau, identifiants et
libellés de succès, plus la `version` qui les date. Piloter le semestre, c'est
éditer ce fichier et redémarrer le conteneur `web` — aucune migration, aucun
changement de logique. Un test refuse qu'un montant réapparaisse en dur dans
le service : sans lui, la politique deviendrait décorative.

**Ce qui produit de la valeur, c'est le SERVEUR en lisant le verdict**, dans
`_enregistrer()` (`routers/soumission.py`) — jamais le navigateur. Une seule règle : la **première** réussite
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
est la phase 2, livrée à côté et JAMAIS mélangée à ces compteurs-ci : voir « La
maîtrise vérifiée » plus bas.

Trois tables s'ajoutent au schéma : `evenement_progression` (le journal),
`transaction_xp` et `succes_obtenu`, toutes en ajout seul. Elles ont leur propre `GRANT` **sans UPDATE**, dans
`schema.sql` : l'API n'en a pas besoin, et c'est Postgres qui tient alors la
propriété d'ajout seul. Ajouter une table sans l'ajouter au `GRANT` **ou** à
`forget()` fait maintenant échouer `python3 test_ctester.py` — deux contrôles
qui lisent le schéma plutôt que d'entretenir une liste.

## La maîtrise vérifiée (phase 2 de la gamification)

Pour les comptes connectés SEULEMENT, comme la progression. Une **vérification**
est une activité distincte de la pratique : elle dit ce qu'un étudiant sait
refaire, là où l'XP ne compte que ce qu'il a soumis. Le contrat complet est dans
`docs/gamification/mastery.md`, la décision dans `D-010`.

**AUCUNE TABLE NOUVELLE, donc rien à changer dans `VHome`.** Une évidence est
une ligne d'`evenement_progression` — le journal en ajout seul existe déjà, son
`type` est libre et sa `charge` est du JSON. Le GRANT `SELECT, INSERT, DELETE`
posé en phase 1 suffit, `forget()` les efface déjà, et le schéma portait
toujours ses treize tables. `test_postgres.py` le rejoue avec le rôle applicatif et ses seuls
droits : c'est là que se vérifie qu'aucun privilège n'a été ajouté en douce.

**Une vérification est un exercice ORDINAIRE, marqué.** `"verification": true`
dans son `exercise.json`, **quel que soit son mode** — un quiz de lecture de
code et un débogage `io` sont l'un et l'autre des vérifications valables. Rien
du juge, du bac à sable ni de la publication ne change. Les trois premières
(`verif-tp1`, `verif-tp2`, `verif-tp2-debogage`) vivent dans la collection
`verifications`, et le corrigé de la seule qui en demande un est dans le dépôt
de solutions sous `verif/tp2-debogage/`.

**ELLE N'ACCORDE AUCUN XP, et c'est le seul `if` que ça coûte** — dans
`_enregistrer()` de `app/routers/soumission.py`. L'XP compte de l'activité, la
maîtrise mesure une capacité ; les mélanger rendrait la vérification farmable et
l'XP indistinguable d'une note. L'état et la tentative de pratique, eux,
s'écrivent dans les deux cas : l'étudiant doit voir qu'il a fait l'activité, et
garder son brouillon.

**L'ÉVIDENCE S'ÉCRIT AUSSI QUAND C'EST RATÉ.** Sans la trace d'un échec, la
bande « à consolider » n'existerait pas et une compétence tentée sans succès
serait indistinguable d'une compétence jamais abordée. L'identifiant est
`verification:<exercice>:<job>` : un sondage rejoué n'écrit rien, un RÉESSAI est
un autre job donc un autre fait — les tentatives restent historiques.

**LES BANDES SONT UNE COUVERTURE, PAS UN SCORE, et il n'y a AUCUN SEUIL
nulle part.** Pour une compétence, on lit la dernière tentative de chacune de
ses vérifications ouvertes : toutes réussies → « vérifié », au moins une → « en
progression », tentée sans succès → « à consolider », rien de tenté → « pas
encore vérifié ». Ajouter une vérification à une compétence rend « vérifié »
plus exigeant tout seul. C'est ce qui permet de livrer la phase 2 sans trancher
la question ouverte des seuils : elle n'était requise qu'avant un affichage
chiffré, et il n'y en a pas. `politique.py` ne porte que les libellés.

**Une compétence sans vérification n'a pas de bande**, et ne s'affiche pas :
lui reprocher « pas encore vérifié » serait lui reprocher une lacune du contenu.

**UNE VÉRIFICATION NE COMPTE DANS AUCUN COMPTEUR DE PRATIQUE**, et le filtre est
posé UNE fois, dans `exercices_pratique()` de `app/services/progression.py`.
Sans lui, elle gonflerait « exercices publiés », les compétences pratiquées, la
recommandation et le `main.c` de remise — quatre endroits, dont trois où
personne ne l'aurait vu. Côté page, `exercicesExportables()` porte le même
filtre : `test_page.js` échoue si on le retire, et le main.c exporté gagne un
`#if exercice == N` que l'énoncé ne prévoit pas.

**Un succès ne se retire pas, une bande si.** `verifications_reussies()` compte
les vérifications réussies AU MOINS UNE FOIS (monotone, pour
`premiere-verification`), `dernieres_tentatives()` ne garde que la dernière
(pour la bande). Confondre les deux ferait disparaître un succès sur un réessai
raté.

`GET /progres` fait maintenant SIX allers-retours SQL derrière le verrou unique
d'`etat.py` — le seuil de refonte reste un p95 au-dessus d'une seconde, que
`load_test.py` signale.

## Le forum d'entraide (hors phases, entre 1 et 2)

Pour les comptes connectés SEULEMENT, **et seulement si des modérateurs sont
configurés**. L'anonyme ne télécharge rien de tout ça — ni `forum.js`, ni les
74 Ko de bibliothèques de rendu — et n'émet aucune requête (hormis `/live`,
comme partout) ; `test_page.js` le vérifie, comme pour la progression.

**Il est ÉTEINT par l'absence d'une variable, pas par un booléen.**
`CTESTER_FORUM_MODERATORS` vide → `forum_enabled()` est faux → le bouton
n'apparaît pas, `/oidc.json` annonce `forum: false`, et les six routes répondent
503 en le disant. Un forum sans personne pour le lire est un canal de partage de
solutions avec une charte dessus ; on ne l'ouvre pas « en attendant ». Le
démarrage l'écrit dans `docker logs` quand OIDC est actif et la liste vide.

**Le rôle de modération est recalculé côté serveur à chaque appel**, depuis le
`sub` authentifié, et jamais depuis un claim OIDC : un rôle dérivé d'un claim non
vérifié se réclame depuis n'importe quel compte. La page reçoit bien un drapeau
`moderateur`, mais il ne sert qu'à décider quoi dessiner.

**Aucun `sub` ne franchit la frontière HTTP.** `forum_vue()` traduit l'auteur en
« Vous » / « Enseignant » / le nom que l'étudiant a **choisi d'afficher**,
sinon « Participant ». Un test l'éprouve en cherchant les `sub` dans la charge
JSON — y compris dans la vue la plus renseignée, celle d'un modérateur.

**L'étiquette du staff est « Enseignant », pas « équipe ».** Le mot « équipe »
est laissé libre pour de futures équipes d'étudiants **au sein d'un groupe** (pas
encore décidé) — l'étiquette du personnel ne doit pas entrer en collision avec.
L'ancienne « Équipe du cours » reste dans `_PSEUDOS_RESERVES` pour que personne
ne puisse la reprendre.

**Le formulaire d'identité vit dans le menu Compte, pas dans la vue.**
`#identitepanneau` est le même encart flottant que la charte et le consentement,
dessiné par `forum.js` (`ouvrirIdentite()`), chargé au clic comme le reste du
module. C'est un réglage : dans la colonne du fil, il repoussait la charte et le
formulaire de publication à chaque visite. Un seul endroit, donc un seul endroit
où la visibilité peut diverger de ce que la base dit — l'intro de la vue
Discussions se contente de dire où le trouver.

**L'identité est choisie, facultative, et invisible par défaut.** `forum_profil`
est un journal en ajout seul (la dernière ligne d'un compte fait foi) : un nom
d'affichage, un numéro de groupe, et **deux** cases de visibilité
indépendantes. Rien n'apparaît sans que son porteur l'ait coché — une seule
exception, écrite dans le formulaire : **l'enseignant voit le numéro
de groupe en tout temps**, jamais le nom s'il n'est pas affiché.

**`CTESTER_FORUM_GROUPES` fixe la liste des groupes de la session** (défaut
`4,6`). Non vide → le formulaire est une liste déroulante fermée et le service
refuse tout autre numéro ; vide → champ libre 1 à 99 (l'ancien comportement).
La colonne reste `SMALLINT CHECK (1..99)` — la liste d'une session ne vit pas
dans le schéma. Cocher sans
avoir écrit n'affiche rien (le service refuse la visibilité d'un champ vide), et
les étiquettes de l'interface (« Vous », « Participant », « Enseignant », et
l'ancienne « Équipe du cours ») sont des noms réservés : un message qui se
ferait passer pour une réponse du cours ne se rattrape par aucune couleur.

**Le `preferred_username` de Rauthy PRÉ-REMPLIT, il ne synchronise pas.**
`current_name()` lit le claim déjà rapporté par `/userinfo` (aucun appel de
plus, il voyage dans le cache de jetons) et il n'est offert que tant que le
compte n'a pas choisi de nom. Rien n'est enregistré ni affiché avant un clic sur
« Enregistrer » avec la case cochée : chez Rauthy ce nom est souvent le code
d'accès de l'école, et le publier tout seul serait un consentement pris de
travers. Il passe par la même validation que ce qu'un étudiant taperait.

**Un nom affiché est signalable**, par la même route que les messages
(`{quoi: "nom"}`) et avec la poignée d'un message, faute d'identifiant de compte
côté page. Le modérateur a une file séparée et une seule action : **effacer le
nom** — une ligne de profil de plus, `par_moderateur` à vrai, le groupe et le
message intacts. Pas de ligne dans `forum_moderation` : ce journal-là porte
l'état `masque` d'un message, et y écrire « masquer-nom » rétablirait un message
caché au passage.

**Le rendu est la partie dangereuse, et il a deux barrières.** Les messages sont
stockés SOUS LEUR FORME SOURCE ; le serveur ne rend rien et n'assainit rien, il
borne. Dans `forum.js` : (1) `<` est échappé AVANT l'analyse Markdown, donc
`marked` ne voit jamais une balise venant d'un étudiant ; (2) sa sortie passe par
DOMPurify avec une allow-list fermée. **`<` seulement, pas `>`** — échapper `>`
tuait la citation Markdown, qui est dans l'allow-list, et une balise commence
toujours par `<`. L'assainissement se fait **à chaque affichage** (le fil,
l'aperçu, la vue de modération) et pas à l'écriture : une règle resserrée plus
tard doit s'appliquer aux messages déjà en base. `rendreMarkdown()` porte le
SEUL `innerHTML` du client, et il reçoit la sortie de l'assainisseur à l'instant
même. Si une bibliothèque manque ou si `DOMPurify.isSupported` est faux, tout
retombe sur `textContent` — du texte brut, jamais du HTML non filtré.

**La CSP n'est pas la défense principale**, et le commentaire de `csp()` le dit.
Elle existe maintenant **en deux exemplaires** : l'en-tête que pose `csp()` (ce
serveur, et le mode local) et le `<meta http-equiv>` de `index.html`, seul
moyen d'en avoir une quand GitHub Pages sert la page — Pages ne pose aucun
en-tête. `test_csp_du_document` compare les deux **directive par directive** :
éditer l'une sans l'autre fait échouer les tests.

**Il n'y a plus AUCUN script inline, et c'est ce qui rend les deux copies
tenables.** Un `<meta>` ne peut pas porter un hachage calculé sur le corps
servi ; recopier le hachage à la main le ferait périmer à la première virgule
changée, en silence, en emportant le thème. Le bootstrap du thème vit donc dans
`web/config.js`, chargé **en tête de `<head>` sans `defer`** — un `<script src>`
classique bloque le rendu, donc il tourne avant la première peinture exactement
comme l'inline qu'il remplace. `script-src 'self'` suffit alors, sans hachage,
et `csp()` **lève** si un inline réapparaît plutôt que de le hacher en douce.

**`frame-ancestors` est la seule perte réelle** : un `<meta>` ne peut pas le
porter, et le navigateur le signale en console — or une console rouge est une
panne prod déjà vécue. Il est donc absent du `<meta>` exprès, présent dans
l'en-tête, et à reposer devant Pages par une Transform Rule Cloudflare
(`X-Frame-Options: DENY`). Le test vérifie cette asymétrie précise.

L'en-tête est aussi posé sur le 304, sinon il disparaîtrait dès la deuxième
visite. `style-src` garde `'unsafe-inline'` : la page pose des attributs `style`
calculés (jauges, coches de verdict).

**Un message est immuable.** Son auteur le supprime, un modérateur le masque ou
le rétablit — et c'est tout. Côté Postgres, les trois tables sont en ajout seul
avec **un GRANT DE COLONNE** pour la seule exception : `UPDATE (masque) ON
forum_message`. Pas d'UPDATE de table : une ligne de Python distraite ne peut pas
réécrire le texte de quelqu'un. `test_postgres.py` éprouve les deux moitiés.

**Le quota du forum est compté PAR COMPTE, pas par IP** (contrairement à celui
des soumissions), et il ne couvre que les écritures : un quota qui empêcherait de
relire un fil empêcherait de suivre la réponse qu'on attend.

**Ajouter une table de forum sans l'ajouter à `forget()` fait échouer
`test_ctester.py`** — le contrôle lit `schema.sql` et compte les tables.

## Le chat en direct (public, à auteurs masqués)

Un étudiant qui a peur du ridicule ne pose pas sa question. Le chat est la
réponse à ça, et **ce n'est pas un canal secret : tout y est public, c'est le
NOM DE L'AUTEUR qui est masqué**, avec la possibilité de l'afficher pour qui le
veut. Le forum, lui, garde ses questions privées (« Je suis bloqué ici »)
exactement comme avant.

**LE CHAT EST UN PRÉFIXE DE CLÉ DE FIL, PAS UNE TABLE.** `@chat:<exercice>` et
`@chat:general` sont des valeurs de plus dans `forum_message.exercise_id`, et
`est_chat()` est le seul prédicat que la distinction coûte — il sert à trois
endroits : forcer la visibilité, choisir le rendu de l'auteur, étiqueter
l'écran. Une table `chat_message` aurait dupliqué la borne de texte, le quota,
le signalement, la modération, le masquage et `forget()` : six règles dont
celle qui dérive est celle qui cesse de border. Une colonne `kind` aurait
ajouté un `WHERE` à chaque requête du forum, et celui qu'on oublie est celui
qui mélange les deux espaces. **`@` ne peut apparaître dans aucun identifiant
du catalogue**, donc une clé de chat ne résout chez personne et ne devient
jamais un chemin.

**TOUT EST PUBLIC, ET C'EST UNE LIGNE DANS `forum_visibility()`.** C'est ce qui
supprime la moitié difficile de la fonctionnalité : `can_see()` **ne change pas
d'un caractère** — « visible de tous » est déjà son premier cas — donc il n'y a
**aucune règle de confidentialité neuve** à écrire pour le chat.

**L'ANONYME EST MASQUÉ, PAS INDISTINCT.** « Participant » pour tout le monde
rendait une conversation illisible : on ne sait pas qui répond à qui. Le repli
de `forum_identite()` est donc l'**alias** — `policy.possible_aliases()`, 324
combinaisons d'un vocabulaire **fermé**, donc rien de ce qu'un étudiant tape ne
peut l'atteindre, **donc il n'y a aucun pseudonyme à modérer**. C'est la même
valeur qu'au classement, exprès : une seule identité masquée par compte.
L'ordre est : soi-même → « Vous (alias) », un modérateur → « Enseignant », un
nom choisi et rendu public → ce nom, sinon l'alias, sinon « Participant ».
**On a modifié `forum_identite()`, pas dupliqué** : une seconde fonction
d'identité serait le second endroit où la visibilité d'un nom peut diverger de
ce que la base dit. Conséquence assumée : le forum en profite aussi.

**L'ALIAS EST RÉTROACTIF, et c'est une propriété.** `forum_profile` est en ajout
seul et la dernière ligne fait foi, donc « Un autre nom » renomme l'auteur
affiché de tout l'historique — un étudiant qui se sent exposé se détache de son
passé d'un clic. Le formulaire le dit avant le clic.

**LE PSEUDONYME ÉTAIT INATTEIGNABLE, ET C'ÉTAIT LE BLOCAGE.** Le bloc de
`forum.js` était dessiné sous `if (profil.alias)` alors que la **seule** chose
qui écrit un alias est le bouton dedans : il était donc caché exactement pour
les comptes qui n'en avaient pas. Bénin tant que l'alias n'était qu'une
décoration de classement, bloquant dès qu'il est la façon d'apparaître. Le
bloc est désormais inconditionnel, un alias est tiré **à la première
écriture** (`_assurer_alias`, best effort — vocabulaire épuisé ⇒
« Participant », **jamais un refus de publier**), et `test_page.js` refuse que
la garde revienne.

**`reply_to` PORTE TOUJOURS LA RACINE.** Répondre à une réponse stocke l'id de
la racine, et l'aplatissement est `COALESCE(t.reply_to, t.message_id)` **dans
le SQL** : un fil reste plat à dessiner, sans profondeur à borner. C'est de la
**navigation, pas de la confidentialité** — la règle que la colonne porte est
l'intégrité (la racine doit exister dans le même fil), et c'est le `WHERE` de
l'`INSERT ... SELECT`.

**LA LECTURE DU FIL SE BORNE PAR RACINE**, et c'est l'historique qui l'impose :
à dix mille messages, borner les messages finirait par couper entre une
question et sa réponse, et la réponse reviendrait seule, illisible pour la
personne à qui elle était écrite. La fenêtre garde aussi les racines les plus
**récentes** — elle gardait les plus anciennes, ce qui aurait affiché les deux
cents premiers messages du semestre et jamais celui qu'on vient d'écrire.

**LA SOCKET EST UNE SONNETTE, PAS UN TRANSPORT.** `WS /forum/live` envoie
`{"t":"new"}` et rien d'autre ; le client relance `GET /forum`. C'est ce qui
garde `can_see()`, le quota, la borne de 1200 caractères, les listes fermées et
le tirage d'alias à **un seul endroit**. Conséquence gratuite : un lecteur sans
droit sur un message reçoit la sonnette et redessine la même chose — même
l'**existence** du message ne fuit pas. `notify()` traverse depuis le
threadpool par `loop.call_soon_threadsafe`, **enveloppé** : une sonnette ratée
ne fait jamais échouer un `POST /forum`. `services/forum_live.py` est un `dict`
en mémoire de processus, comme `collab.py` — **une raison de plus pour un seul
worker**.

**LE −1 EST INTERDIT SUR UNE QUESTION PAR LE `WHERE`, PAS PAR L'INTERFACE.**
`forum_helpful` gagne une colonne `value` (±1) et son INSERT une quatrième
condition : `AND (%(value)s = 1 OR m.reply_to IS NOT NULL)`. Une question ne
peut donc pas être enterrée par un vote — la promesse d'un endroit fait pour
ceux qui ont peur de demander —, et c'est Postgres qui la tient, pas le fait de
ne pas dessiner le bouton. Sur une question, le +1 se lit « moi aussi » : c'est
lui qui donne « les questions les plus courantes », sans compter personne.
Un GRANT de colonne de plus, `UPDATE (value)`, pour le changement d'avis.
**Le vote n'accorde toujours rien** : ni XP, ni succès, ni carte.

**LA RECHERCHE ET LA DÉTECTION DE DOUBLON SONT LA MÊME REQUÊTE**
(`GET /forum/search`), sur une colonne `tsvector` **générée** et un index GIN —
aucune extension, aucun trigger, aucun GRANT. **La confidentialité y est le
`WHERE`** (`visibility = 'thread' OR account = moi`) : une question privée du
forum ne remonte jamais comme « quelqu'un a déjà demandé ça ». **Un modérateur
n'a pas d'exception** — il lit les fils, et une branche de moins est une
branche de moins à se tromper. Pas de `freiner_forum` dessus : c'est une
lecture, et un cooldown de 10 s la rendrait inutile pendant la frappe ; le
débounce est côté page.

**`GET /forum/message` est le permalien**, et il existe parce qu'un résultat de
recherche vieux de trois mille messages n'est dans la fenêtre d'aucun fil :
sans lui, la recherche montre des extraits qu'on ne peut pas ouvrir.

**`GET /forum/top` est une route à part, pas un élargissement de
`/forum/help`.** Le docstring de celle-là est un contrat écrit — « COUNTS AND
STEPS, NEVER PEOPLE » — et un classement a besoin du texte. Les étudiants ne
voient **aucun palmarès** : un compteur public sur ce que chacun a demandé est
le contraire de ce que tout ceci cherche.

**Ce qui n'est PAS construit** : aucun élagueur d'historique (rien ne supprime,
donc il n'y a pas de limite à écrire — `FORUM_MAX_FIL` borne l'affichage, pas
la conservation) ; aucune pastille de non-lu hors de la vue (elle demanderait
une socket permanente pour tout le monde, la charge que `/live` a refusée) ;
aucun regroupement automatique de doublons (on propose, un humain décide) ;
aucun « en train d'écrire ». Et **aucun nouveau drapeau** : tout s'éteint avec
le forum, par `CTESTER_FORUM_MODERATORS` vide.

**Côté déploiement : rien.** « Websockets Support » est déjà coché (`/team/live`
l'a activé), `wsproto` est déjà dans `/deps`, les migrations de `schema.sql`
sont idempotentes, et le seul GRANT nouveau vit dans `schema.sql`.

**Un piège déjà payé ici** : un `CREATE INDEX` sur une colonne ajoutée par un
`ALTER` plus bas passe sur une base neuve et **fait tomber la convergence** sur
une base existante. `test_aucun_index_ne_precede_la_colonne_qu_il_indexe` monte
la garde, et il a servi.

## Le classement : l'enseignant le lit, il n'y figure jamais

Lire `/leaderboard` n'a jamais demandé de participer — la route n'est gardée
que par `Sub`. Ce qui manquait est l'inverse : **rien n'empêchait un enseignant
d'y APPARAÎTRE** s'il cochait la case, et son XP est de l'XP de test.

L'exclusion est **une clause dans le même `WHERE` que l'opt-in**
(`AND p.account <> ALL(%(staff)s::text[])`, la liste venant de
`config.FORUM_MODERATORS`) : un modérateur ne produit **aucune ligne**, donc il
n'y a rien à masquer en aval, et `divisions_view()` hérite de l'exclusion
gratuitement. L'équité ne doit pas dépendre de se souvenir de ne pas cocher.
La charge ne lui renvoie pas non plus d'`alias` — dire « tu apparais sous X » à
quelqu'un que la requête exclut serait la page qui contredit le SQL.

**`?group=` n'est honoré que pour un modérateur**, rôle recalculé côté serveur.
Pour un étudiant il est **ignoré, pas refusé** : c'est un paramètre de confort,
et un 403 ferait ressembler un lien partagé à une panne.

**LE SEUIL DE COHORTE MINIMALE S'APPLIQUE À L'ENSEIGNANT AUSSI**, et c'est un
refus délibéré. C'est le seul garde-fou qui empêche un tableau de décrire
quatre personnes identifiables, et l'enseignant est précisément celui qui
pourrait relier des pseudonymes à des visages au fil des semaines.

## Le thème enregistré sur le compte

**`localStorage` était par appareil, et c'est tout le problème qu'on répare.**
Un étudiant qui passe du labo à son portable repartait chaque fois du thème par
défaut. Le compte transporte déjà le brouillon d'un poste à l'autre ; le réglage
d'affichage prend le même chemin — `preference_affichage`, une ligne par compte,
`GET`/`PUT /preferences`.

**Le stockage local RESTE, et il ne fait pas doublon.** C'est lui que le
`web/config.js` du `<head>` lit avant le premier rendu ; le serveur,
lui, répond toujours après la première peinture. Ce que le compte dit est donc
recopié dans `localStorage` — pas pour être relu dans la foulée, mais pour que
la visite SUIVANTE sur cet appareil parte déjà du bon thème, sans le flash
sombre→clair que ce script existe pour éviter.

**Un thème vide n'est pas une panne**, et `chargerTheme()` distingue les deux :
« aucun choix enregistré » (200, `theme: ""`) prend le thème courant de
l'appareil et l'envoie au compte, « la base ne répond pas » (503) ne touche à
rien. Les confondre écraserait le réglage de quelqu'un à la première panne.

**C'est la SEULE table du schéma, avec le brouillon et l'état, qui n'est pas en
ajout seul** : `ON CONFLICT ... DO UPDATE`. L'ancien thème n'est pas un fait à
relire, et un journal grossirait à chaque clic sur un bouton fait pour être
cliqué. Son `GRANT` porte donc `UPDATE`, comme `exercise_draft` — et il vit dans
`schema.sql`, à côté de la table. Il a vécu dans `VHome`, et **son oubli n'a
échoué qu'en production** : c'est l'une des trois fois qui ont motivé le
déménagement (voir « Les droits du rôle applicatif »).

**Le bouton vit dans le noyau, la synchronisation dans `compte.js`.** L'anonyme
a le bouton et n'émet aucune requête en le cliquant (`test_page.js` le
vérifie) : `app.js` n'appelle `ctester.compte.enregistrerTheme()` que si le
module est là, et le module ne fait rien sans jeton. Rien n'est attendu non
plus — le thème est déjà à l'écran, et un aller-retour raté ne doit pas donner
l'impression que le bouton n'a pas marché.

## Exporter un TP en un seul `main.c`

Le cours distribue et attend un fichier d'un seul tenant : un `#define exercice
N` en tête qui choisit lequel des `main()` est compilé, un `#if exercice == N
... #endif` par exercice, les `#include` remontés une fois au-dessus. CTester
garde un brouillon PAR exercice ; sans ce bouton, l'étudiant recolle huit
fichiers à la main la veille de la remise, et c'est là qu'il en perd un.

**Tout se passe dans la page, et c'est délibéré.** `exporter.js` lit les
brouillons et fabrique le texte ; aucune route n'a été ajoutée. La seule chose
que le serveur a gagnée, c'est `exporter.js` dans la liste blanche des fichiers
servis (`app/routers/page.py`) — un module absent de cette liste tombe en 404.

**Seulement les TP « io », et au moins deux exercices.** `#define exercice N` ne
choisit un `main()` que là où il y en a plusieurs : un exercice « unity » est un
module SANS `main()`, un quiz n'a pas de code, et un TP d'un seul exercice ne
cumule rien. La règle vit dans `groupeExportable()` du **noyau**, pas dans le
module : c'est elle qui décide si le bouton existe, et il faut le savoir avant
d'aller chercher le fichier.

**Deux boutons, un seul module.** Celui de la barre d'actions exporte le TP
affiché ; « Mes progrès » en pose un sous la dernière ligne de chaque TP
exportable. Chacun passe son propre `annoncer(texte, rate)` — `#brouillon` n'est
pas à l'écran depuis la vue liste, et un module qui choisirait lui-même où
écrire écrirait dans le vide une fois sur deux.

**Ça marche SANS compte** : les brouillons de l'appareil suffisent, et l'export
n'émet alors aucune requête. Avec un compte, les exercices qui manquent
localement sont demandés à `/brouillon?ex=` **un par un** — c'est la connexion
Postgres unique derrière son verrou global, dix requêtes d'un coup prendraient la
file à tout le monde.

Quatre détails déjà payés, tous éprouvés dans `test_page.js` :

- **Les `#include` ne remontent qu'au PREMIER NIVEAU.** Un `#include` déjà pris
  dans un `#if` de l'étudiant est là POUR cette condition ; le remonter le
  rendrait inconditionnel et changerait le sens de son code. `demonter()` compte
  donc la profondeur des conditionnelles au lieu de balayer le texte.
- **Le dédoublonnage porte sur l'en-tête, pas sur la ligne.** `#include
  <stdio.h>  // pour printf` et `#include <stdio.h>` sont le même include ; les
  garder tous les deux parce qu'un étudiant a commenté le sien rate exactement
  ce que le bouton promet. La ligne gardée reste la sienne, commentaire compris.
- **Les `#define` restent dans leur bloc.** Deux exercices d'un même TP
  définissent couramment `DIMANCHE`, `LUNDI`, … et c'est le `#if` qui les
  empêche de se marcher dessus. Seul `_CRT_SECURE_NO_WARNINGS` remonte.
- **Le numéro vient de l'identifiant (`tp2-ex0` → 0), et le compteur du premier
  bloc non vide est initialisé à `null`, pas à `0`** : le préambule du
  laboratoire 2 EST l'exercice 0, et `if (!premier)` le prenait pour « rien
  trouvé ». Un exercice sans brouillon garde sa place, avec un commentaire qui
  le dit — le retirer décalerait toute la numérotation par rapport à l'énoncé.

**Le fichier part en UTF-8 AVEC sa marque d'ordre.** Sans elle, Visual Studio
lit un fichier sans en-tête dans la page de code du système et les accents des
commentaires de l'étudiant deviennent du charabia — c'est visible dans le
fichier d'origine du cours. gcc et CLion sautent la marque sans rien dire.

**Le champ `Auteur` est pré-rempli, pas imposé.** CTester ne connaît qu'un `sub`
opaque : le seul nom disponible est celui choisi dans « Mon identité », ou la
proposition de Rauthy. Même traitement que le formulaire d'identité — on
pré-remplit un champ que l'étudiant relit, dans un fichier qui va sur SON
disque. Rien n'est publié, et le champ reste vide si on ne sait pas.

## Mesurer avant de tourner un bouton

`load_test.py` existe pour qu'on arrête de régler `ctester_workers` à l'instinct.
**Jamais pendant une séance** : il écrit dans la base, remplit la file et fait
compiler pour de vrai.

```sh
CTESTER_KEY=<la clé de session> CTESTER_LOAD_EXERCISE=tp2-ex3 \
CTESTER_LOAD_TOKEN=<un vrai jeton, pris dans sessionStorage> \
  python3 load_test.py http://ctester-web-1:8000
```

**Contre l'origine, sur le LAN**, pas contre le nom public : mesurer à travers
Cloudflare mesurerait Cloudflare. C'est aussi ce qui permet au script de poser
lui-même `CF-Connecting-IP` pour simuler 200 étudiants distincts — sans ça, une
seule IP se ferait limiter dès la deuxième soumission et on mesurerait le
régulateur, pas le service.

**Un seul jeton rejoué par tous les fils**, parce qu'on ne fabrique pas 200
comptes OIDC. La mesure reste juste : le coût serveur d'une lecture de
progression ne dépend pas de qui la demande — même travail SQL, même verrou
global dans `etat.py`, et c'est ce verrou qu'on vient regarder.

**Ce que le script ne voit pas, il faut le lire sur le Dell pendant qu'il
tourne** : `docker stats --no-stream ctester-web-1 ctester-postgres`, `uptime`,
`ls /opt/ctester/spool | wc -l`.

Ce qu'on décide APRÈS, et pas avant :

- **`GET /progres` fait six allers-retours SQL sérialisés** derrière le verrou
  unique. Les regrouper en une lecture est faisable et pas fait : à 27 étudiants
  la file derrière ce verrou est vide, et une requête groupée est plus dure à
  relire. Le seuil, c'est un p95 de `/progres` au-dessus d'une seconde — le
  script le signale tout seul.
- **`ctester_workers` et `ctester_queue_max`** ne montent pas parce que la file
  s'allonge : chaque worker prend un cœur, et ce sont les mêmes cœurs que Kea et
  AdGuard. Regarder ce qu'ils laissent libre AVANT, pas le rang maximum seul.

## Exploitation (runbook)

**Rotation de la clé** (entre deux sessions, ou si un lien fuite trop loin) :

```sh
openssl rand -hex 24
ansible-vault edit inventory/group_vars/ctester_hosts/vault.yml   # dans VHome
ansible-playbook playbooks/ctester.yml --ask-vault-pass
```

Les anciens liens cessent immédiatement de fonctionner.

**Les étudiants choisissent leur équipe** dans « Mon identité », dans une liste
numérotée par groupe — la même que sur Moodle, et **les numéros doivent
correspondre** (`team.count` dans le contenu dit combien il y en a par groupe).
Il n'y a rien à faire avant le cours, et rien qui exige de connaître leurs
`sub`.

**Les listes se figent à l'ouverture du devoir**, sans intervention : c'est la
même date que celle qui ouvre le document.

**`import_teams.py` est l'outil de CORRECTION**, quand il faut trancher après
coup. CSV : `group_number,number,account`.

```sh
# SUR LE DELL, `--sql` : le python de l'hôte n'a AUCUN paquet tiers, et y
# installer psycopg pour deux chargements par session mettrait une dépendance
# sur la seule machine que le projet garde propre. Toutes les vérifications de
# `read_roster()` tournent quand même -- elles sont en Python pur, et un
# listage refusé n'imprime pas une ligne.
python3 import_teams.py devoir roster.csv --sql   | docker exec -i ctester-postgres psql -U postgres -d ctester -v ON_ERROR_STOP=1

# Ailleurs (avec psycopg), le même fichier par la connexion directe :
CTESTER_DB_ADMIN_DSN=postgresql://postgres:...@127.0.0.1/ctester   python3 import_teams.py devoir roster.csv --dry-run   # vérifie, n'écrit rien
CTESTER_DB_ADMIN_DSN=... python3 import_teams.py devoir roster.csv
```

Les deux chemins passent par `statements()` — **une seule source d'instructions**,
sinon celui qui dérive est celui qu'on utilise le jour où l'autre ne marche pas.
Le `sub` d'un compte se lit dans Rauthy, ou :

```sh
docker exec ctester-postgres psql -U postgres -d ctester -tAc   "SELECT DISTINCT account FROM exercise_state"
docker exec ctester-postgres psql -U postgres -d ctester -c   "SELECT * FROM team_member"      # ce qui est chargé aujourd'hui
```

Le CSV fait autorité : une appartenance qui n'y est plus est retirée. Les
équipes, elles, ne sont jamais supprimées toutes seules — effacer une équipe
orphelinerait les documents qu'elle a écrits.

**Placer quelqu'un après l'ouverture** — celui qui n'a rien choisi, ou qui
s'est trompé d'équipe : c'est le seul cas qui demande l'enseignant, puisque
les listes sont alors figées pour tout le monde. Volontairement pas de bouton
d'expulsion dans la page : il faudrait décider qui l'a, et à 27 étudiants qui
se connaissent le problème se règle en parlant.

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
journalctl -u ctester-tests -n 30              # le dernier tick de tests
journalctl -u ctester-pull  -n 30              # le dernier tick d'application
cat /opt/ctester/.tests-deployed               # les révisions de tests publiées
docker logs ctester-web-1                      # l'API (silencieuse si tout va bien)
docker exec ctester-web-1 python3 -c   "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"
ls /opt/ctester/spool                          # la file, vide au repos
docker exec nginx-manager-npm-1 getent hosts ctester-web-1   # NPM résout-il ?
python3 /opt/ctester/src/test_ctester.py       # les défenses tiennent-elles ?
grep -rl answer /opt/ctester/published/        # DOIT ne rien trouver
cat /opt/ctester/published/current.json        # la révision servie
ls /opt/ctester/spool/cache | wc -l            # le cache de verdicts
du -sh /opt/ctester/spool/cache                # ~46 Mo pour 20 000 entrées
```

## L'adresse de l'API et CORS

**`web/config.js` est le SEUL endroit où vit l'adresse de l'API**, et il décrit
ce que chaque déploiement est vraiment, pas la cible :

| Hôte | `CTESTER_API` | Pourquoi |
|---|---|---|
| `tch009.thevhome.com` | `""` | le Dell sert encore la page ET l'API : même origine, chemins relatifs |
| `*.github.io` | `https://tch099.thevhome.com` | déploiement de préparation, déjà séparé |
| tout le reste | `""` | `CTESTER_PAGE=web python3 app/main.py` |

`window.API(chemin)` préfixe, et **rien d'autre** : les modules chargés à la
demande et les deux vendor sont à côté de la page, donc `charger()` ne change
pas. Les deux `fetch` OIDC de `compte.js` (découverte, token endpoint) portent
des URL absolues venues de l'émetteur — **ne pas** les préfixer.

`tch099` et pas `api.tch009` : le certificat universel de Cloudflare couvre
`thevhome.com` et `*.thevhome.com`, **une seule étiquette**. Deux étiquettes
demanderaient Advanced Certificate Manager.

**CORS tient dans UN middleware, `app/headers.py`.** Les réponses partent de
partout (JSON, fichiers, 304, erreurs, préflight) : les poser à un seul endroit,
après le routeur, est le seul moyen qu'aucune ne les oublie — **304 compris**,
sans quoi CORS disparaîtrait dès la deuxième visite, comme la CSP avant lui.

- `CTESTER_ORIGINS`, liste séparée par des virgules, **jamais `*`** : chaque
  requête de compte porte un `Authorization`. Une origine inconnue ne reçoit
  **aucun** en-tête et le navigateur bloque de lui-même ; pas de 403, un réglage
  oublié ne doit pas ressembler à une panne de service.
- **Un seul en-tête `Vary`, et il annonce les deux axes** (`Accept-Encoding,
  Origin`). Deux lignes `Vary` séparées sont légales mais mal recombinées par
  certains caches, et un cache qui perd `Origin` sert la réponse d'une origine à
  une autre.
- Le préflight répond 204 pour toute route, depuis le middleware. **`DELETE` est dans
  `Allow-Methods` et doit y rester** : `compte.js` supprime un compte,
  `forum.js` un message. L'oublier ne casse que le cross-origin — donc
  seulement la production, et seulement ces deux boutons-là.
- **Pas de `Allow-Credentials`** : aucun cookie ici, le jeton voyage en en-tête.
- Le préflight est mis en cache 24 h (`Max-Age`) : sans lui, chaque PUT et
  chaque DELETE paierait un aller-retour de plus.

Le tout est éprouvé dans `test_api.py` (`test_cors_origine_connue_et_inconnue`,
`test_un_seul_vary_annoncant_les_deux_axes`,
`test_preflight_sur_toute_route_meme_inconnue`, `test_304_garde_la_csp_et_le_cache`)
et les trois branches de `config.js` à la fin de `test_page.js`.

## La page — ce qui est fragile

Neuf fichiers (voir « L'API — un seul point d'entrée »), `no-cache` (voir plus
bas). `index.html` reste mince : le markup et quelques commentaires de
structure, aucun script. Ce qu'il faut savoir avant d'y toucher :

### index.html

- **L'ordre du `<head>` est : icône, `<meta charset>`, le `<meta
  http-equiv="Content-Security-Policy">`, viewport, robots, titre, `config.js`,
  `style.css`.** Le `<meta>` CSP doit rester juste après `<meta charset>` et
  avant tout ce qu'il gouverne : un navigateur n'applique la politique qu'à
  partir du moment où il la lit.
- **`<script src="config.js">` vient avant `<link rel="stylesheet">`, SANS
  `defer`.** C'est lui qui pose le thème avant le premier rendu depuis qu'il
  n'y a plus d'inline (voir « La CSP » plus haut) ; un `<script src>`
  classique bloque le rendu, donc il tourne avant la première peinture. Avec
  `defer`, ou en fin de `<body>`, le flash sombre→clair serait déjà passé. La
  feuille, elle, est demandée juste après : plus tôt ne l'afficherait pas plus
  vite, puisque rien n'est encore peint.
- **Aucun `<script>` inline, jamais.** `script-src 'self'` du `<meta>` le
  bloquerait, et `csp()` lève plutôt que de le hacher. `test_page.js` et
  `test_ctester.py` le vérifient tous les deux.
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
- **Tout le bloc connexion est inerte** tant que `/oidc.json` ne renvoie pas
  d'`issuer`. Le jeton vit dans `sessionStorage` (meurt avec l'onglet). Le
  contrôle `state` au retour d'OIDC est un anti-CSRF, pas une décoration : sans
  lui, un lien portant le `code` de quelqu'un d'autre ferait finir la connexion
  sous ce compte.
- **`textContent`, jamais `innerHTML`, pour tout ce qui vient du juge ou du dépôt
  de tests** (consignes pleines de `*` et de chevrons, sortie de programme
  étudiant). La coloration syntaxique échappe **après** le découpage, jamais
  avant.
- **Le catalogue vient de `/catalog.json`, et il n'y a plus de repli.**
  `normaliser()` en tire DEUX listes : `collections` (l'arbre du menu, tous les
  exercices avec `access` et `available_from`) et `catalogue` (les exercices
  ouverts, aplatis en `{id, mode, label, group, short, learning, files}` — la
  forme que « Mes progrès » et l'export lisent). `files` ne
  porte que des **noms** ; le chemin serveur ne franchit jamais la publication.
  Le `mode` décide de tout ce que la page affiche et envoie. Un 404 sur
  `/catalog.json` est un message, pas un menu vide.
- **`label` est qualifié, `short` est nu.** « ex.1 » tout seul désigne un
  exercice dans chacun des dix TP, et « Mes progrès » n'a pas de colonne de
  collection pour lever l'ambiguïté.
- **La consigne et les gabarits viennent de `tp/<id>.json`, à la demande.** Ils
  faisaient les trois quarts du catalogue pour 73 exercices dont un seul est
  ouvert. `chargerDetail()` les garde en mémoire, et **ne met PAS en cache le
  repli** : un réseau qui revient doit pouvoir réessayer. Un détail qui n'arrive
  pas ne bloque rien — les noms de fichiers viennent du catalogue, donc
  l'étudiant peut coller son code et soumettre.
- **`afficherVue()` est le seul arbitre des quatre écrans** (exercice, « Mes
  progrès », « Discussions », « Modération »), et il vit dans le noyau. Les
  trois vues sont dans deux modules chargés séparément (`progres.js`,
  `forum.js`) : si chacun masquait les autres de son côté, en ouvrir une
  par-dessus l'autre laisserait deux moitiés à l'écran.
  Revenir depuis « Mes progrès » ne repasse PAS par `switchMode()` : c'est ce
  qui garde l'éditeur et le verdict exactement où on les avait laissés.
- **`currentId` est ce que l'ÉDITEUR tient, pas ce que le menu montre**, et
  c'est `setupFiles()` qui le pose. Le remplissage passe par le réseau : le
  poser dans `switchMode()` ferait attribuer le code de l'exercice précédent,
  toujours affiché, à l'identifiant du nouveau dès le prochain `saveDraft()`.

### quiz.js, compte.js, progres.js, forum.js, exporter.js, classement.js
### et collection.js — à la demande

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
- **Le parcours anonyme ne télécharge rien de `compte.js`, `progres.js`,
  `forum.js`, `classement.js` ni `collection.js`**, même sur un déploiement où la connexion et le forum sont
  offerts. `test_page.js` le vérifie ; c'est la raison d'être du découpage.
  `progres.js` et `forum.js` vont plus loin : leur bouton n'apparaît que
  connecté, et le fichier ne descend qu'au clic — un étudiant connecté qui
  n'ouvre jamais ses progrès n'en paie rien, et celui qui n'ouvre jamais les
  discussions ne paie ni le module ni ses 74 Ko de bibliothèques de rendu.
- **`progres.js` ne calcule RIEN.** Solde, niveau, compétences, succès et
  recommandation arrivent tout faits de `GET /progres`. Une page qui calculerait
  son propre XP serait une page où l'on se le donne depuis la console — c'est
  l'erreur qu'un verdict déclaré par la page a déjà coûtée, en plus petit.
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

## La refonte (Claude Design « Industry »)

Huit écrans maquettés dans `ctester-am-lioration-plateforme-tudiante/`, tous
implémentés. La maquette est le contrat visuel ; ce qui suit est ce que
l'implémentation a tranché **autrement**, et pourquoi.

**Le vocabulaire visuel est retenu, la typographie non.** Accent acier, coins
carrés (`--coin`, une seule variable), cadres au trait avec repères d'angle
(`.plan`). Mais **pas de webfont** : la CSP est `default-src 'none'` sans
`font-src`, elle existe en deux copies qu'un test compare directive par
directive, et la page part vers GitHub Pages où le `<meta>` est la seule
politique. Barlow aurait coûté deux éditions de CSP et 200 Ko sur une page qui
en fait 65 ; la note de conception appelle la typo un « parti pris », pas un
invariant. **Et le thème sombre reste le défaut** : le bouton et sa
synchronisation sur le compte ne bougent pas.

**Une tuile porte DEUX axes, pas un.** La maquette fond « réussi » et « ouvert
dans l'éditeur » en un seul état ; un exercice réussi cessait alors de se lire
comme réussi au moment précis où on l'ouvre. `tuileEtat()` rend donc la
PROGRESSION (`reussi` / `verif` / `afaire`, plus le verrou), et `courant`
s'ajoute par-dessus pour le lieu. Un seul mot par état dans toute la page :
**« réussi », plus jamais « validé »** — deux mots pour un état, c'est un
étudiant qui se demande si ce sont deux choses.

**Aucune vue matérialisée pour le classement**, contrairement à la note de
conception. C'est un `count(*)` indexé sur quelques centaines de lignes pour
une cohorte de trente ; une projection rafraîchie serait un second endroit où
la vérité peut diverger, plus une planification à tenir. Même seuil que
`/progres` : un p95 au-dessus d'une seconde, que `load_test.py` signale.

**Trois règles tiennent le classement, et elles sont dans le service** (donc
éprouvables par appel direct) : l'opt-in EST le `WHERE` SQL (une case non
cochée ne produit aucune ligne, il n'y a donc rien à oublier de masquer
ensuite) ; sous `cohorte_minimale` il n'y a **aucun tableau** — pas un tableau
tronqué, qui divulguerait exactement les mêmes personnes ; et seul le haut du
tableau plus SA PROPRE ligne descendent, **donc personne n'est nommé dernier**.
La marche annoncée est vers le haut seulement.

**Le pseudonyme est tiré d'un vocabulaire fermé** (`policy.alias_possibles()`,
324 combinaisons) : rien de ce qu'un étudiant tape ne peut atteindre un
classement, **donc il n'y a pas de classement à modérer**. « Un autre nom »
garde l'alias courant dans l'ensemble des pris, sinon le bouton pourrait rendre
le même nom et aurait l'air cassé.

**Une carte de collection est un succès déguisé** : même table
(`achievement_unlocked`), même clé primaire, même « une seule fois », même
`forget()`. Le préfixe `carte:` est ce qui les sépare dans un seul espace de
noms. **Aucune table nouvelle pour la collection, donc aucun GRANT nouveau.**
La rareté est un **taux observé** sur les comptes ayant pratiqué, retenu sous
`cohorte_minimale` — un pourcentage sur quatre comptes décrit ces quatre
comptes.

**« Je suis bloqué ici » passe par la route qui existe déjà**, et la différence
est `step` : avec, c'est une demande d'aide, **privée par défaut** ; sans, c'est
la question publique ordinaire. Deux routes auraient été deux endroits où
borner la longueur d'un message, et celui qui dérive est celui qui cesse de
borner. **Aucun code n'est transmis** — il n'y a pas de champ pour en porter.

**Une seule transition de visibilité, et elle est dans le `WHERE`** :
`account = %s AND visibility = 'private'`. L'inverse n'est donc pas exprimable,
pas « refusé par un `if` » : on ne peut pas cacher ce que d'autres ont déjà lu.
Deux clics simultanés ne peuvent pas la doubler.

**Épingler n'édite rien.** La réponse retenue est la DERNIÈRE ligne
`retain`/`unretain` du journal `forum_moderation`, dérivée à la lecture. Pas de
colonne `retained`, donc pas d'UPDATE de plus sur une table dont tout le dessin
est qu'un message ne se réécrit pas.

**« Ça m'a aidé » n'accorde rien** — ni XP, ni succès, ni carte : un message
écrit pour être voté est un message écrit pour le compteur. Trois refus dans
UNE instruction (identifiant inventé, son propre message, doublon), là où trois
`if` en laisseraient chacun un ouvert.

**La vue enseignant compte sans nommer.** Agrégat par exercice et par étape :
aucun `sub`, aucun nom, aucun texte, aucun code. **Les questions privées y sont
comptées sans être révélées** — c'est exactement ce que le formulaire de
l'étudiant promet, et le compromis tient à ce que rien d'autre ne sorte.

### Ce que la refonte a ajouté au schéma

| Quoi | Où | GRANT |
|---|---|---|
| `step`, `blocked_kind`, `visibility` | `forum_message` | `UPDATE (hidden, **visibility**)` — dans `schema.sql` désormais ; c'est cet oubli-là, quand il vivait dans `VHome`, qui a fait descendre les GRANT ici |
| `alias`, `plate_frame`, `badges_public`, `leaderboard_opt_in` | `forum_profile` | aucun : le profil est en ajout seul, la dernière ligne fait foi |
| `forum_helpful` (la 13e table) | nouvelle | `SELECT, INSERT, DELETE`, comme le reste du forum |

**Écrire un profil, c'est le réécrire EN ENTIER.** La dernière ligne EST le
profil : une écriture partielle remettrait à zéro les champs qu'elle omet, et
celui qu'elle remettrait à zéro le plus souvent est une case de visibilité.
`_effacer_nom()` et `POST /forum/profil` repassent donc tous les champs lus.

### Les cinq routes neuves

```
GET  /classement?portee=groupe|cours   le rang, la marche, les divisions
POST /classement/alias                 retirer un pseudonyme (corps `{}`)
GET  /collection                       toutes les cartes, tenues ou non
POST /forum/visibilite                 privé -> groupe, par son auteur
POST /forum/utile                      « ça m'a aidé », une fois par compte
GET  /forum/aide                       qui a besoin d'aide (modérateur)
```

**Tout POST doit porter un corps**, même vide : le middleware borne avant de
parser, et un `Content-Length` absent compte comme hors bornes. C'est ce qui a
fait répondre 413 au premier « Un autre nom ».

## Les devoirs d'équipe

Le devoir « Analyseur de trace GPS » demande trois ou quatre étudiants et
**une seule remise pour l'équipe**. Tout le reste de la plateforme est
individuel ; le plan complet est dans `docs/teams/plan.md`, voici ce qu'il
faut savoir avant de toucher au code.

**UN GROUPE N'EST PAS UNE ÉQUIPE, et surcharger `group_number` aurait été le
raccourci évident et le mauvais.** Le groupe est la section du cours —
`forum_profile.group_number`, que l'ÉTUDIANT tape lui-même, et qui décide qui
lit une question ouverte « à mon groupe ». L'équipe est qui remet avec qui :
elle vit dans `team` / `team_member`. Une seule colonne pour les deux aurait
fait de la visibilité du forum et du contrôle d'accès d'un devoir la même
règle, par accident.

### Les équipes se choisissent dans une liste, comme sur Moodle

**LE LISTAGE DE L'ENSEIGNANT ÉTAIT INÉCRIVABLE**, et c'est ce qui a fait tomber
le premier dessin. `import_teams.py` supposait qu'il peut écrire
« Vianney → `9f3c…` ». Il ne le peut pas : **CTester ne lui montre jamais un
`sub`** — `forum_identite()` tient ça jusque dans la vue d'un modérateur. Il
aurait fallu qu'il se construise une table nom↔`sub` depuis Rauthy, c'est-à-dire
exactement le pouvoir de désanonymisation que le reste du projet refuse.

**LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE DE COURS**, et un étudiant
prend une place libre dans celle qu'il veut. C'est le geste qu'il fait déjà sur
Moodle, et **les numéros doivent correspondre** : « Équipe 7 » ici est
« Équipe 7 » là-bas, sinon l'enseignant tient deux listes qui divergent. D'où
`team.count` dans le contenu — combien d'équipes chaque groupe a — et une
poignée qui porte les deux : `g04-e07`.

**« Équipe 7 » DU GROUPE 04 ET « Équipe 7 » DU GROUPE 06 SONT DEUX ÉQUIPES**,
avec deux documents. Une poignée qui ne porterait que le numéro en ferait une
seule, et les deux sections travailleraient dans le même fichier.

**CE QUI FERME LES ÉQUIPES EST UNE DATE QUE LE CONTENU PORTE DÉJÀ**, et c'est
la propriété centrale : on rejoint et on quitte **tant que le devoir est
fermé**. `joinable()` demande que le devoir soit fermé, `find_assignment()`
qu'il soit ouvert, et **les deux lisent la même valeur** (`access` de l'entrée
publiée). Elles sont donc mutuellement exclusives **par construction** — il
n'existe aucun instant où l'on peut à la fois rejoindre une équipe et lire son
document. Pas parce qu'on l'a vérifié quelque part : parce que c'est la même
condition prise dans les deux sens.

**LE GROUPE DU PROFIL DÉCIDE QUELLE LISTE ON VOIT, ET RIEN D'AUTRE.** C'est le
numéro auto-déclaré de « Mon identité », et c'est son seul pouvoir : il ne
donne accès à rien. Une fois dans une équipe, c'est **elle** qui porte son
groupe (`team.group_number`), et le corriger ensuite ne déplace personne, ni
son document. Sans groupe au profil, la liste répond en disant d'aller le
remplir — le formulaire est juste en dessous, dans le même écran.

**UN DEUXIÈME DESSIN A ÉTÉ ESSAYÉ ET RETIRÉ**, et le savoir évite de le
refaire : un code d'invitation avec confirmation unanime (`invite_code`,
`sealed_at`, `locked_at`, six routes). Il tenait, mais il ne correspondait à
rien de ce que les étudiants font déjà — et surtout il n'était pas nécessaire,
puisque la date d'ouverture faisait déjà le travail.

**`import_teams.py` RESTE, comme outil de CORRECTION** : déplacer quelqu'un une
fois les listes figées, placer celui qui n'a rien choisi. Son CSV est
`group_number,number,account`, et il construit la poignée **exactement comme la
route** — un test compare les deux fonctions, parce que la copie doit vivre
côté hôte (le python du Dell ne voit pas `app/`).

### La chaîne d'autorisation, et il n'y a rien à falsifier

```
jeton validé -> sub -> team_member -> team -> assignment (OUVERT) -> exercise
```

Parcourue **côté serveur, à chaque requête ET à chaque ouverture de socket**,
par `teams.workspace()` puis `teams.exercise_in()` (`app/services/teams.py`).
**Aucune route et aucune trame ne lit d'identifiant d'équipe** : il n'y a pas
d'équipe à modifier dans une URL, un corps JSON ou un message WebSocket. C'est
« aucun modèle ne porte de champ d'identité » étendu d'un cran, et
`test_api.py` l'éprouve en faisant écrire `{"team_id": "e1"}` par un membre
d'une autre équipe — l'écriture va dans la sienne.

**UN `team_id` EST GLOBAL AU DEVOIR, PAS RELATIF AU GROUPE.** La clé primaire
est `(team_id, assignment_id)` — `group_number` n'en fait pas partie. Écrire
`1,4,Équipe 1,…` et `1,6,Équipe 1,…` ne fait donc PAS deux équipes : ça fait
UNE équipe à cheval sur deux groupes, partageant un document, avec le dernier
numéro de groupe écrit. Postgres ne peut pas le voir — les deux lignes sont
valides — alors `import_teams.read_roster()` le refuse, EN DISANT COMMENT
corriger : préfixer la poignée (`g04-e01`, `g06-e01`). Le `label`, lui, peut
rester « Équipe 1 » des deux côtés : c'est ce que l'étudiant lit, et il n'a
aucune raison d'être unique. Mettre le groupe dans la clé aurait fait porter
`(groupe, équipe)` à la clé du document, au nom de la salle et à celui de
l'archive ; une convention de nommage refusée à l'import coûte moins cher.

**PROUVER L'ÉQUIPE NE PROUVE PAS L'EXERCICE.** `exercise_in()` est la seconde
moitié de la porte : sans elle, un membre atteindrait un document clé sur SON
équipe et n'importe quel identifiant d'exercice.

**CE QUE POSTGRES TIENT ENCORE, ET CE QU'IL NE TIENT PLUS.** La garantie était
« rejoindre une équipe est INEXPRIMABLE, il n'y a pas d'INSERT ». Elle est
tombée avec le listage : il fallait bien que quelqu'un puisse écrire. Ce qui la
remplace se lit en trois moitiés, et les trois sont éprouvées :

- **la place est comptée dans le `WHERE` de l'INSERT** (`teams()` dans
  `test_postgres.py`) — deux étudiants sur la dernière place passeraient tous
  les deux un `if` posé côté routeur ;
- **la date**, dans le service : `joinable()` et `find_assignment()` lisent la
  même valeur en sens inverse ;
- **et il n'y a AUCUN `UPDATE`** sur `team` ni sur `team_member`
  (`team_privileges()`). Changer d'équipe, c'est en sortir et entrer ailleurs —
  deux écritures dont chacune porte sa condition. Un `UPDATE` de `team_id` les
  contournerait toutes les deux, la date comprise.

**QUATRE ROUTES RÉPONDENT AVANT LE DEVOIR** — `/team/mine`, `available`,
`join`, `leave`. Elles passent par `published_assignment()`, pas par
`workspace()`, et c'est délibéré : les équipes se choisissent en septembre, le
devoir ouvre en octobre. Un écran qui n'existerait qu'une fois le devoir ouvert
ferait choisir les équipes le matin de la remise.

**AUCUNE D'ELLES N'OUVRE QUOI QUE CE SOIT.** Elles rendent des numéros, des
remplissages et les coéquipiers en POSITIONS — **aucun document, aucune
révision, aucune salle, aucune remise**. Montrer n'est pas donner, la même
règle que le catalogue qui porte un exercice verrouillé avec sa date.

**ET `/team/available` NE NOMME PERSONNE** : « 3/4 » suffit à choisir, et
publier les compositions ferait de ce choix un tri social sur une page.

Tout ça s'affiche dans « Mon identité » (`forum.js`) : c'est l'écran « qui je
suis », « avec qui je remets » en fait partie, et le champ « Groupe » qui
décide de la liste est juste en dessous.


### Cinq tables, et trois d'entre elles ne s'effacent pas

| Table | Ce qu'elle porte | Dans `forget()` ? |
|---|---|---|
| `team` | l'équipe : son groupe, son numéro, son nom | non — pas de colonne `account` |
| `team_member` | l'appartenance | **oui** |
| `team_document` | le code partagé, clé sur (équipe, exercice) | non — c'est le travail de trois autres |
| `team_revision` | l'historique signé | **oui** |
| `team_submission` | la remise, une par équipe | non — `submitted_by`, pas `account` |

Le schéma passe de treize à dix-huit tables, puis à **dix-neuf** avec
`scratch_draft` (la Console).
`test_suppression_couvre_toutes_les_tables` ne compte plus seulement : il lit
les blocs `CREATE TABLE` et exige que **toute table déclarant une colonne
`account` soit dans `forget()`, et aucune autre**. C'est ce qui rend le
contrôle automaintenu, et c'est pour ça que la colonne de `team_submission`
s'appelle `submitted_by` — le nom porte la décision.

**`exercise_draft` NE BOUGE PAS.** Il reste clé sur (compte, exercice), aucune
route d'équipe ne l'écrit, et un étudiant sans équipe travaille un exercice de
devoir seul, avec son brouillon, exactement comme avant.

### L'édition partagée : Yjs relayé, jamais interprété

**La convergence est celle de Yjs, l'autorisation est la nôtre.**
`app/services/collab.py` est un relais : il transmet des trames opaques entre
les membres d'une salle et **tamponne l'émetteur** depuis le listage. Il ne
sait pas ce qu'est un caractère, et c'est le dessin — quatre personnes qui
tapent dans la même ligne est le cas qu'un protocole écrit à la maison rate en
semaine trois.

- **La salle est `(équipe, exercice)`** : deux équipes sur le même exercice
  sont structurellement deux salles. Rien à filtrer, donc rien à oublier de
  filtrer.
- **Le `from` d'une trame est réécrit par le serveur** — un membre ne peut pas
  signer le curseur d'un autre.
- **Ce qui circule est une POSITION** (`m1`…`m4`) plus le nom que le membre a
  CHOISI d'afficher. Aucun `sub` ne franchit la frontière, même règle et même
  test que `forum_vue()`.
- **Le jeton part dans la PREMIÈRE TRAME, jamais dans l'URL** : un navigateur
  ne peut pas poser d'`Authorization` sur une WebSocket, et un jeton en
  paramètre d'URL est un jeton dans tous les journaux de proxy du chemin.
- **`peers` décide qui sème le document.** Le premier arrivé dans une salle
  vide le remplit depuis le texte du serveur ; les suivants le demandent à la
  salle. Deux clients semant le même texte dans un CRDT le fusionneraient DEUX
  FOIS, et l'ordre d'arrivée est décidé dans un seul processus — c'est **une
  raison de plus pour UN SEUL WORKER** : deux workers mettraient deux membres
  de la même équipe dans deux salles différentes.
- **`epoch` est la couture.** Une salle meurt avec son dernier membre et
  renaît, avec une nouvelle époque, pour le suivant ; un client qui revient
  dans une salle reconstruite JETTE son document local au lieu de le
  fusionner. Cinq lignes, et toute une classe de bogues disparaît.
- **Aucun repli si Yjs n'arrive pas**, et il ne doit pas y en avoir : un « au
  mieux » qui pousserait la dernière valeur du `<textarea>` détruirait du
  travail au lieu de dégrader. L'éditeur se verrouille et le dit.

Yjs est **vendorisé** (`web/vendor/yjs-13.6.32.iife.js`, 92 Ko), chargé au clic
comme les deux bibliothèques du forum, et **l'anonyme n'en télécharge pas un
octet** — `test_page.js` le vérifie. Il est bundlé une fois à la main
(esbuild) parce qu'il ne publie que de l'ESM ; le `--footer:js` qui pose
`window.Y` est load-bearing, voir `web/vendor/README.md`.

### L'historique : récupérer, jamais noter

Une révision n'est écrite que si ce compte n'en a pas écrit une pour ce
document depuis `TEAM_REVISION_WINDOW` (120 s) **et** si la dernière ne porte
pas déjà ces octets. **Cette règle est le `WHERE NOT EXISTS` d'un seul
INSERT**, dans la même instruction que l'UPSERT du document — pas une lecture
suivie d'une écriture que deux membres traverseraient en même temps.

**IL N'Y A AUCUN POURCENTAGE DE CONTRIBUTION, ET IL NE DOIT PAS Y EN AVOIR.**
Un chiffre qui compte des caractères tapés devient une note le lendemain de sa
livraison, et il a tort à propos de celui qui réfléchit avant de taper. Un test
lit la charge entière et échoue s'il y trouve un `%` ou un `sub`.

**Restaurer avance, ça ne rembobine pas** : la version restaurée est écrite
comme document courant, sous le compte qui a restauré, et rien ne disparaît.
Le serveur ne pousse RIEN dans le CRDT — la page réapplique le texte par le
chemin d'édition normal, ce qui garde le relais bête.

### L'archive de remise

`handin.files` du devoir dit ce qui entre dans le ZIP : le nom **dans
l'archive**, l'exercice d'où il vient, le fichier de cet exercice. **Aucun nom
de fichier de TCH009 n'est écrit dans l'application** — « main.c et
matrac_lib.c » est un fait sur le contenu de ce devoir-là.

- **Rien n'est concaténé, reformaté ni annoté**, et il n'y a pas de README
  dans l'archive : l'énoncé demande deux fichiers.
- **Déterministe** : entrées triées, horodatage constant, mode et système
  créateur écrits plutôt qu'hérités de la machine qui l'a construite.
- **Un trou est refusé en le NOMMANT**, pas remis : une archive sans
  `matrac_lib.c` est la panne qu'on ne découvre qu'à la correction.
- **Construite côté serveur, depuis les documents de l'équipe.** Le navigateur
  n'envoie que l'identifiant du devoir : une archive assemblée depuis
  l'éditeur serait l'archive d'un onglet.
- **`ponytail:` l'import de ZIP n'est pas fait.** Ce n'est pas le format qui
  coince, c'est qu'un import devrait traverser la session CRDT : un fichier
  écrit côté serveur n'existerait dans aucun des quatre `Y.Doc` ouverts. Le
  bouton « Importer un fichier » existant passe, lui, par l'éditeur, donc par
  le CRDT, donc arrive chez les quatre. `docs/teams/plan.md` dit où le mettre
  le jour où il vaut la peine.

### Un exercice de devoir n'accorde aucun XP

Quatre personnes, un document : une première réussite chacune pour le même
code serait quatre récompenses pour un seul travail — exactement le farming que
`docs/gamification/anti-farming.md` refuse. **Le filtre est posé UNE fois**,
dans `exercices_pratique()`, et la branche de `_record()`
(`app/routers/submission.py`) nomme le même champ. Ce qui reste écrit, c'est
l'état et la tentative : chaque membre doit voir que l'exercice passe, et
garder son brouillon. `exercicesExportables()` porte le même filtre côté page —
un devoir a sa propre remise, six modules partagés n'ont rien à faire dans le
`main.c` personnel de quelqu'un.

### L'espace de travail, côté page

**La navigation locale est celle qui existait.** La bande `#bandelabo` fait
déjà `[1 ✓] [2 ✓] [3 ●]` et le devoir la réutilise telle quelle ; ce qu'il
ajoute est `#teamband` AU-DESSUS — titre, échéance, équipe, présence,
historique, ZIP, remise —, c'est-à-dire ce qu'un écran d'exercice ne pouvait
pas porter. Aucune cinquième vue : `afficherVue()` n'a pas bougé.

`web/team.js` est un module à la demande de plus, chargé quand l'exercice
ouvert porte `assignment` ET qu'il y a un jeton. Le noyau lui expose
exactement deux portes sur l'éditeur (`ctester.editeur.lire` / `.ecrire`) et
un point d'accroche (`ctester.brancherSession`) : le module ne touche jamais
`#code` lui-même, ce qui laisse **un seul endroit où le curseur peut se
perdre**. Un changement distant qui arrive pendant qu'on tape décale le
curseur au lieu de le renvoyer à la fin — c'est ce qui rend un éditeur
partagé utilisable, et `test_page.js` l'éprouve avec un vrai `Y.Doc`.

### Le déploiement

**Les GRANT sont dans `app/schema.sql`, plus dans `VHome`** — voir « Les droits
du rôle applicatif » plus bas. Il n'y a donc rien à ajouter ailleurs pour que
les cinq tables d'équipe soient utilisables : c'est précisément le piège que ce
rapprochement ferme.

Reste **une** chose côté déploiement, et elle est manuelle parce que NPM garde
son routage dans sa propre base : **cocher « Websockets Support »** sur le
proxy host. Sans ça, l'`Upgrade` de `/team/live` ne passe pas, l'espace
partagé se reconnecte en boucle en disant « hors ligne », et **tout le reste du
site marche parfaitement** — ce qui rend la panne longue à trouver.

## Les droits du rôle applicatif

**Ils vivent dans `app/schema.sql`, et plus dans `VHome`.** Une table et ses
droits sont le MÊME FAIT : une table sans son GRANT est muette, un GRANT sans
sa table ne s'applique pas. Les tenir dans deux dépôts, c'est garantir qu'un
jour l'un part sans l'autre — et **c'est arrivé trois fois** : l'`UPDATE` du
thème, la colonne `visibility` du forum, puis les cinq tables d'équipe. Les
trois fois, la panne n'existait **qu'en production**, parce que c'est le seul
endroit où le rôle applicatif sert.

**Le signe qui a tranché** : `test_postgres.py` devait RECOPIER ces GRANT pour
les éprouver. Quand un harnais duplique une règle pour la tester, la règle est
au mauvais endroit. Il applique maintenant `schema.sql`, point — et créer le
rôle est tout ce qu'il reste à faire à la main pour rejouer la production.

**Ce qui reste à `VHome` : `CREATE ROLE ctester_app LOGIN PASSWORD …`.** Le mot
de passe vient du vault, et un secret n'a rien à faire dans un dépôt
d'application. Le rôle est créé AVANT que le schéma ne soit appliqué — c'est
déjà l'ordre des tâches — et `schema.sql` **ne grante rien s'il ne trouve pas
le rôle** plutôt que de tomber sous `ON_ERROR_STOP=1` : c'est ce qui le garde
applicable sur une base de test nue.

**`test_chaque_table_a_ses_droits` est ce qui rend le rapprochement utile.** Il
lit `schema.sql` et refuse une table qui n'apparaît dans aucun GRANT — même
dessin que `test_suppression_couvre_toutes_les_tables`, qui lit le schéma
plutôt que d'entretenir une liste. Ajouter une table sans ses droits fait
maintenant échouer la suite, au lieu d'être muet six mois. Il ne juge PAS
quels droits : c'est `test_postgres.py` qui éprouve que Postgres refuse bien
ce qu'il doit refuser. Ici on attrape l'oubli, là-bas la permission de trop.

**Jamais un GRANT sur le schéma** (`ON ALL TABLES IN SCHEMA public`) : il
couvrirait d'avance une table pas encore écrite, et c'est exactement ce que le
test ci-dessus ne pourrait plus voir. Table par table, une ligne à la fois.

## Raccourcis assumés (ponytail)

Marqués `ponytail:` dans le code, rappelés ici pour ne pas les redécouvrir :

- **`app/security.py`** — cache de jetons : flush complet quand plein, pas de LRU (c'est
  un économiseur d'aller-retour, pas un magasin de sessions). `client_id`
  falsifiable si on tape l'origine sans passer par Cloudflare : régulateur de
  charge, pas contrôle d'accès — la clé de session est le contrôle d'accès.
  Quotas en mémoire, RAZ au redémarrage du conteneur.
- **`etat.py`** — une connexion Postgres derrière un verrou global, pas de pool.
  À 27 étudiants connectés, la file derrière le verrou est vide. `psycopg_pool`
  le jour où elle ne l'est plus.
- **`runner.py`** — le verrou entre workers, c'est `os.mkdir` (atomique, un seul
  hôte). Sondage du spool à 0,5 s ; une unité systemd `.path` le jour où cette
  latence se voit. Un worker tué laisse son `.lock` derrière lui : `reclaim()`
  le reprend au bout de `LOCK_STALE` (3 × `JOB_TIMEOUT` — un worker vivant ne
  peut pas tenir un verrou plus longtemps que le job qu'il exécute), **une seule
  fois**, sinon un job qui tue son worker à tous les coups arrêterait la file
  entière en tuant chaque worker à son tour.
- **`runner.py`** — cache de verdicts : éviction du moins récemment servi,
  décidée par le `mtime` des fichiers et contrôlée une fois toutes les
  `CACHE_ELAGAGE` écritures, par worker. Le magasin dépasse donc son plafond de
  cette marge au plus, et deux workers élaguent chacun de leur côté sans se
  concerter — un tri de 20 000 dates coûte 129 ms, un verrou pour ça coûterait
  plus cher que l'erreur qu'il éviterait.
- **`etat.py` / `schema.sql`** — progression : trois tables de faits, **aucune
  table de projection**. Le solde est un `sum()` sur quelques dizaines de lignes
  par étudiant ; matérialiser créerait un second endroit où la vérité peut
  diverger. Pas de clé étrangère entre le journal et les XP non plus : les deux
  s'écrivent dans UNE instruction et s'effacent ensemble.
- **`services/collab.py`** — les salles de collaboration sont un `dict` en
  mémoire de processus, comme les quotas et la présence : une salle meurt avec
  le processus, et le document plein-texte de Postgres réamorce la suivante.
  Une raison de plus pour UN SEUL WORKER. Redis le jour où il en faut deux, et
  ce jour-là les quotas partent avec.
- **`services/collab.py`** — le serveur relaie une trame de synchronisation à
  TOUTE la salle, pas seulement à celui qui l'a demandée. Un CRDT est
  idempotent, donc c'est gratuit en correction et un peu bavard en octets ; un
  routage par destinataire le jour où une équipe dépasse quatre personnes.
- **`web/team.js`** — les curseurs distants sont positionnés par arithmétique
  sur une largeur de caractère mesurée une fois, pas par un second exemplaire
  du document dans le DOM. Ça tient parce que `#hl` et `#code` partagent leurs
  métriques au pixel ; le jour où l'éditeur accepte une police
  proportionnelle, c'est cette fonction qu'il faut reprendre.
- **`app.js`** — les modules à la demande sont des `<script>` injectés et un
  objet global `window.ctester`, pas des modules ES : voir la section « La page »
  ci-dessus pour la raison (TDZ sur import circulaire). À reprendre le jour où
  l'état partagé est vraiment séparé, pas avant.
- **`services/leaderboard.py`** — le classement est calculé À LA LECTURE, pas
  de vue matérialisée : un `count(*)` indexé sur quelques centaines de lignes
  pour une cohorte de trente. Une projection rafraîchie le jour où le p95 de
  `/classement` dépasse la seconde, et pas avant — même seuil que `/progres`,
  signalé par le même script.
- **`routers/leaderboard.py`** — le tirage d'alias marche en avant depuis une
  graine aléatoire dans une liste de 324, au lieu de tirer sans remise : à
  trente comptes, la première tentative est libre presque toujours, et le
  parcours garantit qu'on en trouve un s'il en reste un.
- **`services/forum.py`** — `etat_du_fil()` rend UN état pour le fil entier,
  parce qu'il y a un fil par exercice et pas d'identifiant de question. Le jour
  où une question devient une entité, cette fonction est le seul endroit à
  reprendre — et les trois compteurs qu'elle rend sont déjà la forme d'une
  liste.
- **`forum.js`** — un fil se lit en entier (200 messages au plus), sans
  pagination ni chargement incrémental. À 27 étudiants et un exercice ouvert à
  la fois, un fil dépasse rarement la dizaine. Paginer le jour où la borne se
  voit. Même remarque pour la file de modération, qui n'a ni filtre ni tri.
