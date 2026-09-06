#!/usr/bin/env python3
"""ctester -- load test. DO NOT RUN DURING A LAB SESSION.

    python3 load_test.py http://ctester-web-1:8000

It writes to the database, fills the queue and makes real compilations
happen. This is a pre-cohort measurement tool, not a monitoring probe.

AGAINST THE ORIGIN, ON THE LAN -- not against the public name. Two reasons:

  1. `client_id()` trusts `CF-Connecting-IP` because Cloudflare always
     OVERWRITES it. By hitting the origin directly, this script sets it
     itself to simulate N distinct students. That is the only way to exercise
     quotas instead of suffering them from a single IP -- and it is the same
     shortcut CLAUDE.md already documents: a load regulator, not access
     control.
  2. Measuring through Cloudflare would measure Cloudflare.

WHAT IT DOES NOT MEASURE: the Dell. CPU, RAM and the spool's real length are
read on the host, WHILE this script runs:

    docker stats --no-stream ctester-web-1 ctester-postgres
    uptime; ls /opt/ctester/spool | wc -l
    journalctl -u 'ctester-runner@*' -n 50

THE TOKEN. `/progres` and `/brouillon` require a real OIDC token, and 200 of
them cannot be manufactured. `CTESTER_LOAD_TOKEN` takes ONE, replayed by every
thread. What gets measured stays valid: a progression read's server cost does
not depend on WHO requests it -- same SQL work, same global lock in
state.py, and that lock is what we come here to look at. Without a token,
the private phases are reported as not played rather than silently skipped.
"""

import http.client
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

CIBLE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CTESTER_LOAD_URL", "")
if not CIBLE:
    raise SystemExit(__doc__)

ETUDIANTS = int(os.environ.get("CTESTER_LOAD_STUDENTS", "200"))
SOUMISSIONS = int(os.environ.get("CTESTER_LOAD_SUBMISSIONS", "40"))
TOKEN = os.environ.get("CTESTER_LOAD_TOKEN", "")
KEY = os.environ.get("CTESTER_KEY", "")
TP = os.environ.get("CTESTER_LOAD_EXERCISE", "")
PATIENCE = int(os.environ.get("CTESTER_LOAD_PATIENCE", "180"))

URL = urllib.parse.urlparse(CIBLE)
HOTE, PORT = URL.hostname, URL.port or (443 if URL.scheme == "https" else 80)
BASE = URL.path.rstrip("/")


