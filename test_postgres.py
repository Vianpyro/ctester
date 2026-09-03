#!/usr/bin/env python3
"""ctester -- éprouve `app/schema.sql` et `app/etat.py` sur un VRAI PostgreSQL.

    docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester \
               -p 55432:5432 postgres:16-alpine
    CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
      python3 test_postgres.py

Avec le rôle applicatif, ce qui reproduit exactement la production -- le
schéma posé par `postgres`, tout le reste joué par `ctester_app` et ses seuls
GRANT :

    CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
    CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester \
      python3 test_postgres.py

POURQUOI CE FICHIER EXISTE. `test_ctester.py` simule la base : ce qu'il éprouve
est la frontière HTTP, pas le SQL. Or les écritures de progression et de forum
ne sont pas du SQL ordinaire -- une CTE modifiante qui alimente un INSERT, une
CTE modifiante qui alimente un UPDATE, un `unnest` d'un tableau paramétré, un
INSERT ... SELECT dont la clause `WHERE` est le contrôle d'accès, un
`DISTINCT ON` et une jointure LATERAL pour le dernier profil, onze DELETE
dans une seule instruction. Ces formes compilent dans la tête et échouent en
production ; il n'y a pas de milieu.

SANS `CTESTER_DB_DSN`, IL NE FAIT RIEN ET SORT EN 0. C'est délibéré : il doit
pouvoir être lancé partout sans devenir une raison de plus de ne pas lancer les
autres contrôles. Il n'est PAS dans la vérification Ansible -- il écrit, et la
seule base que le rôle connaît est celle des étudiants.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

DSN = os.environ.get("CTESTER_DB_DSN", "")
# Le schéma est posé par le propriétaire, jamais par le rôle applicatif : c'est
# ce que fait le rôle Ansible, et c'est justement ce qu'on veut éprouver. Sans
# DSN d'administration, les deux sont le même et le contrôle de privilège plus
# bas s'annonce comme non joué plutôt que de passer en mentant.
ADMIN_DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or DSN
if not DSN:
    print("CTESTER_DB_DSN vide : rien à éprouver ici (voir l'en-tête).")
    raise SystemExit(0)

import etat        # noqa: E402 -- il lit CTESTER_DB_DSN à l'import

if not etat.enabled():
    raise SystemExit("psycopg manque : pip install 'psycopg[binary]'")

TABLES = ("brouillon_exercice", "etat_exercice", "tentative_pratique",
          "evenement_progression", "transaction_xp", "succes_obtenu",
          "forum_message", "forum_signalement", "forum_moderation",
          "forum_profil", "forum_nom_signale")

ALICE, BOB = "sub-alice", "sub-bob"


def compte(table, user):
    rows = etat._query(
        "SELECT count(*) FROM %s WHERE utilisateur = %%s" % table,
        (user,), read=True)
    assert rows is not None, "la base n'a pas répondu sur " + table
    return rows[0][0]


def appliquer_schema():
    """Le schéma tel qu'Ansible l'applique : le fichier, en entier, d'un bloc.

    Le rejouer doit être sans effet -- c'est ce que promettent les
    `IF NOT EXISTS`, et c'est ce que le rôle fait à chaque convergence.
    """
    import psycopg
    with open(os.path.join(HERE, "app", "schema.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    # PAR LE DSN D'ADMINISTRATION : `ctester_app` n'a pas le droit de créer une
    # table, et c'est voulu. Passer par `etat._query` ici ferait échouer ce
    # contrôle pour la bonne raison, au mauvais endroit.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cx:
        for _ in range(2):
            cx.execute(sql)
        trouvees = {row[0] for row in cx.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    manquantes = set(TABLES) - trouvees
    assert not manquantes, "tables absentes : " + ", ".join(sorted(manquantes))
    print("ok   schema.sql s'applique, et se rejoue sans rien casser")


def ajout_seul():
    """LES TABLES DE PROGRESSION SONT EN AJOUT SEUL, ET C'EST POSTGRES QUI TIENT.

    Le rôle applicatif n'a pas `UPDATE` dessus (voir le GRANT dans VHome). La
    propriété ne dépend donc pas de la discipline de `etat.py` : une ligne de
    Python distraite ne peut pas réécrire une attribution d'XP après coup, et
    une correction d'erreur demande un accès d'administration explicite.

    Non joué quand les deux DSN sont le même -- il n'y aurait rien à refuser.
    """
    if ADMIN_DSN == DSN:
        print("--   ajout seul : NON JOUÉ (pas de CTESTER_DB_ADMIN_DSN distinct)")
        return
    import psycopg
    refuses = []
    for table in ("evenement_progression", "transaction_xp", "succes_obtenu"):
        with psycopg.connect(DSN, autocommit=True) as cx:
            try:
                cx.execute("UPDATE %s SET politique = 'triche'" % table)
            except psycopg.errors.InsufficientPrivilege:
                refuses.append(table)
    assert len(refuses) == 3, "UPDATE accepté quelque part : " + str(refuses)
    print("ok   Postgres refuse l'UPDATE sur les trois tables de progression")


def brouillons_et_etats():
    assert etat.write_draft(ALICE, "tp2-ex3", {"submission.c": "int main(void){}"})
    assert etat.read_resume(ALICE, "tp2-ex3") == {"submission.c": "int main(void){}"}
    # Le brouillon l'emporte sur l'état soumis : c'est le travail en cours.
    assert etat.write_state(ALICE, "tp2-ex3", "valide", {"submission.c": "envoyé"})
    assert etat.read_resume(ALICE, "tp2-ex3")["submission.c"] == "int main(void){}"
    # ET « valide » NE RECULE PAS. On continue de bricoler un exercice réussi ;
    # sans le CASE du schéma, le tableau de bord dirait le contraire de ce qui
    # s'est passé.
    assert etat.write_state(ALICE, "tp2-ex3", "essaye", {"submission.c": "cassé"})
    assert etat.read_states(ALICE) == [{"exercice_id": "tp2-ex3", "statut": "valide"}]
    assert etat.write_state(ALICE, "tp2-ex3", "parfait", {}) is False
    print("ok   brouillon, état, et « valide » qui ne recule pas")


def tentatives():
    verdict = {"status": "ok", "total": 3, "passed": 3}
    assert etat.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert etat.write_practice_attempt(ALICE, "job-1", "tp2-ex3", verdict)
    assert etat.write_practice_attempt(ALICE, "job-2", "tp2-ex3",
                                       {"status": "ok", "total": 3, "passed": 1})
    assert etat.read_practice_summary(ALICE) == [
        {"exercice_id": "tp2-ex3", "tentatives": 2, "reussites": 1}]
    # Un verdict malformé ne doit pas violer le CHECK (reussis <= total) : la
    # borne est côté Python ET côté schéma, et c'est le schéma qu'on éprouve.
    assert etat.write_practice_attempt(ALICE, "job-3", "tp2-ex3",
                                       {"status": "ok", "total": 1, "passed": 9})
    print("ok   tentative de pratique : idempotente par job, bornée par le schéma")


def attributions():
    """LE CŒUR DE CE FICHIER : la CTE modifiante qui alimente l'INSERT."""
    accorde = etat.grant_first_solve(
        ALICE, "tp2-ex3", "reussite:tp2-ex3", 15, "première réussite",
        "pilote-1", {"job": "job-1", "difficulte": "foundation"}, 100)
    assert accorde == 15, accorde
    # REJOUER LE MÊME FAIT N'ACCORDE RIEN. C'est la seule chose qui rend le
    # sondage HTTP, un worker relancé et un exercice refait inoffensifs.
    for _ in range(3):
        assert etat.grant_first_solve(
            ALICE, "tp2-ex3", "reussite:tp2-ex3", 15, "première réussite",
            "pilote-1", {"job": "job-9"}, 100) is None
    assert compte("transaction_xp", ALICE) == 1
    assert compte("evenement_progression", ALICE) == 1

    # LE PLAFOND EST CALCULÉ DANS L'INSTRUCTION. Au-delà, le fait s'enregistre
    # à zéro plutôt que de disparaître -- et le CHECK (montant >= 0) l'accepte.
    assert etat.grant_first_solve(
        ALICE, "tp2-ex0", "reussite:tp2-ex0", 30, "première réussite",
        "pilote-1", {"job": "job-4"}, 20) == 5           # 20 - 15 déjà accordés
    assert etat.grant_first_solve(
        ALICE, "tp6-ex1", "reussite:tp6-ex1", 30, "première réussite",
        "pilote-1", {"job": "job-5"}, 20) == 0           # plafond atteint
    assert compte("transaction_xp", ALICE) == 3
    print("ok   attribution : une fois par fait, plafond appliqué dans la même "
          "instruction")


