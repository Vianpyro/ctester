"""La progression : XP, niveau, compétences pratiquées, recommandation.

RIEN N'EST MIS EN CACHE EN BASE. Tout est recalculé à chaque lecture depuis
trois tables de faits en ajout seul et le catalogue public. Il n'y a donc pas de
projection à reconstruire, et changer la politique ne demande pas de migration.

CE QUI PRODUIT DE LA VALEUR, C'EST LE SERVEUR EN LISANT LE VERDICT, jamais le
navigateur. Une seule règle : la PREMIÈRE réussite complète d'un exercice
publié. Un échec ne rapporte rien, refaire le même exercice non plus -- les deux
tiennent par la même chose, l'identifiant d'événement `reussite:<exercice>` dont
la clé primaire refuse le doublon.

PHASE 2 -- LA MAÎTRISE VÉRIFIÉE. Un exercice marqué `verification` dans le
catalogue est d'un autre domaine : il n'accorde AUCUN XP et ne compte dans
aucun compteur de pratique. Son verdict écrit une évidence dans le même journal
en ajout seul (`evenement_progression`, type `VerificationEvaluated`), et les
bandes par compétence en sont DÉRIVÉES à chaque lecture -- il n'y a pas de table
de maîtrise, pas plus qu'il n'y a de table de solde.
"""

import etat
import politique
from services.catalogue import exercices_ouverts


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

# Le type d'événement d'une évidence de maîtrise. `evenement_progression` porte
# déjà `ExerciceReussi` : le journal accepte un type de plus sans migration.
VERIFICATION = "VerificationEvaluated"


def exercices_pratique(entries):
    """Le catalogue ouvert MOINS les vérifications. Le seul filtre, défini ici.

    Une vérification n'est pas de la pratique (invariant 4) : la compter dans
    « exercices pratiqués », dans les compétences pratiquées ou dans la
    recommandation mélangerait les deux domaines dans les trois écrans à la
    fois. Un seul filtre, à un seul endroit, et tous les compteurs le
    traversent.
    """
    return [entry for entry in entries if not entry.get("verification")]


