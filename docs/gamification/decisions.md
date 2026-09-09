# Journal de decisions

## D-001 — Separer pratique et maitrise

**Statut:** Accepted.

**Decision:** seule une verification independante explicitement eligible constitue une preuve forte de maitrise; XP reste distinct.

**Raison:** l'aide et l'IA peuvent etre utiles a la pratique mais ne prouvent pas l'autonomie.

**Alternatives:** assimiler toute reussite du juge a la competence (rejetee).

**Consequences:** nouveaux types de contenu/tentatives et une UI qui explique la difference.

## D-002 — Pas de detecteur IA comme fondation

**Statut:** Accepted.

**Decision:** concevoir des demonstrations de transfert/variantes plutot que classifier l'origine du code.

**Raison:** detection peu fiable et pedagogiquement fragile.

**Alternatives:** detection automatique/sanction (rejetee comme mecanisme principal).

**Consequences:** aucune score IA dans mastery, rating ou discipline.

## D-003 — Evolution incremental compatible avec l'architecture

**Statut:** Accepted.

**Decision:** conserver API Python, page existante, runner et Postgres optionnel; ajouter migrations et projection serveur sans framework ou bus distribue.

**Raison:** l'application est petite, ses frontieres de securite sont importantes et un changement d'architecture serait hors sujet.

**Alternatives:** replatforming/event bus externe (rejetes pour maintenant).

**Consequences:** table outbox et workers simples si necessaire; flux anonyme intact.

## D-004 — Le classement est secondaire et opt-in

**Statut:** Accepted.

**Decision:** pas de ranked avant la Phase 5; pas de leaderboard global par defaut.

**Raison:** le public est debutant et l'objectif est la progression personnelle.

**Alternatives:** classement des le lancement (rejetee).

**Consequences:** consentement et pseudonymes prealables; mastery/anti-farming avant rating.

## D-005 — Politique de valeurs configurable

**Statut:** Accepted.

**Decision:** XP, niveaux, seuils, recence, ratio de recommandations et rating sont versionnes/configures, tous PROVISOIRES tant qu'ils ne sont pas pilotes.

**Raison:** eviter l'illusion de precision et les migrations de logique fragiles.

**Alternatives:** chiffres hard-codes (rejetee).

**Consequences:** stocker policy/version dans les attributions et evidences.

## D-006 — Contexte est orthogonal a la competence

**Statut:** Accepted.

**Decision:** preferer un contexte d'ingenierie configurable sans changer la competence evaluee.

**Raison:** donner du sens sans favoriser un parcours d'etude particulier.

**Alternatives:** pistes par programme fixes (rejetee).

**Consequences:** revue d'equivalence de variantes et preferences reversibles.

## D-007 — L'XP ne recompense qu'une premiere reussite, et ne regarde pas en arriere

**Statut:** Accepted (2026-09-03, phase 1).

**Decision:** une seule attribution par exercice publie, produite par le serveur a la lecture du verdict, sous l'identifiant d'evenement `reussite:<exercice>`. Un echec n'accorde rien; refaire un exercice n'accorde rien; un sondage rejoue n'accorde rien. Les anciennes `tentative_pratique` ne sont PAS relues pour distribuer de l'XP retroactivement: les recompenses commencent a l'activation.

**Raison:** c'est le seul reglage qui laisse la pratique illimitee sans la rendre farmable, sans compter les erreurs ni chronometrer qui que ce soit. Un backfill aurait aussi fabrique un classement implicite entre des etudiants qui n'avaient rien demande.

**Alternatives:** XP par tentative (rejetee: recompense le bruit), XP degressive par repetition (rejetee: complexite sans besoin mesure), backfill des tentatives existantes (rejetee).

**Consequences:** un exercice reussi avant la phase 1 puis refait apres rapporte une fois. Le plafond quotidien reste dans la politique comme defense de profondeur, pas comme mecanisme central. Toute correction ulterieure sera une transaction motivee sous un acces d'administration explicite — le role applicatif n'a pas `UPDATE` sur ces tables.

## D-008 — Un forum d'entraide MVP entre la Phase 1 et la Phase 2

**Statut:** Accepted (2026-09-03).

**Decision:** livrer un forum asynchrone minimal — un fil chronologique par
exercice publie, prive aux comptes connectes — AVANT la Phase 2, et sans qu'il
appartienne a la Phase 4 sociale. Il ne realise pas la Phase 4 : ni objectif de
classe, ni contribution mesuree, ni cohorte, ni visibilite configurable. Il ne
recompense RIEN : aucun XP, aucun succes, aucun compteur, aucune serie. Les
tables de progression ne sont ni lues ni ecrites par ses routes, et le `GRANT`
applicatif ne lui donne aucun privilege nouveau dessus.

