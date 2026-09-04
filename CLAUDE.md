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

La page est en sept fichiers, tous servis par la liste blanche de `do_GET` :
`index.html` (le markup seul), `style.css`, `app.js` (le noyau), puis `quiz.js`,
`compte.js`, `progres.js` et `forum.js`, que le noyau va chercher **à la
demande**. S'y ajoutent deux bibliothèques tierces **épinglées par version** dans
`app/vendor/` (marked et DOMPurify), servies par la même liste blanche et
chargées seulement à l'ouverture des discussions — voir `app/vendor/README.md`.
Rien de tout ça n'est compilé ni assemblé : ce que le dépôt contient est ce que
le navigateur reçoit.

## Avant de déployer une modif de la page ou du contenu

Sur le contrôleur, jamais sur le Dell (les trois derniers ont besoin de gcc) :

```sh
python3 test_ctester.py          # les défenses et la progression, sans rien installer
npm ci                           # UNE FOIS : jsdom, pour les contrôles XSS du forum
node    test_page.js             # le JS de la page, sur un DOM en carton
python3 valider_contenu.py ../unittests
python3 test_bac_a_sable.py      # les deux build.sh, vrai gcc, sans Docker
```

Et avant une cohorte, une fois, avec Docker — pas à chaque modif :

```sh
docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester            -p 55432:5432 postgres:16-alpine
CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester   python3 test_postgres.py
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
- **`test_postgres.py`** — le SEUL contrôle qui éprouve le SQL. Les autres
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
  **Il a maintenant UNE dépendance, de test seulement : `jsdom`** (`npm ci`).
  DOMPurify refuse de travailler sans DOM — `isSupported` passe à faux et
  `sanitize()` rend alors son entrée **telle quelle**. Un harnais qui l'utilisait
  dans cet état écrirait « aucune injection ne passe » sans avoir rien assaini,
  c'est-à-dire le pire des contrôles de sécurité : celui qui rassure. Le fichier
  refuse donc de démarrer sans jsdom, en le disant. L'APPLICATION, elle, n'a
  toujours aucune dépendance npm.

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
`/brouillon`, `/preferences`, `/oidc.json`, `/forum*`, `/live`) restent en
`no-store`. Ce sont des données de compte (ou, pour `/live`, un compteur
volatil), pas des fichiers.

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

## Le compteur de présence

`GET /live?id=<jeton>` → `{"n": <fenêtres ouvertes>}`, affiché discrètement dans
le bandeau (`#live`) **pour tout le monde, anonyme compris**. C'est la SEULE
entorse à « l'anonyme n'émet aucune requête » — assumée, le battement va vers un
`dict` en mémoire (`Handler.presence`, une `Presence`), jamais vers la base ni
un compte, et ne porte aucun jeton.

- **Polling, pas WebSocket.** `app.py` est un `http.server` synchrone à
  connexion Postgres unique : 200 sockets persistantes n'y ont pas leur place.
  Un battement toutes les 60 s × 200 étudiants = ~3 req/s sur une opération de
  dict. `ponytail:` — repasser en WebSocket le jour où « live » doit dire
  quelque chose de plus fin qu'« à la minute ».
- **Le jeton `id` vient du navigateur** (`crypto.randomUUID`, gardé dans
  `sessionStorage`), donc falsifiable et non authentifié : c'est un chiffre
  affiché, pas un contrôle. Sans `id`, `_live()` retombe sur l'IP (une école =
  une fenêtre) plutôt que d'exposer quoi que ce soit.
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
`4,6`). Non vide → le formulaire est une liste déroulante fermée et `app.py`
refuse tout autre numéro ; vide → champ libre 1 à 99 (l'ancien comportement).
La colonne reste `SMALLINT CHECK (1..99)` — la liste d'une session ne vit pas
dans le schéma. Cocher sans
avoir écrit n'affiche rien (`app.py` refuse la visibilité d'un champ vide), et
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
Elle porte le hachage du script de thème **calculé sur le corps servi**, jamais
recopié à la main : un hachage figé se périmerait à la première virgule changée
et la page repartirait sans thème. Elle est aussi posée sur le 304, sinon elle
disparaîtrait dès la deuxième visite. `style-src` garde `'unsafe-inline'` : la
page pose des attributs `style` calculés (jauges, coches de verdict).

