# Devoirs d'équipe — ce qui a été construit, et pourquoi

Le devoir « Analyseur de trace GPS » (TCH009) demande une chose que la
plateforme ne savait pas faire : **trois ou quatre étudiants, un seul rendu**.
Tout le reste de CTester est individuel — un brouillon par compte, une
soumission par personne, une progression par compte — et cette page dit
comment le travail d'équipe s'y est ajouté **sans rien changer à ça**.

## Le modèle, en quatre mots qui ne se confondent pas

| | Ce que c'est | Qui décide | Où ça vit |
|---|---|---|---|
| **Groupe** | la section du cours | l'enseignant (et l'étudiant se l'attribue dans son profil, pour le forum) | `forum_profile.group_number`, et `team.group_number` côté listage |
| **Équipe** | qui remet ensemble | **l'étudiant prend une place**, comme sur Moodle (l'enseignant tranche en correction) | `team` / `team_member` |
| **Devoir** | un travail noté : une date, une remise, un ordre d'exercices | le contenu | `assignments/<id>.json` |
| **Exercice** | une unité de code | le contenu | `exercises/<id>/`, inchangé |

**Le groupe et l'équipe ne sont pas la même chose, et surcharger
`group_number` aurait été le raccourci évident et le mauvais.** Les deux
répondent à des questions différentes (« dans quelle section es-tu » contre
« avec qui remets-tu »), n'ont pas la même autorité — l'une est déclarée par
l'étudiant, l'autre par l'enseignant — et une seule colonne aurait fait de la
règle de visibilité du forum et du contrôle d'accès d'un devoir la même règle,
par accident.

**Un devoir n'est pas une collection non plus.** Une collection est un
chemin dans le catalogue : un titre de menu, aucune date, aucune remise, et
un exercice peut être dans deux. Un devoir a une échéance, dit à quoi
ressemble l'archive finale, et — quand il déclare un bloc `team` — se fait à
plusieurs. Les fondre aurait fait de « dans quel labo est-ce » et « qu'est-ce
que je remets » le même champ, et le jour où ils divergent est le jour où
quelqu'un remet la mauvaise chose.

## L'opt-in est l'absence, pas un drapeau

Un exercice publié avant cette fonctionnalité ne porte pas `assignment`. Un
devoir sans bloc `team` est un devoir individuel ordinaire. Il n'y a **aucune
variable d'environnement** pour allumer ou éteindre la fonctionnalité : c'est
le CONTENU qui l'active (un fichier `assignments/<id>.json` avec `team`) et le
LISTAGE qui décide qui la voit. Un déploiement sans devoir et sans listage se
comporte exactement comme avant — il n'y a pas de troisième endroit où oublier
un drapeau.

## La chaîne d'autorisation, et elle n'a qu'un sens

```
jeton validé → sub → team_member → team → assignment (OUVERT) → exercise
```

Elle est parcourue **côté serveur, à chaque requête et à chaque ouverture de
socket**, par `teams.workspace()` puis `teams.exercise_in()`. Aucune route et
aucune trame ne lit d'identifiant d'équipe : **il n'y a pas d'équipe à
modifier dans une URL, un corps JSON ou un message WebSocket.** C'est la
même propriété que « aucun modèle ne porte de champ d'identité », étendue
d'un cran.

Ce qui remplace le privilège absent depuis que les étudiants prennent leur
place : la place comptée dans le `WHERE` de l'INSERT, la date de fermeture, et
**aucun `UPDATE`** sur les deux tables — voir plus bas.

## Les équipes se choisissent dans une liste, comme sur Moodle

**LE LISTAGE DE L'ENSEIGNANT ÉTAIT INÉCRIVABLE**, et c'est ce qui a fait tomber
le premier dessin. `import_teams.py` supposait qu'il peut écrire
« Vianney → `9f3c…` ». Il ne le peut pas : **CTester ne lui montre jamais un
`sub`**, et `forum_identite()` tient ça jusque dans la vue d'un modérateur.

Les équipes préexistent, **numérotées par groupe de cours**, et un étudiant
prend une place libre dans celle qu'il veut :

| | Qui | Ce que ça tient |
|---|---|---|
| **`team.count`** | le contenu | combien d'équipes par groupe — c'est ce qui rend la numérotation comparable à Moodle |
| **`GET /team/available`** | l'étudiant | la liste de SON groupe, avec le remplissage. **Elle ne nomme personne** |
| **`POST /team/join`** | l'étudiant | `WHERE (SELECT count(*) …) < max` — la place est comptée dans l'INSERT |
| **`POST /team/leave`** | l'étudiant | tant que le devoir est fermé |

