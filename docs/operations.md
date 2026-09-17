# Operations

## Deployment model

- **Everything needed to run CTester is in `deploy/`:** the Compose stack, the systemd units and the
  two update scripts. The TCH009 instance is deployed by the `VHome` repository (`roles/ctester`),
  which only adds gVisor, deploy keys, secrets and the PostgreSQL role.
- **The API container** runs the stock `python:3.13-slim` image on read-only mounted code. The `deps`
  service installs `requirements.txt` into a volume whenever the file changes. There is no Dockerfile.
- **The page** is built by CI (`npm run build` → `frontend/dist`) and published to GitHub Pages.
  `CTESTER_PAGE` may still point at a `dist` directory to serve the page from the API; set it to an
  empty string to disable that router.
- **`ctester-pull.timer`** follows the application branch nightly, deploys only when
  `tests/test_ctester.py` passes, and waits for an empty spool.
- **The judge** (`judge/`, Rust) is built by CI into the release `judge-<commit>`. `ctester-pull` installs
  it into `/opt/ctester/bin` only after checking its SHA-256 and its build attestation, and deploys no
  commit whose judge is not published yet.
- **`ctester-content.timer`** pulls the content every five minutes and republishes the catalog without
  restarting anything.
- **The database schema and its grants** are both in `app/schema.sql`.
- **The admin dashboard** (`admin/`) is a separate read-only app on the LAN; it publishes no
  port and is reached through the proxy. See *The admin dashboard* below before exposing it.

All settings are environment variables read in `app/config.py` (API) and `judge/src/config.rs`
(judge). On a server they all live in
one file, `/opt/ctester/.env`, read by Compose and by every systemd unit. The judge refuses to start
when they break an invariant, such as `CTESTER_LOCK_STALE` outside `JOB_TIMEOUT`..`SWEEP_AFTER`.

## Deploying

Requirements: Linux 5.6+ with systemd (the judge refuses to start without `openat2`), Docker with the
gVisor runtime (`runsc`), Python 3, git, curl, and the GitHub CLI with a read-only `GH_TOKEN` in `.env`
for `gh attestation verify`.

```text
/opt/ctester/
  src/          this repository
  content/      the course content, a git clone or a plain directory; CTESTER_CONTENT
                may list several, joined by ":"
  .env          configuration, from deploy/env.example
  spool/        owned by 65534:65534, the API's: job inputs only
  results/      owned by root, mounted read-only into web and admin: verdicts,
                Console output, durations, and the run journal runs-<date>.jsonl
  published/
  bin/          ctester-judge -> ctester-judge-<commit>, installed by ctester-pull
/var/lib/ctester-judge/   CTESTER_WORK, created by the judge units: staging and verdict cache
```

The API owns the spool, so the root judge only reads it, never through a link, and mounts nothing
from it: sources are copied to `CTESTER_WORK` first. Everything the judge writes back goes to
`results/`, which web can read but not write: the API cannot forge, replace or pre-create a verdict.
Keep `CTESTER_WORK` out of the web container, and never mount `results/` read-write.

```sh
git clone https://github.com/Vianpyro/ctester.git /opt/ctester/src
cd /opt/ctester
cp src/deploy/env.example .env && chmod 600 .env   # then fill it in
mkdir -p published spool results && chown 65534:65534 spool
docker network create ctester-ingress               # or set CTESTER_NETWORK to your proxy's network
ln -s /opt/ctester/src/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl start ctester-content
docker compose up -d
systemctl enable --now ctester-judge@1 ctester-judge@2 ctester-pull.timer ctester-content.timer
docker compose exec -T postgres psql -U postgres -d ctester -v ON_ERROR_STOP=1 < src/app/schema.sql
```

- Start as many `ctester-judge@N` instances as `CTESTER_WORKERS`; `ctester-pull` keeps that count.
  Before the first judge release exists, `ctester-pull` defers, so install one by hand with the
  commands it runs.
- Accounts need a `ctester_app` role created before the schema is applied, and `CTESTER_DB_DSN`,
  `CTESTER_OIDC_ISSUER` and `CTESTER_OIDC_CLIENT_ID` in `.env`.
- `COMPOSE_PROFILES=discord` starts the Discord bridge.
- The timers' schedules can be changed with `systemctl edit ctester-pull.timer`.

The first deployment of the judge also retires the Python `ctester-runner@N` units. On that host,
check the unit's hardening with `systemd-analyze security ctester-judge@1`, then submit one quiz, io,
unity and Console job. A restriction that breaks the judge is removed explicitly, with the reason in
the commit.

## Checks before deploying

Run these on a development machine; the last three need gcc.