**Un message est immuable.** Son auteur le supprime, un modérateur le masque ou
le rétablit — et c'est tout. Côté Postgres, les trois tables sont en ajout seul
avec **un GRANT DE COLONNE** pour la seule exception : `UPDATE (masque) ON
forum_message`. Pas d'UPDATE de table : une ligne de Python distraite ne peut pas
réécrire le texte de quelqu'un. `test_postgres.py` éprouve les deux moitiés.

**Le quota du forum est compté PAR COMPTE, pas par IP** (contrairement à celui
des soumissions), et il ne couvre que les écritures : un quota qui empêcherait de
relire un fil empêcherait de suivre la réponse qu'on attend.

**Ajouter une table de forum sans l'ajouter à `forget()` fait échouer
`test_ctester.py`** — le contrôle lit `schema.sql` et compte douze tables.

## Le thème enregistré sur le compte

**`localStorage` était par appareil, et c'est tout le problème qu'on répare.**
Un étudiant qui passe du labo à son portable repartait chaque fois du thème par
défaut. Le compte transporte déjà le brouillon d'un poste à l'autre ; le réglage
d'affichage prend le même chemin — `preference_affichage`, une ligne par compte,
`GET`/`PUT /preferences`.

**Le stockage local RESTE, et il ne fait pas doublon.** C'est lui que le
`<script id="theme-init">` du `<head>` lit avant le premier rendu ; le serveur,
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
cliqué. Côté `VHome`, son `GRANT` porte donc `UPDATE`, comme
`brouillon_exercice` — **sans lui, l'écriture échoue en production et nulle part
ailleurs**.

**Le bouton vit dans le noyau, la synchronisation dans `compte.js`.** L'anonyme
a le bouton et n'émet aucune requête en le cliquant (`test_page.js` le
vérifie) : `app.js` n'appelle `ctester.compte.enregistrerTheme()` que si le
module est là, et le module ne fait rien sans jeton. Rien n'est attendu non
plus — le thème est déjà à l'écran, et un aller-retour raté ne doit pas donner
l'impression que le bouton n'a pas marché.

## Mesurer avant de tourner un bouton

`charge.py` existe pour qu'on arrête de régler `ctester_workers` à l'instinct.
**Jamais pendant une séance** : il écrit dans la base, remplit la file et fait
compiler pour de vrai.

```sh
CTESTER_KEY=<la clé de session> CTESTER_CHARGE_TP=tp2-ex3 \
CTESTER_CHARGE_TOKEN=<un vrai jeton, pris dans sessionStorage> \
  python3 charge.py http://ctester-web-1:8000
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

- **`GET /progres` fait cinq allers-retours SQL sérialisés** derrière le verrou
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
- **`afficherVue()` est le seul arbitre des quatre écrans** (exercice, « Mes
  exercices », « Mes progrès », « Discussions »), et il vit dans le noyau. Les
  trois vues sont dans trois modules chargés séparément : si chacun masquait
  les autres de son côté, en ouvrir une par-dessus l'autre laisserait deux
  moitiés à l'écran.
  Revenir depuis « Mes progrès » ne repasse PAS par `switchMode()` : c'est ce
  qui garde l'éditeur et le verdict exactement où on les avait laissés.
- **`currentId` est ce que l'ÉDITEUR tient, pas ce que le menu montre**, et
  c'est `setupFiles()` qui le pose. Le remplissage passe par le réseau : le
  poser dans `switchMode()` ferait attribuer le code de l'exercice précédent,
  toujours affiché, à l'identifiant du nouveau dès le prochain `saveDraft()`.

### quiz.js, compte.js, progres.js et forum.js — chargés à la demande

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
- **Le parcours anonyme ne télécharge rien de `compte.js`, `progres.js` ni
  `forum.js`**, même sur un déploiement où la connexion et le forum sont
  offerts. `test_page.js` le vérifie ; c'est la raison d'être du découpage.
  `progres.js` et `forum.js` vont plus loin : leur bouton n'apparaît que
  connecté, et le fichier ne descend qu'au clic — un étudiant connecté qui
  n'ouvre jamais ses progrès n'en paie rien, et celui qui n'ouvre jamais les
  discussions ne paie ni le module ni ses 74 Ko de bibliothèques de rendu.
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
- **`forum.js`** — un fil se lit en entier (200 messages au plus), sans
  pagination ni chargement incrémental. À 27 étudiants et un exercice ouvert à
  la fois, un fil dépasse rarement la dizaine. Paginer le jour où la borne se
  voit. Même remarque pour la file de modération, qui n'a ni filtre ni tri.
