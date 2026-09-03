# Social et cooperation

## Livre : le forum d'entraide (MVP)

Un fil chronologique **par exercice publie**, prive aux comptes connectes.
C'est la seule fonction sociale qui existe, et elle est deliberement petite.
Voir [D-008](decisions.md) pour la decision datee et [D-009](decisions.md) pour
le rendu.

**Ce qu'il fait.** Lire un fil, publier un message, supprimer le sien, signaler
celui d'un autre. Pour des responsables explicitement configures : une vue des
signalements, et masquer/retablir un message avec action journalisee.

**Ce qu'il ne fait pas, et ne fera pas dans ce lot.** Aucun XP, succes, score,
classement, serie, vote, reaction, notification, message prive, temps reel,
profil public ni groupe-cours. Rien ici ne touche a la progression : les routes
du forum ne lisent ni n'ecrivent les trois tables de la Phase 1, et le `GRANT`
applicatif ne leur donne aucun privilege dessus.

**Identite.** « Vous » pour son auteur, « Participant » pour les autres,
« Equipe du cours » pour un moderateur. Ces trois mots sont derives par le
serveur ; le `sub` ne franchit jamais la frontiere HTTP, et il n'y a **pas de
pseudonyme persistant** — ce serait une identite, en plus petit. Deux messages du
meme etudiant ne sont pas recollables par le client.

**Immuabilite.** Un message ne s'edite pas apres publication : son auteur peut le
supprimer, un moderateur peut le masquer ou le retablir. Editer permettrait de
faire dire autre chose a quelqu'un, et rendrait un signalement illisible.

**La moderation est humaine, et l'interface le dit.** Il n'y a aucun detecteur de
solution — ce serait le detecteur que [D-002](decisions.md) rejette, deguise.
Les seules regles automatiques sont des bornes de forme : longueur maximale,
quota d'ecriture par compte, et un rendu assaini par allow-list fermee. Le reste
tient sur la charte, le bouton « Signaler » et quelqu'un qui lit.

**Eteint par defaut.** Sans au moins un `sub` de moderateur dans
`CTESTER_FORUM_MODERATORS`, le bouton n'apparait pas, `forum.js` n'est jamais
telecharge, et les routes repondent 503 en le disant. Un forum sans personne pour
le lire est un canal de partage de solutions avec une charte dessus.

### La charte, telle qu'elle s'affiche

Elle vit a UN seul endroit dans le code (`CHARTE` dans `app/forum.js`), et elle
apparait deux fois : dans la vue, en permanence, et en encart avant la premiere
publication de la session.

- Entraide conceptuelle : une question, une idee, ce qu'on observe, ce qu'on a
  deja essaye.
- Pas de solution complete, pas d'extrait de code, aucun fichier depose.
- Pas de capture d'ecran.
- Pas de lien vers une solution — un lien vers un corrige sera masque.
- Respect mutuel : on parle du probleme, jamais de la personne.
- Une solution qui passe ? La signaler plutot que d'y repondre.

### Conservation

Jusqu'a la **fermeture de decembre**, et pas au-dela : pas de saison, pas
d'archivage, pas de report entre sessions. `DELETE /moi` efface les messages, les
signalements et les actions de moderation **de cette personne**, dans la meme
instruction que le reste de son compte. Ce qu'un autre a ecrit reste : effacer
son compte n'efface pas la conversation des autres.

## Future, pas ce lot

Les objectifs de classe et defis cooperatifs restent en **Phase 4**. Un
`ClassObjective` definirait la cohorte, la periode, une mesure agregable, une
cible, une recompense cosmetique et une visibilite ; les contributions seraient
derivees d'evenements autorises et dedupliquees, et les tableaux publics
montreraient l'objectif collectif sans la contribution individuelle par defaut.
**Le groupe-cours est explicitement hors du lot MVP** : rien dans les trois
tables du forum ne porte de cohorte.

Mesurer participation, pression percue et signalements. Desactiver une mecanique
qui favorise le partage interdit ou l'humiliation.