def succes_et_lecture():
    # `unnest(%s::text[])` : un tableau paramétré, pas une liste de VALUES
    # construite en Python. C'est la forme qui n'existe qu'en vrai SQL.
    assert etat.unlock(ALICE, ["premiere-reussite", "premiere-competence"],
                       "reussite:tp2-ex3", "pilote-1")
    assert etat.unlock(ALICE, ["premiere-reussite", "cinq-reussites"],
                       "reussite:tp2-ex0", "pilote-1")
    assert compte("succes_obtenu", ALICE) == 3          # pas 4 : un doublon
    assert etat.unlock(ALICE, [], "reussite:tp2-ex3", "pilote-1")

    vue = etat.read_progress(ALICE)
    assert vue["xp"] == 20, vue                          # 15 + 5 + 0
    # CHRONOLOGIQUE D'ABORD, alphabétique à égalité d'horodatage. Les deux
    # premiers sont arrivés dans la même instruction, donc à la même
    # microseconde : sans le `succes_id` en second critère, leur ordre serait
    # celui que Postgres a envie de rendre, et il changerait d'un appel à
    # l'autre sous les yeux de l'étudiant.
    assert [s["id"] for s in vue["succes"]] == [
        "premiere-competence", "premiere-reussite", "cinq-reussites"], vue["succes"]
    assert all(len(s["obtenu_le"]) == 10 for s in vue["succes"]), vue["succes"]
    assert len(vue["transactions"]) == 3
    assert vue["transactions"][0]["motif"] == "première réussite"
    print("ok   succès sans doublon, et lecture des faits (dates au jour)")