def verifications(entries):
    """Les vérifications OUVERTES du catalogue, dans l'ordre du cours."""
    return [entry for entry in entries if entry.get("verification")]


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
    libre service. La maîtrise est l'autre axe, dérivé des seules vérifications
    (`maitrise_view`), et les deux ne se rejoignent JAMAIS dans un même chiffre.
    L'écart entre les deux est le sujet entier de docs/gamification/mastery.md,
    et le jour où on l'oublie dans un libellé, on a promis une note.

    `entries` est déjà filtré par `exercices_pratique` chez l'appelant : une
    vérification n'ajoute rien à un dénominateur de pratique.
    """
    order, table = [], {}
    for entry in entries:
        for skill in entry.get("skills") or ():
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
            skills.update(entry.get("skills") or ())
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
        for skill in entry.get("skills") or ():
            if skill in known:
                return {"exercice_id": entry["id"], "competence": skill}
    if remaining:
        return {"exercice_id": remaining[0]["id"], "competence": None}
    return None


# --- Maîtrise vérifiée (phase 2) -------------------------------------------
# La pratique est une évidence faible, une vérification une évidence forte.
# Ce qui est stocké est la TENTATIVE ; la bande est dérivée à la lecture, donc
# resserrer la règle demain s'applique aussi aux évidences déjà en base.


def dernieres_tentatives(evidences):
    """{exercice_id: réussi} -- la DERNIÈRE tentative de chaque vérification.

    `evidences` arrive du plus récent au plus ancien : le premier vu par
    exercice fait foi. Les précédentes restent en base -- les réessais restent
    historiques, ils ne pèsent simplement plus sur la bande affichée.
    """
    dernier = {}
    for row in evidences or ():
        exercise = (row or {}).get("exercice_id")
        if exercise and exercise not in dernier:
            dernier[exercise] = bool((row.get("charge") or {}).get("reussi"))
    return dernier


def verifications_reussies(evidences):
    """Les vérifications réussies AU MOINS UNE FOIS, tentatives comprises.

    Distinct de `dernieres_tentatives` exprès : un succès ne se retire pas, donc
    ce qu'il compte doit être monotone. Un réessai raté fait redescendre une
    bande -- il ne doit pas défaire un succès déjà obtenu.
    """
    return {(row or {})["exercice_id"] for row in evidences or ()
            if (row or {}).get("exercice_id")
            and ((row or {}).get("charge") or {}).get("reussi")}


def maitrise_view(entries, evidences):
    """[{id, bande, reussies, tentees, total}] par compétence VÉRIFIABLE.

    Une compétence n'y figure que si une vérification ouverte la porte : dire
    « pas encore vérifié » d'une compétence qu'aucune activité ne vérifie serait
    reprocher à l'étudiant une lacune du contenu.

    `total` compte les vérifications ouvertes de la compétence, pas les
    tentatives : c'est ce qui fait que « vérifié » se durcit tout seul quand le
    contenu s'étoffe, sans qu'un seuil existe nulle part.
    """
    dernier = dernieres_tentatives(evidences)
    order, table = [], {}
    for entry in verifications(entries):
        tentative = dernier.get(entry["id"])
        for skill in entry.get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "tentees": 0, "reussies": 0}
                order.append(row)
            row["total"] += 1
            row["tentees"] += int(tentative is not None)
            row["reussies"] += int(tentative is True)
    for row in order:
        row["bande"] = politique.bande_maitrise(row["reussies"], row["tentees"],
                                                row["total"])
    return order[:MAX_SKILLS]


def progression_facts(user):
    """Les compteurs dont dépendent les succès. None si la base ne répond pas.

    Bornés au catalogue publié : un exercice retiré ne doit plus rien débloquer.
    """
    states = etat.read_states(user)
    practice = etat.read_practice_summary(user)
    evidences = etat.read_events(user, VERIFICATION)
    if states is None or practice is None or evidences is None:
        return None
    entries = exercices_ouverts()
    pratique = exercices_pratique(entries)
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in pratique}
    verifiables = {e["id"] for e in verifications(entries)}
    return {"reussites": len(solved & published),
            "competences": len(practised_skills(pratique, touched)),
            "verifications": len(verifications_reussies(evidences) & verifiables)}


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
    event_id = "reussite:" + entry["id"]
    granted = etat.grant_first_solve(
        user, entry["id"], event_id, politique.xp_reussite(entry),
        "première réussite de l'exercice", politique.VERSION,
        {"job": job_id, "difficulte": entry.get("difficulty") or ""},
        politique.plafond_quotidien())
    if granted is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        etat.unlock(user, politique.succes_atteints(facts), event_id,
                    politique.VERSION)


def enregistrer_verification(user, entry, job_id, reussi):
    """Un verdict de vérification -> une évidence, réussie OU NON.

    Écrite dans les deux cas, et c'est le point : sans la trace d'un échec, la
    bande « à consolider » n'existerait pas et une compétence tentée sans succès
    serait indistinguable d'une compétence jamais abordée.

    AUCUN XP N'EST ACCORDÉ ICI, jamais. Une vérification mesure une capacité ;
    l'XP compte une activité de pratique. Les mélanger rendrait la vérification
    farmable et l'XP indistinguable d'une note (invariant 1).

    Rien à recalculer quand l'évidence existait déjà -- même sondage rejoué,
    même identifiant, même refus.
    """
    ecrit = etat.record_event(
        user, "verification:%s:%s" % (entry["id"], job_id), VERIFICATION,
        entry["id"], politique.VERSION, {"job": job_id, "reussi": bool(reussi)})
    if ecrit is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        etat.unlock(user, politique.succes_atteints(facts),
                    "verification:" + entry["id"], politique.VERSION)


def progress_payload(entries, facts, states, practice, evidences):
    """Le contrat de GET /progres : borné, dérivé, et sans rien de secret.

    Ni code soumis, ni détail de verdict, ni chemin de tests : des compteurs,
    des identifiants publics du catalogue, et les libellés de succès que porte
    la politique. `politique` voyage avec, pour qu'un écran sache de quelle
    version des chiffres il parle.
    """
    touched, solved = exercise_facts(states, practice)
    pratique = exercices_pratique(entries)
    return {
        "politique": politique.VERSION,
        "xp": facts["xp"],
        "niveau": politique.niveau(facts["xp"]),
        "exercices": {
            "total": len(pratique),
            "pratiques": sum(1 for e in pratique if e["id"] in touched),
            "reussis": sum(1 for e in pratique if e["id"] in solved),
        },
        "competences": skills_view(pratique, touched, solved),
        # Les bandes voyagent UNE fois, en légende : la page doit pouvoir dire
        # ce que « à consolider » veut dire sans le réécrire de son côté.
        "maitrise": {
            "bandes": [dict(bande) for bande in politique.BANDES.values()],
            "competences": maitrise_view(entries, evidences),
        },
        # Un identifiant stocké dont la politique ne connaît plus la définition
        # ne s'affiche pas -- il n'est pas perdu pour autant, il reste en base.
        "succes": [{"id": row["id"],
                    "titre": politique.SUCCES[row["id"]]["titre"],
                    "description": politique.SUCCES[row["id"]]["description"],
                    "obtenu_le": row["obtenu_le"]}
                   for row in facts["succes"] if row["id"] in politique.SUCCES],
        "suivant": recommander(pratique, touched, solved),
        # La consultation/export des attributions, déjà bornée par etat.py.
        "transactions": facts["transactions"],
    }
