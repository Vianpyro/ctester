#!/usr/bin/env python3

import argparse
import collections
import csv
import os
import sys

DSN = os.environ.get("CTESTER_DB_ADMIN_DSN", "") or os.environ.get("CTESTER_DB_DSN", "")

TEAM_NAME = "Équipe %d"


def team_handle(group_number, number):
    # Duplicated from app/services/teams.py because the host Python cannot import app/.
    return "g%02d-e%02d" % (int(group_number), int(number))


def read_roster(path):
    """Validates every line before anything is written."""
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
    return dict(collections.Counter(
        team_handle(groupe, numero) for groupe, numero, _ in rows))


def statements(rows, assignment_id):
    equipes = {}
    for groupe, numero, _account in rows:
        equipes[team_handle(groupe, numero)] = (groupe, numero)
    sql = []
    for team_id, (groupe, numero) in sorted(equipes.items()):
        sql.append((
            "INSERT INTO team"
            "   (team_id, assignment_id, group_number, number, label)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (team_id, assignment_id) DO NOTHING",
            (team_id, assignment_id, groupe, numero, TEAM_NAME % numero)))
    sql.append((
        "DELETE FROM team_member"
        " WHERE assignment_id = %s AND account <> ALL(%s)",
        (assignment_id, [account for _, _, account in rows])))
    for groupe, numero, account in rows:
        sql.append((
            "INSERT INTO team_member (team_id, assignment_id, account)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (assignment_id, account) DO UPDATE SET"
            "   team_id = EXCLUDED.team_id",
            (team_handle(groupe, numero), assignment_id, account)))
    return sql


def _litteral(valeur):
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
    # For the Dell, whose host Python has no psycopg: pipe the output into psql.
    lignes = ["BEGIN;"]
    for sql, params in statements(rows, assignment_id):
        rendu = sql
        for valeur in params:
            rendu = rendu.replace("%s", _litteral(valeur), 1)
        lignes.append(rendu + ";")
    lignes.append("COMMIT;")
    return "\n".join(lignes) + "\n"


def load(rows, assignment_id, dsn, dry_run=False):
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
    parser = argparse.ArgumentParser(
        description="Load or correct an assignment's team roster.")
    parser.add_argument("assignment", help="the published assignment's id")
    parser.add_argument("roster", help="CSV: group_number,number,account")
    parser.add_argument("--dry-run", action="store_true",
                        help="check and roll back, writing nothing")
    parser.add_argument("--sql", action="store_true",
                        help="print the script for psql instead of connecting"
                             " (needs no psycopg -- see to_sql)")
    args = parser.parse_args(argv)
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
