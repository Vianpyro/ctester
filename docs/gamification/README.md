# Gamification et apprentissage

## Statut et lecture

Cette documentation est la source de verite de conception pour l'evolution de ctester. Elle est ecrite pour **TCH009, automne 2026**; les faits de cours viennent du mandat, tandis que les donnees de sondage sont de la recherche de cohorte et non des verites permanentes.

**Exigences confirmees.** Le systeme soutient l'apprentissage du C de debutants, ne modifie jamais les notes officielles, distingue XP, pratique et maitrise, rend le classe optionnel, et ne fonde pas son integrite sur un detecteur d'IA.

**Decision de conception acceptee.** La boucle centrale est `contexte -> pratique -> verification independante -> maitrise verifiee -> recommandation`. La gamification l'entoure; elle ne la remplace pas.

Les chiffres, seuils et formules marques **PROVISOIRE** sont configurables et ne doivent pas etre figees dans du code. Les choix restant a valider sont dans [open-questions.md](open-questions.md); leur raison d'etre est consignée dans [decisions.md](decisions.md).

## Architecture actuelle confirmee

ctester est un juge C sans framework: `app/app.py` est l'API HTTP, `app/index.html` le client, `runner.py` le worker de l'hote, et les scripts de build executent le code dans un conteneur jetable gVisor. Le tier web n'a ni Docker ni les tests secrets. Les exercices exposes par `tps.json` sont quiz, programme I/O ou module Unity. Un compte OIDC/Postgres est facultatif; il conserve seulement brouillons et l'etat `essaye|valide`, rattaches a un `sub` opaque. L'anonyme demeure le parcours par defaut.

Consequences: un futur systeme doit etre facultatif comme la connexion, ne jamais placer de reponses/tests dans `app/`, et ne doit pas interpreter le verdict actuel comme une preuve d'integrite: le README existant documente qu'un verdict peut etre fabrique dans certains modes. Toute donnee de progression qui compte doit donc etre produite par un flux serveur explicite et traceable.

## Carte de conception

| Besoin | Source normative |
| --- | --- |
| Principes, limites et invariants | [principles.md](principles.md), [invariants.md](invariants.md) |
| Pedagogie, pratiques et maitrise | [practice.md](practice.md), [mastery.md](mastery.md), [skills.md](skills.md) |
| Progression et motivation | [xp.md](xp.md), [levels.md](levels.md), [achievements.md](achievements.md) |
| Contenu et IA | [content-model.md](content-model.md), [contextualized-content.md](contextualized-content.md), [ai-and-integrity.md](ai-and-integrity.md) |
| Donnees et integration | [domain-model.md](domain-model.md), [event-model.md](event-model.md) |
| Experience, protection et exploitation | [ui-ux.md](ui-ux.md), [privacy.md](privacy.md), [accessibility.md](accessibility.md), [analytics.md](analytics.md) |
| Fonctions futures | [social.md](social.md), [ranked.md](ranked.md), [leaderboards.md](leaderboards.md), [seasons.md](seasons.md), [roadmap.md](roadmap.md) |

Avant toute implementation, suivre [roadmap.md](roadmap.md), faire une migration versionnee, definir des contrats API et ajouter les tests de confidentialite/degradation. Rien dans ces documents n'autorise un changement de notation ou la collecte de PII.