def appel(methode, chemin, corps=None, etudiant=0, jeton=False):
    """One timed request. Returns (status, seconds, decoded payload|None).

    One connection per call: that is what a browser waking up from sleep
    does, and it keeps a pool from hiding the cost of establishing one.
    """
    entetes = {"Content-Type": "application/json",
               # N distinct students for quota purposes. See the header.
               "CF-Connecting-IP": "10.90.%d.%d" % (etudiant // 250, etudiant % 250)}
    if jeton and TOKEN:
        entetes["Authorization"] = "Bearer " + TOKEN
    fabrique = (http.client.HTTPSConnection if URL.scheme == "https"
                else http.client.HTTPConnection)
    debut = time.perf_counter()
    try:
        cx = fabrique(HOTE, PORT, timeout=30)
        cx.request(methode, BASE + chemin,
                   None if corps is None else json.dumps(corps), entetes)
        reponse = cx.getresponse()
        brut = reponse.read()
        cx.close()
        try:
            return reponse.status, time.perf_counter() - debut, json.loads(brut)
        except ValueError:
            return reponse.status, time.perf_counter() - debut, None
    except Exception as souci:
        # A connection refusal IS a measurement: it is what the student sees.
        return 0, time.perf_counter() - debut, {"erreur": str(souci)}


class Mesures:
    """A phase's latencies and statuses. Percentiles at the nearest rank.

    NO AVERAGE. A latency average hides exactly what we came here to find:
    the tail of the distribution, i.e. the student who is waiting.
    """

    def __init__(self, nom):
        self.nom = nom
        self.temps = []
        self.statuts = {}

    def ajouter(self, statut, secondes):
        self.temps.append(secondes)
        self.statuts[statut] = self.statuts.get(statut, 0) + 1

    def centile(self, part):
        if not self.temps:
            return 0.0
        ordonnes = sorted(self.temps)
        rang = max(0, min(len(ordonnes) - 1, round(part * len(ordonnes)) - 1))
        return ordonnes[rang]

    def ligne(self):
        if not self.temps:
            return "%-14s NOT PLAYED" % self.nom
        histo = " ".join("%s:%d" % (s or "failure", n)
                         for s, n in sorted(self.statuts.items()))
        return ("%-14s n=%-4d  p50=%6.0f ms  p95=%6.0f ms  p99=%6.0f ms  "
                "max=%6.0f ms  %s"
                % (self.nom, len(self.temps), self.centile(.50) * 1000,
                   self.centile(.95) * 1000, self.centile(.99) * 1000,
                   max(self.temps) * 1000, histo))

    def part_503(self):
        return self.statuts.get(503, 0) / max(len(self.temps), 1)


def en_parallele(mesure, combien, travail):
    """`combien` concurrent calls. Concurrency IS the load.

    Zero is a legitimate setting -- measuring reads with nothing compiled at
    all -- not an error to raise on.
    """
    if combien <= 0:
        print("%-14s NOT PLAYED (0 requested)" % mesure.nom)
        return mesure
    with ThreadPoolExecutor(max_workers=min(combien, 256)) as piscine:
        for statut, duree, _ in piscine.map(travail, range(combien)):
            mesure.ajouter(statut, duree)
    print(mesure.ligne())
    return mesure


def phase_page(mesures):
    """The anonymous visit: the page, its stylesheet, its script, the catalog.

    THE BASELINE FLOOR. If this one degrades, it is not progression that
    needs looking at but the machine.
    """
    mesures.append(en_parallele(
        Mesures("page"), ETUDIANTS,
        lambda n: appel("GET", "/", etudiant=n)))
    mesures.append(en_parallele(
        Mesures("catalogue"), ETUDIANTS,
        lambda n: appel("GET", "/catalog.json", etudiant=n)))


def phase_privee(mesures):
    """Progression and autosave: everything that goes through the global lock.

    WHAT WE CAME HERE TO MEASURE. `GET /progres` makes SIX serialized SQL
    round trips behind state.py's single lock. This is where it gets decided
    whether to group them into one read -- not before.
    """
    if not TOKEN:
        print("%-14s NOT PLAYED (CTESTER_LOAD_TOKEN empty)" % "progres")
        print("%-14s NOT PLAYED (CTESTER_LOAD_TOKEN empty)" % "brouillon")
        return
    mesures.append(en_parallele(
        Mesures("progres"), ETUDIANTS,
        lambda n: appel("GET", "/progres", etudiant=n, jeton=True)))
    if not TP:
        print("%-14s NOT PLAYED (CTESTER_LOAD_EXERCISE empty)" % "brouillon")
        return
    corps = {"exercise_id": TP, "files": {}}
    mesures.append(en_parallele(
        Mesures("brouillon"), ETUDIANTS,
        lambda n: appel("PUT", "/brouillon", corps, etudiant=n, jeton=True)))


def phase_soumissions(mesures):
    """The wave: SOUMISSIONS simultaneous drops, then the queue is followed.

    Every drop makes a real compilation happen in a gVisor container. This is
    the only phase that costs Dell cores, and the only one where
    `ctester_workers` and `ctester_queue_max` show themselves.
    """
    if not (KEY and TP):
        print("%-14s NOT PLAYED (CTESTER_KEY or CTESTER_LOAD_EXERCISE empty)" % "submit")
        return
    depot = Mesures("submit")
    jobs = []

    def soumettre(n):
        statut, duree, charge = appel(
            "POST", "/submit",
            {"key": KEY, "exercise_id": TP,
             # A different body per student: a judge that deduplicates
             # identical submissions would make the measurement wrong and
             # flattering.
             "files": {"submission.c": SOURCE % n}},
            etudiant=n)
        if statut == 200 and isinstance(charge, dict) and charge.get("id"):
            jobs.append(charge["id"])
        return statut, duree, charge

    en_parallele(depot, SOUMISSIONS, soumettre)
    if not depot.temps:
        return
    mesures.append(depot)
    print("               %d job(s) accepted, %.0f %% 503s (queue full)"
          % (len(jobs), depot.part_503() * 100))
    if jobs:
        suivre(mesures, jobs)


SOURCE = ("#include <stdio.h>\n"
          "int main(void) { printf(\"charge %%d\n\", %d); return 0; }\n")


def suivre(mesures, jobs):
    """Polls verdicts like the page does, and keeps the worst rank seen in the queue.

    THE MAXIMUM RANK IS THE TRUE MEASURE OF CAPACITY. A flattering p99 on
    /r/<id> says nothing: answering "37th" in 4 ms is still answering 37th.
    """
    sondage = Mesures("verdict")
    rang_max, restants, limite = 0, list(jobs), time.time() + PATIENCE
    while restants and time.time() < limite:
        encore = []
        for n, job in enumerate(restants):
            statut, duree, charge = appel("GET", "/r/" + job, etudiant=n)
            sondage.ajouter(statut, duree)
            if not isinstance(charge, dict):
                continue
            rang_max = max(rang_max, charge.get("position") or 0)
            if charge.get("state") in ("queued", "running"):
                encore.append(job)
        restants = encore
        if restants:
            time.sleep(2)
    mesures.append(sondage)
    print(sondage.ligne())
    print("               max queue rank: %d -- %d job(s) still in flight "
          "after %d s" % (rang_max, len(restants), PATIENCE))


def main():
    print("target     : %s" % CIBLE)
    print("students   : %d   submissions : %d" % (ETUDIANTS, SOUMISSIONS))
    print("token      : %s   exercise : %s\n"
          % ("yes" if TOKEN else "NO", TP or "(none)"))
    depart = time.time()
    mesures = []
    phase_page(mesures)
    phase_privee(mesures)
    phase_soumissions(mesures)
    print("\n--- %.0f s total ---" % (time.time() - depart))
    pires = [m for m in mesures if m.part_503() > 0.01]
    if pires:
        print("503s ABOVE 1%: " + ", ".join(
            "%s %.0f %%" % (m.nom, m.part_503() * 100) for m in pires))
    lentes = [m for m in mesures if m.temps and m.centile(.95) > 1.0]
    if lentes:
        print("p95 ABOVE ONE SECOND: " + ", ".join(
            "%s %.0f ms" % (m.nom, m.centile(.95) * 1000) for m in lentes))
    if not pires and not lentes:
        print("no threshold crossed -- leave ctester_workers alone.")


if __name__ == "__main__":
    main()