def cloisonnement():
    """CE QUI COMPTE VRAIMENT : personne ne voit ni n'efface chez le voisin."""
    assert etat.write_draft(BOB, "tp2-ex3", {"submission.c": "// bob"})
    assert etat.grant_first_solve(
        BOB, "tp2-ex3", "reussite:tp2-ex3", 15, "première réussite",
        "pilote-1", {"job": "job-b"}, 100) == 15
    # LE MÊME IDENTIFIANT D'ÉVÉNEMENT CHEZ DEUX ÉTUDIANTS : la clé primaire
    # porte `utilisateur`, donc « reussite:tp2-ex3 » n'appartient à personne.
    # Une clé primaire sur le seul identifiant aurait donné à Bob l'XP d'Alice.
    assert etat.unlock(BOB, ["premiere-reussite"], "reussite:tp2-ex3", "pilote-1")
    assert etat.read_progress(BOB)["xp"] == 15
    assert etat.read_progress(ALICE)["xp"] == 20
    print("ok   deux comptes, le même fait, aucun mélange")


def forum():
    """Le forum : un fil par exercice, un signalement unique, une modération
    journalisée -- et la CTE modifiante qui écrit l'état ET le journal d'un coup.
    """
    m1, m2 = "a" * 32, "b" * 32
    assert etat.forum_publier(m1, "tp2-ex3", ALICE, "Pourquoi ma boucle tourne ?")
    assert etat.forum_publier(m2, "tp2-ex3", BOB, "j'ai le même souci")
    assert etat.forum_publier("c" * 32, "tp2-ex0", BOB, "autre exercice")
    fil = etat.forum_fil("tp2-ex3", 200)
    assert [m["id"] for m in fil] == [m1, m2], fil
    assert fil[0]["utilisateur"] == ALICE and fil[0]["masque"] is False
    # À LA MINUTE, pas au jour : un fil se lit dans l'ordre. ET EN UTC EXPLICITE
    # : sans le « Z », la page affiche l'heure du serveur comme si elle était
    # celle du lecteur.
    assert len(fil[0]["cree_le"]) == 17 and fil[0]["cree_le"].endswith("Z"),         fil[0]["cree_le"]
    # UN FIL PAR EXERCICE : rien ne fuit d'un exercice à l'autre.
    assert len(etat.forum_fil("tp2-ex0", 200)) == 1
    assert etat.forum_fil("tp2-ex3", 1) == fil[:1]        # la borne s'applique

    # LA CLÉ PRIMAIRE EST LA RÈGLE : deux fois le même signalement, une ligne.
    assert etat.forum_signaler(m2, ALICE) == [(m2,)]
    assert etat.forum_signaler(m2, ALICE) == []
    # Et un identifiant inventé n'insère RIEN -- pas de ligne orpheline portant
    # un `sub` pour rien. C'est le `SELECT ... FROM forum_message` qui le tient.
    assert etat.forum_signaler("f" * 32, ALICE) == []
    assert compte("forum_signalement", ALICE) == 1
    assert etat.forum_signaler(m2, BOB) == [(m2,)]        # deux comptes, oui
    file_mod = etat.forum_signalements(200)
    assert len(file_mod) == 1, file_mod
    assert file_mod[0]["id"] == m2 and file_mod[0]["signalements"] == 2
    assert file_mod[0]["texte"] == "j'ai le même souci"
    assert file_mod[0]["exercice_id"] == "tp2-ex3"

    # MASQUER, PUIS RÉTABLIR : l'état change, le journal s'ajoute, dans UNE
    # instruction. Deux `_query` en autocommit laisseraient un message masqué
    # que rien n'explique si la connexion tombait entre les deux.
    assert etat.forum_moderer("d" * 32, m2, ALICE, "masquer") == [(m2,)]
    assert etat.forum_fil("tp2-ex3", 200)[1]["masque"] is True
    assert etat.forum_moderer("e" * 32, m2, ALICE, "retablir") == [(m2,)]
    assert etat.forum_fil("tp2-ex3", 200)[1]["masque"] is False
    assert compte("forum_moderation", ALICE) == 2        # AJOUT SEUL : les deux
    assert etat.forum_moderer("9" * 32, "f" * 32, ALICE, "masquer") == []
    # LE CHECK DU SCHÉMA, ÉPROUVÉ SANS PASSER PAR LA GARDE PYTHON : deux actions
    # existent, et c'est Postgres qui refuse la troisième.
    assert etat._query(
        "INSERT INTO forum_moderation"
        " (action_id, message_id, utilisateur, action)"
        " VALUES (%s, %s, %s, 'supprimer')",
        ("7" * 32, m2, ALICE)) is None

    # SUPPRIMER LE SIEN, JAMAIS CELUI D'UN AUTRE. La clause `utilisateur` EST le
    # contrôle d'accès : il n'y a pas de lecture préalable à faire mentir.
    assert etat.forum_supprimer(m2, ALICE) == []          # pas le sien
    assert etat.forum_supprimer(m1, ALICE) == [(m1,)]
    assert etat.forum_supprimer(m1, ALICE) == []          # déjà parti
    assert [m["id"] for m in etat.forum_fil("tp2-ex3", 200)] == [m2]
    # On lui en redonne un : `suppression()` plus bas vérifie que CHAQUE table
    # avait quelque chose à effacer.
    assert etat.forum_publier("1" * 32, "tp2-ex3", ALICE, "je reviens")
    print("ok   forum : fil par exercice, signalement unique, modération "
          "journalisée")


