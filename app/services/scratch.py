"""La Console : le protocole d'une session interactive, et rien d'autre.

CE MODULE N'EXÉCUTE RIEN, comme le reste de ce conteneur. Il écrit un job dans
le spool, tient un verrou pour dire que le navigateur est encore là, et relit
deux fichiers par décalage. Le worker, sur l'hôte, fait tout le reste. C'est la
même frontière que pour une soumission notée -- et c'est ce qui permet
d'exposer ce processus à Internet.

UNE SESSION EST UN JOB DE LA FILE EXISTANTE. Pas un canal parallèle : un
répertoire de spool ordinaire, avec `job.json` écrit EN DERNIER par un rename
atomique, exactement comme `spool.ecrire_job()`. Elle attend donc son tour
derrière les soumissions, avec la même position et le même ETA, et `QUEUE_MAX`
la compte comme les autres. Il n'y a aucun compteur de plus à tenir.

`job.json` NE PORTE AUCUNE IDENTITÉ -- ni `owner`, ni `exercise_id`, ni `sub`.
C'est « aucun modèle ne porte de champ d'identité » étendu jusqu'au canal du
worker : ce processus-là ne sait jamais qui est au clavier. Deux conséquences
gratuites : `_enregistrer()` (routers/submission.py) est inatteignable, puisqu'il
exige les deux ; et la passe de cache du worker ignore la session d'elle-même,
`tp_path("")` ne résolvant rien.

CE QUI CIRCULE EST UN FLUX D'OCTETS SANS CADRAGE, et ça ne tient que parce que
PERSONNE NE L'INTERPRÈTE. `in` et `out` sont des fichiers en ajout seul, relus
par décalage : voir un préfixe d'une écriture n'est pas une erreur pour un flux
d'octets. Un FIFO demanderait des sémantiques bloquantes des deux côtés d'un
bind mount, pour ne rien gagner.

LE `flock` EST LA VIVACITÉ, PAS UN BATTEMENT. Un fichier `close` que l'API
écrirait en partant ne serait jamais écrit dans le seul cas qui compte -- le
conteneur web tué, le portable endormi. Le noyau, lui, relâche un `flock` à la
mort du processus qui le tient, et le fait à travers un bind mount puisque
c'est le même inode. Le worker sonde ce verrou toutes les 25 ms ; ça remplace
un seuil de péremption, une période de battement et le mode de panne qui va
avec.
"""

import codecs
import json
import os
import uuid

import config
from services.source import canonicalize

# ponytail: `flock` est POSIX, et la Console ne tourne QUE sur le Dell -- mais
# `app/main.py` importe ce module au chargement, donc sans ce garde-fou c'est
# TOUTE l'API qui devient inimportable sur la machine de développement, et avec
# elle `test_api.py`. Ouvrir une session sans fcntl lève ; l'importer, non.
try:
    import fcntl
except ImportError:
    fcntl = None

# Le genre porté par `job.json`. Le worker dispatche dessus AVANT de réclamer.
KIND = "console"


