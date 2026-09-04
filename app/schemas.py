"""Les corps de requête, déclarés au lieu d'être vérifiés à la main.

CES MODÈLES NE VALIDENT QUE LA FORME -- présence et type. Les règles du domaine
(longueur d'un message, noms de fichiers autorisés, groupe d'une session, thème
connu) restent dans `services/` et dans `etat.py`, pour deux raisons :

  * elles rendent des messages écrits POUR L'ÉTUDIANT (« message trop long
    (maximum 1200 caractères) »), que Pydantic remplacerait par un 400
    générique -- et un étudiant bloqué sans savoir pourquoi renonce ;
  * elles sont éprouvées par appel direct dans `test_ctester.py`, sans monter
    de serveur. Les déplacer ici les rendrait inaccessibles autrement que par
    une requête HTTP.

AUCUN MODÈLE NE PORTE DE CHAMP D'IDENTITÉ, et il ne faut jamais en ajouter :
`utilisateur`, `sub`, `owner`, `moderateur` viennent du jeton validé et de nulle
part ailleurs. Un champ de plus ici serait une porte pour écrire dans l'état de
quelqu'un d'autre.
"""

from pydantic import BaseModel, ConfigDict

# `extra="ignore"` : un client plus récent qui envoie un champ de plus ne se
# fait pas rejeter. `forbid` transformerait un déploiement de page en avance sur
# l'API en panne totale, un jour où seule la page a été redéployée.
_CONFIG = ConfigDict(extra="ignore")


class SoumissionIn(BaseModel):
    """POST /submit -- une soumission de code, ou un quiz.

    `key` EST LA CLÉ DE SESSION, comparée en temps constant et AVANT tout autre
    travail : rien ne doit être mesurable depuis l'extérieur sans elle.

    `files` et `answers` sont laissés en `dict` brut : c'est le catalogue qui
    dit quels noms de fichiers existent pour CET exercice (`validate_files`), et
    un schéma ne peut pas le savoir à l'avance.
    """

    model_config = _CONFIG

    key: str = ""
    tp: str = ""
    files: dict | None = None
    answers: dict | None = None


class BrouillonIn(BaseModel):
    """PUT /brouillon et PUT /etat -- le code en cours, et son statut déclaré."""

    model_config = _CONFIG

    tp: str = ""
    files: dict | None = None
    statut: str = ""


class PreferencesIn(BaseModel):
    """PUT /preferences -- le thème, qui suit le COMPTE et pas l'appareil."""

    model_config = _CONFIG

    theme: str = ""


class ForumMessageIn(BaseModel):
    """POST /forum -- publier dans le fil d'un exercice publié."""

    model_config = _CONFIG

    tp: str = ""
    texte: str | None = None


class ForumSignalementIn(BaseModel):
    """POST /forum/signalement -- signaler un message, ou un nom affiché.

    DEUX CIBLES, UNE ROUTE. Signaler un nom, c'est le même geste et la même
    file : le message sert de poignée parce que le navigateur n'a aucun
    identifiant de compte, et il n'en aura pas.
    """

    model_config = _CONFIG

    id: str = ""
    quoi: str = "message"


class ForumModerationIn(BaseModel):
    """POST /forum/moderation -- masquer, rétablir, ou effacer un nom.

    Éditer un message n'en fait pas partie : un message est immuable, et un
    modérateur qui pourrait le corriger pourrait aussi faire dire autre chose à
    quelqu'un.
    """

    model_config = _CONFIG

    id: str = ""
    action: str = ""


class ForumProfilIn(BaseModel):
    """POST /forum/profil -- son nom, son groupe, et ce qui s'affiche.

    DEUX CASES INDÉPENDANTES, et rien n'apparaît sans que son porteur l'ait
    cochée. `groupe` accepte un entier comme une chaîne : le formulaire envoie
    l'un ou l'autre selon qu'il est une liste déroulante ou un champ libre, et
    `forum_groupe()` tranche.
    """

    model_config = _CONFIG

    pseudo: str | None = None
    groupe: int | str | None = None
    pseudo_public: bool = False
    groupe_public: bool = False
