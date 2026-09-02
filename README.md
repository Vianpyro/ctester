# ctester — le juge C du cours TCH009

Une page sous `tch009.thevhome.com` où un étudiant colle un fichier `.c`,
choisit son TP, et reçoit un verdict contre des tests unitaires qui restent
secrets. Pas de compte : une clé de session dans le lien, distribuée sur Moodle,
la même pour tous les TP.

**Le déploiement n'est pas ici.** Ce dépôt porte l'application ; le rôle Ansible
qui l'installe sur le serveur (gVisor, systemd, Compose, les deux dépôts privés
et leurs deploy keys) vit dans `VHome`, sous `roles/ctester`. Le serveur clone ce
dépôt-ci dans `/opt/ctester/src` et suit `main` tout seul, à cinq minutes près.

**Pour travailler sur le dépôt** — contrôles à repasser avant un déploiement,
runbook, pièges de compilation déjà payés — voir [`CLAUDE.md`](CLAUDE.md).

```
app/app.py        l'API, dans le conteneur exposé (uid 65534)
app/index.html    la page : le markup seul, une centaine de lignes
app/style.css     sa feuille de style
app/app.js        son script : editeur, verdict, soumission
app/quiz.js       le mode quiz, chargé quand un exercice de ce mode s'ouvre
app/compte.js     OIDC et « Mes exercices », chargés seulement si on se connecte
app/etat.py       la persistance des comptes -- facultative, voir plus bas
app/schema.sql    les deux tables Postgres, et pourquoi ce n'est pas SQLite
requirements.txt  psycopg, la seule dépendance externe, et seulement pour ça
runner.py         le worker de l'hôte : lit la file, lance le bac à sable
build-unity.sh    ce qui tourne DANS le bac à sable, mode tests unitaires
build-io.sh       idem, mode programme complet (entrée/sortie)
```

Sans `CTESTER_DB_DSN`, la persistance ne démarre pas : `app.py` reste ce qu'il
était, l'image n'a besoin d'aucune dépendance, et la page ne propose même pas de
se connecter. Tout se règle par variables d'environnement — l'unité systemd du
rôle les fournit, et chaque script porte ses propres défauts pour tourner hors
déploiement.

## La connexion facultative (OIDC + Postgres)

Un étudiant peut se connecter pour retrouver son travail d'une machine à
l'autre et voir ce qu'il a déjà validé. **C'est facultatif de bout en bout** :
le parcours anonyme reste le défaut, et il est intact.

Trois variables l'activent, et il les faut toutes les trois — sinon
`/oidc.json` répond `{}` et la page se comporte comme avant :

```
CTESTER_OIDC_ISSUER      https://... (https exigé : un jeton en clair est un jeton donné)
CTESTER_OIDC_CLIENT_ID   le client public déclaré dans Rauthy (PKCE, sans secret)
CTESTER_DB_DSN           la connexion Postgres du rôle applicatif
```

Ce que le rôle Ansible doit fournir en plus, côté `VHome` : le service
Postgres, `app/schema.sql` appliqué, un rôle SQL limité à ces deux tables, le
client Rauthy avec `https://tch009.thevhome.com/` en URI de redirection, et
`pip install -r requirements.txt` dans l'image.

**Ce que la base contient :** l'identifiant opaque `sub` émis par Rauthy, le
code écrit par exercice, et un statut. Ni nom, ni courriel, ni code permanent.
Le jeton est validé en appelant `/userinfo` de Rauthy — pas de bibliothèque de
crypto embarquée, pas de rotation de clés à tenir. Le bouton « Supprimer mes
données » efface tout ce qui précède, et la phrase de consentement le dit avant
la première redirection.

Rien de tout cela ne touche au bac à sable : le conteneur exposé gagne une
connexion Postgres, pas l'accès aux tests.

## Ce que ce service n'est pas

