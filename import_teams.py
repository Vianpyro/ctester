#!/usr/bin/env python3
"""Load an assignment's team roster into the database. INSTRUCTOR SIDE ONLY.

    CTESTER_DB_ADMIN_DSN=postgresql://postgres:...@host/ctester \\
      python3 import_teams.py devoir roster.csv

THIS SCRIPT IS THE ONLY WAY AN ACCOUNT GETS ONTO A TEAM, and that is the
point rather than a limitation. The API's role has `SELECT` on `team` and
`SELECT, DELETE` on `team_member` -- no INSERT, no UPDATE (see the GRANT in
VHome). So there is no request, and no bug in a request handler, that can put
somebody on a team: a student who could choose their team could choose the one
whose work is furthest along, and "one submission per team" would stop meaning
anything.

    A GROUP IS NOT A TEAM. `group_number` here is the course section the
    instructor assigned; it is written on the team, not read from
    `forum_profile`, whose group number the STUDENT types in for themselves.
    The two are never compared.

THE CSV IS THE ROSTER, AND IT IS AUTHORITATIVE. Memberships for this
assignment that are not in the file are removed; teams that are not in it are
left alone, because deleting a team would orphan the documents it wrote. To
retire a team, remove its members and delete the row by hand -- a destructive
step deserves a deliberate one.

Columns, with a header line:

    team_id,group_number,label,account
    g04-e01,4,Équipe 1,9f3c...-sub-from-rauthy
    g04-e01,4,Équipe 1,2b71...
    g04-e02,4,Équipe 2,c0d9...

`account` IS THE OPAQUE OIDC `sub`, not a name, not a student number, not an
email -- this database has never held any of those and this feature does not
start. Rauthy's admin console lists them; so does `SELECT DISTINCT account
FROM exercise_state` once a student has submitted anything.
"""

import argparse
import collections
import csv
import os
import re
import sys

DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or os.environ.get("CTESTER_DB_DSN", "")

# A TEAM ID IS A HANDLE, NOT A LABEL, and it is bounded HERE because it is the
# one value from this file that travels furthest: it keys the shared document,
# names the collaboration room, and ends up in the archive's
# `Content-Disposition` header. A quote or a newline in there would be header
# injection, delivered by a spreadsheet. What students read is `label`, which
# is free text and only ever crosses as JSON.
TEAM_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,62}\Z")


