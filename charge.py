#!/usr/bin/env python3
"""ctester -- test de charge. NE PAS LANCER PENDANT UNE SEANCE DE LABORATOIRE.

    python3 charge.py http://ctester-web-1:8000

Il ecrit dans la base, remplit la file et fait compiler pour de vrai. C'est un
outil de mesure avant cohorte, pas une sonde de supervision.

CONTRE L'ORIGINE, SUR LE LAN -- pas contre le nom public. Deux raisons:

  1. `client_id()` fait confiance a `CF-Connecting-IP` parce que Cloudflare
     l'ECRASE toujours. En tapant l'origine directement, ce script le pose
     lui-meme pour simuler N etudiants distincts. C'est le seul moyen d'eprouver
     les quotas au lieu de les subir depuis une seule IP -- et c'est le meme
     raccourci que CLAUDE.md documente deja: regulateur de charge, pas controle
     d'acces.
  2. Mesurer a travers Cloudflare mesurerait Cloudflare.

CE QU'IL NE MESURE PAS: le Dell. Le CPU, la RAM et la longueur reelle du spool
se lisent sur l'hote, PENDANT que ce script tourne:

    docker stats --no-stream ctester-web-1 ctester-postgres
    uptime; ls /opt/ctester/spool | wc -l
    journalctl -u 'ctester-runner@*' -n 50

LE JETON. `/progres` et `/brouillon` demandent un vrai jeton OIDC, et on ne
peut pas en fabriquer 200. `CTESTER_CHARGE_TOKEN` en prend UN, rejoue par tous
les fils. Ce qui est mesure reste juste: le cout serveur d'une lecture de
progression ne depend pas de QUI la demande -- meme travail SQL, meme verrou
global dans etat.py, et c'est ce verrou qu'on vient regarder. Sans jeton, les
phases privees sont annoncees non jouees plutot que sautees en silence.
"""

import http.client
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

CIBLE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CTESTER_CHARGE_URL", "")
if not CIBLE:
    raise SystemExit(__doc__)

ETUDIANTS = int(os.environ.get("CTESTER_CHARGE_ETUDIANTS", "200"))
SOUMISSIONS = int(os.environ.get("CTESTER_CHARGE_SOUMISSIONS", "40"))
TOKEN = os.environ.get("CTESTER_CHARGE_TOKEN", "")
KEY = os.environ.get("CTESTER_KEY", "")
TP = os.environ.get("CTESTER_CHARGE_TP", "")
PATIENCE = int(os.environ.get("CTESTER_CHARGE_PATIENCE", "180"))

URL = urllib.parse.urlparse(CIBLE)
HOTE, PORT = URL.hostname, URL.port or (443 if URL.scheme == "https" else 80)
BASE = URL.path.rstrip("/")