**Un outil de notation, ni un anti-triche.** Le code de l'étudiant est compilé
et lié dans le même processus que les tests. Un `exit(0)` en première ligne, ou
un `printf("4 Tests 0 Failures 0 Ignored")`, suffit à afficher une réussite.
C'est inhérent au modèle — pas un défaut d'implémentation — et le corriger
coûterait bien plus cher que ce que ça protégerait, puisque la note ne sort pas
d'ici.

Ce service est du **feedback en libre-service**. La correction reste sur la
machine de l'enseignant. Ne rien construire sur ces verdicts qui ressemble à une
note.

## Le modèle de menace, et ce qui y répond

La menace n'est pas « un scanner trouve l'endpoint ». C'est **du C natif, écrit
par n'importe qui ayant le lien, compilé et exécuté sur l'hôte qui sert aussi le
DNS, le DHCP, le VPN et le coffre de mots de passe**. Un binaire natif émet les
appels système qu'il veut ; c'est une autre catégorie de risque qu'un langage
interprété.

Quatre lignes de défense, dans l'ordre où elles portent :

1. **Un conteneur jetable par soumission**, sous gVisor (`runsc`) : le code
   étudiant tape sur un noyau réimplémenté en espace utilisateur, pas sur celui
   du Dell. Sans réseau, en lecture seule, sans capability, en uid 65534, avec
   `--pids-limit` (la fork bomb est *le* classique du TP de C), un plafond
   mémoire, un plafond CPU, et trois chronomètres. Jamais réutilisé.
2. **Le conteneur exposé à Internet n'a pas le socket Docker.** Il écrit dans un
   répertoire de spool ; un worker systemd de l'hôte le lit et lance Docker. Une
   RCE dans l'API ne donne donc que ce que l'API offre déjà publiquement :
   soumettre du C au bac à sable. C'est ce que Judge0 n'a pas (il tourne en
   `--privileged`), et c'est le seul point d'architecture qui compte ici.
3. **Le tier web n'a pas accès aux tests.** `/opt/ctester/tests` n'est monté
   que dans le bac à sable — c'est le montage, et non le mode du fichier, qui
   fait cette séparation (voir « Une permission qui surprend » plus bas : ce
   répertoire est délibérément lisible par tous). Le web ne connaît que les
   *noms* des TP, via un `tps.json` que le worker publie au démarrage.
4. **La clé de session**, qui filtre le bruit d'Internet et rien d'autre. Une
   clé partagée par 40 étudiants est publique en pratique ; elle n'est pas ce
   qui protège l'hôte.

### Comment les tests restent secrets

Chaque mode a son mécanisme, et aucun ne repose sur le fait que l'étudiant ne
cherchera pas.

**Unity** — la compilation se fait en **deux invocations de gcc** :

- la première compile le fichier de l'étudiant **seul** ; sa `stderr` ne parle
  que de son fichier et lui est rendue intégralement ;
- la seconde lie ce résultat aux tests, **`stderr` jetée** — elle citerait leur
  code source. L'étudiant reçoit un message générique.

Ensuite, la sortie d'Unity est parsée côté hôte et filtrée : compteurs et *noms*
des tests échoués, **jamais** le champ message d'une ligne `FAIL`, qui contient
la valeur attendue par le test. Sans cette coupure, les cas de test se
reconstituent en quelques soumissions bien choisies.

**io** — `io.json` **n'entre jamais dans le conteneur**. Le worker en extrait
les entrées dans le répertoire du job et ne monte que celles-là ; les valeurs
attendues restent sur l'hôte. En cas d'échec, l'étudiant reçoit le numéro du
cas, ses entrées et sa propre sortie — jamais l'attendu, qui transformerait le
débogage en recopie de constantes.

**quiz** — la correction se fait dans le worker, pas dans l'API. Le conteneur
web reçoit un `app/quiz/<tp>.json` reconstruit champ par champ (`id`, `group`,
`label`, `type`) : le corrigé n'est pas *retiré* d'une copie, il n'est **jamais
ajouté**. Une clé ajoutée au fichier de tests demain ne fuite donc pas par
défaut. Le verdict nomme les questions ratées, jamais leur réponse.

### Ce qui reste exposé, dit franchement

