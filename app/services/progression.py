"""La progression : XP, niveau, compétences pratiquées, recommandation.

RIEN N'EST MIS EN CACHE EN BASE. Tout est recalculé à chaque lecture depuis
trois tables de faits en ajout seul et le catalogue public. Il n'y a donc pas de
projection à reconstruire, et changer la politique ne demande pas de migration.

CE QUI PRODUIT DE LA VALEUR, C'EST LE SERVEUR EN LISANT LE VERDICT, jamais le
navigateur. Une seule règle : la PREMIÈRE réussite complète d'un exercice
publié. Un échec ne rapporte rien, refaire le même exercice non plus -- les deux
tiennent par la même chose, l'identifiant d'événement `reussite:<exercice>` dont
la clé primaire refuse le doublon.
"""

import etat
import politique
from services.catalogue import load_tps


# --- Progression (phase 1) --------------------------------------------------
# XP, niveau, compétences pratiquées et recommandation, pour les comptes
# connectés SEULEMENT. Rien ici ne touche au verdict, au bac à sable, au
# catalogue public ni au parcours anonyme : ce sont des lectures de faits que
# le serveur a lui-même écrits, plus les métadonnées publiques du catalogue.
#
# LES CHIFFRES SONT DANS politique.py. Aucune valeur d'équilibrage n'a le droit
# d'apparaître dans ce fichier : piloter le semestre doit rester une édition de
# la politique, pas une relecture de l'API.

MAX_SKILLS = 40


def exercise_facts(states, practice):
    """(pratiqués, réussis) : deux ensembles d'identifiants d'exercice.

    Les deux sources sont fusionnées. `tentative_pratique` sait qu'un job a été
    jugé, `etat_exercice` sait où en est l'exercice ; un compte antérieur aux
    tentatives n'a que la seconde et doit quand même compter.
    """
    touched, solved = set(), set()
    for row in states or ():
        exercise = row.get("exercice_id")
        if not exercise:
            continue
        touched.add(exercise)
        if row.get("statut") == "valide":
            solved.add(exercise)
    for row in practice or ():
        exercise = row.get("exercice_id")
        if exercise:
            touched.add(exercise)
    return touched, solved


def skills_view(entries, touched, solved):
    """[{id, total, pratiques, reussis}] dans l'ordre du cours.

    « PRATIQUÉE », JAMAIS « MAÎTRISÉE ». Ce compteur dit qu'un exercice
    portant cette compétence a été soumis et jugé, rien de plus : le juge est en
    libre service et aucune vérification indépendante n'existe en phase 1.
    L'écart entre les deux est le sujet entier de docs/gamification/mastery.md,
    et le jour où on l'oublie dans un libellé, on a promis une note.
    """
    order, table = [], {}
    for entry in entries:
        for skill in (entry.get("learning") or {}).get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "pratiques": 0, "reussis": 0}
                order.append(row)
            row["total"] += 1
            row["pratiques"] += int(entry["id"] in touched)
            row["reussis"] += int(entry["id"] in solved)
    return order[:MAX_SKILLS]


def practised_skills(entries, touched):
    """Les compétences qu'un exercice touché a fait pratiquer."""
    skills = set()
    for entry in entries:
        if entry["id"] in touched:
            skills.update((entry.get("learning") or {}).get("skills") or ())
    return skills


def recommander(entries, touched, solved):
    """Le prochain exercice à ouvrir, ou None. DÉTERMINISTE : l'ordre du cours.

    D'abord un exercice publié non réussi qui reprend une compétence déjà
    pratiquée -- consolider passe avant découvrir ; sinon le premier non réussi ;
    sinon rien, et la page le dit plutôt que d'inventer une suite.
    """
    known = practised_skills(entries, touched)
    remaining = [e for e in entries if e["id"] not in solved]
    for entry in remaining:
        for skill in (entry.get("learning") or {}).get("skills") or ():
            if skill in known:
                return {"exercice_id": entry["id"], "competence": skill}
    if remaining:
        return {"exercice_id": remaining[0]["id"], "competence": None}
    return None


def progression_facts(user):
    """Les compteurs dont dépendent les succès. None si la base ne répond pas.

    Bornés au catalogue publié : un exercice retiré ne doit plus rien débloquer.
    """
    states = etat.read_states(user)
    practice = etat.read_practice_summary(user)
    if states is None or practice is None:
        return None
    entries = load_tps()
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in entries}
    return {"reussites": len(solved & published),
            "competences": len(practised_skills(entries, touched))}


def recompenser(user, entry, job_id):
    """Une PREMIÈRE réussite complète -> au plus une attribution d'XP.

    Appelée par le serveur quand il lit un verdict complet, jamais par le
    navigateur. Trois règles y tiennent d'un coup :

    - un échec ne rapporte rien : l'appelant n'appelle que sur `solved` ;
    - refaire le même exercice ne rapporte rien -- l'identifiant d'événement est
      « reussite:<exercice> » et sa clé primaire refuse le doublon ;
    - un sondage rejoué ne rapporte rien : même identifiant, même refus.

    Rien ne se célèbre quand `grant_first_solve` rend None -- déjà récompensé,
    ou base muette. Les deux veulent dire « il n'y a pas de fait neuf ».
    """
    learning = entry.get("learning") or {}
    event_id = "reussite:" + entry["id"]
    granted = etat.grant_first_solve(
        user, entry["id"], event_id, politique.xp_reussite(learning),
        "première réussite de l'exercice", politique.VERSION,
        {"job": job_id, "difficulte": learning.get("difficulty", "")},
        politique.plafond_quotidien())
    if granted is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        etat.unlock(user, politique.succes_atteints(facts), event_id,
                    politique.VERSION)


def progress_payload(entries, facts, states, practice):
    """Le contrat de GET /progres : borné, dérivé, et sans rien de secret.

    Ni code soumis, ni détail de verdict, ni chemin de tests : des compteurs,
    des identifiants publics du catalogue, et les libellés de succès que porte
    la politique. `politique` voyage avec, pour qu'un écran sache de quelle
    version des chiffres il parle.
    """
    touched, solved = exercise_facts(states, practice)
    return {
        "politique": politique.VERSION,
        "xp": facts["xp"],
        "niveau": politique.niveau(facts["xp"]),
        "exercices": {
            "total": len(entries),
            "pratiques": sum(1 for e in entries if e["id"] in touched),
            "reussis": sum(1 for e in entries if e["id"] in solved),
        },
        "competences": skills_view(entries, touched, solved),
        # Un identifiant stocké dont la politique ne connaît plus la définition
        # ne s'affiche pas -- il n'est pas perdu pour autant, il reste en base.
        "succes": [{"id": row["id"],
                    "titre": politique.SUCCES[row["id"]]["titre"],
                    "description": politique.SUCCES[row["id"]]["description"],
                    "obtenu_le": row["obtenu_le"]}
                   for row in facts["succes"] if row["id"] in politique.SUCCES],
        "suivant": recommander(entries, touched, solved),
        # La consultation/export des attributions, déjà bornée par etat.py.
        "transactions": facts["transactions"],
    }
