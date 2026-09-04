"""Les routeurs : une frontière HTTP par domaine.

Un routeur ne fait QUE de la traduction : lire une requête, appeler `services/`
ou `etat.py`, rendre une réponse. Aucune règle métier n'a le droit de vivre ici
-- c'est ce qui garde `test_ctester.py` capable d'éprouver les règles sans
monter un serveur.
"""
