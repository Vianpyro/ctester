#!/usr/bin/env python3
"""ctester -- persistence for students who sign in. See schema.sql.

THIS WHOLE MODULE IS OPTIONAL, and that is what gives it its shape. Without
CTESTER_DB_DSN, `enabled()` is false and the API behaves exactly as before: the
anonymous path never needs this layer. A database that is down must not stop a
student from testing their code the evening before a deadline -- so nothing here
raises. Functions return None or False, and the caller says so honestly on screen.

`utilisateur` is ALWAYS the opaque `sub` validated by app.current_user(), never a value
taken from a request body: that is the one thing keeping a student out of
another student's state.

Table and column names stay as the schema declares them (see schema.sql); the
Python around them does not.
"""

import json
import os
import threading
from datetime import timezone

try:
    import psycopg          # the exposed container's only external dependency
except ImportError:         # image built without it: persistence is simply absent
    psycopg = None

DSN = os.environ.get("CTESTER_DB_DSN", "")

# ponytail: ONE connection behind a global lock, not a pool. The most frequent
# write is a draft every 1.5 s per signed-in student; at 27 of them the queue
# behind this lock is permanently empty. Move to psycopg_pool the day it is not.
_lock = threading.Lock()
_conn = None

STATUSES = ("essaye", "valide")
# Les deux seuls thèmes de la page. Même liste que le CHECK de `schema.sql`
# et que le script du `<head>` : trois endroits, une seule règle à tenir.
THEMES = ("light", "dark")


def enabled():
    """True when persistence is both configured and usable."""
    return bool(DSN) and psycopg is not None


def _close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


def _query(sql, params, read=False):
    """One statement, under the lock. Rows, [] for a write, or None on failure.

    None means "the database did not answer", never "there is nothing": that is
    what lets the caller tell a fault apart from an empty dashboard. Confusing
    the two would make a student believe everything was lost.

    The broad `except Exception` is deliberate. What psycopg can raise -- dead
    connection, Postgres restarted, DNS, encoding -- has exactly one correct
    response here: degrade. Letting it propagate would return 500 on a page whose
    "Tester" button was still working perfectly well.
    """
    global _conn
    if not enabled():
        return None
    with _lock:
        for last_try in (False, True):
            try:
                if _conn is None or _conn.closed:
                    _conn = psycopg.connect(DSN, autocommit=True, connect_timeout=5)
                with _conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall() if read else []
            except Exception:
                # A stale connection is the common case (Postgres restarted
                # overnight): drop it and retry ONCE. Two failures in a row are
                # an outage, and an outage gets reported.
                _close()
                if last_try:
                    return None
    return None


def _sources(rows):
    """The `sources` column of a single row, decoded. None if nothing usable.

    The contents come from the database, but a student put them there: check
    again that it is an object before handing it back to a browser.
    """
    if not rows:
        return None
    try:
        value = json.loads(rows[0][0])
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    return {str(k): str(v) for k, v in value.items()}


def read_resume(user, exercise_id):
    """What goes back into the editor: the draft, else the last submission.

    One round trip for both tables. A student who submitted and then closed the
    tab must find what they sent, not a blank template.
    """
    rows = _query(
        "SELECT sources FROM ("
        "  SELECT sources, 0 AS rank FROM brouillon_exercice"
        "   WHERE utilisateur = %s AND exercice_id = %s"
        "  UNION ALL"
        "  SELECT sources, 1 AS rank FROM etat_exercice"
        "   WHERE utilisateur = %s AND exercice_id = %s"
        ") AS both_tables ORDER BY rank LIMIT 1",
        (user, exercise_id, user, exercise_id), read=True)
    return _sources(rows)


def write_draft(user, exercise_id, sources):
    return _query(
        "INSERT INTO brouillon_exercice (utilisateur, exercice_id, sources, maj)"
        " VALUES (%s, %s, %s, now())"
        " ON CONFLICT (utilisateur, exercice_id)"
        " DO UPDATE SET sources = EXCLUDED.sources, maj = now()",
        (user, exercise_id, json.dumps(sources)),
    ) is not None


