# Operations

## Deployment model

Everything needed to run CTester is in `deploy/`: the Compose stack, the systemd units and the
two update scripts. The TCH009 instance is deployed by the `VHome` repository (`roles/ctester`),
which only adds gVisor, deploy keys, secrets and the PostgreSQL role.

- The API container runs the stock `python:3.13-slim` image on read-only mounted code. The `deps`
  service installs `requirements.txt` into a volume whenever the file changes. There is no Dockerfile.
- The judge (`judge/`, Rust) is built by CI into the release `judge-<commit>`. `ctester-pull`
  installs it into `/opt/ctester/bin` after checking its SHA-256 and build attestation, and does not
  deploy a commit whose judge is not published yet.
- `ctester-pull.timer` follows the application branch nightly, deploys only when
  `tests/test_ctester.py` passes, and waits for an empty spool.
- `ctester-content.timer` pulls the content every five minutes and republishes the catalog without
  restarting anything.
- The database schema and its grants are both in `app/schema.sql`.
- The admin dashboard (`admin/`) is a separate read-only app on the LAN, reached through the proxy.
  Read *The admin dashboard* below before exposing it.

The page is built by CI (`npm run build` → `frontend/dist`) and published to GitHub Pages. It names
no host of its own: `CTESTER_API_ORIGIN`, `CTESTER_AUTH_ORIGIN`, `CTESTER_TITLE`, `CTESTER_LANG` and
`CTESTER_PAGES_DOMAIN` are baked in at build time from variables of the `github-pages`
environment. Only the `pages` job enters that environment, so it builds its own copy; the `tests`
artifact stays generic for Lighthouse. `pages` refuses to deploy a build with no CNAME or no API
origin in its CSP, since such a page would ask its own origin for `/catalog.json`.

- `CTESTER_TITLE` is the instance's name alone (`TCH009`). The header and the tab add the tagline,
  and the build refuses a title that already contains it.
- `CTESTER_LANG` is the language a student sees before choosing one (`fr` for ÉTS, `en` by
  default). Set it in `.env` as well, for the Typst statements. See [translations.md](translations.md).
- `CTESTER_API_ORIGIN` is also read by the server, which keeps the CSP in `index.html` and the one
  in `app/csp.py` identical.
- `CTESTER_PAGE` may point at a `dist` directory to serve the page from the API; an empty string
  disables that router.

All settings are environment variables read in `app/config.py` (API) and `judge/src/config.rs`
(judge). On a server they all live in one file, `/opt/ctester/.env`, read by Compose and by every
systemd unit. The judge refuses to start
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
python3 tests/test_sandbox.py                              # the build scripts with a real gcc
python3 scripts/validate_content.py <content root>
python3 scripts/verify_content.py   <content root>         # every reference solution passes its tests
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
python3 scripts/validate_content.py <content root>
python3 worker/publish_content.py   <content root> /tmp/published
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
publication error naming both, which is what lets an id stay a bare string everywhere else. The same goes for collection and assignment ids, and an exercise still
belongs to at most one assignment across all roots. Prerequisites, collection items and
assignment items resolve across roots, so one course may build on another's exercises.

`catalog.json` is read from every root and the `skills` vocabularies are **unioned**, so an
exercise may declare a skill another repository defined. Each root is still checked against the
schema version on its own.

The order of the roots does not matter. The published revision is a hash of the merged model,
which is sorted by id, so reordering `CTESTER_CONTENT` republishes nothing. The one thing order
would have changed is `shared/unity`: **only one root may hold it**, and the judge refuses to
start otherwise, because that tree is hashed into every Unity verdict's cache key.

**Publication is all-or-nothing.** A bad commit in one repository blocks the publication of
every course, so students keep the last good catalogue. The dashboard shows the revision being
served, and a failing `ctester-content` is worth an alert:

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

`admin/` is a second, small FastAPI app: the teacher's view of the service. It never writes a
verdict, a grade or a student's row; the only table it fills is its own copy of the judge's run
journal.

Every `/api` route demands a moderator's OIDC token, from the same `CTESTER_FORUM_MODERATORS`
list the forum and the judge use. Without one the routes answer 401, and a signed-in student
gets 403. The page itself is served to anyone, but shows a sign-in screen and fetches nothing
until it has a token.

Also put an access list on the Nginx Proxy Manager host, restricted to the LAN (for example
`192.168.0.0/16`). A hostname that only resolves on the LAN does not protect anything, because the
proxy routes on the `Host` header. An IP check inside the app would not help either: every
request arrives with the proxy's address.

To audit which proxy hosts carry a list:

```sh
docker cp nginx-manager-npm-1:/data/database.sqlite /tmp/npm.sqlite
sqlite3 /tmp/npm.sqlite "SELECT ph.domain_names, ph.access_list_id, al.name
  FROM proxy_host ph LEFT JOIN access_list al ON al.id = ph.access_list_id
  WHERE ph.is_deleted = 0;"
rm /tmp/npm.sqlite
```

`access_list_id = 0` means no list is attached.

### Student names and code

Both are hidden until asked for, by the server: without `?reveal=1`, `/api/runs` does not send the
account at all. The toggle is there for the projector and for people looking over a shoulder.

`GET /api/code` answers from whichever of two existing sources still has the code; nothing new
is stored for it.

