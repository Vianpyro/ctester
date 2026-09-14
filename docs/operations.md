# Operations

## Deployment model

- **API and worker** run on the Dell. The server clones this repository into `/opt/ctester/src` and
  follows `main` on its own every five minutes. Everything else (gVisor, systemd units, Compose,
  PostgreSQL, the Rauthy client, deploy keys) lives in the `VHome` repository, under `roles/ctester`.
- **The API container** runs the stock `python:3.13-slim` image on read-only mounted code, with the
  packages from `requirements.txt` in the `ctester_deps` volume (`PYTHONPATH=/deps`). There is no
  Dockerfile.
- **The page** is built by CI (`npm run build` → `frontend/dist`) and published to GitHub Pages.
  Nothing is ever built on the Dell. `CTESTER_PAGE` may still point at a `dist` directory to serve the
  page from the API; set it to an empty string to disable that router.
- **Content** comes from the private test repository. `ctester-tests.timer` pulls it every five minutes
  and republishes the catalog without restarting anything.
- **The database schema and its grants** are both in `app/schema.sql`, replayed by Ansible at each
  converge. `VHome` only creates the `ctester_app` role.

All settings are environment variables read in `app/config.py` (API) and at the top of `runner.py`
(worker).

## Checks before deploying

Run these on a development machine; the last three need gcc.

```sh
npm run check                      # TypeScript and Svelte, warnings are errors
npm run build                      # must come before the next two: they read frontend/dist
npm test
python3 test_ctester.py
python3 test_api.py
python3 validate_content.py ../unittests/content
python3 verify_content.py   ../unittests/content   # every reference solution passes its tests
python3 test_sandbox.py     ../unittests/content   # the build scripts with a real gcc
```

- Without `frontend/dist`, the bundle and CSP document checks skip instead of failing.
- Without Docker or `CTESTER_TYPST_BIN`, the Typst rendering checks skip. CI sets `CTESTER_TYPST_BIN`.
- `test_postgres.py` needs a real PostgreSQL and is not part of the Ansible verification because it
  writes. Run it before a cohort, with both roles:

```sh
docker run -d --rm --name pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=ctester -p 55432:5432 postgres:16-alpine
CTESTER_DB_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester python3 test_postgres.py
docker exec -i pg psql -U postgres -d ctester -c "CREATE ROLE ctester_app LOGIN PASSWORD 'y'"
CTESTER_DB_ADMIN_DSN=postgresql://postgres:x@127.0.0.1:55432/ctester \
CTESTER_DB_DSN=postgresql://ctester_app:y@127.0.0.1:55432/ctester python3 test_postgres.py
docker stop pg
```

- `test_ctester.py` also runs on the Dell with the host Python, which has no third-party packages.
  Anything it imports must stay standard-library only, or the automatic deployment stops on an
  `ImportError`.

## Content

```sh
python3 validate_content.py ../unittests/content
python3 publish_content.py  ../unittests/content /tmp/published
```

- Pushing to the private test repository is enough; the timer republishes within five minutes.
  To publish immediately, run `systemctl start ctester-tests`, then check `journalctl -u ctester-tests -n 30`.
- **Rollback** means rewriting `published/current.json` to a previous revision. It is instant. Emptying
  `CTESTER_CONTENT` or `CTESTER_PUBLISHED` causes an outage.
- Invalid content never replaces the active release. A broken `statement.typ` blocks the whole
  publication until it is fixed.
- **After every publication**, `grep -rl answer /opt/ctester/published/` must print nothing.
- **Preview before opening:** `CTESTER_PREVIEW=1` opens every exercise on a local machine. In
  production, moderators (`CTESTER_FORUM_MODERATORS`) can open and submit closed exercises. The
  variable must also be set on the `ctester-runner@` unit, or their verdicts read "Exercice inconnu."
- **Randomized exercises** must set `"cache": false` in `io.json` or `unity.json`, or a lucky or unlucky
  verdict gets cached.
- **Unity test names** must match `[A-Za-z0-9_]{1,64}` and are shown to students, so make them readable.

## Deployment pitfalls

| Topic | What to know |
|---|---|
| Uvicorn | One worker only. Quotas, presence, the token cache and collaboration rooms are held in memory. |
| WebSockets | `wsproto` must be in `/deps`, or every handshake returns 501 silently. The NPM proxy host needs "Websockets Support". |
| Verdict cache | Any change to `runner.py` invalidates it once. Avoid deploying right before a lab. `CTESTER_CACHE_MAX=0` disables it. |
| Console | Needs `CTESTER_SCRATCH=1` on the API, `CTESTER_BUILD_SCRATCH` on the runner units, and at least two workers. |
| gVisor | `--pids-limit` counts the sentry's threads: below 64 the sandbox does not start. Fork bombs are stopped by the memory limit. |
| Compiler | `-std=gnu23`, not `c23` (which hides `M_PI`). `-DUNITY_INCLUDE_DOUBLE` is required, or double assertions always fail. |
| Rauthy | Enable the `refresh_token` flow on the client. `refresh_token_lifetime` (240 h) must match `SESSION_MAX_DAYS` in `frontend/src/lib/auth/keys.ts`. |
| Typst | Pull `ctester_typst_image` and create `/opt/ctester/typst-cache`. Emptying the image variable stops publication. |
| Discord | Off by default (`ctester_discord_enabled`). The webhook, bot token and bridge key belong in the vault. |
| Docs | Never set `CTESTER_DOCS=1` in production: it makes `/docs` and `/openapi.json` public. |
| Schema | Every statement must stay idempotent, and an index must follow the `ALTER` that adds its column. |

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
openssl rand -hex 24
ansible-vault edit inventory/group_vars/ctester_hosts/vault.yml   # in VHome
ansible-playbook playbooks/ctester.yml --ask-vault-pass
```

Diagnose, roughly in the order things break:

```sh
docker info --format '{{json .Runtimes}}'       # runsc registered?
systemctl status 'ctester-runner@*'
journalctl -u 'ctester-runner@*' -n 50
journalctl -u ctester-tests -n 30
journalctl -u ctester-pull  -n 30
docker logs ctester-web-1
ls /opt/ctester/spool                            # empty when idle
cat /opt/ctester/published/current.json          # served revision
grep -rl answer /opt/ctester/published/          # must print nothing
python3 /opt/ctester/src/test_ctester.py
```

Verdict cache activity is logged by the workers:

```sh
journalctl -u 'ctester-runner@*' -n 500 | grep 'ctester: cache '
```

If you see many "written" lines but no "served" ones, cache keys are changing between submissions,
which is expected right after a deploy.

Team rosters: students pick teams themselves until the assignment opens. To move someone
afterwards, load a CSV of `group_number,number,account`:

```sh
python3 import_teams.py devoir roster.csv --sql \
  | docker exec -i ctester-postgres psql -U postgres -d ctester -v ON_ERROR_STOP=1
```

Load testing (never during a lab; it writes to the database and compiles for real). Run it against the
origin on the LAN, not through Cloudflare:

```sh
CTESTER_KEY=... CTESTER_LOAD_EXERCISE=tp2-ex3 CTESTER_LOAD_TOKEN=... \
  python3 load_test.py http://ctester-web-1:8000
```

Watch `docker stats`, `uptime` and the spool length while it runs. Raise `ctester_workers` only if
the other services on the host leave CPU free.