**« Équipe 7 » DU GROUPE 04 ET « Équipe 7 » DU GROUPE 06 SONT DEUX ÉQUIPES**,
avec deux documents. La poignée porte les deux (`g04-e07`) ; sans le groupe,
les deux sections travailleraient dans le même fichier.

### Ce qui ferme les listes est une date que le contenu porte déjà

`joinable()` demande que le devoir soit **fermé**, `find_assignment()` qu'il
soit **ouvert**, et **les deux lisent la même valeur** (`access` de l'entrée
publiée). Elles sont donc mutuellement exclusives **par construction** : il
n'existe aucun instant où l'on peut à la fois rejoindre une équipe et lire son
document. Pas parce qu'on l'a vérifié quelque part — parce que c'est la même
condition prise dans les deux sens.

C'est ce qui remplace « un étudiant ne peut pas choisir son équipe » : pendant
la période de choix il n'y a **rien à voler** (le devoir n'ouvre pas), et une
fois ouvert **plus personne ne bouge**.

### Le groupe du profil décide quelle liste on voit, et rien d'autre

C'est le numéro auto-déclaré de « Mon identité ». Il ne donne accès à rien :
une fois dans une équipe, c'est **elle** qui porte son groupe, et le corriger
ensuite ne déplace ni la personne ni son document. Sans groupe, la liste
répond en disant d'aller le remplir — le formulaire est juste en dessous.

### Un deuxième dessin a été essayé et retiré

Un **code d'invitation** avec **confirmation unanime** (`invite_code`,
`sealed_at`, `locked_at`, six routes, un écran de verrous). Il tenait, et il
est documenté ici pour qu'on ne le refasse pas : il ne correspondait à rien de
ce que les étudiants font déjà, et surtout **la date d'ouverture faisait déjà
le travail**. Trois colonnes et six routes pour ce qu'une donnée existante
tenait toute seule.

### `import_teams.py` reste l'outil de correction

Placer quelqu'un après l'ouverture, corriger une erreur. CSV :
`group_number,number,account`. Il construit la poignée **exactement comme la
route** — et un test compare les deux fonctions, parce que la copie doit vivre
côté hôte (le python du Dell ne voit pas `app/`).

```sh
python3 import_teams.py devoir roster.csv --sql \
  | docker exec -i ctester-postgres psql -U postgres -d ctester -v ON_ERROR_STOP=1
```

## Voir son équipe avant que le devoir n'ouvre

`GET /team/mine` → les équipes de ce compte, **tous devoirs publiés, ouverts ou
non**, avec `joinable` : la page sait ainsi s'il faut dessiner la liste de choix
ou expliquer que c'est figé. Comme les trois autres routes de choix, elle
n'ouvre **rien** — pas de document, pas de révision, pas de salle.

Affichée dans « Mon identité », à côté du champ « Groupe » qui décide de la
liste qu'on voit.

## L'édition partagée : Yjs relayé, jamais interprété

**La convergence est celle de Yjs, l'autorisation est la nôtre.** Le serveur
(`app/services/collab.py`) est un relais : il transmet des trames opaques d'un
membre d'une salle aux autres et **tamponne l'émetteur** à partir du listage.
Il ne sait pas ce qu'est un caractère, et c'est délibéré — quatre personnes
qui tapent dans la même ligne est exactement le cas qu'un protocole écrit à la
maison rate en semaine trois.

- **La salle est `(équipe, exercice)`**, donc deux équipes sur le même
  exercice sont structurellement deux salles. Il n'y a rien à filtrer, donc
  rien à oublier de filtrer.
- **Le `from` d'une trame est réécrit par le serveur.** Un membre ne peut pas
  signer le curseur d'un autre.
- **L'identité qui circule est une POSITION** (`m1`…`m4`), dérivée du listage,
  plus le nom que le membre a **choisi d'afficher** (sinon « Coéquipier 2 »).
  Aucun `sub` ne franchit la frontière — même règle et même test que
  `forum_vue()`.
- **Le jeton part dans la PREMIÈRE TRAME, pas dans l'URL.** Un navigateur ne
  peut pas poser d'en-tête `Authorization` sur une WebSocket ; un jeton en
  paramètre d'URL est un jeton dans tous les journaux de proxy du chemin.

### `peers` et `epoch` : les deux seuls mécanismes de synchronisation

- **`peers`** dit au client s'il est le premier dans la salle. S'il l'est, il
  sème son document depuis le texte du serveur ; sinon il demande son état à
  la salle. Deux clients ne peuvent pas voir tous les deux une salle vide :
  l'ordre d'arrivée est décidé dans un seul processus, sous une seule boucle
  d'événements. **Sans cette distinction, deux clients semant le même texte
  dans un CRDT le fusionneraient deux fois** — le fichier serait écrit en
  double, et c'est le seul dégât que ce dessin doit rendre impossible.
