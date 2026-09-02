# UX et architecture d'information

Le tableau de bord connecte privilegie: (1) ce que j'ai appris, (2) ce qui est a consolider, (3) l'action suivante. Il contient niveau/XP en second plan, une progression de skills lisible, «pratiquer X» et accomplissements. Classe et leaderboard restent une destination distincte, jamais une modalite par defaut.

Dans l'exercice, afficher objectif/skill/contexte, politique d'aide, statut `pratique` ou `verification`, feedback et action suivante. Avant une verification, expliquer l'independance, le temps s'il existe, les accommodations et ce qui sera enregistre. Apres, afficher resultat, confiance compréhensible et recommandations; pas de couleur rouge sans texte ni de comparaison a autrui.

L'integration peut commencer par un onglet «Mes progres» uniquement pour comptes OIDC, sans regresser le flux anonyme ni alourdir l'editeur. Toute UI nouvelle requiert tests JS, et les donnees venant des tests/etudiants restent rendues avec `textContent` comme le client actuel.
