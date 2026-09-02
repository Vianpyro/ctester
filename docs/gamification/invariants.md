# Invariants d'implementation

Ces assertions doivent etre protegees par revue, tests et contrats API.

1. XP, niveau, maitrise, note officielle et rating sont des domaines distincts.
2. Aucun endpoint, affichage ou export de gamification ne produit ou ne modifie une note officielle.
3. Seule une tentative de verification eligible peut augmenter la maitrise verifiee.
4. Une tentative de pratique conserve sa valeur pedagogique mais n'est pas assimilee a une verification.
5. Le detecteur d'IA n'est pas un pre-requis ni une source autoritaire de sanction ou de maitrise.
6. La repetition d'un contenu trivial a rendement decroissant ne peut pas dominer XP, distinctions ou classement.
7. Le mode classe, les profils publics et le partage social sont des consentements reversibles.
8. Aucun test secret, reponse attendue, chemin de tests ou code d'enseignant ne traverse le tier web.
9. Un contexte, une cosmetique ou un secret n'est jamais une condition de reussite academique.
10. Une personne sans compte, sans competition ou avec besoin d'accessibilite peut accomplir le parcours pedagogique principal.
11. Les transitions a valeur (XP, verification, succes) sont idempotentes et auditees.
12. Les valeurs d'equilibrage sont configurees/versionnees, non encodees implicitement.