def appel(methode, chemin, corps=None, etudiant=0, jeton=False):
    """Une requete, chronometree. Rend (statut, secondes, charge decodee|None).

    Une connexion par appel: c'est ce que fait un navigateur qui vient de se
    reveiller, et ca evite qu'un pool masque le cout d'etablissement.
    """
    entetes = {"Content-Type": "application/json",
               # N etudiants distincts pour les quotas. Voir l'en-tete.
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
        # Un refus de connexion EST une mesure: c'est ce que voit l'etudiant.
        return 0, time.perf_counter() - debut, {"erreur": str(souci)}


class Mesures:
    """Les latences et les statuts d'une phase. Percentiles au rang le plus proche.

    PAS DE MOYENNE. Une moyenne de latence cache exactement ce qu'on vient
    chercher: la queue de distribution, c'est-a-dire l'etudiant qui attend.
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
            return "%-14s NON JOUE" % self.nom
        histo = " ".join("%s:%d" % (s or "panne", n)
                         for s, n in sorted(self.statuts.items()))
        return ("%-14s n=%-4d  p50=%6.0f ms  p95=%6.0f ms  p99=%6.0f ms  "
                "max=%6.0f ms  %s"
                % (self.nom, len(self.temps), self.centile(.50) * 1000,
                   self.centile(.95) * 1000, self.centile(.99) * 1000,
                   max(self.temps) * 1000, histo))

    def part_503(self):
        return self.statuts.get(503, 0) / max(len(self.temps), 1)


def en_parallele(mesure, combien, travail):
    """`combien` appels concurrents. Le parallelisme EST la charge.

    Zero est un reglage legitime -- on vient mesurer les lectures sans faire
    compiler quoi que ce soit -- et pas une erreur a faire lever.
    """
    if combien <= 0:
        print("%-14s NON JOUE (0 demande)" % mesure.nom)
        return mesure
    with ThreadPoolExecutor(max_workers=min(combien, 256)) as piscine:
        for statut, duree, _ in piscine.map(travail, range(combien)):
            mesure.ajouter(statut, duree)
    print(mesure.ligne())
    return mesure


def phase_page(mesures):
    """La visite anonyme: la page, sa feuille, son script, le catalogue.

    LE PLANCHER DE REFERENCE. Si celle-ci se degrade, ce n'est pas la
    progression qu'il faut regarder mais la machine.
    """
    mesures.append(en_parallele(
        Mesures("page"), ETUDIANTS,
        lambda n: appel("GET", "/", etudiant=n)))
    mesures.append(en_parallele(
        Mesures("catalogue"), ETUDIANTS,
        lambda n: appel("GET", "/tps.json", etudiant=n)))


def phase_privee(mesures):
    """Progression et autosauvegarde: tout ce qui passe par le verrou global.

    CE QU'ON VIENT MESURER. `GET /progres` fait CINQ allers-retours SQL
    serialises derriere le verrou unique de etat.py. C'est la que se decide
    s'il faut les regrouper en une seule lecture -- pas avant.
    """
    if not TOKEN:
        print("%-14s NON JOUE (CTESTER_CHARGE_TOKEN vide)" % "progres")
        print("%-14s NON JOUE (CTESTER_CHARGE_TOKEN vide)" % "brouillon")
        return
    mesures.append(en_parallele(
        Mesures("progres"), ETUDIANTS,
        lambda n: appel("GET", "/progres", etudiant=n, jeton=True)))
    if not TP:
        print("%-14s NON JOUE (CTESTER_CHARGE_TP vide)" % "brouillon")
        return
    corps = {"tp": TP, "files": {}}
    mesures.append(en_parallele(
        Mesures("brouillon"), ETUDIANTS,
        lambda n: appel("PUT", "/brouillon", corps, etudiant=n, jeton=True)))


def phase_soumissions(mesures):
    """La vague: SOUMISSIONS depots simultanes, puis on suit la file.

    Chaque depot fait vraiment compiler dans un conteneur gVisor. C'est la
    seule phase qui coute des coeurs au Dell, et la seule ou `ctester_workers`
    et `ctester_queue_max` se voient.
    """
    if not (KEY and TP):
        print("%-14s NON JOUE (CTESTER_KEY ou CTESTER_CHARGE_TP vide)" % "submit")
        return
    depot = Mesures("submit")
    jobs = []

    def soumettre(n):
        statut, duree, charge = appel(
            "POST", "/submit",
            {"key": KEY, "tp": TP,
             # Un corps different par etudiant: un juge qui deduplique les
             # soumissions identiques rendrait la mesure fausse et flatteuse.
             "files": {"submission.c": SOURCE % n}},
            etudiant=n)
        if statut == 200 and isinstance(charge, dict) and charge.get("id"):
            jobs.append(charge["id"])
        return statut, duree, charge

    en_parallele(depot, SOUMISSIONS, soumettre)
    if not depot.temps:
        return
    mesures.append(depot)
    print("               %d job(s) accepte(s), %.0f %% de 503 (file pleine)"
          % (len(jobs), depot.part_503() * 100))
    if jobs:
        suivre(mesures, jobs)


SOURCE = ("#include <stdio.h>\n"
          "int main(void) { printf(\"charge %%d\n\", %d); return 0; }\n")


def suivre(mesures, jobs):
    """Sonde les verdicts comme la page, et retient le pire rang vu dans la file.

    LE RANG MAXIMUM EST LA VRAIE MESURE DE CAPACITE. Un p99 flatteur sur
    /r/<id> ne dit rien: repondre << 37e >> en 4 ms reste repondre 37e.
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
    print("               rang max dans la file : %d -- %d job(s) encore en "
          "vol apres %d s" % (rang_max, len(restants), PATIENCE))


def main():
    print("cible      : %s" % CIBLE)
    print("etudiants  : %d   soumissions : %d" % (ETUDIANTS, SOUMISSIONS))
    print("jeton      : %s   exercice : %s\n"
          % ("oui" if TOKEN else "NON", TP or "(aucun)"))
    depart = time.time()
    mesures = []
    phase_page(mesures)
    phase_privee(mesures)
    phase_soumissions(mesures)
    print("\n--- %.0f s au total ---" % (time.time() - depart))
    pires = [m for m in mesures if m.part_503() > 0.01]
    if pires:
        print("503 AU-DELA DE 1 % : " + ", ".join(
            "%s %.0f %%" % (m.nom, m.part_503() * 100) for m in pires))
    lentes = [m for m in mesures if m.temps and m.centile(.95) > 1.0]
    if lentes:
        print("p95 AU-DELA D'UNE SECONDE : " + ", ".join(
            "%s %.0f ms" % (m.nom, m.centile(.95) * 1000) for m in lentes))
    if not pires and not lentes:
        print("aucun seuil franchi -- ne pas toucher a ctester_workers.")


if __name__ == "__main__":
    main()