def identite():
    """Le nom choisi et le numéro de groupe : un JOURNAL dont la dernière ligne
    fait foi.

    LES DEUX FORMES QUI NE SE VÉRIFIENT QUE SUR UNE VRAIE BASE : le
    `DISTINCT ON (utilisateur) ... ORDER BY utilisateur, cree_le DESC` qui
    ramène le dernier profil de plusieurs comptes en une passe, et la jointure
    LATERAL qui accroche ce même dernier profil à chaque nom signalé. Les deux
    compilent dans la tête.
    """
    # Rien de posé : ce n'est pas une erreur, c'est l'anonymat par défaut.
    assert etat.forum_profils([ALICE, BOB]) == {}
    assert etat.forum_profil(ALICE) == {"pseudo": None, "groupe": None,
                                        "pseudo_public": False,
                                        "groupe_public": False}
    assert etat.forum_profil_ecrire("p" * 32, ALICE, "Alice", 3, True, False)
    assert etat.forum_profil_ecrire("q" * 32, BOB, "Bob", 7, False, True)
    # LA DERNIÈRE LIGNE FAIT FOI, et l'ancienne reste : changer de nom n'efface
    # pas l'historique qu'une modération veut pouvoir relire.
    assert etat.forum_profil_ecrire("r" * 32, ALICE, "Alice B", 3, True, True)
    assert compte("forum_profil", ALICE) == 2
    profils = etat.forum_profils([ALICE, BOB, "sub-personne"])
    assert profils[ALICE] == {"pseudo": "Alice B", "groupe": 3,
                              "pseudo_public": True, "groupe_public": True}
    assert profils[BOB]["pseudo"] == "Bob" and profils[BOB]["groupe"] == 7
    assert "sub-personne" not in profils
    # LE CHECK DU SCHÉMA, ÉPROUVÉ SANS PASSER PAR LA GARDE PYTHON : un groupe
    # va de 1 à 99, et c'est Postgres qui refuse le reste.
    assert etat.forum_profil_ecrire("s" * 32, ALICE, "Alice", 0, False, False)         is False
    assert etat.forum_profil_ecrire("t" * 32, ALICE, "Alice", 100, False, False)         is False

    # SIGNALER UN NOM : mêmes deux protections que pour un message.
    message = etat.forum_fil("tp2-ex3", 200)[0]["id"]
    assert etat.forum_auteur(message) in (ALICE, BOB)
    assert etat.forum_auteur("f" * 32) is None
    assert etat.forum_nom_signaler(message, BOB) == [(message,)]
    assert etat.forum_nom_signaler(message, BOB) == []      # une seule fois
    assert etat.forum_nom_signaler("f" * 32, BOB) == []     # rien d'orphelin
    signales = etat.forum_noms_signales(200)
    assert len(signales) == 1 and signales[0]["id"] == message, signales
    # LA JOINTURE LATERAL : le nom rendu est le DERNIER, pas le premier.
    auteur = etat.forum_auteur(message)
    assert signales[0]["pseudo"] == etat.forum_profils([auteur])[auteur]["pseudo"]
    assert signales[0]["signalements"] == 1
    print("ok   identité : journal, dernière ligne, bornes du schéma, "
          "nom signalé")