def write_state(user, exercise_id, status, sources):
    """Write the state, WITHOUT EVER LETTING IT GO BACKWARDS.

    The CASE exists for a precise reason: after solving an exercise, people keep
    poking at it. Without it, the first failed experiment would turn the green
    dot back to amber, and the dashboard would say the opposite of what happened.
    """
    if status not in STATUSES:
        return False
    return _query(
        "INSERT INTO etat_exercice (utilisateur, exercice_id, statut, sources, maj)"
        " VALUES (%s, %s, %s, %s, now())"
        " ON CONFLICT (utilisateur, exercice_id) DO UPDATE SET"
        "   statut = CASE WHEN etat_exercice.statut = 'valide' THEN 'valide'"
        "                 ELSE EXCLUDED.statut END,"
        "   sources = EXCLUDED.sources, maj = now()",
        (user, exercise_id, status, json.dumps(sources)),
    ) is not None


def read_states(user):
    """[{exercice_id, statut}] for the list view, or None if the database is mute."""
    rows = _query(
        "SELECT exercice_id, statut FROM etat_exercice WHERE utilisateur = %s",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercice_id": exercise, "statut": status} for exercise, status in rows]


def write_practice_attempt(user, job_id, exercise_id, result):
    """Persist one completed practice attempt, once per worker job.

    The API, not JavaScript, reads `result.json` and calls this function.  A
    verdict is practice evidence only; it must never be reused as verified
    mastery while the self-service judge remains intentionally non-secure.
    """
    status = str(result.get("status", "error"))[:64]
    total = result.get("total", 0)
    passed = result.get("passed", 0)
    if not isinstance(total, int) or not isinstance(passed, int):
        total, passed = 0, 0
    total, passed = max(total, 0), max(min(passed, total), 0)
    return _query(
        "INSERT INTO tentative_pratique "
        "(job_id, utilisateur, exercice_id, statut, total, reussis) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (job_id) DO NOTHING",
        (job_id, user, exercise_id, status, total, passed),
    ) is not None


def read_practice_summary(user):
    """Per-exercise practice counts; derived mastery is intentionally absent."""
    rows = _query(
        "SELECT exercice_id, count(*), "
        "count(*) FILTER (WHERE total > 0 AND reussis = total) "
        "FROM tentative_pratique WHERE utilisateur = %s "
        "GROUP BY exercice_id",
        (user,), read=True)
    if rows is None:
        return None
    return [{"exercice_id": ex, "tentatives": attempts, "reussites": solved}
            for ex, attempts, solved in rows]


def grant_first_solve(user, exercise_id, event_id, amount, motif,
                      policy, payload, daily_cap):
    """Enregistre UNE première réussite et son XP, en une seule instruction.

    Rend le montant réellement accordé (0 si le plafond du jour est atteint),
    ou None si le fait existait déjà -- ou si la base n'a pas répondu. Les deux
    se traitent pareil chez l'appelant : il n'y a rien de neuf à célébrer.

    L'IDEMPOTENCE EST DANS LA CLÉ, pas dans une lecture préalable. `event_id`
    nomme le fait (« reussite:tp2-ex3 »), sa clé primaire le rend unique par
    étudiant, et l'`ON CONFLICT` fait que deux sondages simultanés du même
    verdict, un worker relancé ou un rejeu HTTP n'accordent qu'une fois. Une
    lecture suivie d'une écriture aurait laissé la course ouverte.

    Le plafond est calculé DANS la même instruction : le lire à part le rendrait
    faux dès deux réussites concurrentes.
    """
    rows = _query(
        "WITH reste AS ("
        "  SELECT GREATEST(%(cap)s - COALESCE(sum(montant), 0), 0) AS solde"
        "    FROM transaction_xp"
        "   WHERE utilisateur = %(user)s"
        "     AND accorde_le >= date_trunc('day', now())"
        "), nouveau AS ("
        "  INSERT INTO evenement_progression"
        "    (utilisateur, evenement_id, type, exercice_id, politique, charge)"
        "  VALUES (%(user)s, %(event)s, 'ExerciceReussi', %(ex)s,"
        "          %(policy)s, %(payload)s)"
        "  ON CONFLICT (utilisateur, evenement_id) DO NOTHING"
        "  RETURNING evenement_id"
        ") "
        "INSERT INTO transaction_xp"
        "  (utilisateur, evenement_id, montant, motif, exercice_id, politique) "
        "SELECT %(user)s, nouveau.evenement_id,"
        "       LEAST(%(amount)s, reste.solde), %(motif)s, %(ex)s, %(policy)s "
        "  FROM nouveau, reste "
        "RETURNING montant",
        {"user": user, "event": event_id, "ex": exercise_id,
         "policy": policy, "payload": json.dumps(payload),
         "amount": max(int(amount), 0), "motif": motif,
         "cap": max(int(daily_cap), 0)},
        read=True)
    return int(rows[0][0]) if rows else None


def unlock(user, achievement_ids, event_id, policy):
    """Ajoute les succès manquants. Rejouer la même liste ne crée rien de plus."""
    if not achievement_ids:
        return True
    return _query(
        "INSERT INTO succes_obtenu"
        "  (utilisateur, succes_id, evenement_id, politique) "
        "SELECT %s, quoi, %s, %s FROM unnest(%s::text[]) AS quoi "
        "ON CONFLICT (utilisateur, succes_id) DO NOTHING",
        (user, event_id, policy, list(achievement_ids)),
    ) is not None


def read_progress(user):
    """Les faits de progression d'un étudiant, ou None si la base est muette.

    {"xp": int, "succes": [{id, obtenu_le, politique}],
     "transactions": [{exercice_id, montant, motif, accorde_le}]}

    Le solde, le niveau et les compétences ne sont PAS ici : ce sont des
    projections, `app.py` les recalcule à partir de ces faits et du catalogue
    public. Ce qui est stocké est ce qui s'est passé, pas ce qui s'affiche.

    Les dates sortent en JOUR seulement. C'est ce que l'interface montre, et
    l'heure exacte d'une soumission n'a pas à voyager.
    """
    total = _query(
        "SELECT COALESCE(sum(montant), 0) FROM transaction_xp"
        " WHERE utilisateur = %s", (user,), read=True)
    unlocked = _query(
        "SELECT succes_id, obtenu_le, politique FROM succes_obtenu"
        " WHERE utilisateur = %s ORDER BY obtenu_le, succes_id",
        (user,), read=True)
    # BORNÉ, et c'est le contrat : cette liste est la consultation/export des
    # attributions, pas un journal illimité. Une réussite par exercice publié
    # tient largement dessous.
    grants = _query(
        "SELECT exercice_id, montant, motif, accorde_le FROM transaction_xp"
        " WHERE utilisateur = %s ORDER BY accorde_le DESC, evenement_id LIMIT 200",
        (user,), read=True)
    if total is None or unlocked is None or grants is None:
        return None
    return {
        "xp": int(total[0][0]) if total else 0,
        "succes": [{"id": row[0], "obtenu_le": _jour(row[1]),
                    "politique": row[2]} for row in unlocked],
        "transactions": [{"exercice_id": row[0], "montant": int(row[1]),
                          "motif": row[2], "accorde_le": _jour(row[3])}
                         for row in grants],
    }


def _jour(valeur):
    """La date d'un horodatage, en ISO. La chaîne telle quelle si ce n'en est pas un."""
    try:
        return valeur.date().isoformat()
    except AttributeError:
        return str(valeur)[:10]


# --- Les préférences d'affichage -------------------------------------------
# Le thème, et rien d'autre pour l'instant. Il vit ici plutôt que dans le seul
# `localStorage` parce que le stockage local est PAR APPAREIL : un étudiant qui
# travaille au labo puis chez lui repartait chaque fois du thème par défaut.
# Le compte transporte déjà le brouillon d'un poste à l'autre ; le réglage
# d'affichage prend le même chemin.
#
# LE STOCKAGE LOCAL RESTE, et il ne fait pas doublon : c'est lui que le script
# du `<head>` lit avant le premier rendu, bien avant qu'une réponse HTTP puisse
# arriver. Ce qui est ici est la vérité du COMPTE ; ce qui est là-bas est ce
# qui évite le flash sombre->clair à chaque visite.


def read_theme(user):
    """Le thème de ce compte : "light", "dark", ou "" s'il n'a rien choisi.

    None -- et rien d'autre -- veut dire « la base n'a pas répondu ». La chaîne
    vide veut dire « aucun choix enregistré », et l'appelant garde alors celui
    de l'appareil : confondre les deux ferait sauter le réglage de quelqu'un
    chaque fois que Postgres est muet ou neuf.
    """
    rows = _query("SELECT theme FROM preference_affichage WHERE utilisateur = %s",
                  (user,), read=True)
    if rows is None:
        return None
    return rows[0][0] if rows else ""


def write_theme(user, theme):
    """Le thème choisi, écrasé en place. False si la valeur ou la base refuse.

    AVEC LE BROUILLON ET L'ÉTAT, LA SEULE ÉCRITURE DE CE FICHIER QUI REMPLACE
    AU LIEU D'AJOUTER. L'ancien thème de quelqu'un n'est pas un fait à relire,
    et un journal grossirait à chaque clic sur un bouton fait pour être cliqué.

    La liste blanche est répétée ici ET dans le CHECK du schéma : celle-ci
    évite un aller-retour, celui-là tient pour tous les chemins d'écriture.
    """
    if theme not in THEMES:
        return False
    return _query(
        "INSERT INTO preference_affichage (utilisateur, theme, maj)"
        " VALUES (%s, %s, now())"
        " ON CONFLICT (utilisateur)"
        " DO UPDATE SET theme = EXCLUDED.theme, maj = now()",
        (user, theme),
    ) is not None


# --- Forum d'entraide (MVP) ------------------------------------------------
# UN fil par exercice publié, pour les comptes connectés seulement. Rien ici ne
# touche à la progression : ni XP, ni succès, ni statut d'exercice.
#
# `utilisateur` EST TOUJOURS le `sub` validé par app.current_user(), comme
# partout ailleurs dans ce fichier -- jamais une valeur prise dans un corps de
# requête. C'est ce qui empêche de publier, de supprimer ou de signaler au nom
# d'un autre.
#
# CE MODULE REND LE `sub` DE L'AUTEUR à l'appelant, et c'est `app.py` qui le
# traduit en « Vous » / « Participant » / « Enseignant » sans jamais le
# laisser sortir. Le traduire ici aurait demandé de connaître la liste des
# modérateurs dans la couche SQL, où elle n'a rien à faire.


def forum_fil(exercise_id, limite):
    """Le fil d'un exercice, du plus ancien au plus récent. None si base muette.

    Les messages masqués SONT rendus, avec leur drapeau : c'est `app.py` qui les
    retire pour un étudiant ordinaire et les garde pour un modérateur, parce que
    c'est lui qui sait qui appelle.
    """
    rows = _query(
        "SELECT message_id, utilisateur, texte, masque, cree_le"
        " FROM forum_message WHERE exercice_id = %s"
        " ORDER BY cree_le, message_id LIMIT %s",
        (exercise_id, max(int(limite), 0)), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "utilisateur": row[1], "texte": row[2],
             "masque": bool(row[3]), "cree_le": _minute(row[4])} for row in rows]


