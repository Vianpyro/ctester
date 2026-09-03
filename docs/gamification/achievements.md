# Accomplissements

Les accomplissements reconnaissent des comportements ou jalons, sans etre une voie obligatoire. Une definition contient: id, titre, description accessible, categorie, visibilite (`public|prive|secret`), critere versionne, repetable ou non, et recompense eventuelle. `UserAchievement` conserve date, source/evidence et version de definition.

Categories recommandees: apprentissage (premiere verification), perseverance (reprise constructive), exploration (contexte optionnel), qualite lorsque le juge peut l'etablir, cooperation et collection. Eviter «zero erreur» comme norme: une distinction de premier essai ne doit pas devaloriser le debogage.

**Phase 1:** cinq definitions dans `app/politique.py`, toutes privees, non obligatoires et derivees de compteurs que le serveur constate lui-meme (`reussites`, `competences`). Aucune n'est un « zero erreur ». `succes_obtenu` a pour cle primaire `(utilisateur, succes_id)`: un rejeu ne cree qu'une obtention. L'interface affiche titre, description et date en texte — jamais une couleur ou une icone seule. Un identifiant stocke dont la politique ne porte plus la definition cesse simplement de s'afficher; il n'est pas efface.

Un secret cache le critere avant obtention, jamais une obligation ou un avantage d'apprentissage. Les criteres sont evalues cote serveur a partir d'evenements fiables. Les doublons et evenements rejoues ne creent qu'une obtention. Les taux de deblocage et ecarts d'accessibilite sont suivis avant d'ajouter de la rarete.
