"""Le forum d'entraide : bornes, identité choisie, et vue sans `sub`.

AUCUN `sub` NE FRANCHIT LA FRONTIÈRE HTTP. `forum_vue()` traduit l'auteur en
« Vous » / « Enseignant » / le nom que l'étudiant a CHOISI d'afficher, sinon
« Participant ». C'est la propriété la plus importante de ce module, et un test
l'éprouve en cherchant les `sub` dans la charge JSON -- y compris dans la vue la
plus renseignée, celle d'un modérateur.

LE SERVEUR NE REND RIEN ET N'ASSAINIT RIEN, IL BORNE. Les messages sont stockés
sous leur forme SOURCE ; c'est `forum.js` qui échappe `<` avant l'analyse
Markdown puis passe la sortie dans DOMPurify. Assainir ici figerait la règle au
moment de l'écriture, alors qu'une règle resserrée plus tard doit s'appliquer
aux messages déjà en base.
"""

import config
from security import is_moderator, oidc_enabled


# --- Forum d'entraide (MVP) -------------------------------------------------
# UN fil chronologique par exercice PUBLIÉ, privé aux comptes connectés. Rien
# ici ne produit de valeur de jeu : pas d'XP, pas de succès, pas de compteur, et
# la progression de la phase 1 n'est ni lue ni écrite depuis ces routes.
#
# LA MODÉRATION EST HUMAINE, ET ON NE PRÉTEND PAS L'INVERSE. Il n'y a pas de
# détecteur de solution : les seules règles automatiques sont des bornes
# (longueur, quota) et le refus des liens, qui est une règle de la charte -- pas
# un jugement sur le contenu. Tout le reste passe par un signalement et par
# quelqu'un qui lit.


def forum_enabled():
    """True quand le forum peut être offert. FAUX par défaut.

    Il faut la connexion (donc l'émetteur, le client et la base) ET au moins un
    modérateur configuré. La seconde condition n'est pas cosmétique : le
    signalement doit aboutir chez quelqu'un, sinon on offre un canal public sans
    recours.
    """
    return oidc_enabled() and bool(config.FORUM_MODERATORS)


def forum_texte(brut):
    """(texte, message d'erreur) -- du Markdown restreint, court, et rien d'autre.

    CE QUI EST STOCKÉ EST LA SOURCE, PAS DU HTML. Le serveur ne rend rien et
    n'assainit rien : il borne. Le rendu -- Markdown puis assainisseur -- se
    fait au moment de l'AFFICHAGE, à chaque affichage, dans `forum.js`. Assainir
    à l'écriture seulement serait la mauvaise moitié du travail : une règle
    resserrée plus tard ne s'appliquerait pas aux messages déjà en base.

    Les caractères de contrôle partent quand même : ils ne servent à rien dans
    du Markdown, ils compliquent une relecture humaine, et ils n'ont aucune
    raison d'attendre le navigateur pour disparaître.
    """
    if not isinstance(brut, str):
        return None, "message manquant"
    texte = brut.replace("\r\n", "\n")
    texte = "".join(c for c in texte if c in "\n\t" or c >= " ").strip()
    if not texte:
        return None, "un message vide n'aide personne"
    if len(texte) > config.FORUM_MAX_CHARS:
        return None, f"message trop long (maximum {config.FORUM_MAX_CHARS} caractères)"
    return texte, None


# Un nom d'affichage : court, sur une ligne, et qui ne se fait pas passer pour
# une étiquette de l'interface.
_PSEUDOS_RESERVES = frozenset({"vous", "participant", "equipe du cours",
                               "équipe du cours", "moderateur", "modérateur",
                               "anonyme", "enseignant"})