def forum_publier(message_id, exercise_id, user, texte):
    """Ajoute un message. L'identifiant est généré par l'appelant (uuid4)."""
    return _query(
        "INSERT INTO forum_message (message_id, exercice_id, utilisateur, texte)"
        " VALUES (%s, %s, %s, %s)",
        (message_id, exercise_id, user, texte),
    ) is not None


def forum_supprimer(message_id, user):
    """Supprime SON message. [] si ce n'est pas le sien (ou s'il n'existe plus).

    Le `utilisateur = %s` de la clause EST le contrôle d'accès : il n'y a pas de
    lecture préalable à faire mentir, et supprimer chez le voisin demanderait
    d'être le voisin.
    """
    return _query(
        "DELETE FROM forum_message WHERE message_id = %s AND utilisateur = %s"
        " RETURNING message_id", (message_id, user), read=True)


def forum_signaler(message_id, user):
    """Signale un message. [] s'il n'existe pas OU s'il est déjà signalé par lui.

    DEUX PROTECTIONS DANS UNE SEULE INSTRUCTION : le `SELECT ... FROM
    forum_message` interdit de signaler un identifiant inventé -- donc pas de
    ligne orpheline portant un `sub` pour rien -- et la clé primaire interdit le
    doublon. Une lecture suivie d'une écriture aurait laissé les deux courses
    ouvertes.
    """
    return _query(
        "INSERT INTO forum_signalement (message_id, utilisateur)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, utilisateur) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_signalements(limite):
    """Les messages signalés, les plus signalés d'abord. La vue d'un modérateur.

    LE MINIMUM UTILE À LA MODÉRATION, et rien de plus : le texte, l'exercice, la
    date, l'état et le NOMBRE de signalements. Jamais qui a signalé, jamais qui
    a écrit, jamais du code soumis, un verdict détaillé ou une donnée de
    progression.
    """
    rows = _query(
        "SELECT m.message_id, m.exercice_id, m.texte, m.masque, m.cree_le,"
        "       count(*) AS combien"
        "  FROM forum_message m"
        "  JOIN forum_signalement s ON s.message_id = m.message_id"
        " GROUP BY m.message_id, m.exercice_id, m.texte, m.masque, m.cree_le"
        " ORDER BY combien DESC, m.cree_le LIMIT %s",
        (max(int(limite), 0),), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "exercice_id": row[1], "texte": row[2],
             "masque": bool(row[3]), "cree_le": _minute(row[4]),
             "signalements": int(row[5])} for row in rows]