**Raison:** le besoin observe est immediat et modeste — quelqu'un bloque le soir
sur un exercice n'a personne a qui poser une question conceptuelle. Le faire
attendre la maitrise verifiee (Phase 2), puis les objectifs collectifs (Phase 4),
c'est ne rien livrer avant la fermeture de decembre. Un fil par exercice est la
plus petite chose qui reponde a ce besoin, et c'est la seule qui puisse etre
moderee par une personne a 80 etudiants.

**La moderation est HUMAINE, et c'est la condition d'existence de la fonction.**
Le produit ne pretend a aucun endroit reconnaitre une solution automatiquement —
ce serait le detecteur que [D-002](#d-002--pas-de-detecteur-ia-comme-fondation)
rejette, deguise. Les seules regles automatiques sont des bornes de forme
(longueur, quota d'ecriture) et un rendu assaini. Le reste passe par une charte
visible, un bouton « Signaler », et quelqu'un qui lit. Consequence directe : le
forum est **eteint par defaut** et ne s'allume qu'avec au moins un `sub` de
moderateur configure (`CTESTER_FORUM_MODERATORS`). Sans moderateur, le
signalement n'aboutirait nulle part ; on n'ouvre pas le canal « en attendant ».

**Aucune identite ne traverse.** Une publication s'annonce « Vous » a son auteur,
« Participant » aux autres, « Enseignant » pour un moderateur. Ces trois
mots sont derives par le serveur a partir du `sub` ; le `sub` lui-meme ne franchit
jamais la frontiere HTTP. *(Revise par [D-011](#d-011--lidentite-choisie-facultative-et-invisible-par-defaut) :
un compte peut depuis choisir un nom d'affichage, mais rien n'apparait sans
qu'il l'ait explicitement coche.)*

**Alternatives:** attendre la Phase 4 (rejetee : rien avant decembre) ; un canal
externe type Discord (rejetee : hors du controle du cours, transporte du code
evalue, et aucune suppression a la demande) *(revise par
[D-013](#d-013--le-pont-discord-par-compte-de-service) : le Discord n'est plus
une ALTERNATIVE au forum mais un PONT vers lui — CTester reste la source de
verite, la suppression a la demande continue de marcher, et seul le chat
PUBLIC traverse)* ; recompenser la participation en XP
(rejetee : cela fabriquerait du bruit et transformerait l'entraide en farming) ;
un detecteur de solution (rejetee, voir D-002).

**Consequences:** trois tables de faits de plus (`forum_message`,
`forum_signalement`, `forum_moderation`), toutes couvertes par `forget()` dans la
meme instruction ; un role de moderation configure par variable d'environnement,
jamais par un claim OIDC ; une charte a maintenir a jour ; et une dette assumee —
la conservation va jusqu'a la fermeture de decembre, sans archivage ni report,
conformement a l'absence de saisons. Le message reste immuable apres publication :
son auteur peut le supprimer, un moderateur peut le masquer ou le retablir, avec
action journalisee, et personne ne peut le reecrire.

## D-009 — Markdown restreint, assaini a chaque affichage, avec deux dependances vendorisees

**Statut:** Accepted (2026-09-03).

**Decision:** les messages du forum sont saisis en Markdown restreint et **stockes
sous leur forme source**. Le rendu se fait dans le navigateur, a CHAQUE point
d'affichage — le fil, l'apercu de redaction, la vue de moderation — par
[marked](https://github.com/markedjs/marked) puis
[DOMPurify](https://github.com/cure53/DOMPurify), tous deux **epingles par
version et servis depuis cette origine** (`web/vendor/`, jamais un CDN). Le HTML
brut est echappe AVANT l'analyse Markdown. L'allow-list est fermee : `p`, `br`,
`strong`, `em`, `ul`, `ol`, `li`, `blockquote`, `code`, `a`, avec `href` et `rel`
pour seuls attributs, `http(s)` absolus pour seuls schemas, `rel="noopener
noreferrer"` pose systematiquement et aucune cible nommee.

**Raison:** une question de programmation se lit mal en un seul bloc de texte —
une liste d'etapes, un mot en gras, une citation de l'enonce changent
l'utilisabilite. Mais rendre du HTML ecrit par un etudiant est la surface la
plus dangereuse de toute la page, et la seule ou une injection reussie serait
executee **chez quelqu'un d'autre**. Ecrire notre propre assainisseur serait
l'erreur classique ; deux bibliotheques maintenues, epinglees, valent mieux que
cent lignes maison.

**Assainir a l'AFFICHAGE et pas a l'ECRITURE**, et la nuance porte : une regle
resserree plus tard ne s'appliquerait pas aux messages deja en base. Le serveur
ne rend rien et n'assainit rien — il borne (longueur, caracteres de controle) et
stocke la source. C'est aussi ce qui rend la vue de moderation sure : elle passe
par le meme pipeline, et jamais par un « HTML brut pour voir ce qu'il y a
dedans » qui serait la page la plus attaquable du site.

**Pas de bloc de code, et c'est voulu.** `pre` n'est pas dans l'allow-list : un
bloc cloture retombe en texte. Le forum est pour les questions conceptuelles, pas
pour coller du code — la charte le dit, et le rendu ne le facilite pas.

**La CSP n'est PAS la defense principale.** Elle existe (`default-src 'none'`,
`script-src 'self'`, sans hachage : il n'y a plus de script inline,
`frame-ancestors 'none'`), elle est calculee sur le corps servi pour rester en phase avec la page,
et elle limite les degats si les deux barrieres ci-dessus cedaient. `style-src`
garde `'unsafe-inline'` : la page pose des attributs `style` calcules (largeur de
jauge, rang d'une coche de verdict) et les retirer demanderait de reecrire trois
composants pour un gain nul face a la menace visee.

**Alternatives:** texte brut integral (rejetee : le besoin de mise en forme est
reel et une liste d'etapes en texte plat se lit mal) ; un assainisseur maison
(rejetee) ; un CDN pour les deux bibliotheques (rejetee : la CSP l'interdit, et
« ce que le depot contient est ce que le navigateur recoit » est une propriete
qu'on garde) ; assainir a l'ecriture (rejetee, voir ci-dessus) ; Typst compile ou
rendu (rejetee : un moteur de rendu de plus, pour un besoin qui n'existe pas ;
du Typst cite reste du texte brut).

**Consequences:** 74 Ko de bibliotheques, telecharges **uniquement** a
l'ouverture de la vue « Discussions » d'un compte connecte — le parcours anonyme
n'en paie rien, et un connecte qui n'ouvre jamais le forum non plus. Si l'une des
deux n'arrive pas, ou si `DOMPurify.isSupported` est faux, le rendu retombe sur
`textContent` : du texte brut, jamais du HTML non filtre. Le harnais
`test_page.js` gagne une dependance de TEST (jsdom) pour donner un vrai DOM a
DOMPurify — sans quoi ses controles XSS ne prouveraient rien, `sanitize()` rendant
son entree telle quelle en l'absence de DOM. Monter de version demande de toucher
au nom de fichier, a `config.VENDOR` et a `forum.js` : c'est le prix
volontaire de l'epinglage.

## D-010 — La maitrise est DERIVEE, pas stockee

**Statut:** Accepted (phase 2 livree).

**Decision:** une verification est un exercice ordinaire du catalogue portant
`verification: true`, quel que soit son mode. Son verdict -- reussi OU NON --
ecrit une evidence dans `evenement_progression` (type `VerificationEvaluated`,
identifiant `verification:<exercice>:<job>`), et n'accorde AUCUN XP. La bande
d'une competence est recalculee a chaque `GET /progres` par COUVERTURE : toutes
les verifications ouvertes de la competence reussies = « verifie », au moins une
= « en progression », tentee sans succes = « a consolider », rien de tente =
« pas encore verifie ». Aucun seuil, aucun poids de recence, aucune degradation.

**Raison:** trois choses tombent d'un coup. (1) `evenement_progression` EST deja
un journal en ajout seul avec un `type` libre et une charge JSON : une table
`mastery_evidence` aurait ajoute une ligne a `forget()`, un GRANT dans `VHome`,
et une table au compte de `test_suppression_couvre_toutes_les_tables`, pour
stocker exactement la meme chose. `domain-model.md` dit deja que le
`MasteryRecord` est derive et recalculable. (2) [mastery.md](mastery.md) demande
un modele hybride D dont les seuils et la recence sont « a valider par donnees ;
ne pas les choisir maintenant » -- une bande par couverture n'a AUCUN nombre a
choisir, et se durcit toute seule quand le contenu s'etoffe. (3) Ne rien afficher
de chiffre laisse la question ouverte « quel modele, seuils et recence » ouverte
sans qu'elle bloque : elle etait requise « avant affichage chiffre ».

Pas d'XP parce que l'XP compte de l'ACTIVITE ([D-007](#)) et la verification
mesure une CAPACITE. Les melanger rendrait la verification farmable et l'XP
indistinguable d'une note (invariants 1 et 4).

**Alternatives:** une table `mastery_evidence` dediee (rejetee : voir 1) ; un
score numerique de maitrise (rejetee : bloquee par une question ouverte, et un
chiffre non calibre se lit comme une note) ; un evenement `MasteryChanged`
(rejetee : un evenement pour une valeur derivee cree un second endroit ou la
verite peut diverger) ; des variantes parametrees a graine serveur (rejetee pour
maintenant : `publish_content.py` interdit `seed` et `cases` en projection, et
c'est une propriete qu'on garde) ; un defi chronometre (rejetee : imposerait de
definir une alternative accessible avant publication, [open-questions.md](open-questions.md)).

**Consequences:** AUCUNE migration, AUCUN changement dans `VHome` -- le GRANT
`SELECT, INSERT, DELETE ON evenement_progression` existant suffit, et
`test_postgres.py` le rejoue avec le role applicatif et ses seuls droits.
`GET /progres` passe a six allers-retours SQL. Une verification ne compte dans
aucun compteur de pratique (denominateur, competences pratiquees,
recommandation, export `main.c`) : le filtre est pose une seule fois dans
`exercices_pratique()`. Le rollback est de retirer `verification: true` du
contenu : les evidences restent en base, plus rien ne les lit.

## D-011 — L'identite choisie, facultative et invisible par defaut

**Statut:** Accepted (livree).

**Decision:** un compte peut choisir un nom d'affichage et un numero de
groupe (`forum_profil`, journal en ajout seul -- la derniere ligne fait foi),
chacun derriere sa propre case de visibilite. Rien n'apparait sans que son
porteur l'ait explicitement coche -- une seule exception : l'enseignant voit
le numero de groupe en tout temps, jamais le nom si l'etudiant ne l'a pas
affiche. Un nom affiche est signalable par la meme route que les messages ;
le moderateur peut l'effacer (une ligne de profil de plus, `par_moderateur`
a vrai), jamais le message ni le groupe qui l'accompagnent.

**Raison:** [D-008](#d-008--un-forum-dentraide-mvp-entre-la-phase-1-et-la-phase-2)
excluait tout pseudonyme persistant pour eviter de reconstituer une identite.
L'usage a montre un besoin different : un groupe de travail veut pouvoir se
reconnaitre d'un message a l'autre sans que ce soit impose ni permanent par
defaut. La difference avec l'identite que D-008 rejetait est le consentement
explicite et reversible : le nom n'est ni derive d'un claim OIDC, ni affiche
tant que le compte ne l'a pas choisi et coche.

**Alternatives:** un pseudonyme genere automatiquement (rejetee : imposerait
une identite sans consentement) ; le `preferred_username` de Rauthy affiche
directement (rejetee : c'est souvent le code d'acces de l'ecole, le publier
sans consentement explicite serait un consentement pris de travers -- il ne
fait que pre-remplir le champ).

**Consequences:** deux tables de plus (`forum_profil`, `forum_nom_signale`),
en ajout seul, couvertes par `forget()` -- le schema passe de trois a cinq
tables de forum. `CTESTER_FORUM_GROUPES` fixe optionnellement la liste des
groupes valides pour la session. Voir [social.md](social.md) et
[privacy.md](privacy.md).



## D-012 — Le chat en direct, un prefixe de cle de fil

**Statut:** Accepted (2026-09-09), retroactif — la fonctionnalite etait livree
avant d'etre decidee par ecrit.

**Decision:** un espace public a auteurs masques, ou tout est lisible par tous
les comptes du cours. Il n'a NI TABLE NI COLONNE a lui : `@chat:<exercice>` et
`@chat:general` sont des valeurs de plus dans `forum_message.exercise_id`, et
`est_chat()` est le seul predicat que la distinction coute — il sert a trois
endroits (forcer la visibilite, choisir le rendu de l'auteur, etiqueter
l'ecran). L'auteur y apparait sous un ALIAS tire d'un vocabulaire ferme, jamais
sous un pseudonyme tape. La mise a jour passe par une SONNETTE WebSocket qui ne
transporte aucun contenu : `{"t":"new"}`, et le client relance `GET /forum`.

**Raison:** un etudiant qui a peur du ridicule ne pose pas sa question. Le forum
repond a « je suis bloque » en prive ; il ne repond pas a « est-ce que je suis
le seul a ne pas comprendre ». Il fallait un endroit ou la question est publique
mais l'auteur ne l'est pas.

**Alternatives:** une table `chat_message` (rejetee : elle aurait duplique la
borne de texte, le quota, le signalement, la moderation, le masquage et
`forget()` — six regles dont celle qui derive est celle qui cesse de border) ;
une colonne `kind` (rejetee : un `WHERE` de plus a chaque requete du forum, et
celui qu'on oublie est celui qui melange les deux espaces) ; relayer le texte
par la socket (rejetee : il faudrait reimplementer `can_see()` par destinataire,
sur le chemin le plus difficile a eprouver).

**Consequences:** `@` ne peut apparaitre dans aucun identifiant du catalogue,
donc une cle de chat ne resout chez personne et ne devient jamais un chemin.
`forum_live` est un `dict` en memoire de processus — une raison de plus pour UN
SEUL WORKER. Le `-1` reste interdit sur une question, par le `WHERE` d'un INSERT
et non par l'interface.

## D-013 — Le pont Discord, par compte de service

**Statut:** Accepted (2026-09-09). Revise
[D-008](#d-008--un-forum-dentraide-mvp-entre-la-phase-1-et-la-phase-2).

**Decision:** relayer LES DEUX SENS entre le chat public de CTester et un salon
Discord du cours. Un message venu de Discord est ecrit sous un COMPTE DE SERVICE
`@discord:<id_discord>`, avec une ligne `forum_profile` portant le pseudo
Discord comme nom affiche. **Il n'existe aucune table Discord<->`sub`, et il ne
doit pas en exister.** Seul le chat PUBLIC traverse, dans les deux sens : une
question privee ne sort jamais, et le pont ne peut pas en ecrire une.

**Raison:** le cours a deja un Discord, et c'est la que la cohorte est. Un chat
vide reste vide : le probleme n'est pas l'interface, c'est la masse critique.
D-008 rejetait Discord comme ALTERNATIVE au forum — « hors du controle du cours,
transporte du code evalue, aucune suppression a la demande ». Aucun des trois ne
s'applique a un PONT : CTester reste la source de verite et la seule surface de
moderation, rien de prive ne traverse (donc pas de code d'exercice qu'un
etudiant aurait cru envoyer a son enseignant seul), et « Supprimer mes donnees »
continue d'effacer tout ce que CTester detient.

**Alternatives:** un simple lien vers le Discord (rejetee : ne resout pas la
masse critique, les deux endroits restent a surveiller — il est garde EN PLUS,
comme repli quand le pont est eteint) ; un webhook sortant seul (rejetee : les
reponses resteraient sur Discord, donc invisibles a qui a pose la question dans
CTester) ; une commande `/lier` associant un compte Discord a un `sub` (**rejetee
fermement** : elle donnerait a l'enseignant le moyen de relier un pseudonyme
CTester a un visage, c'est-a-dire exactement le pouvoir de desanonymisation que
`forum_identite()` refuse jusque dans la vue d'un moderateur) ; une gateway
Discord temps reel (rejetee pour l'instant : cent cinquante lignes et une
machine a etats, pour passer de 5 s a 0,2 s dans un cours dont le compteur de
presence sonde a 60 s — voir le `ponytail:` de `bot/bridge.py`).

**Consequences:** AUCUNE table, AUCUNE colonne, AUCUN GRANT nouveau. Le compte
de service traverse `forum_identite()`, `is_moderator()`, `freiner_forum()` et
`forget()` sans un `if` de plus, parce qu'il n'est qu'une chaine prefixee — la
meme propriete que `@chat:`. L'anti-boucle a deux moities et il faut les deux :
le bot saute les messages portant un `webhook_id`, `annoncer()` refuse un compte
`@discord:`. `allowed_mentions: {"parse": []}` est obligatoire sur le webhook,
sinon un etudiant tape `@everyone` dans CTester et reveille tout le serveur
Discord depuis une page ou il n'a jamais consenti a ca. Un conteneur de plus
(`ctester-bridge`), pas une unite systemd, en stdlib pure. Le pont s'eteint par
`ctester_discord_enabled: false`, et le rollback est cette ligne.