def valider_bloc_notes(code):
    """(code, message, statut) -- LA MÊME PORTE que `validate_files`, côté Console.

    Elle existe parce que la borne était écrite DEUX FOIS dans
    `routers/scratch.py` : une pour `PUT /scratch/draft`, une pour la trame
    `hello` de `WS /scratch/live`. Deux copies d'une borne, c'est celle qu'on
    oublie de corriger qui devient la borne réelle.

    LA FORME CANONIQUE D'ABORD, LA BORNE ENSUITE, pour la même raison que dans
    `validate_files` : ce qui est mesuré doit être ce qui est écrit. Ici ça
    compte pour de bon -- `scratch_draft` porte un `CHECK (length(code) <=
    65536)` en base, et un octet de plus entre la mesure et l'écriture rendrait
    « la base ne répond pas » sur un bloc-notes parfaitement valide.
    """
    if not isinstance(code, str):
        return None, "bloc-notes manquant", 400
    code = canonicalize(code)
    if len(code.encode("utf-8")) > config.MAX_CODE:
        return None, "bloc-notes > %d Ko" % (config.MAX_CODE // 1024), 413
    return code, None, 200


class Session:
    """Un répertoire de spool, un verrou tenu, et deux décalages de lecture."""

    def __init__(self, job_id, chemin, verrou):
        self.job_id = job_id
        self.chemin = chemin
        self._verrou = verrou
        self._lus = {"build": 0, "out": 0}
        # UN DÉCODEUR PAR FLUX, ET INCRÉMENTAL. Un caractère multi-octets à
        # cheval sur deux lectures est mis EN ATTENTE par le décodeur au lieu
        # d'être mutilé -- sans ça, un étudiant qui imprime « é » à un multiple
        # de 64 Ko recevrait deux losanges, une fois sur mille, sans que rien
        # ne le signale. `errors="replace"` ne s'applique donc plus qu'à des
        # octets vraiment invalides, ce qu'un programme C peut très bien
        # produire.
        self._decodeurs = {nom: codecs.getincrementaldecoder("utf-8")("replace")
                           for nom in ("build", "out")}
        self._entree = 0

    def fermer(self):
        """Relâche le verrou. Le worker le voit et détruit le conteneur."""
        try:
            os.close(self._verrou)
        except OSError:
            pass

    # --- ce que l'étudiant tape -------------------------------------------
    def ecrire_entree(self, texte):
        """Ajoute des octets à `in`. Rend False quand la session a trop reçu.

        LE PLAFOND EST ICI ET PAS DANS LE WORKER : c'est la frontière HTTP qui
        décide de ce qu'un client a le droit de pousser, et le worker n'a pas à
        savoir qu'il existe un client.
        """
        octets = texte.encode("utf-8", "replace")
        if self._entree + len(octets) > config.SCRATCH_IN_MAX:
            return False
        try:
            with open(os.path.join(self.chemin, "in"), "ab", buffering=0) as fh:
                fh.write(octets)
        except OSError:
            return False
        self._entree += len(octets)
        return True

    def fermer_entree(self):
        """Ferme l'entrée standard du programme. C'est la fin d'un `scanf`.

        UN TÉMOIN, PAS UN OCTET DANS LE FLUX. « Plus rien ne viendra » ne
        s'exprime pas dans un flux d'octets : n'importe quelle séquence qu'on
        choisirait serait une séquence qu'un étudiant peut taper. Un fichier à
        côté ne peut pas entrer en collision avec des données.

        Sans ça, un `while (scanf("%d", &n) == 1)` n'aurait aucun moyen de se
        terminer autrement qu'en tuant la session -- ce qui n'est pas la même
        chose, et ne rend pas le même code de sortie.
        """
        try:
            with open(os.path.join(self.chemin, "eof"), "wb"):
                pass
        except OSError:
            pass

    # --- ce que le programme écrit ----------------------------------------
    def lire_sortie(self, nom):
        """Les nouveaux octets de `build` ou `out`, décodés, depuis le décalage."""
        try:
            with open(os.path.join(self.chemin, nom), "rb") as fh:
                paquet = os.pread(fh.fileno(), 65536, self._lus[nom])
        except OSError:
            return ""
        if not paquet:
            return ""
        self._lus[nom] += len(paquet)
        return self._decodeurs[nom].decode(paquet)

    def etat(self):
        """`state.json`, ou None tant que le worker ne l'a pas écrit.

        Le worker le réécrit ATOMIQUEMENT (tmp + rename), donc il n'y a pas de
        moitié de fichier à lire ici.
        """
        try:
            with open(os.path.join(self.chemin, "state.json"),
                      encoding="utf-8") as fh:
                etat = json.load(fh)
        except (OSError, ValueError):
            return None
        return etat if isinstance(etat, dict) else None

    def prise_en_charge(self):
        """Le worker a-t-il réclamé ce job ? (le même `.lock` que partout)"""
        return os.path.exists(os.path.join(self.chemin, ".lock"))

    def worker_vivant(self):
        """False quand le worker qui tenait la session est mort.

        Sans ça, une unité tuée en pleine session laisse un terminal qui
        s'arrête sans rien dire, et l'étudiant ne peut pas savoir si c'est son
        programme ou le service.
        """
        return _verrou_tenu(os.path.join(self.chemin, "claim"))


def ouvrir(code):
    """Écrit la session dans le spool et rend la Session. Ordre load-bearing.

    LE VERROU EST PRIS AVANT LE DÉCLENCHEUR, par construction : quand
    `job.json` apparaît -- la seule chose que le worker regarde -- `alive` est
    déjà tenu. Un worker ne peut donc jamais voir une session dont l'API n'a
    pas encore prouvé qu'elle est vivante, et la conclure abandonnée.

    C'est la même discipline que `spool.ecrire_job()`, qui écrit `job.json` en
    dernier pour que le worker ne lise jamais un `submission.c` à moitié écrit.
    """
    # LE MESSAGE DIT QUOI, PAS « une erreur ». Hors POSIX il n'y a pas de
    # `flock`, donc pas de duree de vie de session -- la Console ne tourne que
    # sur le Dell. Ce qui compte est que la panne se NOMME : le harnais de
    # test s'en sert pour sauter ces controles-la sur un poste Windows au lieu
    # de tomber sur un `AttributeError: NoneType`.
    if fcntl is None:
        raise RuntimeError("flock indisponible : la Console demande POSIX")

    job_id = uuid.uuid4().hex
    chemin = os.path.join(config.SPOOL, job_id)
    os.mkdir(chemin, 0o755)
    os.mkdir(os.path.join(chemin, "src"), 0o755)
    with open(os.path.join(chemin, "src", "main.c"), "w",
              encoding="utf-8") as fh:
        fh.write(code)
    verrou = os.open(os.path.join(chemin, "alive"),
                     os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(verrou)
        raise
    tmp = os.path.join(chemin, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        # Le genre, et RIEN D'AUTRE. Voir l'en-tête de ce module.
        json.dump({"kind": KIND}, fh)
    os.replace(tmp, os.path.join(chemin, "job.json"))
    return Session(job_id, chemin, verrou)


def _verrou_tenu(chemin):
    """Quelqu'un tient-il le `flock` de ce fichier ?

    On le teste EN L'ESSAYANT : réussir à le prendre, c'est constater que le
    tenant n'est plus là. Le descripteur est refermé aussitôt, donc on sonde
    sans prendre la place. Jumeau de `runner.verrou_tenu()` -- les deux côtés
    de la même frontière, et il n'y a rien à garder synchronisé entre eux
    puisque c'est le noyau qui répond.
    
    L'OUVERTURE EST EN LECTURE SEULE, ET C'EST LOAD-BEARING. Les deux verrous
    ne sont pas crees par le meme utilisateur : `alive` l'est par l'API (uid
    65534 dans le conteneur), `claim` par le worker (root sur l'hote), et tous
    les deux en 0644. Ouvrir en O_RDWR pour SONDER demandait donc le droit
    d'ecriture sur le fichier de l'autre -- l'API prenait un EACCES sur
    `claim`, le `except OSError` le traduisait en « personne ne le tient », et
    la session mourait en annoncant « le service s'est interrompu » sur un
    worker parfaitement vivant. Une panne parfaitement asymetrique : root
    pouvait ouvrir `alive`, nobody ne pouvait pas ouvrir `claim`.

    `flock` NE DEMANDE AUCUN DROIT D'ECRITURE -- contrairement aux verrous
    POSIX de `fcntl.lockf` -- parce qu'il porte sur la description de fichier
    ouverte et pas sur son contenu. Sonder en lecture seule est donc la
    correction complete : rien a changer aux modes, rien a aligner entre deux
    utilisateurs.
    """
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_CREAT, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
