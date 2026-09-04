"""La logique, sans HTTP.

Rien ici ne connaît `Request` ni `Response`. Ce sont les fonctions qui vivaient
au niveau module de l'ancien `app.py`, déplacées telles quelles : elles sont
éprouvées par appel direct, pas par un client de test.
"""
