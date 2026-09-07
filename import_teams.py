#!/usr/bin/env python3
"""Load an assignment's team roster into the database. INSTRUCTOR SIDE ONLY.

    CTESTER_DB_ADMIN_DSN=postgresql://postgres:...@host/ctester \\
      python3 import_teams.py devoir roster.csv

THIS IS NOT THE MAIN PATH. Students pick their own team from a numbered list,
the way they already do on Moodle -- and the numbering matches, which is the
whole point. What is left here is the CORRECTION tool: move someone after the
assignment has opened (when the lists are frozen), place a student who never
picked one, undo a mistake.

    A GROUP IS NOT A TEAM, and teams are numbered WITHIN a group. « Équipe 7 »
    of group 04 and « Équipe 7 » of group 06 are two teams, with two
    documents; the handle carries both (`g04-e07`), and this script builds it
    exactly the way the join route does -- one construction, or the two would
    eventually name different teams with the same words.

THE CSV IS THE ROSTER, AND IT IS AUTHORITATIVE. Memberships for this
assignment that are not in the file are removed; teams that are not in it are
left alone, because deleting a team would orphan the documents it wrote and
renumber everything after it.

Columns, with a header line:

    group_number,number,account
    4,1,9f3c...-sub-from-rauthy
    4,1,2b71...
    6,3,c0d9...

`account` IS THE OPAQUE OIDC `sub`, not a name, not a student number, not an
email -- this database has never held any of those, and that is precisely why
the instructor cannot write this file from scratch. Rauthy's admin console
lists them; so does `SELECT DISTINCT account FROM exercise_state`.
"""

import argparse
import collections
import csv
import os
import sys

DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or os.environ.get("CTESTER_DB_DSN", "")

# Ce qu'une équipe s'appelle. Le mot est celui de l'énoncé, le numéro celui de
# Moodle -- et cette constante DOIT dire la même chose que
# `services/teams.TEAM_NAME`, sinon deux chemins d'écriture donneraient deux
# noms à la même équipe.
TEAM_NAME = "Équipe %d"


def team_handle(group_number, number):
    """`g04-e07`. LA MÊME CONSTRUCTION QUE `services/teams.team_handle()`.

    Recopiée plutôt qu'importée : ce script tourne avec le python de l'HÔTE,
    qui ne voit pas `app/` (voir `test_le_controle_de_l_hote_ne_depend_d_aucun_tiers`).
    Un test compare les deux, pour que la copie ne dérive pas.
    """
    return "g%02d-e%02d" % (int(group_number), int(number))


def read_roster(path):
    """[(group_number, number, account)] -- ou lève avec tout ce qui cloche.

    EVERY LINE IS CHECKED BEFORE ANY LINE IS WRITTEN. A roster half-loaded
    because line 30 had a typo is worse than one not loaded at all: the
    instructor would see "done", and three students would silently have no
    team on the morning of the lab.
    """
    rows, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for line, row in enumerate(csv.DictReader(fh), 2):
            account = (row.get("account") or "").strip()
            groupe = (row.get("group_number") or "").strip()
            numero = (row.get("number") or "").strip()
            if not account:
                errors.append("line %d: account is required" % line)
                continue
            if not groupe.isdigit() or not 1 <= int(groupe) <= 99:
                errors.append("line %d: group_number must be 1..99" % line)
                continue
            if not numero.isdigit() or not 1 <= int(numero) <= 99:
                errors.append("line %d: number must be 1..99" % line)
                continue
            if len(account) > 128:
                errors.append("line %d: account is too long to be a `sub`" % line)
                continue
            rows.append((int(groupe), int(numero), account))
    if not rows:
        errors.append("the roster is empty")
    # ONE TEAM PER ACCOUNT, checked here as well as by the primary key. The
    # constraint would refuse the second row with a message about an index;
    # this one names the student's line.
    seen = {}
    for groupe, numero, account in rows:
        equipe = team_handle(groupe, numero)
        if seen.setdefault(account, equipe) != equipe:
            errors.append("%s appears on two teams (%s and %s)"
                          % (account[:12] + "\u2026", seen[account], equipe))
    if errors:
        raise SystemExit("roster refused, nothing was written:\n- "
                         + "\n- ".join(errors))
    return rows


def sizes(rows):
    """{team_id: members} -- what the caller prints, and checks against the
    assignment's own `team.min`/`team.max` if it wants to."""
    return dict(collections.Counter(
        team_handle(groupe, numero) for groupe, numero, _ in rows))


def statements(rows, assignment_id):
    """[(sql, params)] -- LE listage, en instructions. UNE seule source.

    `load()` les exécute avec psycopg, `--sql` les imprime pour psql. Deux
    chemins qui écriraient chacun leur SQL finiraient par ne plus écrire la
    même chose, et celui qui divergerait serait celui qu'on utilise le jour où
    l'autre ne marche pas.
    """
    equipes = {}
    for groupe, numero, _account in rows:
        equipes[team_handle(groupe, numero)] = (groupe, numero)
    sql = []
    for team_id, (groupe, numero) in sorted(equipes.items()):
        # `DO NOTHING` PLUTÔT QUE `DO UPDATE` : une équipe qui existe déjà a
        # peut-être un document, et son numéro est celui de Moodle. Rien à
        # corriger dessus -- ce que ce script corrige, ce sont les
        # APPARTENANCES.
        sql.append((
            "INSERT INTO team"
            "   (team_id, assignment_id, group_number, number, label)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (team_id, assignment_id) DO NOTHING",
            (team_id, assignment_id, groupe, numero, TEAM_NAME % numero)))
    # THE FILE IS THE ROSTER: a membership that is no longer in it goes.
    # Scoped to THIS assignment -- another assignment's teams are not this
    # file's business.
    sql.append((
        "DELETE FROM team_member"
        " WHERE assignment_id = %s AND account <> ALL(%s)",
        (assignment_id, [account for _, _, account in rows])))
    for groupe, numero, account in rows:
        # A STUDENT MOVED BETWEEN TEAMS IS AN UPDATE, not a duplicate: the
        # primary key is (assignment_id, account), so the conflict target is
        # the student, and what changes is their team.
        sql.append((
            "INSERT INTO team_member (team_id, assignment_id, account)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (assignment_id, account) DO UPDATE SET"
            "   team_id = EXCLUDED.team_id",
            (team_handle(groupe, numero), assignment_id, account)))
    return sql


