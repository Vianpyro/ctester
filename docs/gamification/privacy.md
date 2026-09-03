# Vie privee

Par defaut, les prefererences, tentatives, mastery, XP, recommandations et historique sont prives de l'utilisateur et des roles pedagogiques autorises. Le profil public et le classement demandent un consentement explicite, reversible; ils utilisent un pseudonyme configurable et exposent seulement les champs annonces.

**Forum d'entraide (MVP).** Un message est **visible des autres comptes
connectes** — c'est la seule donnee de ce systeme qui ne soit pas privee, et
l'interface le dit avant qu'on publie. Ce qui est stocke, et rien d'autre: le
`sub` opaque de l'auteur, l'identifiant du message, l'exercice PUBLIC, le texte
sous sa forme source, les dates, l'etat visible/masque, l'auteur d'un
signalement, et les actions de moderation. **Aucun `sub` ne traverse la
frontiere HTTP**: aux etudiants, une publication s'annonce « Vous », « Participant
» ou « Equipe du cours », trois mots derives par le serveur. Pas de pseudonyme
persistant — ce serait une identite, en plus petit — donc deux messages du meme
etudiant ne sont pas recollables par le client. Les messages masques et les
signalements sont invisibles aux etudiants ordinaires; un moderateur ne voit que
le minimum utile a la moderation (texte, exercice, date, etat, NOMBRE de
signalements), jamais qui a signale, jamais qui a ecrit, jamais du code soumis,
un verdict detaille ou une donnee de progression. Conservation jusqu'a la
fermeture de decembre, sans archivage ni report. `DELETE /moi` efface les
messages, signalements et actions de moderation **de cette personne**; ce qu'un
autre a ecrit reste, et un signalement laisse sur un message supprime
n'apparait plus nulle part.

Donnees minimales: `sub` OIDC opaque, donnees de progression, versions de contenu/politique et dates. Ne pas stocker nom, courriel, numero etudiant, jeton OIDC, prompt IA ou code complet pour analytics sans nouvelle base legale et politique. Le code soumis suit deja la politique de brouillon/etat existante; la nouvelle retention doit etre definie avant ecriture.

Offrir consultation/export et suppression de toutes les donnees de gamification avec le mecanisme «oublier» existant ou une extension atomique. **Phase 1:** `GET /progres` est la consultation et l'export — une reponse JSON authentifiee, incluant les attributions d'XP bornees; `DELETE /moi` efface les neuf tables en UNE instruction, parce qu'une par table en autocommit laisserait quelqu'un a moitie efface si la connexion tombe au milieu. Un test lit `schema.sql` et `etat.py` pour qu'une table ajoutee sans etre effacee fasse echouer la suite. Expliquer ce qui ne peut pas etre retire d'agregats anonymises. Les enseignants voient le minimum necessaire a l'accompagnement; ils n'utilisent pas ces donnees pour une note sans une autorisation institutionnelle distincte. Journaliser les acces admin.