- Un `printf` peut fabriquer un faux verdict — voir plus haut, c'est assumé.
- Un étudiant qui change de réseau repart avec des quotas neufs (ils sont en
  mémoire, par IP).
- L'IP d'origine du Dell est découvrable comme pour tous les autres services de
  cette infra ; qui la trouve peut forger `CF-Connecting-IP` et contourner les
  quotas. La clé reste la porte, et le plafond global de file reste le garde-fou
  de charge.
- Une évasion de gVisor est possible en théorie. C'est le pari, et il est
  meilleur que le pari « namespaces seuls » que font Piston et Judge0.

## Le dépôt de tests

Privé : `ETS-TCH009-S26/unittests`, cloné par une deploy key **en lecture
seule** (GitHub → Settings → Deploy keys, case *Allow write access* décochée —
une clé volée sur le Dell ne peut alors pas réécrire les tests).

```
tp1/quiz.json                 ← quiz : la config est à la racine du TP
tp2/ex3/io.json               ← un sous-dossier par exercice
tp6/ex1/unity.json
tp6/ex1/test_calendrier.c
tp6/ex1/allowed_includes.txt  ← optionnel, tous modes compilés
unity/{unity.c,unity.h,unity_internals.h}
```

**Deux niveaux : un dossier par TP, un sous-dossier par exercice.** À 13
laboratoires de 8 exercices, une racine plate ferait 104 dossiers. Un TP dont la
configuration est à sa racine — le quiz, qui n'a pas d'exercices — reste une
entrée à lui seul. **Le mode se déduit du fichier présent**, il n'est configuré
nulle part : un champ `"mode"` serait une deuxième source de vérité.

| Fichier | Mode | Ce que fait le juge |
|---|---|---|
| `quiz.json` | **quiz** | corrige des réponses. Aucune compilation, aucun conteneur, verdict en millisecondes |
| `io.json` | **io** | compile un programme complet **avec** son `main()`, l'exécute une fois par cas sur une entrée standard, compare la sortie |
| `unity.json` | **unity** | compile le module de l'étudiant, **sans** `main()`, et le lie aux tests |

**L'IDENTIFIANT PUBLIC RESTE PLAT** : `tp6-ex1`, jamais `tp6/ex1`. Il part vers
le navigateur, revient dans une soumission, et est ensuite joint à un chemin
racine — y autoriser une barre oblique rouvrirait exactement la traversée de
répertoire que `TP_RE` existe pour fermer. Le chemin réel est porté par le
catalogue (`tp_path()`), jamais reconstruit par découpage du nom, et il est
**retiré avant publication** vers le conteneur web : c'est un chemin serveur, il
décrit l'arborescence des secrets et n'apprend rien au navigateur.

L'ordre du menu est **numérique à tous les niveaux** : trié comme du texte,
`tp10` passerait avant `tp2` et `ex10` avant `ex2`. Un nom hors convention finit
dans un groupe « Autres », à la fin. Le `label` gagne à commencer par `TP<N> :` —
le second menu retire ce préfixe, que le premier affiche déjà, et garde le
libellé entier s'il n'y est pas.

**Une soumission est un ensemble de fichiers, pas un fichier.** À partir du
laboratoire 5, l'étudiant écrit un module — `calendrier.h` + `calendrier.c` — et
les deux doivent être montés côte à côte pour que son propre `#include` résolve.
La configuration du TP **déclare les noms**, qui deviennent les onglets de
l'éditeur et la liste blanche que l'API oppose à la soumission ; l'étudiant ne
les choisit pas, parce qu'un fichier mal nommé ne compile pas et que sanctionner
ça n'apprend rien. Sans déclaration, un seul fichier `submission.c`.