- **`epoch`** est la couture. Une salle meurt avec son dernier membre et
  renaît, avec une nouvelle époque, pour le suivant. Un client qui revient
  dans une salle RECONSTRUITE doit jeter son document local plutôt que de le
  fusionner. Cinq lignes, et toute une classe de bogues disparaît.

**ponytail : l'état CRDT ne survit pas à une salle vide.** Le document
plein-texte, lui, est dans Postgres, et c'est lui qui réamorce la salle
suivante. Garder le CRDT en mémoire entre deux sessions supprimerait le
réamorçage ; ça voudrait aussi dire une salle qui ne meurt jamais, sur une
plateforme de cours qui ferme en décembre.

**Aucun repli si Yjs n'arrive pas**, et il ne doit pas y en avoir. Sans CRDT
il n'y a pas de façon sûre pour quatre personnes d'éditer un document, et un
« au mieux » qui pousserait la dernière valeur du `<textarea>` détruirait du
travail au lieu de dégrader. L'éditeur se verrouille et le dit.

## L'historique : récupérer, jamais noter

Une révision est écrite **seulement** si ce compte n'en a pas écrit une pour ce
document depuis `TEAM_REVISION_WINDOW` (120 s) ET si la dernière ne porte pas
déjà ces octets-là. **Cette règle est le `WHERE NOT EXISTS` d'un seul INSERT**,
dans la même instruction que l'UPSERT du document — pas une lecture suivie
d'une écriture que deux membres traverseraient en même temps.

**Il n'y a aucun pourcentage de contribution, nulle part, et il ne doit pas y
en avoir.** Un chiffre qui compte des caractères tapés devient une note le
lendemain de sa livraison, et il a tort à propos de celui qui réfléchit avant
de taper. Ce que l'historique rend, c'est « Coéquipier 2, 14 h 32, 0,6 Ko » —
de quoi reconstruire un après-midi, et rien de plus. Un test lit la charge
entière et échoue s'il y trouve un `%` ou un `sub`.

**Restaurer avance, ça ne rembobine pas** : la version restaurée est écrite
comme le document courant, sous le compte qui a restauré. Rien ne disparaît de
l'histoire.

## L'archive

`handin.files` du devoir dit ce qui entre dans le ZIP : le nom **dans
l'archive**, l'exercice d'où il vient, et le fichier de cet exercice. **Aucun
nom de fichier de TCH009 n'est écrit dans l'application** — « main.c et
matrac_lib.c » est un fait sur le contenu de ce devoir-là.

- **Rien n'est concaténé, reformaté ni annoté.** Ce que l'équipe a écrit est
  ce qui est remis, octet pour octet.
- **Pas de README dans l'archive.** L'énoncé demande deux fichiers ; un
  troisième est une chose de plus dont un correcteur doit se demander ce
  qu'elle fait là.
- **Déterministe** : entrées triées, horodatage constant, mode et système
  créateur écrits plutôt qu'hérités de la machine. Sinon « déterministe » est
  un mot sans contrôle derrière.
- **Un trou est refusé, pas remis** : un fichier déclaré sans contenu fait
  échouer la remise en le NOMMANT. Remettre une archive sans `matrac_lib.c`
  est la panne qu'on ne découvre qu'à la correction.

