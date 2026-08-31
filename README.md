# ctester — le juge C du cours TCH009

Une page sous `tch009.thevhome.com` où un étudiant colle un fichier `.c`,
choisit son TP, et reçoit un verdict contre des tests unitaires qui restent
secrets. Pas de compte : une clé de session dans le lien, distribuée sur Moodle,
la même pour tous les TP.

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
3. **Le tier web n'a pas accès aux tests.** `/opt/ctester/tests` est en `0700
   root` et n'est monté que dans le bac à sable. Le web connaît les *noms* des
   TP, via un `tps.json` rendu par Ansible.
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
tp1/quiz.json                 ← mode quiz
tp2-ex3/io.json               ← mode io
tp5/test_pile.c               ← mode unity
tp5/allowed_includes.txt      ← optionnel, tous modes compilés
unity/{unity.c,unity.h,unity_internals.h}
```

Un répertoire = un TP = une entrée du menu déroulant (`unity/` et tout ce qui ne
correspond pas à `[a-z0-9_-]{1,32}` sont exclus). **Le mode se déduit du fichier
présent**, il n'est configuré nulle part — un champ `"mode"` serait une deuxième
source de vérité à tenir d'accord avec la première.

| Fichier | Mode | Ce que fait le juge |
|---|---|---|
| `quiz.json` | **quiz** | corrige des réponses. Aucune compilation, aucun conteneur, verdict en millisecondes |
| `io.json` | **io** | compile un programme complet **avec** son `main()`, l'exécute une fois par cas sur une entrée standard, compare la sortie |
| `test_*.c` | **unity** | compile les fonctions de l'étudiant, **sans** `main()`, et les lie aux tests |

Le format de chacun est documenté dans le README du dépôt de tests, avec les
pièges qui comptent (la règle « toute valeur attendue dépasse 1 », le champ
`absent`, la normalisation des réponses de quiz).

**Ajouter ou modifier un TP** : pousser sur le dépôt privé, puis

```sh
ansible-playbook playbooks/ctester.yml --tags tests --ask-vault-pass
```

Ça met à jour le clone et redémarre les workers, ce qui republie le catalogue.

**Le catalogue, justement.** Le conteneur web ne lit pas les tests : il lit
`app/tps.json` (id, mode, libellé) et `app/quiz/<tp>.json` (les questions **sans
les réponses**), tous deux écrits par le worker au démarrage
(`publish_catalogue()` dans `runner.py`). C'est la frontière du service, et elle
est une fonction Python précisément pour que `test_ctester.py` puisse la mettre
à l'épreuve à chaque convergence — un gabarit Jinja n'aurait été relu par
personne.

**`allowed_includes.txt`** : un en-tête par ligne (`stdio.h`, `pile.h`…). Sa
présence active la liste blanche ; son absence la désactive. La vérification est
une expression rationnelle sur le texte brut — elle voit un `#include` en
commentaire et ne voit pas un `#include` produit par macro. Les deux sont hors
de portée d'un étudiant de première session, et le coût d'un faux positif est un
message d'erreur clair.

**Écrire un test Unity** : le fichier de test fournit `main()`, `setUp()` et
`tearDown()` ; le fichier de l'étudiant ne doit pas définir `main()` (sinon :
erreur d'édition de liens, et le message générique le mentionne). Les noms de
test doivent tenir dans `[A-Za-z0-9_]{1,64}` pour remonter à l'étudiant — ce
sont eux qu'il verra, donc autant les écrire pour lui : `test_pop_pile_vide`
plutôt que `test_3b`.

**C23 en dialecte GNU** (`-std=gnu23`, gcc 14) est appliqué au fichier de
l'étudiant. En mode unity, les tests et Unity sont compilés à part et gardent le
`-std` par défaut : deux unités de traduction, deux normes, une seule édition de
liens. Si Unity finit par ne pas aimer C23, ça ne touche pas le cours.

**`gnu23` et pas `c23`**, et ça a coûté un exercice avant d'être compris : un
mode ISO strict définit `__STRICT_ANSI__`, la glibc désactive alors
`_DEFAULT_SOURCE`, et `M_PI` disparaît de `<math.h>` — `M_PI` n'est pas dans le C
standard, c'est une extension POSIX. Du code correct, qui compile dans CLion,
était refusé par le juge avec `'M_PI' undeclared`.