**Un exercice peut s'ouvrir à une date** : la clé `available_from`
(`"2025-09-11"`, à la racine du fichier de configuration) écarte l'entrée du
catalogue tant que le jour n'est pas venu. Le filtre est dans `catalogue()` et
pas à l'affichage, donc une entrée fermée n'a ni ligne de menu, ni chemin
(`tp_path()` rend `None`), ni corrigé de quiz publié — un lien profond
`?tp=tp5-ex1` partagé par un étudiant en avance ne résout pas au lieu de
contourner. Clé absente = ouvert, ce qui est le bon défaut : un exercice ajouté
en cours de session est visible sans qu'on y pense. (`CTESTER_APERCU=1` lève le
filtre pour éprouver un TP avant les étudiants — voir [`CLAUDE.md`](CLAUDE.md).)

**`allowed_includes.txt`** : un en-tête par ligne (`stdio.h`, `pile.h`…). Sa
présence active la liste blanche ; son absence la désactive. La vérification est
une expression rationnelle sur le texte brut — elle voit un `#include` en
commentaire et ne voit pas un `#include` produit par macro. Les deux sont hors
de portée d'un étudiant de première session, et le coût d'un faux positif est un
message d'erreur clair.

Le format de chaque fichier est documenté dans le README du dépôt de tests, avec
les pièges qui comptent (la règle « toute valeur attendue dépasse 1 », le champ
`absent`, la normalisation des réponses de quiz).

**Le catalogue.** Le conteneur web ne lit pas les tests : il lit `app/tps.json`
(id, mode, libellé, noms de fichiers), `app/tp/<tp>.json` (la consigne et les
gabarits, chargés quand l'étudiant ouvre l'exercice) et `app/quiz/<tp>.json`
(les questions **sans les réponses**), tous écrits par le worker au démarrage
(`publish_catalogue()` dans `runner.py`). La consigne et les gabarits sont à
part parce qu'ils faisaient les trois quarts du catalogue pour 73 exercices dont
un seul est ouvert ; les **noms** de fichiers, eux, restent dans `tps.json` :
c'est la liste blanche qu'`app.py` oppose à une soumission. C'est la frontière du service, et elle est une fonction Python
précisément pour que `test_ctester.py` puisse la mettre à l'épreuve à chaque
convergence — un gabarit Jinja n'aurait été relu par personne. Il est republié
au changement de jour, pour qu'une ouverture de minuit prenne effet sans
redémarrage ; sinon, une modification pousse par `ansible-playbook … --tags
tests` (voir [`CLAUDE.md`](CLAUDE.md)).

## Une permission qui surprend

`/opt/ctester/tests` appartient à root **mais est lisible par tous** (0755/0644).
Ce n'est pas un oubli : un bind mount ne remappe pas les uid, le bac à sable
tourne en 65534, et gcc doit pouvoir lire les tests pour les compiler. Un 0700
rendrait le service inopérant.

Ce que ça coûte est nommable : tout processus de l'hôte qui lit ce chemin voit
les sources de test. Aucun ne le fait — le conteneur web, le seul exposé à
Internet, ne monte pas ce répertoire. La confidentialité vient du filtrage de la
sortie, pas d'un mode de fichier sur une machine dont l'accès shell est déjà la
fin de la partie.

**`quiz.json` et `io.json` font exception et restent en 0600.** L'argument
ci-dessus est un argument de *montage* : il vaut pour ce que gcc doit lire à
travers un bind mount, et ces deux-là ne sont montés nulle part — ils sont lus
par le worker, qui est root. Ce sont pourtant les fichiers les plus secrets du
dépôt. Les laisser en 0644 « parce que le répertoire l'était » serait exactement
l'élargissement qu'on cesse de remarquer.

## Ce qui n'est pas là, volontairement

Un fichier `.c` par soumission ; pas d'historique ni de statistiques (il n'y a
pas de compte à quoi les rattacher) ; pas de clé par étudiant ; quotas non
persistants ; pas de règle Cloudflare — la file et les quotas sont dans
l'application, où ils comptent des *compilations* et savent répondre « 7ᵉ dans
la file » plutôt qu'un 429 opaque à quelqu'un qui attend son résultat.

Les warnings d'une compilation réussie ne remontent pas non plus : les afficher
demanderait de les mêler à la sortie Unity dans le même flux, donc un protocole
entre le script du bac à sable et le worker. À ajouter le jour où le cours veut
noter la propreté du code.