def forum_privileges():
    """Le GRANT du forum : l'API met à jour `masque`, ET RIEN D'AUTRE.

    Y COMPRIS SUR LE PROFIL : le nom choisi et sa visibilité sont un journal en
    ajout seul, sans aucune colonne modifiable.

    C'est un GRANT DE COLONNE (`UPDATE (masque)`), pas un `UPDATE` de table. Un
    message est immuable : l'API ne doit pas pouvoir réécrire le texte de
    quelqu'un, ni changer l'auteur d'un signalement, ni retoucher le journal de
    modération. La propriété ne dépend donc pas de la discipline de `etat.py`.

    Non joué quand les deux DSN sont le même -- il n'y aurait rien à refuser.
    """
    if ADMIN_DSN == DSN:
        print("--   privilèges du forum : NON JOUÉ (pas de CTESTER_DB_ADMIN_DSN "
              "distinct)")
        return
    import psycopg
    essais = (
        ("forum_message.texte", "UPDATE forum_message SET texte = 'réécrit'"),
        ("forum_message.utilisateur",
         "UPDATE forum_message SET utilisateur = 'sub-x'"),
        ("forum_signalement",
         "UPDATE forum_signalement SET utilisateur = 'sub-x'"),
        ("forum_moderation",
         "UPDATE forum_moderation SET action = 'retablir'"),
        # L'IDENTITÉ EST UN JOURNAL, ELLE AUSSI : on ajoute une ligne, on ne
        # réécrit pas le nom que quelqu'un s'est donné. Sans ce refus-là, une
        # requête distraite pourrait renommer un étudiant en silence.
        ("forum_profil.pseudo", "UPDATE forum_profil SET pseudo = 'autre'"),
        ("forum_profil.pseudo_public",
         "UPDATE forum_profil SET pseudo_public = true"),
        ("forum_nom_signale",
         "UPDATE forum_nom_signale SET utilisateur = 'sub-x'"),
    )
    refuses = []
    for nom, sql in essais:
        with psycopg.connect(DSN, autocommit=True) as cx:
            try:
                cx.execute(sql)
            except psycopg.errors.InsufficientPrivilege:
                refuses.append(nom)
    assert len(refuses) == len(essais), "UPDATE accepté quelque part : " \
                                       + str(refuses)
    # ET `masque` PASSE : c'est le seul état que la modération a besoin de
    # changer, et le seul que le GRANT accorde. Sans ce contrôle-ci, un GRANT
    # trop étroit rendrait la modération muette sans que rien ne le dise.
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("UPDATE forum_message SET masque = masque")
    print("ok   forum : seul `masque` est modifiable, le reste est en ajout seul")


