# Pratique

La pratique est le parcours normal: lire une consigne, tenter, recevoir un verdict, diagnostiquer, corriger et reessayer. Elle accepte les aides autorisees, y compris IA si la politique le permet. Elle peut octroyer XP plafonne, progres visuel, eligibility d'accomplissement et evidence faible de maitrise.

Etats: `non commence -> en cours -> soumis -> feedback -> resolu|a reprendre`; `resolu` reste vrai pour l'historique. Les transitions doivent etre rattachees a une tentative serveur, pas au statut editable actuel du navigateur. Un exercice resolu peut etre revisite sans retirer la reussite.

## Fondation disponible

Pour un compte connecte, chaque job termine produit une `tentative_pratique`
immuable: identifiant de job, exercice, statut du verdict, total et reussites.
L'API associe le job au `sub` OIDC lors de la soumission, puis ecrit la tentative
lorsqu'elle lit le resultat du worker; un second sondage est sans effet grace a
l'unicite du job. `GET /pratique` retourne un resume par exercice. Cette
information de pratique ne constitue pas une verification de maitrise et ne
produit ni XP ni note.

Depuis la phase 1, cette meme lecture de verdict accorde l'XP d'une premiere reussite complete (voir [xp.md](xp.md)). La tentative reste ce qu'elle etait: une preuve de pratique, jamais une verification de maitrise.

Garde-fous: dedupliquer la premiere reussite d'une variante, diminuer la valeur de repetitions similaires, plafonner les boucles de soumission et separer les erreurs techniques des echecs pedagogiques. Le feedback ne divulgue pas les secrets existants du juge. Mesurer abandon, tentatives, aides et reprise; ne pas transformer le nombre d'erreurs en etiquette de faiblesse.