def forum_moderer(action_id, message_id, moderator, action):
    """Masque ou rétablit un message ET journalise l'action, en UNE instruction.

    [] quand le message n'existe pas ; None quand la base n'a pas répondu.

    LE JOURNAL EST EN AJOUT SEUL et l'état courant est une colonne : les deux
    écritures doivent donc tomber ensemble. Séparées en deux `_query` en
    autocommit, une connexion coupée au milieu laisserait un message masqué que
    rien n'explique -- ou l'inverse, un journal qui ment.
    """
    if action not in ("masquer", "retablir"):
        return []
    return _query(
        "WITH agi AS ("
        "  INSERT INTO forum_moderation"
        "    (action_id, message_id, utilisateur, action)"
        "  SELECT %(aid)s, m.message_id, %(who)s, %(quoi)s"
        "    FROM forum_message m WHERE m.message_id = %(id)s"
        "  RETURNING message_id"
        ") UPDATE forum_message SET masque = %(masque)s"
        "  WHERE message_id = (SELECT message_id FROM agi)"
        "  RETURNING message_id",
        {"aid": action_id, "id": message_id, "who": moderator,
         "quoi": action, "masque": action == "masquer"}, read=True)


# --- Le nom choisi et le numéro de groupe ----------------------------------
# EN AJOUT SEUL, LA DERNIÈRE LIGNE FAIT FOI. Pas d'UPDATE, donc pas de GRANT
# d'UPDATE : la propriété est tenue par Postgres et pas par la discipline de
# celui qui écrit la requête suivante. `DISTINCT ON` fait la lecture en une
# passe sur l'index (utilisateur, cree_le DESC).