CLion compile en dialecte gnu (`CMAKE_C_EXTENSIONS` vaut `ON` par défaut). Le
juge doit accepter ce que l'outil de l'étudiant accepte, sinon on rejoue la même
scène à chaque extension GNU rencontrée. `-D_DEFAULT_SOURCE` aurait soigné le
symptôme sans traiter ça.

Et non, ce n'était **pas** `-lm`, que le juge passe déjà : la glibc moderne a
fusionné libm dans libc, et l'erreur était de compilation, pas d'édition de liens.

**Deux scripts de bac à sable, et ils ne sont pas interchangeables.**
`build-unity.sh` tait la stderr de l'édition de liens, parce qu'elle citerait le
code des tests ; `build-io.sh` la laisse passer entière, parce qu'il ne voit
aucun secret — les valeurs attendues restent dans `io.json`, sur l'hôte, et le
conteneur ne reçoit que les entrées. Les fusionner ferait dépendre la
confidentialité d'un `if` bien placé.

## Exploitation

**Rotation de la clé** (entre deux sessions, ou si un lien fuite trop loin) :

```sh
openssl rand -hex 24
ansible-vault edit inventory/group_vars/ctester_hosts/vault.yml
ansible-playbook playbooks/ctester.yml --ask-vault-pass
```

Les anciens liens cessent immédiatement de fonctionner.

**Charge.** `ctester_workers` (2) = compilations simultanées = cœurs que le juge
peut prendre au Dell, puisque chaque conteneur est plafonné à 1 CPU. Ce sont les
mêmes cœurs que Kea et AdGuard : ne pas monter cette valeur sans regarder ce
qu'ils laissent libre. Réduire `ctester_workers` **ne désactive pas** les
instances déjà activées — `systemctl disable --now ctester-runner@3` à la main.

Le reste se règle par variables : `ctester_cooldown_seconds` (15),
`ctester_hourly_quota` (40), `ctester_queue_max` (60, au-delà duquel `/submit`
répond 503). Les bons chiffres se découvrent au premier TP.

**Diagnostic**, dans l'ordre où ça casse :

```sh
docker info --format '{{json .Runtimes}}'      # runsc enregistré ?
systemctl status 'ctester-runner@*'            # les workers tournent ?
journalctl -u 'ctester-runner@*' -n 50         # ce que dit un job en erreur
docker logs ctester-web-1                      # l'API (silencieuse si tout va bien)
ls /opt/ctester/spool                          # la file, vide au repos
docker exec nginx-manager-npm-1 getent hosts ctester-web-1   # NPM résout-il ?
python3 /opt/ctester/test_ctester.py           # les défenses tiennent-elles ?
grep -rl answer /opt/ctester/app/              # DOIT ne rien trouver
```

Et sur le contrôleur, avant de déployer une modification de la page :

```sh
node roles/ctester/files/test_page.js roles/ctester/files/index.html
```

Il exécute le JavaScript de la page contre un DOM en carton et vérifie que la
soumission part vraiment. **`node --check` ne suffit pas** : il valide la
syntaxe, et la seule panne que cette page ait connue en production était une
`ReferenceError` de zone morte temporelle — une variable redéclarée dans le bloc
`try` qui masquait la charge utile utilisée deux lignes plus haut. Le `fetch` ne
partait jamais, le `catch` affichait « le serveur ne répond pas », et les logs
du conteneur étaient vides parce qu'aucune requête n'était jamais émise.

La dernière est la vérification de la frontière : le répertoire `app/` est tout
ce que le conteneur exposé peut lire, et aucun corrigé n'a le droit d'y être. À
refaire après chaque `--tags tests`.

**Les quatre soumissions hostiles** à repasser après toute modification du bac à
sable — elles sont la seule preuve que les défenses tiennent encore :

| Soumission | Attendu |
|---|---|
| `while (1) fork();` | `timeout`, l'hôte ne bouge pas |
| `system("curl http://exemple");` | échoue, `--network=none` |
| `while (1);` | `timeout` à 5 s |
| `#include <unistd.h>` hors liste blanche | rejeté avant même de lancer un conteneur |

Sur la fork bomb, **vérifier le résultat et pas le mécanisme** : sous `runsc`,
les processus créés dans le bac à sable sont internes à gVisor et ne sont pas
des processus de l'hôte, donc `--pids-limit` (un contrôle cgroup) ne les compte
pas forcément. Ce qui l'arrête alors est le plafond mémoire du sandbox et le
chronomètre. Les deux options restent en place — l'une couvre `runc`, l'autre
couvre `runsc` — et ce qui compte est que `uptime` sur le Dell ne bronche pas.

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
