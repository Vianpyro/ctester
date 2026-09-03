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
est la frontière HTTP, pas le SQL. Or les écritures de progression ne sont pas
du SQL ordinaire -- une CTE modifiante qui alimente un INSERT, un `unnest`
d'un tableau paramétré, six DELETE dans une seule instruction. Ces formes
compilent dans la tête et échouent en production ; il n'y a pas de milieu.

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
          "evenement_progression", "transaction_xp", "succes_obtenu")

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


def suppression():
    avant = {t: compte(t, ALICE) for t in TABLES}
    assert all(avant.values()), "test inutile : il n'y a rien à effacer " + str(avant)
    assert etat.forget(ALICE)
    apres = {t: compte(t, ALICE) for t in TABLES}
    assert not any(apres.values()), apres
    # LES SIX DELETE SONT DANS UNE SEULE INSTRUCTION, et les CTE non
    # référencées s'exécutent quand même -- c'est ce qu'on vérifie ici, pas la
    # documentation de PostgreSQL.
    assert compte("brouillon_exercice", BOB) == 1, "effacé chez le voisin !"
    assert etat.read_progress(BOB)["xp"] == 15
    assert etat.forget(ALICE)                            # rejouable
    print("ok   « Supprimer mes données » vide les six tables, et seulement les "
          "siennes")


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
    suppression()
    etat.forget(BOB)
    print("\nle SQL tient sur un vrai PostgreSQL.")


if __name__ == "__main__":
    main()