```sh
(cd judge && cargo clippy --all-targets -- -D warnings && cargo test)
(cd judge && cargo build --release)  # verify_content.py and test_sandbox.py call judge/target/release
npm run check                      # TypeScript and Svelte, warnings are errors
npm run build                      # must come before the next two: they read frontend/dist
npm test
python3 tests/test_ctester.py
python3 tests/test_api.py
python3 scripts/validate_content.py ../unittests/content
python3 scripts/verify_content.py   ../unittests/content   # every reference solution passes its tests
python3 tests/test_sandbox.py       ../unittests/content   # the build scripts with a real gcc
```

- Without `frontend/dist`, the bundle and CSP document checks skip instead of failing.
- Without Docker or `CTESTER_TYPST_BIN`, the Typst rendering checks skip. CI sets `CTESTER_TYPST_BIN`.
- `tests/test_postgres.py` needs a real PostgreSQL and is not part of the Ansible verification because it
  writes. Run it before a cohort, with both roles:

```sh
docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester -p 55432:5432 postgres:16-alpine
CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester python3 tests/test_postgres.py
docker exec -i pg psql -U postgres -d ctester -c "CREATE ROLE ctester_app LOGIN PASSWORD 'y'"
CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester python3 tests/test_postgres.py
docker stop pg
```

- `tests/test_ctester.py` also runs on the Dell with the host Python, which has no third-party packages.
  Anything it imports must stay standard-library only, or the automatic deployment stops on an
  `ImportError`.

## Content

```sh
python3 scripts/validate_content.py ../unittests/content
python3 worker/publish_content.py   ../unittests/content /tmp/published
```

- Pushing to the private test repository is enough; the timer republishes within five minutes.
  To publish immediately, run `systemctl start ctester-content`, then check `journalctl -u ctester-content -n 30`.
- **Rollback** means rewriting `published/current.json` to a previous revision. It is instant. Emptying
  `CTESTER_CONTENT` or `CTESTER_PUBLISHED` causes an outage.
- Invalid content never replaces the active release. A broken `statement.typ` blocks the whole
  publication until it is fixed.
- **After every publication**, `grep -rl answer /opt/ctester/published/` must print nothing.
- **Preview before opening:** `CTESTER_PREVIEW=1` opens every exercise on a local machine. In
  production, moderators (`CTESTER_FORUM_MODERATORS`) can open and submit closed exercises.
- **Randomized exercises** must set `"cache": false` in `io.json` or `unity.json`, or a lucky or unlucky
  verdict gets cached.
- **Unity test names** must match `[A-Za-z0-9_]{1,64}` and are shown to students, so make them readable.

## Deployment pitfalls

| Topic | What to know |
|---|---|
| Uvicorn | One worker only. Quotas, presence, the token cache and collaboration rooms are held in memory. |
| WebSockets | `wsproto` must be in `/deps`, or every handshake returns 501 silently. The NPM proxy host needs "Websockets Support". |
| Verdict cache | Lives in `CTESTER_WORK/cache`. Any new judge build invalidates it once. Avoid deploying right before a lab. `CTESTER_CACHE_MAX=0` disables it. |
| Console | Needs `CTESTER_SCRATCH=1` and at least two workers. |
| gVisor | `--pids-limit` counts the sentry's threads: below 64 the sandbox does not start. Fork bombs are stopped by the memory limit. |
| Compiler | `-std=gnu23`, not `c23` (which hides `M_PI`). `-DUNITY_INCLUDE_DOUBLE` is required, or double assertions always fail. |
| Rauthy | Enable the `refresh_token` flow on the client. `refresh_token_lifetime` (240 h) must match `SESSION_MAX_DAYS` in `frontend/src/lib/auth/keys.ts`. |
| Typst | Pull the `CTESTER_TYPST_IMAGE` image (default `ghcr.io/typst/typst:0.15.1`) before the first publication. |
| Discord | Off by default (`COMPOSE_PROFILES=discord`). The webhook, bot token and bridge key are secrets. |
| Docs | Never set `CTESTER_DOCS=1` in production: it makes `/docs` and `/openapi.json` public. |
| Schema | Every statement must stay idempotent, and an index must follow the `ALTER` that adds its column. |

## The origin must only answer Cloudflare

Anonymous quotas are keyed by `security.client_id()`, which reads `CF-Connecting-IP` and falls back
to `X-Forwarded-For`. Both are plain request headers. Anyone who reaches the origin directly sends a
different one on every request, lands in a fresh bucket each time, and the `/submit` cooldown stops
existing: the judge queue fills up instead of the caller being turned away. The headers are only
trustworthy because Cloudflare overwrites them, so the origin has to be unreachable without it.