def _litteral(valeur):
    """Une valeur, citee pour psql.

    `standard_conforming_strings` est a `on` depuis PostgreSQL 9.1 : doubler
    l'apostrophe EST tout l'echappement, une barre oblique inverse reste une
    barre oblique inverse. Les trois autres formes ne viennent pas d'un
    fichier -- un entier valide par `read_roster`, un tableau de comptes, ou
    l'absence de libelle.
    """
    if valeur is None:
        return "NULL"
    if isinstance(valeur, bool):
        raise ValueError("un booleen n'a rien a faire dans ce listage")
    if isinstance(valeur, int):
        return str(valeur)
    if isinstance(valeur, list):
        return "ARRAY[" + ", ".join(_litteral(v) for v in valeur) + "]::text[]"
    return "'" + str(valeur).replace("'", "''") + "'"


def to_sql(rows, assignment_id):
    """Le listage en script pour `psql`. SANS psycopg, ET C'EST TOUT L'INTERET.

    Le python de l'hote du Dell n'a AUCUN paquet tiers, deliberement (voir
    `test_le_controle_de_l_hote_ne_depend_d_aucun_tiers`). Installer psycopg
    la-bas pour charger un listage deux fois par session mettrait une
    dependance sur la seule machine que le projet garde propre. Donc :

        python3 import_teams.py devoir roster.csv --sql \
          | docker exec -i ctester-postgres psql -U postgres -d ctester \
              -v ON_ERROR_STOP=1

    TOUTES LES VERIFICATIONS DE `read_roster()` TOURNENT QUAND MEME -- elles
    sont en Python pur, et c'est la moitie qui compte : le listage est refuse,
    en entier, avant qu'une seule ligne ne soit imprimee.

    UNE SEULE TRANSACTION, comme `load()` : ou bien l'appartenance de ce devoir
    est ce que dit le fichier, ou bien la base n'a pas bouge.
    """
    lignes = ["BEGIN;"]
    for sql, params in statements(rows, assignment_id):
        rendu = sql
        for valeur in params:
            rendu = rendu.replace("%s", _litteral(valeur), 1)
        lignes.append(rendu + ";")
    lignes.append("COMMIT;")
    return "\n".join(lignes) + "\n"


def load(rows, assignment_id, dsn, dry_run=False):
    """Writes the roster in ONE transaction. Returns (teams, members, removed).

    ONE TRANSACTION, no autocommit: unlike the API -- which degrades rather
    than fails -- a roster that half-applies is a roster nobody can reason
    about. Either the assignment's membership is what the file says, or the
    database is untouched.
    """
    import psycopg

    equipes = {team_handle(groupe, numero) for groupe, numero, _ in rows}
    removed = 0
    with psycopg.connect(dsn) as cx:
        with cx.cursor() as cur:
            for sql, params in statements(rows, assignment_id):
                cur.execute(sql, params)
                if sql.startswith("DELETE"):
                    removed = cur.rowcount
            if dry_run:
                cx.rollback()
    return len(equipes), len(rows), removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("assignment", help="the published assignment's id")
    parser.add_argument("roster", help="CSV: group_number,number,account")
    parser.add_argument("--dry-run", action="store_true",
                        help="check and roll back, writing nothing")
    parser.add_argument("--sql", action="store_true",
                        help="print the script for psql instead of connecting"
                             " (needs no psycopg -- see to_sql)")
    args = parser.parse_args(argv)
    # `--sql` N'A BESOIN NI DE DSN NI DE PSYCOPG : c'est tout son interet sur
    # une machine que le projet garde sans dependance tierce. Le listage est
    # verifie AVANT d'imprimer quoi que ce soit.
    if args.sql:
        sys.stdout.write(to_sql(read_roster(args.roster), args.assignment))
        return 0
    if not DSN:
        return _fail("CTESTER_DB_ADMIN_DSN is empty: this script writes the "
                     "roster, so it needs the owner's connection string. "
                     "Or use --sql and pipe it into psql.")
    rows = read_roster(args.roster)
    for team_id, members in sorted(sizes(rows).items()):
        print("%-16s %d member(s)" % (team_id, members))
    try:
        teams, members, removed = load(rows, args.assignment, DSN, args.dry_run)
    except ImportError:
        return _fail("psycopg is missing: pip install 'psycopg[binary]'")
    print("%s: %d team(s), %d membership(s), %d removed%s"
          % (args.assignment, teams, members, removed,
             "  [DRY RUN, rolled back]" if args.dry_run else ""))
    return 0


def _fail(message):
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
