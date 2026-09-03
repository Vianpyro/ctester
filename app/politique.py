#!/usr/bin/env python3
"""ctester -- la politique de gamification : des CHIFFRES, pas de la logique.

TOUT CE QUI SE RÈGLE VIT DANS `POLITIQUE`, en haut, et rien d'autre dans ce
dépôt ne contient un montant d'XP, un seuil de niveau ou un libellé de succès.
C'est la raison d'être du fichier : piloter la première session veut dire
changer ces nombres, et il ne doit jamais falloir relire `app.py` pour le
faire. Les fonctions en dessous ne font que LIRE cette table.

CES VALEURS SONT PROVISOIRES. Elles n'ont pas été observées sur une cohorte ;
elles sont volontairement sobres, et `version` les date. Une transaction et un
succès enregistrés portent la version qui les a produits : changer un montant
ne réécrit donc pas l'histoire, il ouvre une nouvelle page.

CE QUE L'XP N'EST PAS : une note, une aptitude, une maîtrise vérifiée. C'est un
compteur d'activité de pratique, et l'interface le dit à l'écran. Le seul fait
qui en produit est une PREMIÈRE réussite complète d'un exercice publié,
constatée par le serveur en lisant le verdict du worker -- jamais un échec,
jamais une répétition, jamais une déclaration du navigateur.
"""

POLITIQUE = {
    "version": "pilote-1",

    # Ce que vaut la première réussite complète d'un exercice, selon la
    # difficulté annoncée par ses métadonnées publiques `learning`. Un exercice
    # sans difficulté déclarée prend `defaut` : ne rien donner punirait
    # l'étudiant pour une métadonnée manquante côté enseignant.
    "xp": {
        "intro": 10,
        "foundation": 15,
        "intermediate": 20,
        "advanced": 30,
        "defaut": 10,
    },

    # PLAFOND PAR JOUR, en défense de profondeur seulement. La règle « une
    # seule fois par exercice » rend déjà le farming impossible ; ce plafond
    # existe pour qu'un catalogue soudain plus généreux, ou un import massif,
    # ne fabrique pas un solde absurde en une soirée. Il ne bloque JAMAIS la
    # pratique : au-delà, l'exercice se corrige normalement, il ne rapporte
    # simplement plus rien ce jour-là.
    "plafond_quotidien": 100,

    # XP cumulé requis pour chaque niveau, du niveau 1 au dernier. Pas de
    # titres : « expert » sur un compteur d'activité laisserait croire à une
    # qualification, ce que ce nombre n'est pas.
    "niveaux": [0, 30, 80, 150, 250, 400, 600],

    # PEU NOMBREUX, PRIVÉS, NON OBLIGATOIRES, et dérivés de faits que le
    # serveur constate lui-même. Aucun « zéro erreur » : déboguer est le
    # travail, pas un échec. `sur` nomme le fait compté, `seuil` la valeur à
    # atteindre -- une définition de plus est une ligne de plus, pas du code.
    "succes": [
        {"id": "premiere-reussite", "sur": "reussites", "seuil": 1,
         "titre": "Premier exercice réussi",
         "description": "Tu as fait passer tous les tests d'un exercice."},
        {"id": "cinq-reussites", "sur": "reussites", "seuil": 5,
         "titre": "Cinq exercices réussis",
         "description": "Cinq exercices différents, tous tests passés."},
        {"id": "dix-reussites", "sur": "reussites", "seuil": 10,
         "titre": "Dix exercices réussis",
         "description": "Dix exercices différents, tous tests passés."},
        {"id": "premiere-competence", "sur": "competences", "seuil": 1,
         "titre": "Première compétence pratiquée",
         "description": "Tu as pratiqué un exercice qui annonce une compétence."},
        {"id": "trois-competences", "sur": "competences", "seuil": 3,
         "titre": "Trois compétences pratiquées",
         "description": "Ta pratique touche trois compétences différentes."},
    ],
}

VERSION = POLITIQUE["version"]

# Ce que l'API renvoie avec un succès obtenu : la définition est ici, la date
# et la version dans la base. Un identifiant stocké dont la définition a disparu
# n'est pas une erreur -- il ne s'affiche simplement plus.
SUCCES = {s["id"]: s for s in POLITIQUE["succes"]}


def xp_reussite(learning):
    """L'XP d'une première réussite, d'après les métadonnées publiques du TP."""
    table = POLITIQUE["xp"]
    difficulte = (learning or {}).get("difficulty")
    return int(table.get(difficulte, table["defaut"]))


def plafond_quotidien():
    return int(POLITIQUE["plafond_quotidien"])


def niveau(xp):
    """{rang, depuis, prochain, restant} pour ce solde. `prochain` None au bout.

    Le rang est 1-based : personne n'est « niveau 0 ». `restant` est ce qu'il
    faut encore, jamais un pourcentage -- l'interface a besoin des deux nombres
    pour écrire une phrase, et une barre sans phrase ne se lit pas à voix haute.
    """
    seuils = POLITIQUE["niveaux"]
    xp = max(int(xp or 0), 0)
    rang = 1
    for n, seuil in enumerate(seuils, 1):
        if xp >= seuil:
            rang = n
    depuis = seuils[rang - 1]
    prochain = seuils[rang] if rang < len(seuils) else None
    return {
        "rang": rang,
        "depuis": depuis,
        "prochain": prochain,
        "restant": (prochain - xp) if prochain is not None else 0,
    }


def succes_atteints(faits):
    """Les identifiants de succès que ces faits débloquent, dans l'ordre déclaré.

    `faits` est un dictionnaire de compteurs ({"reussites": 3, ...}). Un fait
    absent vaut zéro : ajouter un critère à la politique ne peut donc pas faire
    lever sur un appelant plus ancien.
    """
    return [s["id"] for s in POLITIQUE["succes"]
            if int((faits or {}).get(s["sur"], 0)) >= s["seuil"]]