Docker inserts its own rules ahead of ufw, so `ufw deny` on the proxy's ports looks like it works and
does nothing. Filter in `DOCKER-USER`, dropping first and allowing above it:

```sh
iptables -I DOCKER-USER 1 -p tcp -m multiport --dports 80,443 -j DROP
# Cloudflare's ranges change; refresh them, do not paste them in once.
for cidr in $(curl -fsS https://www.cloudflare.com/ips-v4); do
    iptables -I DOCKER-USER 1 -p tcp -m multiport --dports 80,443 -s "$cidr" -j RETURN
done
```

Repeat with `ip6tables` and `ips-v6`, and persist the rules, or a reboot reopens the origin.

Verify from off the LAN: connecting to the origin's address must time out while the Cloudflare
hostname still serves. `ctester-pull` and `scripts/load_test.py` reach the origin from the LAN, which
these rules leave alone.

## Hostile submissions

Replay these after any change to the sandbox, on both the graded path and the Console.

| Submission | Expected |
|---|---|
| `while (1) fork();` | timeout, host load unchanged |
| `system("curl http://example.com");` | fails (`--network=none`) |
| `while (1);` | timeout after 5 s (graded) or 10 s CPU (Console) |
| `#include <unistd.h>` outside the allow-list | rejected before any container starts (graded only) |

## Runbook

Rotate the session key:

```sh
sed -i "s/^CTESTER_KEY=.*/CTESTER_KEY=$(openssl rand -hex 24)/" /opt/ctester/.env
cd /opt/ctester && docker compose up -d
```

Diagnose, roughly in the order things break:

```sh
docker info --format '{{json .Runtimes}}'       # runsc registered?
/opt/ctester/bin/ctester-judge self-check        # resolved settings, openat2, build scripts
systemctl status 'ctester-judge@*'
journalctl -u 'ctester-judge@*' -n 50
journalctl -u ctester-content -n 30
journalctl -u ctester-pull  -n 30
docker logs ctester-web-1
ls /opt/ctester/spool                            # empty when idle
ls /opt/ctester/results                          # verdicts, swept after CTESTER_SWEEP_AFTER
cat /opt/ctester/published/current.json          # served revision
grep -rl answer /opt/ctester/published/          # must print nothing
python3 /opt/ctester/src/tests/test_ctester.py
```

Verdict cache activity is logged by the workers:

```sh
journalctl -u 'ctester-judge@*' -n 500 | grep 'ctester: cache '
```

If you see many "written" lines but no "served" ones, cache keys are changing between submissions,
which is expected right after a deploy.

## Several content repositories

`CTESTER_CONTENT` is one path or several joined by `:`, like a `PATH`. Every root is merged
into **one** catalogue and one published release: the API, the database, the page and the job
envelope never name a source, so nothing downstream changes when a second course arrives.

```sh
CTESTER_CONTENT=/opt/ctester/tests/content:/opt/ctester/tests-tch101/content
```

**Exercise ids stay unique across every root.** Two repositories claiming `tp1-ex1` is a
publication error naming both, not a silent winner — that rule is what lets an id stay a bare
string everywhere else. The same goes for collection and assignment ids, and an exercise still
belongs to at most one assignment across all roots. Prerequisites, collection items and
assignment items resolve across roots, so one course may build on another's exercises.

`catalog.json` is read from every root and the `skills` vocabularies are **unioned**, so an
exercise may declare a skill another repository defined. Each root is still checked against the
schema version on its own.

The order of the roots does not matter. The published revision is a hash of the merged model,
which is sorted by id, so reordering `CTESTER_CONTENT` republishes nothing. The one thing order
would have changed is `shared/unity`: **only one root may hold it**, and the judge refuses to
start otherwise, because that tree is hashed into every Unity verdict's cache key.

**Publication is all-or-nothing.** One repository pushing a bad commit blocks the publication of
*every* course — deliberately, since a half-published catalogue is worse than a slightly old
one. The dashboard shows the revision actually being served, and `ctester-content` failing is
worth an alert:

```sh
systemctl status ctester-content
journalctl -u ctester-content -n 30
python3 scripts/validate_content.py /path/to/a/content /path/to/b/content
```

One branch (`CTESTER_CONTENT_BRANCH`) and one deploy key (`CTESTER_CONTENT_SSH_KEY`) serve every
repository; `content.sh` reads one of each. For per-repository keys, use `Host` aliases in the
deploy account's `~/.ssh/config` and change no script. On the TCH009 host, add a course through
`ctester_extra_content_repos` in the Ansible role; each entry is cloned to
`/opt/ctester/tests-<name>/` and appended to `CTESTER_CONTENT`. An empty list deploys exactly
what was there before.