_PROFIL_COLONNES = ("pseudo", "groupe", "pseudo_public", "groupe_public")


def _profil(row):
    return {"pseudo": row[1], "groupe": None if row[2] is None else int(row[2]),
            "pseudo_public": bool(row[3]), "groupe_public": bool(row[4])}


def forum_profils(utilisateurs):
    """{sub: profil} pour ces comptes. {} pour ceux qui n'en ont jamais posé.

    UNE SEULE REQUÊTE POUR TOUT UN FIL : un fil de vingt messages ne doit pas
    coûter vingt allers-retours derrière le verrou global. `= ANY(%s)` prend la
    liste telle quelle -- même forme que le `unnest` de la progression.
    """
    gens = sorted({u for u in utilisateurs if u})
    if not gens:
        return {}
    rows = _query(
        "SELECT DISTINCT ON (utilisateur)"
        "       utilisateur, pseudo, groupe, pseudo_public, groupe_public"
        "  FROM forum_profil WHERE utilisateur = ANY(%s)"
        " ORDER BY utilisateur, cree_le DESC, profil_id DESC",
        (gens,), read=True)
    if rows is None:
        return None
    return {row[0]: _profil(row) for row in rows}


def forum_profil(user):
    """Le profil de CE compte, {} s'il n'en a jamais posé. None si base muette."""
    profils = forum_profils([user])
    if profils is None:
        return None
    return profils.get(user, {"pseudo": None, "groupe": None,
                              "pseudo_public": False, "groupe_public": False})


