# Partage de code entre pairs — plan d'implémentation

## Contexte

Le forum d'entraide permet aujourd'hui de discuter d'un exercice, mais pas de
montrer du code. Or c'est ce que les étudiants demandent le plus souvent une
fois l'exercice réussi : « comment tu l'as fait, toi ? ». Le publier
librement en ferait un canal de distribution de solutions ; le publier
**seulement à ceux qui ont déjà validé l'exercice** en fait autre chose — une
comparaison d'approches entre gens qui ont déjà fait le travail.

Deuxième besoin, du côté du chargé de laboratoire : pouvoir déposer sa propre
implémentation comme **référence**, sous l'étiquette « Enseignant » déjà
réservée par `forum_identite()`, soumise aux **mêmes** règles d'accès que
n'importe quel partage. Une seule règle à défendre, une seule à tester.

Résultat attendu : sur un exercice validé, la vue Discussions gagne une
seconde section « Codes partagés » ; sur un exercice non validé, cette section
n'existe pas et l'API ne renvoie rien.

**Décisions déjà prises** (ne pas les rouvrir en implémentant) :

| Question | Décision |
|---|---|
| Droit de lecture | avoir **validé** l'exercice (`etat_exercice.statut = 'valide'`) |
| Source du code | **snapshot serveur** des sources déjà stockées ; jamais l'éditeur |
| Interface | **section de la vue Discussions**, dans `forum.js`, pas de 5ᵉ écran |
| Référence du cours | **mêmes règles d'accès** que les autres, épinglée en tête |
| Cardinalité | **un partage par compte et par exercice**, remplaçable |
| Rendu du code | `textContent` + la coloration syntaxique existante |
| Note de l'auteur | oui, texte court, `forum_texte()` + `rendreMarkdown()` |
| Modération | signalable et masquable, comme un message |

---

## Invariant central

> **Le contrôle d'accès est la clause `WHERE` d'une seule instruction SQL, des
> deux côtés.**