**L'import de ZIP n'est pas fait, et c'est délibéré.** Ce n'est pas le format
qui coince — c'est que l'import devrait traverser la session CRDT en cours :
un fichier écrit côté serveur n'existerait dans aucun des quatre `Y.Doc`
ouverts, et il faudrait faire tourner l'époque pour les forcer à repartir du
serveur. Le bouton « Importer un fichier » qui existe déjà passe, lui, par
l'éditeur, donc par le CRDT, donc arrive correctement chez les quatre. Le jour
où l'import complet vaut la peine, l'endroit est `web/team.js` (dézipper dans
le navigateur avec `DecompressionStream`, puis écrire fichier par fichier par
le chemin d'édition normal) — **pas** une route serveur.

## Ce qui ne change pas, et c'est la moitié du travail

- **`exercise_draft` reste clé sur (compte, exercice).** Aucune route d'équipe
  ne l'écrit. Un étudiant sans équipe travaille un exercice de devoir seul,
  avec son brouillon, exactement comme avant.
- **Le pipeline de soumission est inchangé** : `/submit`, le spool, le worker,
  les quotas, `QUEUE_MAX`, le cache de verdicts. Un exercice de devoir est un
  exercice ordinaire pour le juge.
- **Le worker revalide tout seul**, comme toujours : `tp_path()` rejoue la
  release et ne fait confiance à personne, y compris à notre conteneur web.
- **La navigation locale est celle qui existait** : la bande `#bandelabo` fait
  déjà `[1 ✓] [2 ✓] [3 ●]`, et le devoir la réutilise telle quelle. Ce qu'il
  ajoute est un bandeau AU-DESSUS — titre, équipe, présence, échéance, ZIP,
  remise — c'est-à-dire ce qu'un écran d'exercice ne pouvait pas porter.

**Un exercice de devoir n'accorde aucun XP et ne compte dans aucune
pratique.** Quatre personnes, un document : une première réussite chacune pour
le même code serait quatre récompenses pour un seul travail — exactement le
farming que `docs/gamification/anti-farming.md` refuse. Le filtre est posé
**une fois**, dans `exercices_pratique()`, et la branche de `_record()` nomme
le même champ. Ce qui reste écrit, c'est l'état et la tentative : chaque
membre doit voir que l'exercice passe.

## Le déploiement

**Les GRANT sont dans `app/schema.sql`**, à côté des tables qu'ils ouvrent —
ils ont commencé dans `VHome`, et cette fonctionnalité est ce qui a fait
déborder : c'était la troisième fois qu'une table arrivait sans ses droits.
`test_chaque_table_a_ses_droits` refuse désormais une table qui n'apparaît dans
aucun GRANT, et `VHome` ne garde que le `CREATE ROLE` (son mot de passe vient
du vault).

Ce que ces droits valent depuis que les équipes se forment elles-mêmes :

| Table | Droits | Ce que ça ferme |
|---|---|---|
| `team` | `SELECT, INSERT` | **aucun `UPDATE`, aucun `DELETE`** : une équipe est créée à la volée quand quelqu'un y entre, et son numéro est celui de Moodle |
| `team_member` | `SELECT, INSERT, DELETE` | **aucun `UPDATE`** : changer d'équipe, c'est en sortir et entrer ailleurs — deux écritures dont chacune porte sa condition |
| `team_document`, `team_submission` | `SELECT, INSERT, UPDATE` | pas de `DELETE` : c'est le travail de trois autres |
| `team_revision` | `SELECT, INSERT, DELETE` | ajout seul, comme le forum |

**La garantie a changé de nature, et c'est écrit.** Elle était « rejoindre une
équipe est inexprimable, il n'y a pas d'INSERT » ; elle est maintenant la place
comptée dans le `WHERE` (éprouvée par `teams()`), la date de fermeture, et
l'absence totale d'`UPDATE` (éprouvée par `team_privileges()`).

Reste **une** étape manuelle, et elle n'est pas dans Ansible non plus parce que
NPM garde son routage dans sa propre base : **cocher « Websockets Support »**
sur le proxy host. Sans ça, l'`Upgrade` de `/team/live` ne passe pas, l'espace
partagé se reconnecte en boucle en disant « hors ligne », et tout le reste du
site marche — ce qui rend la panne longue à trouver.

## Vérification de bout en bout

```sh
python3 test_ctester.py        # les règles, la porte, le relais, l'archive
python3 test_api.py            # la frontière HTTP, deux équipes, la socket
node    test_page.js           # le CRDT réellement branché sur l'éditeur
python3 validate_content.py ../unittests/content

docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester \
  -p 55432:5432 postgres:16-alpine
docker exec -i pg psql -U postgres -d ctester \
  -c "CREATE ROLE ctester_app LOGIN PASSWORD 'y'"   # le rôle, et RIEN d'autre :
                                                    # ses droits viennent de
                                                    # schema.sql
CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester \
  python3 test_postgres.py     # LES DEUX DSN : sinon les GRANT ne sont pas
                               # éprouvés, et c'est justement eux qui
                               # empêchent de choisir son équipe
docker stop pg
```

Puis, à la main, avec deux navigateurs et deux comptes de la même équipe :

1. les deux ouvrent `dev-a` → chacun voit l'autre dans le bandeau ;
2. l'un tape → l'autre voit le texte **et le curseur coloré** arriver ;
3. l'un recharge → il retrouve le document, pas son brouillon d'hier ;
4. un troisième compte, d'une autre équipe, ouvre le même exercice → il ne
   voit rien des deux premiers, et l'onglet réseau confirme que
   `/team/document` lui rend `{}` ;
5. « Télécharger le ZIP » → `main.c` et `matrac_lib.c`, sous `Devoir-TCH009/` ;
6. « Remettre » → l'autre membre voit « remis le … » en rechargeant.