def forum_profil_ecrire(profil_id, user, pseudo, groupe, pseudo_public,
                        groupe_public, par_moderateur=False):
    """Ajoute une ligne de profil. Les anciennes restent, et c'est voulu."""
    return _query(
        "INSERT INTO forum_profil (profil_id, utilisateur, pseudo, groupe,"
        "                          pseudo_public, groupe_public, par_moderateur)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (profil_id, user, pseudo, groupe, bool(pseudo_public),
         bool(groupe_public), bool(par_moderateur)),
    ) is not None


def forum_nom_signaler(message_id, user):
    """Signale le NOM de l'auteur d'un message. Mêmes deux protections que
    `forum_signaler` : le SELECT interdit un identifiant inventé, la clé
    primaire interdit le doublon."""
    return _query(
        "INSERT INTO forum_nom_signale (message_id, utilisateur)"
        " SELECT m.message_id, %s FROM forum_message m WHERE m.message_id = %s"
        " ON CONFLICT (message_id, utilisateur) DO NOTHING"
        " RETURNING message_id", (user, message_id), read=True)


def forum_noms_signales(limite):
    """Les NOMS signalés, pour un modérateur. Le nom, le groupe, le compte à
    poignée -- jamais le `sub` : `app.py` ne recopie que ce qui s'affiche.

    Un même compte peut être signalé depuis plusieurs de ses messages ; on rend
    une ligne par message porteur, la plus signalée d'abord, avec le profil
    courant de l'auteur.
    """
    rows = _query(
        "SELECT m.message_id, m.utilisateur, p.pseudo, p.groupe, m.cree_le,"
        "       count(*) AS combien"
        "  FROM forum_nom_signale s"
        "  JOIN forum_message m ON m.message_id = s.message_id"
        "  LEFT JOIN LATERAL ("
        "       SELECT pseudo, groupe FROM forum_profil"
        "        WHERE utilisateur = m.utilisateur"
        "        ORDER BY cree_le DESC, profil_id DESC LIMIT 1) p ON true"
        " GROUP BY m.message_id, m.utilisateur, p.pseudo, p.groupe, m.cree_le"
        " ORDER BY combien DESC, m.cree_le LIMIT %s",
        (max(int(limite), 0),), read=True)
    if rows is None:
        return None
    return [{"id": row[0], "utilisateur": row[1], "pseudo": row[2],
             "groupe": None if row[3] is None else int(row[3]),
             "cree_le": _minute(row[4]), "signalements": int(row[5])}
            for row in rows]