- Publier : `INSERT INTO forum_partage … SELECT … FROM etat_exercice WHERE
  utilisateur = %s AND exercice_id = %s AND statut = 'valide'`. Zéro ligne
  insérée = pas validé. Le code publié ne peut littéralement pas venir
  d'ailleurs que d'une soumission que le juge a acceptée, parce que
  `etat_exercice.sources` n'est écrit que par `_result()`
  ([app/app.py:1534](app/app.py#L1534)) via `job_sources()`
  ([app/app.py:401](app/app.py#L401)).
- Lire : `SELECT … FROM forum_partage p WHERE p.exercice_id = %s AND EXISTS
  (SELECT 1 FROM etat_exercice WHERE utilisateur = %(moi)s AND exercice_id =
  %s AND statut = 'valide')`. Pas validé = zéro ligne, jamais un filtre en
  Python. C'est l'idiome que `forum_supprimer()`
  ([app/etat.py:345](app/etat.py#L345)) et `forum_signaler()`
  ([app/etat.py:357](app/etat.py#L357)) utilisent déjà.

Le filtrage en Python reste interdit : une garde `if` bien placée est ce que
`build-unity.sh` / `build-io.sh` refusent de devenir.

**Caveat à écrire dans le code et dans l'interface** : `write_state()`
([app/etat.py:132](app/etat.py#L132)) réécrit `sources` à **chaque**
soumission tout en gardant `statut = 'valide'`. Le snapshot est donc « le
dernier code que vous avez soumis sur un exercice que vous avez validé », pas
« le code exact du verdict vert ». Le bouton doit le dire : *« Publier le
code actuellement enregistré »*, et l'aperçu montre ce qui partira **avant**
de confirmer.

---

## 1. Schéma — `app/schema.sql`

Deux tables, à la suite du bloc forum (après `forum_nom_signale`, l.237). Le
schéma passe de **onze à treize** tables.

### `forum_partage` — journal en ajout seul, la dernière ligne d'un compte fait foi

```
partage_id   TEXT PRIMARY KEY          -- uuid4().hex, généré par app.py
exercice_id  TEXT NOT NULL
utilisateur  TEXT NOT NULL             -- le sub, ne franchit jamais la frontière
sources      JSONB NOT NULL            -- {nom_de_fichier: contenu}
note         TEXT                      -- facultative, forme SOURCE, ≤ FORUM_MAX_CHARS
masque       BOOLEAN NOT NULL DEFAULT false
cree_le      TIMESTAMPTZ NOT NULL DEFAULT now()
```

Index `forum_partage_dernier_idx (exercice_id, utilisateur, cree_le DESC)` —
il sert le `DISTINCT ON (utilisateur)` de la lecture d'un exercice.

Même forme que `forum_profil` ([app/schema.sql:217](app/schema.sql#L217)) :
ajout seul, `DISTINCT ON … ORDER BY utilisateur, cree_le DESC, partage_id
DESC` pour ne rendre que le dernier. « Remplacer » = insérer une ligne de
plus. « Supprimer » = un vrai `DELETE` de **toutes** les lignes du compte sur
cet exercice (c'est le retrait d'un contenu, pas une révision).

**Le trou à ne pas creuser** : avec un journal, republier après avoir été
masqué se démasquerait tout seul. La règle est donc : *un compte dont le
dernier partage sur cet exercice est masqué ne peut pas republier* — refus
explicite côté `app.py` (409 + message), pas un masquage silencieux. Un test
dédié.

### `forum_partage_signalement`

```
partage_id  TEXT NOT NULL
utilisateur TEXT NOT NULL
cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
PRIMARY KEY (partage_id, utilisateur)
```

Copie exacte de `forum_signalement` ([app/schema.sql:179](app/schema.sql#L179))
— la PK **est** la règle « un compte ne signale qu'une fois ».

**Pas de table de journal de modération séparée.** Masquer/rétablir un
partage réutilise `forum_moderation` en y stockant le `partage_id` dans la
colonne `message_id`ⁿᵒⁿ — *non*, c'est exactement le mélange que
`_forum_effacer_nom` a refusé de faire. Choix retenu : **ajouter une colonne
`cible` à `forum_moderation`** (`TEXT NOT NULL DEFAULT 'message'`, `CHECK
(cible IN ('message','partage'))`). Une table de journal, deux natures de
cible explicitement nommées, aucune ambiguïté à la relecture.

---

## 2. Privilèges — côté `VHome`, `roles/ctester`

À ajouter au `GRANT`, sur le modèle **exact** de `forum_message` :

- `GRANT SELECT, INSERT, DELETE ON forum_partage TO ctester_app`
- `GRANT UPDATE (masque) ON forum_partage TO ctester_app` — **GRANT DE
  COLONNE**, jamais `UPDATE` de table : c'est Postgres qui garantit qu'aucune
  ligne de Python distraite ne réécrit le code ou la note de quelqu'un.
- `GRANT SELECT, INSERT ON forum_partage_signalement TO ctester_app`
- `forum_moderation` gagne sa colonne : rien à changer au GRANT.

`test_postgres.py::forum_privileges()` ([test_postgres.py:325](test_postgres.py#L325))
doit gagner les `UPDATE` refusés correspondants (`sources`, `note`,
`utilisateur`) et le `UPDATE … SET masque = masque` qui doit passer.

---

## 3. `app/etat.py` — six fonctions, aucune logique

À placer dans le bloc forum (après `forum_auteur`, l.517). Rappel de
l'en-tête l.312 : ce module **rend le `sub`**, c'est `app.py` qui traduit.

| Fonction | Rôle | Forme |
|---|---|---|
| `forum_partage_ecrire(partage_id, exercise_id, user, note)` | publie | `INSERT … SELECT %s,%s,%s,e.sources,%s FROM etat_exercice e WHERE e.utilisateur=%s AND e.exercice_id=%s AND e.statut='valide' RETURNING partage_id` — **la clause WHERE est le contrôle d'accès** ; `[]` = pas validé |
| `forum_partages(exercise_id, lecteur, limite)` | lit le fil des partages | `SELECT DISTINCT ON (utilisateur) …` + `WHERE EXISTS (… etat_exercice … statut='valide')` pour le lecteur ; rend **aussi** les masqués avec leur drapeau, comme `forum_fil` ([app/etat.py:318](app/etat.py#L318)) |
| `forum_partage_mien(exercise_id, user)` | l'état de mon propre partage (existe ? masqué ?) | `DISTINCT ON` limité à `utilisateur = %s`, sans la garde EXISTS |
| `forum_partage_supprimer(exercise_id, user)` | retire le sien | `DELETE … WHERE exercice_id=%s AND utilisateur=%s RETURNING partage_id` |
| `forum_partage_signaler(partage_id, user)` | signale | `INSERT … SELECT p.partage_id, %s FROM forum_partage p WHERE p.partage_id=%s ON CONFLICT DO NOTHING RETURNING` — pas d'orphelin **et** pas de doublon, en une instruction |
| `forum_partages_signales(limite)` | la file du modérateur | JOIN + `count(*)`, `ORDER BY combien DESC, p.cree_le`. Ne rend **jamais** qui a signalé |
| `forum_partage_moderer(action_id, partage_id, moderator, action)` | masque / rétablit | CTE `agi` insère dans `forum_moderation` (`cible='partage'`) puis `UPDATE forum_partage SET masque=… WHERE partage_id=(SELECT … FROM agi) RETURNING` — copie de `forum_moderer` ([app/etat.py:396](app/etat.py#L396)) |

Toutes passent par `_query()` : `None` = « la base n'a pas répondu », jamais
« il n'y a rien » ([app/etat.py:57](app/etat.py#L57)).

**`forget(user)` ([app/etat.py:547](app/etat.py#L547)) gagne deux CTE de
DELETE.** Le test compte les tables du schéma et exige `_query(` **une seule
fois** dans la fonction : la seule façon correcte est d'ajouter deux CTE à
l'instruction unique, pas deux appels.

Les horodatages passent par `_minute()` ([app/etat.py:527](app/etat.py#L527)),
comme les messages.

---

## 4. `app/app.py` — trois routes, zéro nouvelle notion

### Bornes
`FORUM_PARTAGE_MAX_OCTETS` (défaut : réutiliser `MAX_CODE`) plafonne le
snapshot ; la note passe par `forum_texte()`
([app/app.py:615](app/app.py#L615)) inchangé. Une constante de plus dans le
bloc de configuration l.48-69.

### Routes
Toutes derrière `_forum_qui()` ([app/app.py:1166](app/app.py#L1166)) — donc
503 si le forum est éteint, 401 sans jeton — et `_forum_entree()`
([app/app.py:1189](app/app.py#L1189)) pour l'exercice.

| Route | Handler | Notes |
|---|---|---|
| `GET /forum/partages?ex=<id>` | `_forum_partages` | `{exercice_id, autorise, mien, partages: [...]}`. **`autorise: false` et une liste vide** quand le lecteur n'a pas validé — pas un 403 : « vous n'y avez pas droit » et « il n'y a rien » se ressemblent, et la page a besoin de savoir laquelle des deux pour afficher le bon encart |
| `POST /forum/partages` | `_forum_partager` | corps `{ex, note}`. Ordre : qui → corps → entrée → `forum_texte` (si note) → **`_forum_throttle(sub)`** → refus 409 si mon dernier partage est masqué → `forum_partage_ecrire` → **`[]` ⇒ 403 « il faut avoir validé cet exercice »** |
| `DELETE /forum/partages?ex=<id>` | `_forum_partage_supprimer` | 404 identique pour « rien à supprimer » et « pas à vous », comme `_forum_supprimer` ([app/app.py:1268](app/app.py#L1268)) |

Deux routes existantes gagnent une branche, sans nouvelle route :
- `POST /forum/signalement` : `{quoi: "partage", id: <partage_id>}` à côté de
  `"nom"` et du défaut ([app/app.py:1288](app/app.py#L1288)). **Même réponse**
  pour neuf / doublon / inconnu.
- `GET` et `POST /forum/moderation` : la file gagne une clé `partages`, et
  l'action accepte `cible: "partage"` avec `masquer` / `retablir`
  ([app/app.py:1322](app/app.py#L1322), [app/app.py:1339](app/app.py#L1339)).

### La frontière de confidentialité
`forum_vue()` ([app/app.py:728](app/app.py#L728)) ne convient pas tel quel
(un partage n'a pas de `texte`). Écrire **`forum_partage_vue(partages, sub,
moderateur, profils)`** juste à côté, qui réutilise **`forum_identite()`**
([app/app.py:704](app/app.py#L704)) sans la réécrire, et rend :

```
{id, sources, note, cree_le, auteur, groupe, nom_signalable, mien,
 masque, reference}
```

- `reference = is_moderator(<sub de l'auteur>)` — c'est ce drapeau qui épingle
  le code du chargé de labo en tête. Recalculé serveur, jamais un claim.
- **Aucun `sub` ne sort.** Le test existant
  `test_forum_vue_ne_laisse_sortir_aucun_sub`
  ([test_ctester.py:1574](test_ctester.py#L1574)) doit être étendu à cette
  charge-là, y compris dans la vue la plus renseignée (celle du modérateur).
- Le filtre des masqués est le même : `if not (moderateur or not
  p["masque"]) and not p["mien"]: continue` — l'auteur d'un partage masqué doit
  voir qu'il est masqué, sinon il republie en boucle sans comprendre.

### Ce qui ne bouge pas
`_result()` ([app/app.py:1534](app/app.py#L1534)) n'est **pas** touché :
publier ne rapporte aucun XP et ne débloque aucun succès. La progression
récompense la réussite, pas l'exhibition. `politique.py` reste inchangé.

---

## 5. `app/forum.js` — une section de plus, un seul `innerHTML` de plus

Le module est déjà l'endroit où vit l'identité, le signalement et la
modération ; le partage réutilise tout ça.

### Ce que `app.js` doit exposer
`highlight()` ([app/app.js:497](app/app.js#L497)) est privé au noyau. L'exposer
sur le contexte : **`ctester.colorer(src)`** — même fonction, même échappement
**après** découpage. Sens unique respecté : `forum.js` lit `window.ctester`,
le noyau n'importe rien ([app/app.js:9](app/app.js#L9)).

### Rendu d'un partage — `unPartage(p)`
1. En-tête identique à `unMessage()` ([app/forum.js:535](app/forum.js#L535)) :
   `span.auteur` (le mot rendu par le serveur), `span.groupe`, `time.quand` via
   `quandLocal`, `span.etat` « masqué » en toutes lettres. Si `p.reference`,
   une puce « Référence du cours » et l'élément est **placé en tête** de la
   liste.
2. La note, s'il y en a une, par **`rendreMarkdown()`**
   ([app/forum.js:123](app/forum.js#L123)) — inchangé, deux barrières.
3. Le code : un `<pre><code>` **par fichier**, précédé du nom de fichier en
   `textContent`. Contenu posé par `codeEl.innerHTML = ctester.colorer(src)` —
   `colorer` échappe chaque tranche, c'est le même contrat que l'éditeur. Si
   `ctester.colorer` manque, repli sur `textContent`, exactement comme
   `rendreMarkdown` retombe sur `textContent` quand DOMPurify est absent.
4. Actions : « Retirer mon code » si `p.mien`, sinon « Signaler » ;
   « Signaler le nom » si `p.nom_signalable` ; « Masquer » / « Rétablir » si
   modérateur.

### Où ça s'accroche
`dessiner()` ([app/forum.js:647](app/forum.js#L647)) place déjà deux colonnes.
La colonne large gagne, **sous le fil**, une section `Codes partagés` qui a
trois états et un seul :

- **pas validé** → un encart qui le dit sans détour : *« Les codes partagés
  s'ouvrent quand vous avez réussi cet exercice. »* Aucune liste, aucun bouton.
- **validé, rien publié** → la liste + un bouton « Publier mon code », qui
  ouvre un **aperçu de ce qui partira** (fichiers + note facultative) avant
  confirmation.
- **validé, déjà publié** → la liste, mon partage marqué « Vous », et
  « Remplacer » / « Retirer ».

La file de modération ([app/forum.js:590](app/forum.js#L590)) gagne une
troisième pile, `filePartages()`, à côté de `fileModeration()` et
`fileNoms()`, qui rend le code par le **même** chemin — la remarque l.610
(« une vue de modération qui rendrait le HTML brut pour voir ce qu'il y a
dedans serait la page la plus facile à attaquer du site ») vaut mot pour mot.

`charger(id)` ([app/forum.js:184](app/forum.js#L184)) fait un appel de plus
(`forum/partages?ex=`) et `oublier()` ([app/forum.js:724](app/forum.js#L724))
remet le nouvel état à zéro à la déconnexion.

**Aucune nouvelle bibliothèque**, aucun fichier `vendor/` de plus : le code
n'est pas du Markdown.

### `app/style.css`
Les `<pre>` de partage réutilisent les classes `.tc .ts .tp .tk .tn .tf .tu`
déjà définies pour `#hl` — mais **pas** les métriques de la superposition
`#hl`/`#code`/`#gutter`, qui ne concernent que l'éditeur. Une classe
`.partagecode` autonome (police monospace, `white-space: pre`,
`overflow-x: auto`).

### `ASSET_REVISION`
À incrémenter dans [app/app.js:14](app/app.js#L14) **et** `index.html` — les
deux, sinon le module arrive en version de cache et `activerModule` affiche
« le fichier ne s'est pas déclaré ».

---

## 6. Tests — la partie qui rend le reste vrai

### `test_ctester.py`
- **`test_suppression_couvre_toutes_les_tables`**
  ([test_ctester.py:830](test_ctester.py#L830)) : `assert len(tables) == 11`
  devient `== 13`. C'est le contrôle qui échoue tout seul si une des deux
  tables n'est pas dans `forget()` — ne pas le contourner, le mettre à jour.
- **`test_forum_vue_ne_laisse_sortir_aucun_sub`**
  ([test_ctester.py:1574](test_ctester.py#L1574)) : étendre à
  `forum_partage_vue`, avec un partage de modérateur (le cas `reference`) et
  un partage masqué, et rechercher `sub-*` et `"utilisateur"` dans le JSON.
- **Nouveau `test_forum_partage_vue`** : les trois identités, `reference`
  vrai pour le seul modérateur, `mien` correct, un masqué invisible pour un
  tiers **et visible pour son auteur**.
- **`test_http_forum`** ([test_ctester.py:1667](test_ctester.py#L1667)) —
  la `BaseSimulee` gagne les sept fonctions ; nouveaux cas :
  - alice n'a pas validé → `GET /forum/partages` rend `autorise: false` et une
    liste vide **même si bob a publié** ;
  - alice publie sans avoir validé → **403**, et rien n'entre en base ;
  - alice valide puis publie → 200, et **le corps de la requête ne contient
    aucune source** (la page n'envoie que `{ex, note}`) ;
  - republier remplace : une seule entrée dans la vue, deux lignes en base ;
  - republier après masquage → **409**, le masquage tient ;
  - retirer supprime **toutes** les lignes du compte sur cet exercice ;
  - signalement idempotent, sans orphelin, réponse identique dans les trois
    cas ;
  - modération : 403 pour alice ; masquer puis rétablir, deux lignes de
    `forum_moderation` avec `cible = 'partage'` ;
  - quota : publier est comptabilisé par `_forum_throttle`, **lire ne l'est
    jamais** ;
  - `DELETE /moi` efface les partages d'alice sans toucher ceux de bob.
- Forum éteint (`CTESTER_FORUM_MODERATORS` vide) → **503 sur les trois
  nouvelles routes**, comme les six autres
  ([test_ctester.py:1460](test_ctester.py#L1460)).

### `test_postgres.py` — le seul contrôle qui éprouve le SQL
Les formes ajoutées sont précisément celles que le fichier existe pour
attraper ([test_postgres.py:18](test_postgres.py#L18)) : un `INSERT … SELECT`
dont le `WHERE` **est** le contrôle d'accès, un `SELECT … WHERE EXISTS` qui
fait la même chose en lecture, un `DISTINCT ON`, une CTE modifiante qui
alimente un `UPDATE`, et treize `DELETE` dans une seule instruction.

- `TABLES` ([test_postgres.py:53](test_postgres.py#L53)) : deux noms de plus.
- **`partages()`** : publier sans état → 0 ligne ; avec `statut='essaye'` →
  0 ligne ; avec `'valide'` → 1 ligne et **`sources` égal à celui de
  `etat_exercice`** ; `forum_partages` pour un lecteur non validé → `[]`, pour
  un lecteur validé → la liste ; `DISTINCT ON` rend la dernière de deux
  lignes ; masquer/rétablir avec deux lignes de journal en `cible='partage'` ;
  signalement unique par compte.
- **`forum_privileges()`** ([test_postgres.py:325](test_postgres.py#L325)) :
  `UPDATE forum_partage SET sources = …`, `SET note = …`, `SET utilisateur =
  …` et `UPDATE forum_partage_signalement` doivent lever
  `InsufficientPrivilege` ; `UPDATE forum_partage SET masque = masque` doit
  passer. **C'est la moitié du contrat que Python ne peut pas tenir.**
- **`suppression()`** ([test_postgres.py:377](test_postgres.py#L377)) : treize
  compteurs non nuls avant, tous nuls après, bob intact.

### `test_page.js`
- Le parcours **anonyme** ne demande toujours **rien** — ni `forum.js`, ni
  `forum/partages`. C'est la raison d'être du découpage.
- `ctester.colorer` est exposé et échappe : `colorer('<script>')` ne contient
  pas `<script`.
- `rendreMarkdown` reste inchangé et couvert.
- Un partage rendu dans un DOM en carton : le code d'un fichier nommé
  `<img onerror=…>` ne produit **aucun** attribut d'événement, et un `sources`
  contenant `</code><script>` ressort en texte.
- La section n'apparaît pas quand `autorise: false`.

---

## 7. Documentation

- **`CLAUDE.md`**, section « Le forum d'entraide » : un paragraphe sur le
  partage — la règle d'accès en une phrase, le fait que le snapshot vient du
  serveur, le compte de tables qui passe de onze à treize, et le piège du
  republish-après-masquage.
- **`app/schema.sql`** : le commentaire de bloc avant les deux tables, dans le
  ton des autres (pourquoi ajout seul, pourquoi pas de clé étrangère).
- **`VHome`, `roles/ctester`** : les `GRANT`, avec la note « GRANT DE COLONNE,
  jamais UPDATE de table ».

---

## Ordre d'exécution suggéré

1. `schema.sql` + les `GRANT` dans `VHome` (rien ne marche sans).
2. `etat.py` : les sept fonctions + les deux CTE dans `forget()`.
3. `test_postgres.py` : `partages()`, `forum_privileges()`, `suppression()`,
   `TABLES` — **avant** l'API, parce que c'est le seul contrôle qui dit si le
   SQL est juste.
4. `app.py` : bornes, `forum_partage_vue`, trois routes, deux branches.
5. `test_ctester.py` : les 13 tables, la frontière, `test_http_forum`.
6. `app.js` (`ctester.colorer`, `ASSET_REVISION`), `forum.js`, `style.css`.
7. `test_page.js`.
8. `CLAUDE.md`.

## Vérification de bout en bout

```sh
python3 test_ctester.py
node    test_page.js                     # npm ci une fois
python3 valider_contenu.py ../unittests

docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester \
  -p 55432:5432 postgres:16-alpine
CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
  python3 test_postgres.py               # LES DEUX DSN : sans le second, les
                                         # GRANT ne sont pas éprouvés
docker stop pg
```

Puis, à la main, dans la vraie page (`CTESTER_APERCU=1` + un worker) :

1. Compte A, exercice non validé → la vue Discussions ne montre **aucun**
   code, seulement l'encart d'explication.
2. Compte A valide → recharger → la section apparaît, vide.
3. Compte A publie → l'aperçu montre ce qui part, puis le partage apparaît
   marqué « Vous ».
4. Compte B, non validé, même exercice → il ne voit **rien** ; l'onglet réseau
   confirme que `/forum/partages` rend `autorise: false` et une liste vide,
   pas les sources.
5. Compte B valide → il voit le partage de A, sous « Participant » ou le nom
   choisi.
6. Compte modérateur publie → son partage apparaît épinglé « Référence du
   cours » chez A et B.
7. Modérateur masque le partage de A → invisible pour B, visible et marqué
   « masqué » pour A ; A qui republie reçoit un refus explicite.
8. `DELETE /moi` sur le compte A → ses partages disparaissent, ceux de B et du
   modérateur restent.

Et le contrôle qui ne se saute jamais :

```sh
grep -rl answer app/*.json app/quiz/ app/tp/     # DOIT ne rien trouver
```
