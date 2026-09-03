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
moderee par une personne a 27 etudiants.

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
« Participant » aux autres, « Equipe du cours » pour un moderateur. Ces trois
mots sont derives par le serveur a partir du `sub` ; le `sub` lui-meme ne franchit
jamais la frontiere HTTP, et il n'y a pas de pseudonyme persistant — ce serait
une identite, en plus petit. Deux messages du meme etudiant ne sont pas
recollables par le client.

**Alternatives:** attendre la Phase 4 (rejetee : rien avant decembre) ; un canal
externe type Discord (rejetee : hors du controle du cours, transporte du code
evalue, et aucune suppression a la demande) ; recompenser la participation en XP
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
version et servis depuis cette origine** (`app/vendor/`, jamais un CDN). Le HTML
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
`script-src 'self'` plus le hachage du script de theme inline, `frame-ancestors
'none'`), elle est calculee sur le corps servi pour rester en phase avec la page,
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
au nom de fichier, a la liste blanche de `do_GET` et a `forum.js` : c'est le prix
volontaire de l'epinglage.

## D-006 — Contexte est orthogonal a la competence

**Statut:** Accepted.

**Decision:** preferer un contexte d'ingenierie configurable sans changer la competence evaluee.

**Raison:** donner du sens sans favoriser un parcours d'etude particulier.

**Alternatives:** pistes par programme fixes (rejetee).

**Consequences:** revue d'equivalence de variantes et preferences reversibles.