def suppression():
    avant = {t: compte(t, ALICE) for t in TABLES}
    assert all(avant.values()), "test inutile : il n'y a rien à effacer " + str(avant)
    assert etat.forget(ALICE)
    apres = {t: compte(t, ALICE) for t in TABLES}
    assert not any(apres.values()), apres
    # LES ONZE DELETE SONT DANS UNE SEULE INSTRUCTION, et les CTE non
    # référencées s'exécutent quand même -- c'est ce qu'on vérifie ici, pas la
    # documentation de PostgreSQL.
    assert compte("brouillon_exercice", BOB) == 1, "effacé chez le voisin !"
    assert etat.read_progress(BOB)["xp"] == 15
    # ET LES MESSAGES DU VOISIN RESTENT. Effacer son compte n'efface pas la
    # conversation des autres -- seulement ce que cette personne a écrit.
    assert compte("forum_message", BOB) == 2, "message effacé chez le voisin !"
    assert compte("forum_signalement", BOB) == 1
    assert etat.forget(ALICE)                            # rejouable
    print("ok   « Supprimer mes données » vide les onze tables, et seulement "
          "les siennes")


def main():
    appliquer_schema()
    ajout_seul()
    for user in (ALICE, BOB):
        etat.forget(user)
    brouillons_et_etats()
    tentatives()
    attributions()
    succes_et_lecture()
    cloisonnement()
    forum()
    identite()
    forum_privileges()
    suppression()
    etat.forget(BOB)
    print("\nle SQL tient sur un vrai PostgreSQL.")


if __name__ == "__main__":
    main()