def forum_auteur(message_id):
    """Le `sub` de l'auteur d'un message, ou None. Réservé à la modération de
    nom : la page n'a qu'une poignée de message, jamais un identifiant."""
    rows = _query("SELECT utilisateur FROM forum_message WHERE message_id = %s",
                  (message_id,), read=True)
    if not rows:
        return None
    return rows[0][0]


def _minute(valeur):
    """Un horodatage à la MINUTE, en UTC explicite. La chaîne telle quelle sinon.

    À la minute et pas au jour, contrairement à la progression : un fil se lit
    dans l'ordre, et « aujourd'hui » sur dix messages n'aide personne. À la
    minute et pas à la seconde : personne n'a besoin de chronométrer qui a
    répondu le premier.

    AVEC LE FUSEAU, ET C'EST TOUT LE POINT. La colonne est TIMESTAMPTZ, donc
    l'instant stocké a toujours été juste ; c'est la chaîne envoyée qui n'en
    disait rien, et la page l'affichait comme si elle était locale -- un
    message écrit à Montréal partait quatre heures dans le futur. Le « Z » suffit
    à la page pour le retraduire dans le fuseau de qui lit. Rien à migrer.
    """
    try:
        return valeur.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except AttributeError:
        return str(valeur)[:16]


def forget(user):
    """Erase everything stored for this user, in ONE statement.

    The consent sentence shown before redirecting to Rauthy promises this exists,
    so it exists -- not "later".

    TWELVE DELETEs, ONE ROUND TRIP, and that is the point: with one autocommit
    statement per table, a connection dropped in the middle would leave half a
    student erased and half not -- and the half that stays is the half nobody
    can see any more to ask for again. Data-modifying CTEs run exactly once each
    and commit together.

    CHAQUE TABLE PORTE `utilisateur`, ET C'EST LA MÊME CLAUSE PARTOUT : ce qui
    part est ce que CETTE personne a écrit -- ses messages, ses signalements, et
    les actions de modération qu'elle a elle-même prises si elle est
    modératrice. Rien de ce qu'un autre a écrit n'est touché. Un signalement
    laissé sur un message supprimé n'apparaît plus nulle part -- toute lecture
    part de `forum_message` -- et reste effaçable par celui qui l'a posé.
    """
    return _query(
        "WITH b AS (DELETE FROM brouillon_exercice WHERE utilisateur = %(u)s),"
        "     e AS (DELETE FROM etat_exercice      WHERE utilisateur = %(u)s),"
        "     t AS (DELETE FROM tentative_pratique WHERE utilisateur = %(u)s),"
        "     j AS (DELETE FROM evenement_progression WHERE utilisateur = %(u)s),"
        "     x AS (DELETE FROM transaction_xp     WHERE utilisateur = %(u)s),"
        "     s AS (DELETE FROM succes_obtenu      WHERE utilisateur = %(u)s),"
        "     f AS (DELETE FROM forum_message      WHERE utilisateur = %(u)s),"
        "     g AS (DELETE FROM forum_signalement  WHERE utilisateur = %(u)s),"
        "     h AS (DELETE FROM forum_moderation   WHERE utilisateur = %(u)s),"
        "     i AS (DELETE FROM forum_profil       WHERE utilisateur = %(u)s),"
        "     k AS (DELETE FROM forum_nom_signale  WHERE utilisateur = %(u)s),"
        "     p AS (DELETE FROM preference_affichage WHERE utilisateur = %(u)s)"
        " SELECT 1",
        {"u": user},
    ) is not None