## The admin dashboard

`admin/` is a second, small FastAPI app: the teacher's view of the service. It is read-only —
it never writes a verdict, a grade or a student's row. The only table it fills is its own copy
of the judge's run journal.

**It has no sign-in of its own.** The proxy in front of it is the entire boundary.

> **Before exposing it:** the Nginx Proxy Manager host for the dashboard must carry an
> **Access List restricted to the LAN** (for example `192.168.0.0/16`). Without it, anyone who
> can reach the proxy gets the dashboard. An IP check inside the app would be theatre: every
> request arrives with the proxy's address, not the visitor's.

The `admin` service publishes **no port**. It listens on `8001` on the `CTESTER_NETWORK`
(`ctester-ingress` by default), which is how the proxy reaches it — point a proxy host at
`admin:8001`. Confirm it is not exposed anywhere else:

```sh
docker compose ps admin                          # the PORTS column must stay empty
docker compose exec -T admin python3 -c \
  'import urllib.request as u;print(u.urlopen("http://127.0.0.1:8001/healthz").read())'
```

It shows the live workers and queue, the published revision, the history of every run, and
per-exercise statistics. What it reads:

| Source | Used for |
|---|---|
| `judge_run` (SQL) | runs, workers, durations, cache rate, reprises, failures per exercise |
| `spool/` | queue depth, oldest job, ETA |
| `published/current.json` | the revision the API is serving |
| `exercise_state`, `practice_attempt`, `xp_transaction` | solved counts, active accounts, XP |
| `web`'s `/live` | open browser windows right now |

The window count comes from the API's own presence map over `CTESTER_ADMIN_WEB_URL`
(`http://web:8000` by default, reached on the Compose network). `/live` counts windows *and*
registers its caller, so the dashboard subtracts itself -- the same thing `ctester-pull` does.
It counts **windows, not accounts**: a signed-out visitor is one too, and the count empties
`CTESTER_PRESENCE_TTL` seconds (150) after the last request. If the API is down the tile shows
`--` and nothing else on the page is affected.

"En file" counts jobs still waiting; a job a worker has already claimed is shown separately as
"en cours de correction". Many waiting with none running means the workers are stuck, not busy.

### The run journal

The judge appends one JSON line per finished run to `results/runs-<YYYY-MM-DD>.jsonl` — every
run, including the ones nothing else records: anonymous submissions, Console sessions, cache
hits, jobs the student never polled, and jobs abandoned after a reclaim. Every worker appends
to the same file; a single `write` to a file opened `O_APPEND` cannot interleave on a local
filesystem, which is one more reason `results/` must never sit on NFS.

`CTESTER_WORKER_ID` names the instance in each line; the systemd unit passes `%i`, so
`ctester-judge@2` writes `"worker_id": "2"`. A worker counts as alive when it has finished a
run in the last five minutes — the judge keeps no other identity, and on a service students
poll constantly a dead worker shows up within one job.

The admin app ingests the journal into `judge_run` every 30 seconds, remembering a byte offset
per file, and skips any job id it already stored — so a restart, a retry or a replay never
duplicates a row. `results/` is read-only to it, so it never truncates a journal file.

Nothing prunes the journal: one line per run is roughly 1 MB a day. If it ever matters:

```sh
find /opt/ctester/results -name 'runs-*.jsonl' -mtime +30 -delete
```

`judge_run` carries **no account column**. It is the history of the service, not of a student,
so "delete my data" leaves it alone.

```sh
ls /opt/ctester/results/runs-*.jsonl             # the journal, one file per day
tail -1 /opt/ctester/results/runs-$(date +%F).jsonl
docker logs ctester-admin-1                      # "drain failed" lines if ingestion is stuck
```

If the dashboard says *Base de données injoignable*, the queue and the published revision still
show: those come from the filesystem, not from SQL.

Team rosters: students pick teams themselves until the assignment opens. To move someone
afterwards, load a CSV of `group_number,number,account`:

```sh
python3 scripts/import_teams.py devoir roster.csv --sql \
  | docker exec -i ctester-postgres psql -U postgres -d ctester -v ON_ERROR_STOP=1
```

Load testing (never during a lab; it writes to the database and compiles for real). Run it against the
origin on the LAN, not through Cloudflare:

```sh
CTESTER_KEY=... CTESTER_LOAD_EXERCISE=tp2-ex3 CTESTER_LOAD_TOKEN=... \
  python3 scripts/load_test.py http://ctester-web-1:8000
```

Watch `docker stats`, `uptime` and the spool length while it runs. Raise `CTESTER_WORKERS` only if
the other services on the host leave CPU free.
