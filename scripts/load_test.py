#!/usr/bin/env python3

import http.client
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

TARGET = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CTESTER_LOAD_URL", "")
if not TARGET:
    raise SystemExit("usage: python3 scripts/load_test.py http://ctester-web-1:8000"
                     "  (writes to the database: never during a lab)")

STUDENTS = int(os.environ.get("CTESTER_LOAD_STUDENTS", "200"))
SUBMISSIONS = int(os.environ.get("CTESTER_LOAD_SUBMISSIONS", "40"))
TOKEN = os.environ.get("CTESTER_LOAD_TOKEN", "")
KEY = os.environ.get("CTESTER_KEY", "")
TP = os.environ.get("CTESTER_LOAD_EXERCISE", "")
PATIENCE = int(os.environ.get("CTESTER_LOAD_PATIENCE", "180"))

URL = urllib.parse.urlparse(TARGET)
HOST, PORT = URL.hostname, URL.port or (443 if URL.scheme == "https" else 80)
BASE = URL.path.rstrip("/")


def call(method, path, body=None, student=0, token=False):
    headers = {"Content-Type": "application/json",
               "CF-Connecting-IP": "10.90.%d.%d" % (student // 250, student % 250)}
    if token and TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    factory = (http.client.HTTPSConnection if URL.scheme == "https"
                else http.client.HTTPConnection)
    start = time.perf_counter()
    try:
        cx = factory(HOST, PORT, timeout=30)
        cx.request(method, BASE + path,
                   None if body is None else json.dumps(body), headers)
        response = cx.getresponse()
        raw = response.read()
        cx.close()
        try:
            return response.status, time.perf_counter() - start, json.loads(raw)
        except ValueError:
            return response.status, time.perf_counter() - start, None
    except Exception as issue:
        return 0, time.perf_counter() - start, {"error": str(issue)}


class Measures:
    def __init__(self, name):
        self.name = name
        self.temps = []
        self.statuses = {}

    def add(self, status, seconds):
        self.temps.append(seconds)
        self.statuses[status] = self.statuses.get(status, 0) + 1

    def percentile(self, part):
        if not self.temps:
            return 0.0
        ordered = sorted(self.temps)
        rank = max(0, min(len(ordered) - 1, round(part * len(ordered)) - 1))
        return ordered[rank]

    def line(self):
        if not self.temps:
            return "%-14s NOT PLAYED" % self.name
        histogram = " ".join("%s:%d" % (s or "failure", n)
                         for s, n in sorted(self.statuses.items()))
        return ("%-14s n=%-4d  p50=%6.0f ms  p95=%6.0f ms  p99=%6.0f ms  "
                "max=%6.0f ms  %s"
                % (self.name, len(self.temps), self.percentile(.50) * 1000,
                   self.percentile(.95) * 1000, self.percentile(.99) * 1000,
                   max(self.temps) * 1000, histogram))

    def part_503(self):
        return self.statuses.get(503, 0) / max(len(self.temps), 1)


def in_parallel(measure, how_many, workdir):
    if how_many <= 0:
        print("%-14s NOT PLAYED (0 requested)" % measure.name)
        return measure
    with ThreadPoolExecutor(max_workers=min(how_many, 256)) as pool:
        for status, duration, _ in pool.map(workdir, range(how_many)):
            measure.add(status, duration)
    print(measure.line())
    return measure


def phase_page(measures):
    measures.append(in_parallel(
        Measures("page"), STUDENTS,
        lambda n: call("GET", "/", student=n)))
    measures.append(in_parallel(
        Measures("catalogue"), STUDENTS,
        lambda n: call("GET", "/catalog.json", student=n)))


def private_phase(measures):
    if not TOKEN:
        print("%-14s NOT PLAYED (CTESTER_LOAD_TOKEN empty)" % "progres")
        print("%-14s NOT PLAYED (CTESTER_LOAD_TOKEN empty)" % "brouillon")
        return
    measures.append(in_parallel(
        Measures("progres"), STUDENTS,
        lambda n: call("GET", "/progres", student=n, token=True)))
    if not TP:
        print("%-14s NOT PLAYED (CTESTER_LOAD_EXERCISE empty)" % "brouillon")
        return
    body = {"exercise_id": TP, "files": {}}
    measures.append(in_parallel(
        Measures("brouillon"), STUDENTS,
        lambda n: call("PUT", "/brouillon", body, student=n, token=True)))


def submission_phase(measures):
    if not (KEY and TP):
        print("%-14s NOT PLAYED (CTESTER_KEY or CTESTER_LOAD_EXERCISE empty)" % "submit")
        return
    repository = Measures("submit")
    jobs = []

    def submit(n):
        status, duration, payload = call(
            "POST", "/submit",
            {"key": KEY, "exercise_id": TP,
             "files": {"submission.c": SOURCE % n}},
            student=n)
        if status == 200 and isinstance(payload, dict) and payload.get("id"):
            jobs.append(payload["id"])
        return status, duration, payload

    in_parallel(repository, SUBMISSIONS, submit)
    if not repository.temps:
        return
    measures.append(repository)
    print("               %d job(s) accepted, %.0f %% 503s (queue full)"
          % (len(jobs), repository.part_503() * 100))
    if jobs:
        follow(measures, jobs)


SOURCE = ("#include <stdio.h>\n"
          "int main(void) { printf(\"charge %%d\n\", %d); return 0; }\n")


def follow(measures, jobs):
    poll = Measures("verdict")
    max_rank, remaining, limit = 0, list(jobs), time.time() + PATIENCE
    while remaining and time.time() < limit:
        again = []
        for n, job in enumerate(remaining):
            status, duration, payload = call("GET", "/r/" + job, student=n)
            poll.add(status, duration)
            if not isinstance(payload, dict):
                continue
            max_rank = max(max_rank, payload.get("position") or 0)
            if payload.get("state") in ("queued", "running"):
                again.append(job)
        remaining = again
        if remaining:
            time.sleep(2)
    measures.append(poll)
    print(poll.line())
    print("               max queue rank: %d -- %d job(s) still in flight "
          "after %d s" % (max_rank, len(remaining), PATIENCE))


def main():
    print("target     : %s" % TARGET)
    print("students   : %d   submissions : %d" % (STUDENTS, SUBMISSIONS))
    print("token      : %s   exercise : %s\n"
          % ("yes" if TOKEN else "NO", TP or "(none)"))
    start = time.time()
    measures = []
    phase_page(measures)
    private_phase(measures)
    submission_phase(measures)
    print("\n--- %.0f s total ---" % (time.time() - start))
    worst = [m for m in measures if m.part_503() > 0.01]
    if worst:
        print("503s ABOVE 1%: " + ", ".join(
            "%s %.0f %%" % (m.name, m.part_503() * 100) for m in worst))
    slow = [m for m in measures if m.temps and m.percentile(.95) > 1.0]
    if slow:
        print("p95 ABOVE ONE SECOND: " + ", ".join(
            "%s %.0f ms" % (m.name, m.percentile(.95) * 1000) for m in slow))
    if not worst and not slow:
        print("no threshold crossed -- leave ctester_workers alone.")


if __name__ == "__main__":
    main()