def forum_pseudo(brut):
    """(nom|None, erreur) -- le nom qu'on se donne, ou rien.

    RIEN NE VIENT D'UN CLAIM OIDC : ce champ est saisi, donc il est borné comme
    un message. Vide ou absent veut dire « pas de nom », pas une erreur -- c'est
    l'état par défaut et il reste offert.

    Les étiquettes de l'interface sont réservées : un « Enseignant » choisi
    par un étudiant ferait passer son message pour une réponse du cours, et
    aucune couleur ne rattrape ça. L'ancienne étiquette « Équipe du cours »
    reste réservée elle aussi -- rien ne doit pouvoir la reprendre.
    """
    if brut is None:
        return None, None
    if not isinstance(brut, str):
        return None, "nom invalide"
    # LES CARACTÈRES DE CONTRÔLE DEVIENNENT DES ESPACES, ils ne disparaissent
    # pas : les retirer collerait un nom écrit sur deux lignes en un seul mot,
    # c'est-à-dire en un autre nom que celui qui a été tapé.
    nom = " ".join("".join(c if c >= " " else " " for c in brut).split())
    if not nom:
        return None, None
    if len(nom) > config.FORUM_PSEUDO_MAX:
        return None, f"nom trop long (maximum {config.FORUM_PSEUDO_MAX} caractères)"
    if nom.casefold() in _PSEUDOS_RESERVES:
        return None, "ce nom est réservé à l'interface, choisis-en un autre"
    return nom, None


def forum_groupe(brut):
    """(numéro|None, erreur) -- le numéro de groupe, ou rien.

    Si `CTESTER_FORUM_GROUPES` liste des groupes, seuls ceux-là passent ; sinon
    un numéro à deux chiffres (1..99), ce qu'un plan de cours distribue.
    """
    if brut is None or brut == "":
        return None, None
    if isinstance(brut, bool):
        return None, "numéro de groupe invalide"
    try:
        numero = int(brut)
    except (TypeError, ValueError):
        return None, "numéro de groupe invalide"
    if config.FORUM_GROUPES:
        if numero not in config.FORUM_GROUPES:
            return None, "groupe inconnu pour cette session"
    elif not 1 <= numero <= 99:
        return None, "le numéro de groupe va de 1 à 99"
    return numero, None


def forum_identite(profil, sub, auteur, moderateur_lecteur):
    """(auteur affiché, numéro de groupe affiché, le nom est-il choisi).

    LA SEULE PLACE OÙ UN PROFIL DEVIENT PUBLIC. Un nom ne sort que si son
    porteur l'a rendu visible ; le numéro de groupe sort en plus pour
    l'enseignant, en tout temps, parce que c'est ce qui permet de rattacher un
    problème à un groupe sans demander de nom à personne.
    """
    profil = profil or {}
    pseudo = profil.get("pseudo")
    choisi = bool(pseudo) and bool(profil.get("pseudo_public"))
    if auteur == sub:
        nom = "Vous"
    elif is_moderator(auteur):
        nom = "Enseignant"
    else:
        nom = pseudo if choisi else "Participant"
    groupe = profil.get("groupe")
    if groupe is not None and not (profil.get("groupe_public")
                                  or moderateur_lecteur or auteur == sub):
        groupe = None
    return nom, groupe, choisi and auteur != sub


def forum_vue(messages, sub, moderateur, profils=None):
    """Ce qu'un fil devient pour CET appelant. AUCUN `sub` ne franchit cette ligne.

    « Vous » pour son auteur, « Enseignant » pour un modérateur, et pour
    les autres le nom qu'ils ont CHOISI D'AFFICHER, sinon « Participant ».
    Le nom et le numéro de groupe sont saisis par l'étudiant et n'apparaissent
    que s'il les a rendus visibles -- l'anonymat reste l'état par défaut, et
    deux messages ne se recollent que si leur auteur l'a voulu. Le `sub`, lui,
    ne traverse toujours pas.

    Les messages masqués ne sortent QUE vers un modérateur : c'est lui qui doit
    pouvoir les rétablir.
    """
    profils = profils or {}
    vus = []
    for m in messages:
        if not (moderateur or not m["masque"]):
            continue
        nom, groupe, signalable = forum_identite(
            profils.get(m["utilisateur"]), sub, m["utilisateur"], moderateur)
        vus.append({"id": m["id"], "texte": m["texte"], "cree_le": m["cree_le"],
                    "auteur": nom, "groupe": groupe,
                    "nom_signalable": signalable,
                    "mien": m["utilisateur"] == sub,
                    "masque": m["masque"]})
    return vus