| Source | What it is | When it answers |
|---|---|---|
| the spool's `files.json` | the code of *that* run, even for a signed-out student | until the judge sweeps, `CTESTER_SWEEP_AFTER` (600 s) |
| `exercise_state.sources` | the student's *latest* code for that exercise | any time, signed-in students only |

The page says which one answered. A run the student never polled has no row, so once it is
swept its code is gone.

The dashboard never compiles or runs student code, but it does display it in a page that holds a
moderator token. It is inserted with `textContent`, never `innerHTML`, and the app's
`Content-Security-Policy` forbids inline scripts, so a `.c` file full of HTML is shown as text.

### Signing in

The dashboard runs the same PKCE authorization-code flow as the student page, ported to plain
JavaScript in `admin/static/auth.js`. It reuses `CTESTER_OIDC_CLIENT_ID`: a student's token is
accepted by the IdP and then refused with 403 by the app, which is where the moderator check
belongs.

Two entries are needed on the IdP side, and neither lives in this repository:

| What | Value |
|---|---|
| Redirect URI | the dashboard's own URL, `location.origin + location.pathname`, e.g. `https://tch999.thevhome.com/` |
| CORS origin | the same origin, because the browser posts the code to the IdP's token endpoint |

The dashboard must be served over HTTPS: PKCE uses `crypto.subtle`, which browsers only expose in
a secure context. The `*.thevhome.com` wildcard certificate covers this.

The `admin` service publishes no port. It listens on `8001` on `CTESTER_NETWORK`
(`ctester-ingress` by default), so point a proxy host at `admin:8001`, and confirm it is not
exposed anywhere else:

```sh
docker compose ps admin                          # the PORTS column must stay empty
docker compose exec -T admin python3 -c \
  'import urllib.request as u;print(u.urlopen("http://127.0.0.1:8001/healthz").read())'
```

It shows the live workers and queue, the published revision, the history of every run,
per-exercise statistics and where the discussion is. What it reads:

| Source | Used for |
|---|---|
| `judge_run` (SQL) | runs, workers, durations, cache rate, reprises, failures per exercise |
| `spool/` | queue depth, oldest job, ETA |
| `published/current.json` | the revision the API is serving |
| `exercise_state`, `practice_attempt`, `xp_transaction` | solved counts, active accounts, XP |
| `web`'s `/live` | open browser windows right now |
| `forum_message` | the Discussions panel: per-channel message counts and last activity, never any message text |

Console sessions are kept out of every timing and success aggregate: their duration is the
student's typing, and their queue wait is the global console lock rather than a busy worker.
They keep their own `:console` row under *Par exercice*, which is where console usage belongs.

Everything on the page refreshes on the same 5 s tick. A request is skipped while the previous
one is still out, so on a long period the dashboard slows to the database's real speed instead
of queueing; a backgrounded tab asks for nothing at all. Measured on 720 000 runs, a full tick
costs ~160 ms over 24 h and ~1 s over a full session.

The window count comes from the API's presence map over `CTESTER_ADMIN_WEB_URL`
(`http://web:8000` by default, on the Compose network). `/live` also registers its caller, so the
dashboard subtracts itself, as `ctester-pull` does. It counts browser windows, signed in or not, and
empties `CTESTER_PRESENCE_TTL` seconds (150) after the last request. If the API is down the tile
shows `--` and the rest of the page is unaffected.

"En file" counts jobs still waiting; a job a worker has claimed is shown as "en cours de
correction". Many waiting jobs with none running means the workers are stuck.

### The run journal

The judge appends one JSON line per finished run to `results/runs-<YYYY-MM-DD>.jsonl`, including
the runs nothing else records: anonymous submissions, Console sessions, cache hits, jobs the
student never polled and jobs abandoned after a reclaim. All workers append to the same file,
which only works on a local filesystem: keep `results/` off NFS.

`CTESTER_WORKER_ID` names the instance in each line; the systemd unit passes `%i`, so
`ctester-judge@2` writes `"worker_id": "2"`. A worker counts as alive when it has finished a run
in the last five minutes; during a lab, a dead worker shows up within one job.

The admin app ingests the journal into `judge_run` every 30 seconds. It remembers a byte offset
per file and skips job ids it already stored, so a restart never duplicates a row. `results/` is
read-only to it.

If ingestion stalls, the page says so. The drain does not advance its cursor when a write fails,
so the journal is replayed once the cause is fixed. The usual cause is a schema older than the
code: the drain writes `account`, which an older database rejects. The state line turns red with
"Le journal ne s'ingère plus", and `docker logs ctester-admin-1` logs the error once.

```sh
docker exec ctester-postgres psql -U postgres -d ctester -tAc \
  "SELECT count(*) FROM information_schema.columns
   WHERE table_name='judge_run' AND column_name='account'"
```

`0` means the schema is behind. Ansible applies `app/schema.sql` on every converge, so the fix is
usually to converge, once the clone at `ctester_app_dir` has the commit.

Nothing prunes the journal: one line per run is roughly 1 MB a day. If it ever matters:

```sh
find /opt/ctester/results -name 'runs-*.jsonl' -mtime +30 -delete
```

"Delete my data" also removes the student's rows from `judge_run`.

```sh
ls /opt/ctester/results/runs-*.jsonl             # the journal, one file per day
tail -1 /opt/ctester/results/runs-$(date +%F).jsonl
docker logs ctester-admin-1                      # "drain failed" lines if ingestion is stuck
```

If the dashboard says *Base de données injoignable*, the queue and the published revision still
show, since they are read from the filesystem.

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