def read_roster(path):
    """[(team_id, group_number, label, account)] -- or raise with what is wrong.

    EVERY LINE IS CHECKED BEFORE ANY LINE IS WRITTEN. A roster half-loaded
    because line 30 had a typo is worse than one not loaded at all: the
    instructor would see "done", and three students would silently have no
    team on the morning of the lab.
    """
    rows, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for number, row in enumerate(csv.DictReader(fh), 2):
            team_id = (row.get("team_id") or "").strip()
            account = (row.get("account") or "").strip()
            # LE LIBELLE EST DU TEXTE LIBRE, et il finit dans du SQL genere
            # (`--sql`) : les caracteres de controle deviennent des espaces
            # plutot que de disparaitre -- retirer un saut de ligne collerait
            # deux mots ensemble, ce qui change le nom au lieu de le nettoyer.
            label = " ".join("".join(
                c if c >= " " else " " for c in (row.get("label") or "")).split())
            label = label[:64] or None
            raw_group = (row.get("group_number") or "").strip()
            if not team_id or not account:
                errors.append("line %d: team_id and account are required" % number)
                continue
            if not TEAM_ID_RE.match(team_id):
                errors.append("line %d: team_id must be letters, digits, "
                              "'.', '_' or '-' (got %r)" % (number, team_id[:32]))
                continue
            if not raw_group.isdigit() or not 1 <= int(raw_group) <= 99:
                errors.append("line %d: group_number must be 1..99" % number)
                continue
            if len(account) > 128:
                errors.append("line %d: account is too long to be a `sub`" % number)
                continue
            rows.append((team_id, int(raw_group), label, account))
    if not rows:
        errors.append("the roster is empty")
    # ONE TEAM PER ACCOUNT, checked here as well as by the primary key. The
    # constraint would refuse the second row with a message about an index;
    # this one names the student's line.
    seen = {}
    for team_id, _group, _label, account in rows:
        if seen.setdefault(account, team_id) != team_id:
            errors.append("%s appears on two teams (%s and %s)"
                          % (account[:12] + "…", seen[account], team_id))
    # A `team_id` IS GLOBAL TO THE ASSIGNMENT, NOT RELATIVE TO A GROUP -- the
    # primary key is (team_id, assignment_id), and `group_number` is not in it.
    # So `1,4,...` and `1,6,...` are NOT two independent "team 1"s: they are ONE
    # team straddling two groups, sharing one document, with whichever group
    # number was written last. That is the quietest way this roster can go
    # wrong, and Postgres cannot see it -- both lines are perfectly valid.
    #
    # THE FIX IS A NAMING CONVENTION, and this refusal is what makes it one:
    # `g04-e01` and `g06-e01` carry the group in the handle. `label` is free to
    # read "Équipe 1" in both -- it is what students see, and it never has to
    # be unique.
    groupes = {}
    for team_id, group, _label, _account in rows:
        if groupes.setdefault(team_id, group) != group:
            errors.append(
                "team_id %r is used by group %d AND group %d -- a team id is "
                "global to the assignment, so these would be ONE team sharing "
                "one document. Prefix it with the group (g%02d-%s, g%02d-%s); "
                "the `label` may stay the same in both."
                % (team_id, groupes[team_id], group,
                   groupes[team_id], team_id, group, team_id))
            groupes[team_id] = group
    if errors:
        raise SystemExit("roster refused, nothing was written:\n- "
                         + "\n- ".join(errors))
    return rows


def sizes(rows):
    """{team_id: members} -- what the caller prints, and checks against the
    assignment's own `team.min`/`team.max` if it wants to."""
    counts = collections.Counter(team_id for team_id, _, _, _ in rows)
    return dict(counts)


def statements(rows, assignment_id):
    """[(sql, params)] -- LE listage, en instructions. UNE seule source.

    `load()` les execute avec psycopg, `--sql` les imprime pour psql. Deux
    chemins qui ecriraient chacun leur SQL finiraient par ne plus ecrire la
    meme chose, et celui qui divergerait serait celui qu'on utilise le jour ou
    l'autre ne marche pas.
    """
    equipes = {}
    for team_id, group_number, label, _account in rows:
        equipes[team_id] = (group_number, label)
    sql = []
    for team_id, (group_number, label) in sorted(equipes.items()):
        sql.append((
            "INSERT INTO team (team_id, assignment_id, group_number, label)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (team_id, assignment_id) DO UPDATE SET"
            "   group_number = EXCLUDED.group_number,"
            "   label = EXCLUDED.label",
            (team_id, assignment_id, group_number, label)))
    # THE FILE IS THE ROSTER: a membership that is no longer in it goes.
    # Scoped to THIS assignment -- another assignment's teams are not this
    # file's business.
    sql.append((
        "DELETE FROM team_member"
        " WHERE assignment_id = %s AND account <> ALL(%s)",
        (assignment_id, [account for _, _, _, account in rows])))
    for team_id, _group, _label, account in rows:
        # A STUDENT MOVED BETWEEN TEAMS IS AN UPDATE, not a duplicate: the
        # primary key is (assignment_id, account), so the conflict target is
        # the student, and what changes is their team.
        sql.append((
            "INSERT INTO team_member (team_id, assignment_id, account)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (assignment_id, account) DO UPDATE SET"
            "   team_id = EXCLUDED.team_id",
            (team_id, assignment_id, account)))
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

    equipes = {team_id for team_id, _, _, _ in rows}
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
    parser.add_argument("roster", help="CSV: team_id,group_number,label,account")
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
